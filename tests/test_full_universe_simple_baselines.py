from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import full_universe_simple_baselines as subject


class Result:
    def __init__(self, columns, rows):
        self.columns, self.rows = list(columns), list(rows)


class Window:
    def __init__(self, number, train, test):
        self.fold_number, self.train_positions, self.test_positions = number, train, test


class Config:
    def __init__(self, **values):
        self.__dict__.update(values)


class Primitives:
    calls = []

    @staticmethod
    def windows(index, config):
        first = len(index) - config.test_sessions * config.outer_folds
        output = []
        for i in range(config.outer_folds):
            test_start = first + i * config.test_sessions
            train_end = test_start - config.purge_sessions
            output.append(Window(i + 1,
                np.arange(train_end - config.training_window_sessions, train_end),
                np.arange(test_start, test_start + config.test_sessions)))
        return output

    @classmethod
    def fit(cls, X_train, y_train, X_test, *, min_fit_observations):
        cls.calls.append((tuple(X_train.index), tuple(y_train.index), tuple(X_test.index),
                          min_fit_observations))
        if len(X_train.join(y_train.rename("y")).dropna()) < min_fit_observations:
            raise subject.BaselineContractError("not enough fit data")
        return np.where(X_test.iloc[:, 0].to_numpy() >= 0, .6, .4)

    @classmethod
    def primitives(cls):
        return (Config, cls.windows, cls.fit)


def rows_for(dates, *, flip_final=False):
    values = [1.0 if i % 3 else -1.0 for i in range(len(dates))]
    if flip_final:
        values[-30:] = [-value for value in values[-30:]]
    return [{"date": date, "daily_return_pct": value} for date, value in zip(dates, values)]


def complete_checkpoint(ticker, lineage):
    result = subject.evaluate_ticker(ticker, lineage["sessions"], rows_for(lineage["sessions"]),
                                     primitives=Primitives.primitives())
    payload = {**result, "lineage_sha256": subject.canonical_sha(lineage)}
    payload["checkpoint_sha256"] = subject.canonical_sha(payload)
    return payload


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        Primitives.calls = []
        self.dates = [f"2022-01-{i:04d}" for i in range(subject.EXPECTED_SESSIONS)]

    def test_exact_common_denominators_and_three_baselines(self):
        result = subject.evaluate_ticker("AAPL", self.dates, rows_for(self.dates),
                                         primitives=Primitives.primitives())
        self.assertEqual(result["coverage"], {"folds": 4, "oos_observations": 120})
        self.assertEqual(len(result["folds"]), 4)
        self.assertEqual(set(result["aggregate"]), {
            "majority_direction", "constant_training_rate", "lag1_logistic"})
        self.assertEqual(result["persisted_probabilities"], 0)
        self.assertTrue(all(fold["test_observations"] == 30 for fold in result["folds"]))

    def test_fold_local_training_and_purge_are_leakage_safe(self):
        result = subject.evaluate_ticker("AAPL", self.dates, rows_for(self.dates),
                                         primitives=Primitives.primitives())
        first_train, _y_index, first_test, minimum = Primitives.calls[0]
        self.assertEqual(len(first_train), 289)
        self.assertEqual(minimum, 126)
        self.assertEqual(self.dates.index(first_test[0]) - self.dates.index(first_train[-1]), 8)
        self.assertTrue(set(first_train).isdisjoint(first_test))
        self.assertEqual(result["folds"][0]["purge_sessions"], 7)

    def test_future_test_labels_do_not_change_fold_training_rate(self):
        original = subject.evaluate_ticker("AAPL", self.dates, rows_for(self.dates),
                                            primitives=Primitives.primitives())
        changed = subject.evaluate_ticker("AAPL", self.dates,
            rows_for(self.dates, flip_final=True), primitives=Primitives.primitives())
        self.assertEqual(original["folds"][-1]["training_positive_rate"],
                         changed["folds"][-1]["training_positive_rate"])

    def test_missing_test_target_is_rejected(self):
        rows = rows_for(self.dates)[:-1]
        with self.assertRaisesRegex(subject.BaselineContractError, "exact governed"):
            subject.evaluate_ticker("AAPL", self.dates, rows, primitives=Primitives.primitives())

    def test_duplicate_and_nonfinite_returns_are_rejected(self):
        rows = rows_for(self.dates)
        with self.assertRaises(subject.BaselineContractError):
            subject.evaluate_ticker("AAPL", self.dates, rows + [rows[0]], primitives=Primitives.primitives())
        rows[0]["daily_return_pct"] = float("nan")
        with self.assertRaises(subject.BaselineContractError):
            subject.evaluate_ticker("AAPL", self.dates, rows, primitives=Primitives.primitives())


