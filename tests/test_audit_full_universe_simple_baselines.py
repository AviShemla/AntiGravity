from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_full_universe_simple_baselines as subject


OBSERVED = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)
VERIFIED = OBSERVED + timedelta(minutes=30)


def session_calendar() -> list[str]:
    end = datetime(2026, 8, 25, tzinfo=timezone.utc)
    return [(end - timedelta(days=subject.EXPECTED_SESSIONS - 1 - position)).date().isoformat()
            for position in range(subject.EXPECTED_SESSIONS)]


def accumulator(observations: int) -> dict[str, object]:
    return {
        "observations": observations,
        "correct": observations // 2,
        "brier_sum": observations * 0.25,
        "log_loss_sum": observations * 0.69,
        "calibration_bins": [
            {"count": observations, "truth_sum": observations // 2,
             "probability_sum": observations * 0.5},
            *[{"count": 0, "truth_sum": 0, "probability_sum": 0.0} for _ in range(9)],
        ],
    }


def pair(value: dict[str, object]) -> dict[str, object]:
    return {"metrics": subject._metrics(value), "accumulator": value}


def checkpoint(ticker: str, lineage_sha: str, sessions: list[str]) -> dict[str, object]:
    folds = []
    first_test = len(sessions) - 120
    for number in range(1, 5):
        test_start = first_test + (number - 1) * 30
        train_end = test_start - 7
        train_start = train_end - 289
        fold_acc = {name: accumulator(30) for name in subject.MODEL_NAMES}
        folds.append({
            "fold_number": number,
            "train_start_date": sessions[train_start],
            "train_end_date": sessions[train_end - 1],
            "test_start_date": sessions[test_start],
            "test_end_date": sessions[test_start + 29],
            "purge_sessions": 7,
            "train_direction_observations": 289,
            "test_observations": 30,
            "training_positive_rate": 145 / 289,
            "baselines": {name: pair(value) for name, value in fold_acc.items()},
        })
    aggregate = {
        name: pair(subject._merge_accumulators(
            fold["baselines"][name]["accumulator"] for fold in folds))
        for name in subject.MODEL_NAMES
    }
    result: dict[str, object] = {
        "contract_id": subject.PRODUCER_CONTRACT_ID,
        "ticker": ticker,
        "input": {"row_count": 1246, "return_rows_sha256": "1" * 64},
        "coverage": {"folds": 4, "oos_observations": 120},
        "folds": folds,
        "aggregate": aggregate,
        "persisted_probabilities": 0,
    }
    result["ticker_evidence_sha256"] = subject.canonical_sha(result)
    result["lineage_sha256"] = lineage_sha
    result["checkpoint_sha256"] = subject.canonical_sha(result)
    return result


def refresh_checkpoint(payload: dict[str, object]) -> None:
    payload.pop("checkpoint_sha256", None)
    lineage = payload.pop("lineage_sha256")
    payload.pop("ticker_evidence_sha256", None)
    payload["ticker_evidence_sha256"] = subject.canonical_sha(payload)
    payload["lineage_sha256"] = lineage
    payload["checkpoint_sha256"] = subject.canonical_sha(payload)


def manifest(checkpoints: dict[str, dict[str, object]], commit: str) -> dict[str, object]:
    ordered = [checkpoints[ticker] for ticker in sorted(checkpoints)]
    merged = {
        name: subject._merge_accumulators(
            item["aggregate"][name]["accumulator"] for item in ordered)
        for name in subject.MODEL_NAMES
    }
    deterministic: dict[str, object] = {
        "contract_id": subject.PRODUCER_CONTRACT_ID,
        "lineage_sha256": "a" * 64,
        "coverage": {"tickers": 2, "folds": 8, "oos_observations": 240},
        "aggregate": {name: pair(value) for name, value in merged.items()},
        "ticker_checkpoints": [
            {"ticker": item["ticker"], "checkpoint_sha256": item["checkpoint_sha256"]}
            for item in ordered
        ],
        "side_effects": dict(subject.ZERO_SIDE_EFFECTS),
    }
    return {
        **deterministic,
        "deterministic_evidence_sha256": subject.canonical_sha(deterministic),
        "runtime": {"executor_git_commit": commit,
                    "observed_at_utc": OBSERVED.isoformat()},
    }


def refresh_manifest_digest(value: dict[str, object]) -> None:
    runtime = value.pop("runtime")
    value.pop("deterministic_evidence_sha256", None)
    value["deterministic_evidence_sha256"] = subject.canonical_sha(value)
    value["runtime"] = runtime


