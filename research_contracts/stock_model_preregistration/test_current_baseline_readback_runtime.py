import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import stat
import unittest
from unittest import mock

try:
    from . import produce_current_baseline_readback as producer
    from . import verify_current_baseline_readback as verifier
    from . import stock_model_preregistration_binding as binding
    from . import test_stock_model_preregistration_binding as fixtures
    from .current_baseline_readback_contract import REQUIRED_SELECT_QUERIES
except ImportError:
    import produce_current_baseline_readback as producer
    import verify_current_baseline_readback as verifier
    import stock_model_preregistration_binding as binding
    import test_stock_model_preregistration_binding as fixtures
    from current_baseline_readback_contract import REQUIRED_SELECT_QUERIES


class Result:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class FakeDatabase:
    def __init__(self, sessions, tickers=None, *, nonzero=False, run_drift=None):
        self.sessions = sessions
        self.tickers = tickers or [f"T{index:03d}" for index in range(474)]
        self.nonzero = nonzero
        self.run_drift = run_drift or {}
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        if "SELECT DISTINCT date" in sql:
            return Result(("date",), [(value,) for value in self.sessions])
        if "FROM predictive_screening_runs" in sql:
            rows = []
            for expected in binding.EXPECTED_ARMS:
                config = {**binding.EXPECTED_COMMON_CONFIG,
                          "signal_lookback_sessions": expected["signal_lookback_sessions"]}
                row = {
                    "screening_run_id": expected["run_id"],
                    "market_snapshot_id": binding.SNAPSHOT_ID,
                    "source_session_date": binding.SOURCE_SESSION_DATE,
                    "code_version": binding.SCREENING_CODE_VERSION,
                    "config_json": json.dumps(config, sort_keys=True),
                    "status": "VALIDATED",
                    "source_checksum_sha256": binding.SNAPSHOT_SHA256,
                    "snapshot_status": "VALIDATED",
                    "expected_ticker_count": 474,
                }
                row.update(self.run_drift)
                rows.append(tuple(row[name] for name in (
                    "screening_run_id", "market_snapshot_id", "source_session_date",
                    "code_version", "config_json", "status", "source_checksum_sha256",
                    "snapshot_status", "expected_ticker_count")))
            return Result(("screening_run_id", "market_snapshot_id", "source_session_date",
                           "code_version", "config_json", "status", "source_checksum_sha256",
                           "snapshot_status", "expected_ticker_count"), rows)
        if "predictive_screening_results" in sql:
            return Result(
                ("screening_run_id", "ticker"),
                [(run_id, ticker) for run_id in args for ticker in self.tickers],
            )
        if "sqlite_schema" in sql:
            return Result(("name", "type"), [(name, "table") for name in producer.DOWNSTREAM_TABLES])
        return Result(
            tuple(producer.DOWNSTREAM_TABLES),
            [tuple(1 if self.nonzero and index == 0 else 0
                   for index, _name in enumerate(producer.DOWNSTREAM_TABLES))],
        )


class CurrentBaselineReadbackRuntimeTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.V4BindingTests(
            methodName="test_happy_path_is_fixture_only_pass_and_zero_execution"
        )
        fixture.setUp()
        self.f = fixture
        self.model_commit = "4" * 40
        self.db = FakeDatabase(fixture.sessions, fixture.tickers)
        self.outputs = []

    def patches(self):
        f = self.f
        return mock.patch.multiple(
            binding,
            SESSION_SHA256=f.session_sha,
            PINNED_FINAL_MANIFEST_RAW_SHA256=f.final_raw,
            PINNED_IMMUTABLE_AUDIT_RAW_SHA256=f.immutable_raw,
            PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256=f.immutable["audit_evidence_sha256"],
            PINNED_EXECUTOR_COMMIT=f.executor_commit,
            PINNED_EXECUTOR_MANIFEST_RAW_SHA256="2" * 64,
            PINNED_CHECKPOINT_SET_SHA256="3" * 64,
            PINNED_DETERMINISTIC_EVIDENCE_SHA256=f.final["deterministic_evidence_sha256"],
            PINNED_BASELINE_LINEAGE_SHA256=binding.canonical_sha(f.lineage),
            PINNED_UNIVERSE_SHA256=f.lineage["ticker_universe_sha256"],
            PINNED_MODEL_SLICE_SHA256=binding.canonical_sha(f.sessions[-416:]),
        )

    def writer(self, _path, payload):
        self.outputs.append(copy.deepcopy(payload))
        raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True,
                          allow_nan=False) + "\n").encode()
        return hashlib.sha256(raw).hexdigest()

    def produce(self, db=None):
        times = iter((
            self.f.completion + timedelta(hours=2),
            self.f.completion + timedelta(hours=2, seconds=2),
            self.f.completion + timedelta(hours=2, seconds=3),
        ))
        def config_hash(raw):
            lookback = json.loads(raw)["signal_lookback_sessions"]
            return next((item["config_sha256"] for item in binding.EXPECTED_ARMS
                         if item["signal_lookback_sessions"] == lookback),
                        hashlib.sha256(raw.encode()).hexdigest())
        with (self.patches(),
              mock.patch.object(producer, "_config_sha256", side_effect=config_hash),
              mock.patch.object(producer, "write_json_once", side_effect=self.writer)):
            return producer.produce(
                db=db or self.db,
                final_manifest=self.f.final,
                immutable_audit=self.f.immutable,
                final_raw_sha256=self.f.final_raw,
                immutable_raw_sha256=self.f.immutable_raw,
                proposed_model_git_commit=self.model_commit,
                source_output=Path("/root/source.json"),
                artifact_output=Path("/root/artifact.json"),
                now=lambda: next(times),
            )

    def test_producer_runs_exact_five_selects_and_builds_two_bound_layers(self):
        source, artifact, source_sha, artifact_sha = self.produce()
        self.assertEqual(len(self.db.calls), 5)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql, _ in self.db.calls))
        self.assertEqual(source["select_query_ids"], list(REQUIRED_SELECT_QUERIES))
        self.assertEqual(len(REQUIRED_SELECT_QUERIES), 5)
        self.assertEqual(len(source["screening_runs_readback"]), 3)
        self.assertEqual(source["lineage_mapping"], self.f.lineage)
        self.assertEqual(source["coverage"], {"folds": 1896, "oos_observations": 56880,
                                              "tickers": 474})
        self.assertEqual(len(source["full_session_calendar_dates"]), 1246)
        self.assertEqual(source["model_session_dates"], self.f.sessions[-416:])
        self.assertEqual(artifact["evidence"]["source_readback_artifact_sha256"], source_sha)
        self.assertEqual(
            artifact["evidence"]["source_readback_embedded_evidence_sha256"],
            source["source_evidence_sha256"],
        )
        self.assertEqual(self.db.calls[-1][1], [self.model_commit] * 8)
        self.assertNotEqual(source_sha, source["source_evidence_sha256"])
        self.assertNotIn(artifact_sha, {source_sha, source["source_evidence_sha256"]})

        with self.patches():
            result = verifier.verify(
                source=source, source_raw_sha256=source_sha,
                artifact=artifact, artifact_raw_sha256=artifact_sha,
                final_manifest=self.f.final, final_raw_sha256=self.f.final_raw,
                immutable_audit=self.f.immutable,
                immutable_audit_raw_sha256=self.f.immutable_raw,
                proposed_model_git_commit=self.model_commit,
            )
        self.assertEqual(result["status"], "VERIFIED_SELECT_ONLY")
        self.assertFalse(result["model_fit_authorized"])
        self.assertEqual(result["source_file_sha256"], source_sha)
        self.assertEqual(result["artifact_file_sha256"], artifact_sha)

    def test_nonzero_downstream_for_proposed_commit_stops_before_outputs(self):
        with self.assertRaisesRegex(Exception, "already has downstream outputs"):
            self.produce(FakeDatabase(self.f.sessions, self.f.tickers, nonzero=True))
        self.assertEqual(self.outputs, [])

    def test_calendar_drift_stops_before_outputs(self):
        changed = list(self.f.sessions)
        changed[-1] = "2099-01-01"
        with self.assertRaisesRegex(Exception, "calendar differs"):
            self.produce(FakeDatabase(changed, self.f.tickers))
        self.assertEqual(self.outputs, [])

    def test_screening_or_snapshot_lineage_drift_stops_before_outputs(self):
        for drift in ({"status": "RUNNING"}, {"snapshot_status": "STAGING"},
                      {"source_checksum_sha256": "0" * 64},
                      {"expected_ticker_count": 473}):
            with self.subTest(drift=drift), self.assertRaisesRegex(
                    Exception, "screening/snapshot lineage differs"):
                self.produce(FakeDatabase(self.f.sessions, self.f.tickers, run_drift=drift))
            self.outputs.clear()

    def test_screening_config_hash_and_semantics_are_both_required(self):
        invalid = json.dumps({**binding.EXPECTED_COMMON_CONFIG,
                              "signal_lookback_sessions": 999}, sort_keys=True)
        with self.assertRaisesRegex(Exception, "configuration hash differs"):
            self.produce(FakeDatabase(
                self.f.sessions, self.f.tickers, run_drift={"config_json": invalid}
            ))
        self.assertEqual(self.outputs, [])

    def test_independent_verifier_rejects_resigned_source_and_cross_layer_substitution(self):
        source, artifact, source_sha, artifact_sha = self.produce()
        attacks = []
        changed = copy.deepcopy(source)
        changed["database_writes"] = 1
        body = dict(changed); body.pop("source_evidence_sha256")
        changed["source_evidence_sha256"] = binding.canonical_sha(body)
        attacks.append((changed, source_sha, artifact, artifact_sha))
        changed_screening = copy.deepcopy(source)
        changed_screening["screening_runs_readback"][0]["status"] = "RUNNING"
        body = dict(changed_screening); body.pop("source_evidence_sha256")
        changed_screening["source_evidence_sha256"] = binding.canonical_sha(body)
        attacks.append((changed_screening, source_sha, artifact, artifact_sha))
        substituted = copy.deepcopy(artifact)
        substituted["evidence"]["source_readback_artifact_sha256"] = "a" * 64
        attacks.append((source, source_sha, substituted, artifact_sha))
        for attacked_source, attacked_source_sha, attacked_artifact, attacked_artifact_sha in attacks:
            with self.subTest():
                with self.patches(), self.assertRaises(Exception):
                    verifier.verify(
                        source=attacked_source, source_raw_sha256=attacked_source_sha,
                        artifact=attacked_artifact, artifact_raw_sha256=attacked_artifact_sha,
                        final_manifest=self.f.final, final_raw_sha256=self.f.final_raw,
                        immutable_audit=self.f.immutable,
                        immutable_audit_raw_sha256=self.f.immutable_raw,
                        proposed_model_git_commit=self.model_commit,
                    )

    def test_input_gate_requires_exact_root_owned_0600(self):
        path = (Path.cwd() / "input.json").resolve()
        base = mock.Mock(st_uid=0, st_mode=stat.S_IFREG | 0o600, st_nlink=1)
        with (mock.patch.object(producer.os, "lstat", return_value=base),
              mock.patch.object(producer, "read_root_owned_json", return_value=({}, "a" * 64))):
            self.assertEqual(producer._read_exact_0600(path, "input")[1], "a" * 64)
        for mode, owner, links in ((0o640, 0, 1), (0o600, 1000, 1), (0o600, 0, 2)):
            metadata = mock.Mock(st_uid=owner, st_mode=stat.S_IFREG | mode, st_nlink=links)
            with mock.patch.object(producer.os, "lstat", return_value=metadata):
                with self.assertRaises(producer.ReadbackRuntimeError):
                    producer._read_exact_0600(path, "input")

    def test_query_guard_rejects_write_extra_and_unknown_query(self):
        for sql, query_id in (
            ("UPDATE x SET y=1", "SELECT_SESSION_CALENDAR"),
            ("SELECT 1; SELECT 2", "SELECT_SESSION_CALENDAR"),
            ("SELECT 1", "SELECT_EXTRA"),
        ):
            with self.subTest(sql=sql, query_id=query_id):
                with self.assertRaises(producer.ReadbackRuntimeError):
                    producer._query(self.db, sql, [], query_id)


if __name__ == "__main__":
    unittest.main()