class GuardTests(unittest.TestCase):
    def test_select_guard_rejects_mutation_and_comments(self):
        db = mock.Mock()
        for sql in ("DELETE FROM x", "SELECT * FROM x;", "SELECT * FROM x -- no"):
            with self.assertRaises(subject.BaselineContractError):
                subject.select_only(db, sql, [], "guard")
        db.execute.assert_not_called()

    def test_records_require_exact_columns(self):
        with self.assertRaises(subject.BaselineContractError):
            subject._records(Result(["wrong"], [[1]]), ("right",), "rows")

    def test_config_hash_and_common_geometry_are_exact(self):
        raw = json.dumps({"training_window_sessions": 289, "min_train_sessions": 289,
            "test_sessions": 30, "outer_folds": 4, "purge_sessions": 7,
            "min_fit_observations": 126, "min_oos_sessions": 120,
            "signal_lookback_sessions": 60}, sort_keys=True)
        arm = subject.ExpectedArm("run", 60, subject.hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(subject._validate_config(raw, arm)["training_window_sessions"], 289)
        with self.assertRaises(subject.BaselineContractError):
            subject._validate_config(raw + " ", arm)

    def test_root_and_absolute_path_guards_precede_credentials(self):
        loader = mock.Mock()
        self.assertEqual(subject.main(["--env-file", "x", "--checkpoint-dir", "y",
            "--final-manifest", "z", "--executor-manifest", "m"],
            effective_uid=lambda: 1000, credentials_loader=loader), 1)
        loader.assert_not_called()

    def test_main_error_is_redacted(self):
        with mock.patch("sys.stderr") as stderr:
            status = subject.main([], effective_uid=lambda: 0)
        self.assertEqual(status, 1)
        rendered = "".join(str(call) for call in stderr.write.call_args_list)
        self.assertNotIn("token", rendered.lower())
        self.assertNotIn("password", rendered.lower())

    @unittest.skipUnless(os.name == "posix", "root directory contract is POSIX deployment behavior")
    def test_output_directory_must_be_root_owned_mode_700(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            path.chmod(0o700)
            if path.stat().st_uid == 0:
                self.assertEqual(subject.require_root_output_directory(path, "output"), path)
            path.chmod(0o755)
            with self.assertRaisesRegex(subject.BaselineContractError, "root-owned mode-0700"):
                subject.require_root_output_directory(path, "output")

    @unittest.skipUnless(os.name == "posix", "executor manifest is POSIX deployment behavior")
    def test_executor_manifest_binds_exact_root_owned_artifacts(self):
        if os.geteuid() != 0:
            self.skipTest("root is required to exercise deployed-artifact ownership")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            module = root / "full_universe_simple_baselines.py"
            entrypoint = root / "scripts" / "run_full_universe_simple_baselines.py"
            artifacts = {}
            for relative in subject.REQUIRED_EXECUTOR_ARTIFACTS:
                artifact = root / relative
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text(relative)
                artifact.chmod(0o444)
                artifacts[relative] = subject.hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = root / "executor.json"
            manifest.write_text(json.dumps({"executor_git_commit": "a" * 40,
                                             "artifacts": artifacts}))
            manifest.chmod(0o600)
            (root / "scripts").chmod(0o555)
            root.chmod(0o555)
            self.assertEqual(subject.load_executor_manifest(manifest, module, entrypoint), "a" * 40)
            root.chmod(0o755); (root / "scripts").chmod(0o755)
            entrypoint.chmod(0o600)
            entrypoint.write_text("tampered")
            entrypoint.chmod(0o444)
            (root / "scripts").chmod(0o555); root.chmod(0o555)
            with self.assertRaisesRegex(subject.BaselineContractError,
                                        "executor artifact identity differs"):
                subject.load_executor_manifest(manifest, module, entrypoint)


@unittest.skipUnless(os.name == "posix", "mode/link contract is POSIX deployment behavior")
class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self):
        dates = [f"2022-01-{i:04d}" for i in range(subject.EXPECTED_SESSIONS)]
        self.lineage = {"ticker_universe": ["AAPL"], "sessions": dates}
        return complete_checkpoint("AAPL", self.lineage)

    def test_write_once_mode_600_and_resume(self):
        path = self.folder / "checkpoint.json"
        subject.write_json_once(path, self.payload())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        loaded = subject.read_checkpoint(path, "AAPL", self.lineage)
        self.assertEqual(loaded["ticker"], "AAPL")
        with self.assertRaises(subject.BaselineContractError):
            subject.write_json_once(path, self.payload())

    def test_resume_tamper_is_rejected(self):
        path = self.folder / "checkpoint.json"
        subject.write_json_once(path, self.payload())
        value = json.loads(path.read_text())
        value["ticker"] = "MSFT"
        path.chmod(0o600); path.write_text(json.dumps(value)); path.chmod(0o600)
        with self.assertRaisesRegex(subject.BaselineContractError, "digest"):
            subject.read_checkpoint(path, "AAPL", self.lineage)


class AggregateTests(unittest.TestCase):
    def test_self_consistent_but_semantically_invalid_checkpoint_is_rejected(self):
        dates = [f"2022-01-{i:04d}" for i in range(subject.EXPECTED_SESSIONS)]
        lineage = {"ticker_universe": ["AAA"], "sessions": dates}
        payload = complete_checkpoint("AAA", lineage)
        payload["aggregate"]["lag1_logistic"]["accumulator"]["observations"] = 119
        ticker_evidence = dict(payload)
        ticker_evidence.pop("checkpoint_sha256")
        ticker_evidence.pop("ticker_evidence_sha256")
        ticker_evidence.pop("lineage_sha256")
        payload["ticker_evidence_sha256"] = subject.canonical_sha(ticker_evidence)
        without_checkpoint_hash = dict(payload)
        without_checkpoint_hash.pop("checkpoint_sha256")
        payload["checkpoint_sha256"] = subject.canonical_sha(without_checkpoint_hash)
        with self.assertRaisesRegex(subject.BaselineContractError, "accumulator totals"):
            subject.validate_checkpoint_payload(payload, "AAA", lineage)

    def test_ticker_evidence_digest_is_independently_checked(self):
        dates = [f"2022-01-{i:04d}" for i in range(subject.EXPECTED_SESSIONS)]
        lineage = {"ticker_universe": ["AAA"], "sessions": dates}
        payload = complete_checkpoint("AAA", lineage)
        payload["ticker_evidence_sha256"] = "0" * 64
        without_checkpoint_hash = dict(payload)
        without_checkpoint_hash.pop("checkpoint_sha256")
        payload["checkpoint_sha256"] = subject.canonical_sha(without_checkpoint_hash)
        with self.assertRaisesRegex(subject.BaselineContractError, "ticker evidence"):
            subject.validate_checkpoint_payload(payload, "AAA", lineage)

    def test_deterministic_aggregate_is_order_independent(self):
        dates = [f"2022-01-{i:04d}" for i in range(subject.EXPECTED_SESSIONS)]
        lineage = {"ticker_universe": ["AAA", "BBB"], "sessions": dates}
        first = [complete_checkpoint("AAA", lineage), complete_checkpoint("BBB", lineage)]
        with mock.patch.multiple(subject, EXPECTED_TICKERS=2, EXPECTED_TOTAL_FOLDS=8,
                                 EXPECTED_TOTAL_OOS=240):
            a = subject.build_final_manifest(lineage, first, executor_git_commit="a"*40,
                observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
            b = subject.build_final_manifest(lineage, list(reversed(first)),
                executor_git_commit="a"*40, observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(a["deterministic_evidence_sha256"], b["deterministic_evidence_sha256"])
        self.assertEqual(a["coverage"], {"tickers": 2, "folds": 8, "oos_observations": 240})
        self.assertEqual(a["side_effects"]["database_writes"], 0)

    def test_incomplete_denominator_is_rejected(self):
        with self.assertRaises(subject.BaselineContractError):
            subject.build_final_manifest({"ticker_universe": []}, [],
                executor_git_commit="a"*40, observed_at=datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