class ContractFixture(unittest.TestCase):
    def setUp(self):
        self.constants = mock.patch.multiple(
            subject, EXPECTED_TICKERS=2, EXPECTED_TOTAL_FOLDS=8, EXPECTED_TOTAL_OOS=240)
        self.constants.start()
        self.addCleanup(self.constants.stop)
        self.commit = "b" * 40
        self.sessions = session_calendar()
        self.checkpoints = {
            ticker: checkpoint(ticker, "a" * 64, self.sessions) for ticker in ("AAA", "BBB")
        }
        self.manifest = manifest(self.checkpoints, self.commit)

    def rebind(self, ticker: str) -> None:
        value = self.checkpoints[ticker]
        refresh_checkpoint(value)
        entry = next(item for item in self.manifest["ticker_checkpoints"]
                     if item["ticker"] == ticker)
        entry["checkpoint_sha256"] = value["checkpoint_sha256"]
        refresh_manifest_digest(self.manifest)


class PayloadAuditTests(ContractFixture):
    def test_exact_payloads_reconcile_independently(self):
        result = subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                           self.sessions, verified_at=VERIFIED)
        self.assertEqual(result["coverage"], {"tickers": 2, "folds": 8,
                                              "oos_observations": 240})

    def test_checkpoint_digest_tamper_is_rejected(self):
        self.checkpoints["AAA"]["input"]["row_count"] = 1
        with self.assertRaisesRegex(subject.AuditError, "checkpoint digest"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_ticker_digest_tamper_is_rejected_even_with_refreshed_outer_digest(self):
        self.checkpoints["AAA"]["ticker_evidence_sha256"] = "0" * 64
        value = self.checkpoints["AAA"]
        value.pop("checkpoint_sha256")
        value["checkpoint_sha256"] = subject.canonical_sha(value)
        self.manifest["ticker_checkpoints"][0]["checkpoint_sha256"] = value["checkpoint_sha256"]
        refresh_manifest_digest(self.manifest)
        with self.assertRaisesRegex(subject.AuditError, "ticker digest"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_checkpoint_aggregate_must_reconcile_with_folds(self):
        value = self.checkpoints["AAA"]
        value["aggregate"]["majority_direction"]["accumulator"]["correct"] += 1
        value["aggregate"]["majority_direction"]["metrics"] = subject._metrics(
            value["aggregate"]["majority_direction"]["accumulator"])
        refresh_checkpoint(value)
        self.manifest["ticker_checkpoints"][0]["checkpoint_sha256"] = value["checkpoint_sha256"]
        refresh_manifest_digest(self.manifest)
        with self.assertRaisesRegex(subject.AuditError, "aggregate does not reconcile"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_fold_denominator_is_not_accepted_via_rehashed_artifacts(self):
        value = self.checkpoints["AAA"]
        value["folds"][0]["train_direction_observations"] = 125
        value["folds"][0]["training_positive_rate"] = 63 / 125
        refresh_checkpoint(value)
        self.manifest["ticker_checkpoints"][0]["checkpoint_sha256"] = value["checkpoint_sha256"]
        refresh_manifest_digest(self.manifest)
        with self.assertRaisesRegex(subject.AuditError, "fold denominator"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_global_aggregate_must_reconcile_with_checkpoints(self):
        aggregate = self.manifest["aggregate"]["lag1_logistic"]
        aggregate["accumulator"]["correct"] += 1
        aggregate["metrics"] = subject._metrics(aggregate["accumulator"])
        refresh_manifest_digest(self.manifest)
        with self.assertRaisesRegex(subject.AuditError, "final lag1_logistic aggregate"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_side_effect_declaration_must_be_exactly_zero(self):
        self.manifest["side_effects"]["predictions"] = 1
        refresh_manifest_digest(self.manifest)
        with self.assertRaisesRegex(subject.AuditError, "side-effect boundary"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_runtime_commit_must_match_executor_manifest(self):
        with self.assertRaisesRegex(subject.AuditError, "runtime Git commit"):
            subject.validate_manifest(self.manifest, self.checkpoints, "c" * 40,
                                      self.sessions, verified_at=VERIFIED)

    def test_missing_or_extra_ticker_is_rejected(self):
        del self.checkpoints["BBB"]
        with self.assertRaisesRegex(subject.AuditError, "file/universe coverage"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_rehashed_row_count_below_producer_minimum_is_rejected(self):
        self.checkpoints["AAA"]["input"]["row_count"] = 119
        self.rebind("AAA")
        with self.assertRaisesRegex(subject.AuditError, "input identity"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_rehashed_training_count_above_window_is_rejected(self):
        fold = self.checkpoints["AAA"]["folds"][0]
        fold["train_direction_observations"] = 290
        fold["training_positive_rate"] = 0.5
        self.rebind("AAA")
        with self.assertRaisesRegex(subject.AuditError, "fold denominator"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_rehashed_non_integer_training_rate_is_rejected(self):
        self.checkpoints["AAA"]["folds"][0]["training_positive_rate"] = 0.5
        self.rebind("AAA")
        with self.assertRaisesRegex(subject.AuditError, "integer-consistent"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_rehashed_fold_dates_must_match_live_calendar(self):
        self.checkpoints["AAA"]["folds"][0]["test_start_date"] = self.sessions[-1]
        self.rebind("AAA")
        with self.assertRaisesRegex(subject.AuditError, "live calendar"):
            subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                      self.sessions, verified_at=VERIFIED)

    def test_audit_time_must_follow_completion_within_one_hour(self):
        for invalid in (OBSERVED - timedelta(seconds=1), OBSERVED + timedelta(hours=1,
                                                                              seconds=1)):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(subject.AuditError, "one-hour"):
                    subject.validate_manifest(self.manifest, self.checkpoints, self.commit,
                                              self.sessions, verified_at=invalid)


class Result:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = list(rows)


class FakeDB:
    def __init__(self, sessions: list[str], *, present: set[str] | None = None,
                 counts: dict[str, int] | None = None):
        self.sessions = sessions
        self.present = present if present is not None else {
            "model_runs", "model_scorecards", "etf_prior_lineage",
            "stock_prediction_decision_audits", "stock_prediction_criterion_audits",
        }
        self.counts = counts or {name: 0 for name in subject.DOWNSTREAM_TABLES}
        self.calls: list[tuple[str, list[object]]] = []

    def execute(self, sql, args):
        self.calls.append((sql, args))
        if "market_daily_features" in sql:
            return Result(["date"], [[value] for value in self.sessions])
        if "sqlite_schema" in sql:
            return Result(["name", "type"],
                          [[name, "table"] for name in sorted(self.present)])
        columns = [name for name in subject.DOWNSTREAM_TABLES if name in self.present]
        return Result(columns, [[self.counts[name] for name in columns]])


class LiveReadbackTests(unittest.TestCase):
    def setUp(self):
        self.sessions = session_calendar()
        self.sha_patch = mock.patch.object(subject, "SESSION_SHA256",
                                          subject.canonical_sha(self.sessions))
        self.sha_patch.start()
        self.addCleanup(self.sha_patch.stop)

    def test_exact_calendar_and_zero_downstream_readback(self):
        db = FakeDB(self.sessions)
        evidence = subject.read_live_evidence(db, "b" * 40)
        self.assertEqual(evidence["session_count"], 1246)
        self.assertEqual(evidence["downstream_counts"],
                         {name: 0 for name in subject.DOWNSTREAM_TABLES})
        self.assertEqual(evidence["schema_presence"]["model_runs"], "present")
        self.assertEqual(evidence["schema_presence"]["execution_plans"], "schema_absent")
        self.assertEqual(evidence["select_statements"], 3)
        self.assertEqual(len(db.calls), 3)
        self.assertEqual(db.calls[0][1], [subject.SNAPSHOT_ID])
        self.assertEqual(db.calls[1][1], list(subject.DOWNSTREAM_TABLES))
        self.assertEqual(db.calls[2][1], ["b" * 40] * 5)

    def test_wrong_calendar_column_or_nonzero_downstream_is_rejected(self):
        db = FakeDB(self.sessions)
        db.execute = mock.Mock(return_value=Result(["wrong"], []))
        with self.assertRaisesRegex(subject.AuditError, "column contract"):
            subject.read_live_evidence(db, "b" * 40)
        counts = {name: 0 for name in subject.DOWNSTREAM_TABLES}
        counts["stock_prediction_decision_audits"] = 1
        with self.assertRaisesRegex(subject.AuditError, "unauthorized downstream"):
            subject.read_live_evidence(FakeDB(self.sessions, counts=counts), "b" * 40)

    def test_dependent_table_without_parent_is_rejected(self):
        with self.assertRaisesRegex(subject.AuditError, "without required parent"):
            subject.read_live_evidence(FakeDB(self.sessions, present={"execution_events"}),
                                       "b" * 40)

    def test_select_guard_rejects_mutation_and_comments(self):
        db = mock.Mock()
        for sql in ("DELETE FROM x", "SELECT * FROM x;", "SELECT * FROM x -- unsafe"):
            with self.assertRaisesRegex(subject.AuditError, "SELECT-only"):
                subject.select_only(db, sql, [], "guard")
        db.execute.assert_not_called()


class ExecutorAndJsonTests(unittest.TestCase):
    def test_executor_manifest_requires_producer_artifacts(self):
        payload = {
            "executor_git_commit": "a" * 40,
            "artifacts": {name: "b" * 64 for name in subject.REQUIRED_EXECUTOR_ARTIFACTS},
        }
        self.assertEqual(subject.validate_executor_manifest(payload), "a" * 40)
        del payload["artifacts"]["full_universe_simple_baselines.py"]
        with self.assertRaisesRegex(subject.AuditError, "closure"):
            subject.validate_executor_manifest(payload)

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        with self.assertRaisesRegex(subject.AuditError, "duplicate key"):
            subject.decode_json(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(subject.AuditError, "non-finite"):
            subject.decode_json(b'{"a":NaN}')

    def test_credentials_require_root_owned_mode_600_single_link(self):
        path = mock.Mock()
        path.is_absolute.return_value = True
        path.is_symlink.return_value = False
        path.read_text.return_value = (
            "TURSO_DATABASE_URL=https://example.invalid/v2/pipeline\n"
            "TURSO_AUTH_TOKEN=unit-test-placeholder\n")
        secure = mock.Mock(st_mode=subject.stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)
        with mock.patch.object(subject.os, "lstat", return_value=secure):
            self.assertEqual(subject.production_credentials(path),
                             ("https://example.invalid/v2/pipeline", "unit-test-placeholder"))
        insecure = mock.Mock(st_mode=subject.stat.S_IFREG | 0o644, st_uid=0, st_nlink=1)
        with mock.patch.object(subject.os, "lstat", return_value=insecure):
            with self.assertRaisesRegex(subject.AuditError, "root-owned mode-0600"):
                subject.production_credentials(path)

    def test_endpoint_normalization_is_strict_and_idempotent(self):
        self.assertEqual(subject.normalize_turso_pipeline_endpoint(
            "libsql://oracle.example"),
            "https://oracle.example/v2/pipeline")
        self.assertEqual(subject.normalize_turso_pipeline_endpoint(
            "https://oracle.example/v2/pipeline"),
            "https://oracle.example/v2/pipeline")
        for value in (
                "http://oracle.example", "libsql://user@oracle.example",
                "libsql://oracle.example/not-pipeline", " libsql://oracle.example",
                "https://oracle.example:443", "https://oracle.example:abc",
                "https://oracle.example\\evil", "https://user%40oracle.example",
                "https://oracle.example?query=1", "https://oracle.example#fragment",
                "https://oracle.example?", "https://oracle.example#",
                "https://oracle.example/v2/pipeline?",
                "libsql://oracle.example/v2/pipeline#",
                "https://oracle.example\n.evil", "https://oracle.example\r.evil",
                "https://oracle.example\t.evil", "https://oracle.example\x00.evil",
                "https://ORACLE.example", "https://-oracle.example",
                "https://oracle-.example",
        ):
            with self.assertRaises(subject.AuditError):
                subject.normalize_turso_pipeline_endpoint(value)


class FileSetTests(ContractFixture):
    def test_extra_checkpoint_file_is_rejected_before_payload_acceptance(self):
        class FakeDirectory:
            def __init__(self, names):
                self.names = names

            def iterdir(self):
                return [Path(name) for name in self.names]

            def __truediv__(self, name):
                return Path("C:/checkpoints") / name

        names = [subject.checkpoint_name(ticker) for ticker in self.checkpoints]
        checkpoint_dir = FakeDirectory([*names, "stale.tmp"])
        final_path = Path("C:/artifacts/final.json")
        executor_path = Path("C:/executor/executor.json")
        executor = {"executor_git_commit": self.commit,
                    "artifacts": {name: "1" * 64
                                  for name in subject.REQUIRED_EXECUTOR_ARTIFACTS}}

        def fake_read(path, _label):
            if path == executor_path:
                return executor, "3" * 64
            if path == final_path:
                return self.manifest, "4" * 64
            ticker = next(t for t in self.checkpoints
                          if subject.checkpoint_name(t) == path.name)
            return self.checkpoints[ticker], "5" * 64

        live = {"sessions": self.sessions, "session_count": 1246,
                "session_sha256": subject.canonical_sha(self.sessions),
                "schema_presence": {name: "present" for name in subject.DOWNSTREAM_TABLES},
                "downstream_counts": {name: 0 for name in subject.DOWNSTREAM_TABLES},
                "select_statements": 3}
        with mock.patch.object(subject, "_secure_directory", side_effect=lambda p, _l: p), \
                mock.patch.object(subject, "verify_runtime_boundary",
                                  return_value=(self.commit, executor, "3" * 64)), \
                mock.patch.object(subject, "read_live_evidence", return_value=live), \
                mock.patch.object(subject, "_read_secure_json", side_effect=fake_read), \
                mock.patch.object(subject, "_verify_executor_artifacts"):
            with self.assertRaisesRegex(subject.AuditError, "missing or extra"):
                subject.audit_files(object(), checkpoint_dir, final_path, executor_path,
                                    verified_at=datetime.now(timezone.utc))


class CliTests(unittest.TestCase):
    def test_root_guard_precedes_auditor(self):
        auditor = mock.Mock()
        arguments = [
            "--checkpoint-dir", str(Path.cwd().resolve()),
            "--final-manifest", str((Path.cwd() / "final.json").resolve()),
            "--executor-manifest", str((Path.cwd() / "executor.json").resolve()),
            "--audit-evidence", str((Path.cwd() / "audit.json").resolve()),
            "--env-file", str((Path.cwd() / "runtime.env").resolve()),
        ]
        self.assertEqual(subject.main(arguments, effective_uid=lambda: 1000,
                                      auditor=auditor), 1)
        auditor.assert_not_called()

    def test_cli_writes_only_after_audit_success(self):
        auditor = mock.Mock(return_value={"stage": "VERIFIED"})
        writer = mock.Mock()
        runtime_verifier = mock.Mock()
        credentials = mock.Mock(return_value=(
            "libsql://example.invalid", "unit-test-placeholder"))
        db = object()
        client_factory = mock.Mock(return_value=db)
        root = Path.cwd().resolve()
        arguments = [
            "--checkpoint-dir", str(root),
            "--final-manifest", str(root / "absent-final.json"),
            "--executor-manifest", str(root / "absent-executor.json"),
            "--audit-evidence", str(root / "absent-audit.json"),
            "--env-file", str(root / "absent-runtime.env"),
        ]
        self.assertEqual(subject.run_cli(arguments, effective_uid=lambda: 0,
                                         runtime_verifier=runtime_verifier,
                                         credentials_loader=credentials,
                                         client_factory=client_factory,
                                         auditor=auditor, writer=writer,
                                         now=lambda: VERIFIED), 0)
        runtime_verifier.assert_called_once_with(root / "absent-executor.json")
        credentials.assert_called_once_with(root / "absent-runtime.env")
        client_factory.assert_called_once_with(
            "https://example.invalid/v2/pipeline", "unit-test-placeholder", 120.0)
        auditor.assert_called_once_with(db, root, root / "absent-final.json",
                                        root / "absent-executor.json", verified_at=VERIFIED)
        writer.assert_called_once_with(root / "absent-audit.json", {"stage": "VERIFIED"})

    def test_runtime_boundary_failure_precedes_credentials_and_client(self):
        root = Path.cwd().resolve()
        credentials = mock.Mock()
        client_factory = mock.Mock()
        arguments = [
            "--checkpoint-dir", str(root),
            "--final-manifest", str(root / "absent-final.json"),
            "--executor-manifest", str(root / "absent-executor.json"),
            "--audit-evidence", str(root / "absent-audit.json"),
            "--env-file", str(root / "absent-runtime.env"),
        ]
        with self.assertRaisesRegex(subject.AuditError, "boundary"):
            subject.run_cli(arguments, effective_uid=lambda: 0,
                            runtime_verifier=mock.Mock(
                                side_effect=subject.AuditError("boundary rejected")),
                            credentials_loader=credentials, client_factory=client_factory)
        credentials.assert_not_called()
        client_factory.assert_not_called()

    def test_main_error_is_redacted(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            status = subject.main([], effective_uid=lambda: 0)
        self.assertEqual(status, 1)
        self.assertNotIn("token", stderr.getvalue().lower())
        self.assertNotIn("password", stderr.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
