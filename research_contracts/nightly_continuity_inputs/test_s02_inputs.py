from __future__ import annotations

import copy
import hashlib
import json
import uuid
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

try:
    from research_contracts.nightly_continuity_inputs import (
        turso_idempotency_preflight as preflight_module,
    )
    from research_contracts.nightly_continuity.continuity_controller import (
        ContractError as ConsumerContractError,
        load_calendar as consumer_load_calendar,
        validate_snapshot_evidence as consumer_validate_snapshot_evidence,
    )
    from research_contracts.nightly_continuity_inputs.nyse_calendar_artifact import (
        CalendarContractError,
        build_calendar_artifact,
        canonical_bytes as calendar_bytes,
        load_ruleset,
        validate_calendar_artifact,
    )
    from research_contracts.nightly_continuity_inputs.turso_idempotency_preflight import (
        APPROVAL_SQL,
        QUERY_SET_SHA256,
        SCREENING_SQL,
        SNAPSHOT_SQL,
        PreflightContractError,
        QueryResult,
        TursoSelectReader,
        _read_environment,
        _read_process_environment,
        _write_once,
        build_preflight_evidence,
        canonical_bytes as preflight_bytes,
        normalize_turso_endpoint,
        validate_preflight_evidence,
        main as preflight_main,
    )
except ModuleNotFoundError:
    from s02_recurring_deployment_impl import (
        turso_idempotency_preflight as preflight_module,
    )
    from nightly_continuity_impl.continuity_controller import (
        ContractError as ConsumerContractError,
        load_calendar as consumer_load_calendar,
        validate_snapshot_evidence as consumer_validate_snapshot_evidence,
    )
    from s02_recurring_deployment_impl.nyse_calendar_artifact import (
        CalendarContractError,
        build_calendar_artifact,
        canonical_bytes as calendar_bytes,
        load_ruleset,
        validate_calendar_artifact,
    )
    from s02_recurring_deployment_impl.turso_idempotency_preflight import (
        APPROVAL_SQL,
        QUERY_SET_SHA256,
        SCREENING_SQL,
        SNAPSHOT_SQL,
        PreflightContractError,
        QueryResult,
        TursoSelectReader,
        _read_environment,
        _read_process_environment,
        _write_once,
        build_preflight_evidence,
        canonical_bytes as preflight_bytes,
        normalize_turso_endpoint,
        validate_preflight_evidence,
        main as preflight_main,
    )


HERE = Path(__file__).resolve().parent
RULESET_PATH = HERE / "nyse_ruleset_2026.json"
IO_ROOT = HERE / "_test_io"


def setUpModule() -> None:
    IO_ROOT.mkdir(mode=0o700, exist_ok=True)
    if hasattr(IO_ROOT, "chmod"):
        IO_ROOT.chmod(0o700)


class FakeReader:
    def __init__(self, snapshots=(), approvals=0, screenings=0):
        self.snapshots = tuple(snapshots)
        self.approvals = approvals
        self.screenings = screenings
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, tuple(args)))
        if sql == SNAPSHOT_SQL:
            return QueryResult(("snapshot_id", "status"), self.snapshots)
        if sql == APPROVAL_SQL:
            return QueryResult(("approval_count",), ((self.approvals,),))
        if sql == SCREENING_SQL:
            return QueryResult(("screening_count",), ((self.screenings,),))
        raise AssertionError(sql)


class FakeResponse:
    status = 200

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


class PreflightTests(unittest.TestCase):
    observed = datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)

    def test_absent_snapshot_exact_consumer_contract(self):
        reader = FakeReader()
        raw = build_preflight_evidence(
            reader, source_session="2026-08-26", observed_at=self.observed
        )
        self.assertEqual(raw["contract_id"], "codex-market-ingestion-idempotency-preflight-v1")
        self.assertEqual(raw["database_writes"], 0)
        self.assertEqual(raw["query_set_sha256"], QUERY_SET_SHA256)
        state = consumer_validate_snapshot_evidence(raw, source_session="2026-08-26")
        self.assertEqual(state.snapshot_count, 0)
        self.assertEqual(
            reader.calls,
            [
                (SNAPSHOT_SQL, ("MARKET_FEATURES", "2026-08-26")),
                (APPROVAL_SQL, ("MARKET_FEATURES", "2026-08-26")),
                (SCREENING_SQL, ("MARKET_FEATURES", "2026-08-26")),
            ],
        )

    def test_unique_staging_snapshot_exact_consumer_contract(self):
        raw = build_preflight_evidence(
            FakeReader((("snapshot-1", "STAGING"),)),
            source_session="2026-08-26",
            observed_at=self.observed,
        )
        state = consumer_validate_snapshot_evidence(raw, source_session="2026-08-26")
        self.assertEqual((state.snapshot_id, state.status), ("snapshot-1", "STAGING"))

    def test_duplicate_snapshot_is_preserved_for_consumer_fail_closed(self):
        raw = build_preflight_evidence(
            FakeReader((("one", "STAGING"), ("two", "STAGING"))),
            source_session="2026-08-26",
            observed_at=self.observed,
        )
        self.assertEqual(raw["snapshot_count"], 2)
        self.assertIsNone(raw["snapshot_id"])
        with self.assertRaises(ConsumerContractError):
            consumer_validate_snapshot_evidence(raw, source_session="2026-08-26")

    def test_downstream_counts_are_not_silently_zeroed(self):
        raw = build_preflight_evidence(
            FakeReader((("snapshot-1", "STAGING"),), approvals=1, screenings=2),
            source_session="2026-08-26",
            observed_at=self.observed,
        )
        self.assertEqual((raw["approval_count"], raw["screening_count"]), (1, 2))

    def test_result_shape_mismatch_rejected(self):
        class BadReader(FakeReader):
            def execute(self, sql, args):
                if sql == SNAPSHOT_SQL:
                    return QueryResult(("wrong",), ())
                return super().execute(sql, args)

        with self.assertRaises(PreflightContractError):
            build_preflight_evidence(
                BadReader(), source_session="2026-08-26", observed_at=self.observed
            )

    def test_session_must_be_real_canonical_date(self):
        for value in ("2026-02-30", "2026-8-1", "../../etc/passwd"):
            with self.subTest(value=value), self.assertRaises(PreflightContractError):
                build_preflight_evidence(
                    FakeReader(), source_session=value, observed_at=self.observed
                )

    def test_evidence_validator_rejects_statement_tamper(self):
        raw = build_preflight_evidence(
            FakeReader(), source_session="2026-08-26", observed_at=self.observed
        )
        raw["statements"] = ["SELECT 1"]
        with self.assertRaises(PreflightContractError):
            validate_preflight_evidence(raw, source_session="2026-08-26")

    def test_evidence_is_canonical_and_token_free(self):
        token = "secret-token-marker"
        raw = build_preflight_evidence(
            FakeReader(), source_session="2026-08-26", observed_at=self.observed
        )
        encoded = preflight_bytes(raw)
        self.assertEqual(encoded, preflight_bytes(json.loads(encoded)))
        self.assertNotIn(token.encode(), encoded)

    def test_endpoint_normalization(self):
        self.assertEqual(
            normalize_turso_endpoint("libsql://example.turso.io"),
            "https://example.turso.io/v2/pipeline",
        )
        self.assertEqual(
            normalize_turso_endpoint("https://example.turso.io/v2/pipeline"),
            "https://example.turso.io/v2/pipeline",
        )

    def test_endpoint_rejects_credentials_and_arbitrary_path(self):
        for value in (
            "http://example.turso.io",
            "https://user:pass@example.turso.io",
            "https://example.turso.io/other",
        ):
            with self.subTest(value=value), self.assertRaises(PreflightContractError):
                normalize_turso_endpoint(value)

    def test_http_reader_has_fixed_select_payload(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            body = {
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "result": {
                                "cols": [{"name": "approval_count"}],
                                "rows": [[{"type": "integer", "value": "0"}]],
                            }
                        },
                    }
                ]
            }
            return FakeResponse(json.dumps(body).encode())

        reader = TursoSelectReader(
            "libsql://example.turso.io", "secret-token-marker", opener=opener
        )
        result = reader.execute(APPROVAL_SQL, ("MARKET_FEATURES", "2026-08-26"))
        self.assertEqual(result.rows, ((0,),))
        payload = json.loads(captured["request"].data)
        self.assertEqual(payload["requests"][0]["stmt"]["sql"], APPROVAL_SQL)
        self.assertEqual(payload["requests"][1], {"type": "close"})
        self.assertNotIn("secret-token-marker", json.dumps(payload))

    def test_http_reader_rejects_non_select_before_transport(self):
        calls = []
        reader = TursoSelectReader(
            "libsql://example.turso.io", "token", opener=lambda *a, **k: calls.append(1)
        )
        with self.assertRaises(PreflightContractError):
            reader.execute("UPDATE model_input_snapshots SET status='VALIDATED'", ())
        self.assertEqual(calls, [])

    def test_write_once_creates_canonical_file_and_rejects_overwrite(self):
        path = IO_ROOT / f"preflight-{uuid.uuid4().hex}.json"
        raw = build_preflight_evidence(
            FakeReader(), source_session="2026-08-26", observed_at=self.observed
        )
        try:
            _write_once(path, preflight_bytes(raw))
            self.assertEqual(path.read_bytes(), preflight_bytes(raw))
            with self.assertRaises(PreflightContractError):
                _write_once(path, preflight_bytes(raw))
        finally:
            if path.exists():
                path.unlink()

    def test_environment_file_parser_reads_only_required_credentials(self):
        path = IO_ROOT / f"environment-{uuid.uuid4().hex}.env"
        try:
            path.write_text(
                "TURSO_DATABASE_URL=libsql://example.turso.io\n"
                "TURSO_AUTH_TOKEN=secret-token-marker\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            endpoint, token = _read_environment(path)
            self.assertEqual(endpoint, "libsql://example.turso.io")
            self.assertEqual(token, "secret-token-marker")
        finally:
            if path.exists():
                path.unlink()

    def test_environment_file_rejects_duplicate_credentials(self):
        path = IO_ROOT / f"environment-{uuid.uuid4().hex}.env"
        try:
            path.write_text(
                "TURSO_DATABASE_URL=libsql://one\n"
                "TURSO_DATABASE_URL=libsql://two\n"
                "TURSO_AUTH_TOKEN=token\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            with self.assertRaises(PreflightContractError):
                _read_environment(path)
        finally:
            if path.exists():
                path.unlink()

    def test_protected_process_environment_contract(self):
        with patch.dict(
            "os.environ",
            {
                "TURSO_DATABASE_URL": "libsql://example.turso.io",
                "TURSO_AUTH_TOKEN": "secret-token-marker",
            },
            clear=True,
        ):
            self.assertEqual(
                _read_process_environment(),
                ("libsql://example.turso.io", "secret-token-marker"),
            )

    def test_cli_requires_root_before_reading_credentials_or_transport(self):
        output = IO_ROOT / f"preflight-{uuid.uuid4().hex}.json"
        environment = IO_ROOT / "does-not-exist.env"
        errors = StringIO()
        with patch.object(
            preflight_module,
            "_require_root",
            side_effect=PreflightContractError("preflight executable must run as root"),
        ), redirect_stderr(errors):
            exit_code = preflight_main(
                [
                    "--source-session",
                    "2026-08-26",
                    "--output",
                    str(output),
                    "--environment-file",
                    str(environment),
                ]
            )
        self.assertEqual(exit_code, 2)
        self.assertFalse(output.exists())
        self.assertIn("must run as root", errors.getvalue())

    def test_exact_continuity_controller_two_argument_invocation(self):
        output = IO_ROOT / f"preflight-{uuid.uuid4().hex}.json"
        written = []
        reader = FakeReader((("snapshot-1", "STAGING"),))
        standard_output = StringIO()
        try:
            with patch.object(
                preflight_module, "_require_root"
            ), patch.object(
                preflight_module, "_read_process_environment",
                return_value=("libsql://example.turso.io", "token"),
            ), patch.object(
                preflight_module, "TursoSelectReader",
                return_value=reader,
            ), patch.object(
                preflight_module, "_write_once",
                side_effect=lambda path, payload: written.append((path, payload)),
            ), redirect_stdout(standard_output):
                exit_code = preflight_main(
                    ["--source-session", "2026-08-26", "--output", str(output)]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(written[0][0], output)
            raw = json.loads(written[0][1])
            consumer_validate_snapshot_evidence(raw, source_session="2026-08-26")
        finally:
            if output.exists():
                output.unlink()


class CalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ruleset_bytes = RULESET_PATH.read_bytes()
        cls.ruleset_sha = hashlib.sha256(cls.ruleset_bytes).hexdigest()
        cls.ruleset = load_ruleset(RULESET_PATH, cls.ruleset_sha)
        cls.artifact = build_calendar_artifact(
            cls.ruleset, ruleset_sha256=cls.ruleset_sha
        )
        cls.by_date = {item["session_date"]: item for item in cls.artifact["sessions"]}

    def test_ruleset_and_artifact_are_canonical(self):
        self.assertEqual(self.ruleset_bytes, calendar_bytes(json.loads(self.ruleset_bytes)))
        encoded = calendar_bytes(self.artifact)
        self.assertEqual(encoded, calendar_bytes(json.loads(encoded)))

    def test_explicit_validity_horizon_and_pins(self):
        self.assertEqual(self.artifact["valid_from_utc"], "2026-01-01T00:00:00Z")
        self.assertEqual(self.artifact["valid_through_utc"], "2026-12-31T23:59:59Z")
        self.assertEqual(self.artifact["ruleset_sha256"], self.ruleset_sha)
        self.assertEqual(self.artifact["dependency_pins"]["external_runtime_packages"], [])
        self.assertEqual(
            self.artifact["data_provenance"]["retrieval_status"],
            "VERIFIED_PRIMARY_NYSE_2026",
        )

    def test_dst_spring_transition_has_real_utc_closes(self):
        self.assertEqual(self.by_date["2026-03-06"]["close_utc"], "2026-03-06T21:00:00Z")
        self.assertEqual(self.by_date["2026-03-09"]["close_utc"], "2026-03-09T20:00:00Z")

    def test_dst_fall_transition_has_real_utc_closes(self):
        self.assertEqual(self.by_date["2026-10-30"]["close_utc"], "2026-10-30T20:00:00Z")
        self.assertEqual(self.by_date["2026-11-02"]["close_utc"], "2026-11-02T21:00:00Z")

    def test_holidays_are_absent(self):
        for holiday in ("2026-01-01", "2026-04-03", "2026-06-19", "2026-07-03", "2026-11-26", "2026-12-25"):
            with self.subTest(holiday=holiday):
                self.assertNotIn(holiday, self.by_date)

    def test_early_closes_are_real_utc_instants(self):
        self.assertEqual(self.by_date["2026-11-27"]["close_utc"], "2026-11-27T18:00:00Z")
        self.assertEqual(self.by_date["2026-12-24"]["close_utc"], "2026-12-24T18:00:00Z")
        self.assertTrue(all(self.by_date[item]["close_type"] == "EARLY" for item in ("2026-11-27", "2026-12-24")))

    def test_july_2_is_regular_not_early_close(self):
        row = self.by_date["2026-07-02"]
        self.assertEqual(row["close_type"], "REGULAR")
        self.assertEqual(row["close_utc"], "2026-07-02T20:00:00Z")
        self.assertIsNone(row["exception_reason"])

    def test_weekends_are_absent_and_session_count_is_exact(self):
        self.assertNotIn("2026-08-29", self.by_date)
        self.assertNotIn("2026-08-30", self.by_date)
        self.assertEqual(len(self.by_date), 251)

    def test_validator_detects_close_tamper(self):
        changed = copy.deepcopy(self.artifact)
        changed["sessions"][0]["close_utc"] = "2099-01-01T00:00:00Z"
        with self.assertRaises(CalendarContractError):
            validate_calendar_artifact(
                changed, ruleset=self.ruleset, ruleset_sha256=self.ruleset_sha
            )

    def test_ruleset_hash_mismatch_rejected(self):
        with self.assertRaises(CalendarContractError):
            load_ruleset(RULESET_PATH, "0" * 64)

    def test_ruleset_rejects_false_july_2_early_close(self):
        changed = copy.deepcopy(self.ruleset)
        changed["early_closes"].append(
            {
                "date": "2026-07-02",
                "close_local": "13:00:00",
                "reason": "contradictory non-NYSE exception",
            }
        )
        path = IO_ROOT / f"ruleset-{uuid.uuid4().hex}.json"
        try:
            path.write_bytes(calendar_bytes(changed))
            with self.assertRaisesRegex(
                CalendarContractError, "early-close set mismatch"
            ):
                load_ruleset(path, hashlib.sha256(path.read_bytes()).hexdigest())
        finally:
            if path.exists():
                path.unlink()

    def test_ruleset_requires_exact_primary_source_set(self):
        changed = copy.deepcopy(self.ruleset)
        changed["provenance"]["supporting_sources"].pop()
        path = IO_ROOT / f"ruleset-{uuid.uuid4().hex}.json"
        try:
            path.write_bytes(calendar_bytes(changed))
            with self.assertRaisesRegex(CalendarContractError, "source set mismatch"):
                load_ruleset(path, hashlib.sha256(path.read_bytes()).hexdigest())
        finally:
            if path.exists():
                path.unlink()

    def test_sub_horizon_is_deterministic(self):
        one = build_calendar_artifact(
            self.ruleset,
            ruleset_sha256=self.ruleset_sha,
            valid_from=date(2026, 8, 1),
            valid_through=date(2026, 8, 31),
        )
        two = build_calendar_artifact(
            self.ruleset,
            ruleset_sha256=self.ruleset_sha,
            valid_from=date(2026, 8, 1),
            valid_through=date(2026, 8, 31),
        )
        self.assertEqual(calendar_bytes(one), calendar_bytes(two))

    def test_consumer_accepts_artifact_and_horizon(self):
        path = IO_ROOT / f"calendar-{uuid.uuid4().hex}.json"
        try:
            path.write_bytes(calendar_bytes(self.artifact))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sessions = consumer_load_calendar(
                path,
                digest,
                now=datetime(2026, 8, 27, tzinfo=timezone.utc),
                minimum_future_horizon=timedelta(days=7),
            )
            self.assertEqual(len(sessions), 251)
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
