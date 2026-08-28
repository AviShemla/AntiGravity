from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import ast
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from oracle_research_dataset import (  # noqa: E402
    OracleProviderLineage, compute_provider_lineage_sha256,
)
from oracle_research_dataset_serializers import (  # noqa: E402
    MARKET_DAILY_FEATURE_COLUMNS, MarketDatasetStreamingDigester,
)
from research_contracts.fold_selection_approval import (  # noqa: E402
    s08_select_only_proposal_runtime as runtime,
)
from research_contracts.fold_selection_approval.s08_signal_panel_materializer import (  # noqa: E402
    canonical_session_dates_sha256, canonical_ticker_list_sha256,
)

RUNTIME_GIT_COMMIT = "f" * 40


class Result:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = list(rows)


class FrozenFixtureClient:
    def __init__(self, rows, dates, content, providers):
        self.rows = rows
        self.dates = dates
        self.content = content
        self.providers = providers
        self.calls = []
        self.write_count = 0

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        normalized = " ".join(sql.split())
        if normalized == runtime._VERSION_SQL:
            columns = (
                "dataset_version_id", "market_snapshot_id", "market_snapshot_checksum_sha256",
                "source_session_date", "evidence_cutoff_utc", "first_session_date",
                "last_session_date", "expected_row_count", "expected_ticker_count",
                "expected_session_count", "expected_provider_lineage_count", "content_sha256",
                "ticker_universe_sha256", "provider_lineage_sha256", "schema_version",
                "code_version", "status", "freeze_approval_id", "frozen_by", "frozen_at_utc",
                "snapshot_dataset_type", "snapshot_source_session_date",
                "snapshot_available_at_utc", "snapshot_checksum_sha256",
                "snapshot_expected_row_count", "snapshot_expected_ticker_count", "snapshot_status",
            )
            row = (
                "dataset-fixture", "snapshot-fixture", "a" * 64, self.dates[-1],
                "2026-08-26T07:00:00Z", self.dates[0], self.dates[-1], len(self.rows), 474,
                len(self.dates), len(self.providers), self.content.content_sha256,
                self.content.ticker_universe_sha256, compute_provider_lineage_sha256(self.providers),
                "1", "b" * 40, "FROZEN", "freeze-event", "AviShemla",
                "2026-08-27T13:33:40Z", "MARKET_FEATURES", self.dates[-1],
                "2026-08-26T06:44:37+00:00", "a" * 64, len(self.rows), 474, "VALIDATED",
            )
            return Result(columns, [row])
        if normalized == runtime._EVENT_SQL:
            return Result(
                ("event_id", "event_type", "market_snapshot_checksum_sha256", "content_sha256",
                 "ticker_universe_sha256", "provider_lineage_sha256", "actor",
                 "decided_at_utc", "evidence_sha256"),
                [("freeze-event", "FREEZE", "a" * 64, self.content.content_sha256,
                  self.content.ticker_universe_sha256,
                  compute_provider_lineage_sha256(self.providers), "AviShemla",
                  "2026-08-27T13:33:40Z", "c" * 64)],
            )
        if normalized == runtime._COVERAGE_SQL:
            return Result(
                ("row_count", "ticker_count", "session_count", "first_session_date",
                 "last_session_date"),
                [(len(self.rows), 474, len(self.dates), self.dates[0], self.dates[-1])],
            )
        provider_columns = (
            "ticker", "provider", "requested_source_session_date", "first_available_date",
            "last_available_date", "source_row_count", "source_checksum_sha256",
        )
        if normalized in {runtime._BOUND_PROVIDER_SQL, runtime._ACTUAL_PROVIDER_SQL}:
            return Result(provider_columns, [
                (p.ticker, p.provider, p.requested_source_session_date.isoformat(),
                 p.first_available_date.isoformat(), p.last_available_date.isoformat(),
                 p.source_row_count, p.source_checksum_sha256) for p in self.providers
            ])
        if sql == runtime.FIRST_PAGE_SQL:
            start = 0
        elif sql == runtime.NEXT_PAGE_SQL:
            cursor = (args[1], args[3])
            start = next((i for i, row in enumerate(self.rows)
                          if (row[1], row[2]) > cursor), len(self.rows))
        else:
            raise AssertionError("unexpected SQL")
        size = args[-1]
        return Result(MARKET_DAILY_FEATURE_COLUMNS, self.rows[start:start + size])


def fixture():
    snapshot = "snapshot-fixture"
    start = date(2025, 7, 5)
    dates = tuple((start + timedelta(days=i)).isoformat() for i in range(417))
    tickers = tuple(f"T{i:03d}" for i in range(474))
    rows = []
    for ticker_index, ticker in enumerate(tickers):
        for day_index, session in enumerate(dates):
            price = 100.0 + ticker_index / 1000.0 + day_index / 100.0
            row = [None] * len(MARKET_DAILY_FEATURE_COLUMNS)
            row[0:3] = [snapshot, ticker, session]
            for name in ("open_price", "high_price", "low_price", "close_price", "adjusted_close"):
                row[MARKET_DAILY_FEATURE_COLUMNS.index(name)] = price
            rows.append(tuple(row))
    digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
    digester.update_rows(rows)
    content = digester.finalize()
    providers = tuple(OracleProviderLineage(
        ticker=f"P{i:03d}", provider="TIINGO_EOD",
        requested_source_session_date=date.fromisoformat(dates[-1]),
        first_available_date=date.fromisoformat(dates[0]),
        last_available_date=date.fromisoformat(dates[-1]), source_row_count=417,
        source_checksum_sha256=f"{i:064x}",
    ) for i in range(476))
    logical_core = {
        "canonical_content": {
            "content_sha256": content.content_sha256,
            "ticker_universe_sha256": content.ticker_universe_sha256,
            "row_count": len(rows), "ticker_count": 474,
            "first_session_date": dates[0], "last_session_date": dates[-1],
        },
        "read_only": True,
        "snapshot": {
            "snapshot_id": snapshot,
            "source_checksum_sha256": "a" * 64,
            "source_session_date": dates[-1],
            "available_at_utc": "2026-08-26T06:44:37+00:00",
        },
    }
    evidence_sha = hashlib.sha256(runtime._canonical_evidence(logical_core)).hexdigest()
    logical = {**logical_core, "evidence_sha256": evidence_sha}
    audit = {
        "logical_evidence": logical,
        "independent_readback": {"matches": True},
    }
    completion = {
        "status": "VERIFIED_SELECT_ONLY",
        "fresh_readback": {
            **logical_core["canonical_content"], "snapshot_id": snapshot,
            "evidence_sha256": evidence_sha,
            "read_only": True, "retained_row_count": 0,
        },
    }
    freeze = {
        "status": "VERIFIED", "dataset_version_id": "dataset-fixture",
        "independent_readback": {
            "freeze_event_count": 1, "provider_lineage_count": 476, "status": "FROZEN",
        },
    }
    source = {
        "contract_id": "codex-oracle-current-baseline-source-evidence-v1",
        "status": "VERIFIED_SELECT_ONLY", "database_writes": 0,
        "model_fit_authorized": False,
        "proposed_model_git_commit": RUNTIME_GIT_COMMIT,
        "model_session_dates": list(dates[-416:]),
        "full_session_calendar_dates": list(dates),
        "immutable_lineage": {
            "snapshot_id": snapshot,
            "model_session_dates_sha256": canonical_session_dates_sha256(dates[-416:]),
            "full_session_calendar_sha256": canonical_session_dates_sha256(dates),
            "universe_sha256": canonical_ticker_list_sha256(tickers),
        },
        "lineage_mapping": {"ticker_universe": list(tickers)},
    }
    source_raw = json.dumps(source, sort_keys=True).encode()
    manifest = {
        "contract_id": "codex-oracle-hierarchical-stock-preregistration-v2",
        "model_session_dates": list(dates[-416:]),
        "full_session_calendar_dates": list(dates),
        "lineage": {
            "snapshot_id": snapshot,
            "model_session_dates_sha256": canonical_session_dates_sha256(dates[-416:]),
            "full_session_calendar_sha256": canonical_session_dates_sha256(dates),
            "universe_sha256": canonical_ticker_list_sha256(tickers),
        },
        "execution": {"model_fit_started": False},
        "preflight": {"fixture_only": True, "model_fit_authorized": False},
    }
    manifest_raw = json.dumps(manifest, sort_keys=True).encode()
    readback = {
        "artifact_id": "fixture-readback",
        "contract_id": "codex-oracle-current-baseline-readback-v1",
        "status": "VERIFIED_SELECT_ONLY",
        "observed_at_utc": "2026-08-28T11:58:00+00:00",
        "model_session_dates": list(dates[-416:]),
        "full_session_calendar_dates": list(dates),
        "boundary": {
            "database_writes": 0, "evaluator_performed_io": False,
            "fixture_only": True, "model_fit_authorized": False,
            "model_fit_performed": False, "ready_state_available": False,
        },
        "evidence": {
            "source_readback_artifact_sha256": hashlib.sha256(source_raw).hexdigest(),
            "source_readback_embedded_evidence_sha256": "d" * 64,
            "snapshot_id": snapshot,
            "model_session_dates_sha256": canonical_session_dates_sha256(dates[-416:]),
            "full_session_calendar_sha256": canonical_session_dates_sha256(dates),
            "universe_sha256": canonical_ticker_list_sha256(tickers),
        },
    }
    readback_raw = json.dumps(readback, sort_keys=True).encode()
    verification = {
        "artifact_file_sha256": hashlib.sha256(readback_raw).hexdigest(),
        "artifact_id": "fixture-readback", "database_writes": 0,
        "model_fit_authorized": False, "request_sha256": "e" * 64,
        "select_query_ids": [
            "SELECT_DOWNSTREAM_COUNTS", "SELECT_DOWNSTREAM_SCHEMA",
            "SELECT_SCREENING_RUNS", "SELECT_SESSION_CALENDAR",
            "SELECT_TICKER_UNIVERSE",
        ],
        "source_embedded_evidence_sha256": "d" * 64,
        "source_file_sha256": hashlib.sha256(source_raw).hexdigest(),
        "status": "VERIFIED_SELECT_ONLY",
    }
    # The verifier binds the same request identity as the readback.
    readback["request_sha256"] = verification["request_sha256"]
    readback_raw = json.dumps(readback, sort_keys=True).encode()
    verification["artifact_file_sha256"] = hashlib.sha256(readback_raw).hexdigest()
    verification_raw = json.dumps(verification, sort_keys=True).encode()
    s07 = runtime.InstalledS07Artifacts(
        current_readback=readback_raw, current_readback_source=source_raw,
        preregistration_manifest=manifest_raw,
        independent_verification=verification_raw,
        owner_uid=0, owner_gid=0, mode=0o600, link_count=1,
    )
    base = runtime.load_canonical_artifacts(ROOT)
    bundle = replace(
        base,
        freeze_completion=json.dumps(freeze, sort_keys=True).encode(),
        content_completion=json.dumps(completion, sort_keys=True).encode(),
        content_audit=json.dumps(audit, sort_keys=True).encode(),
    )
    hashes = {name: hashlib.sha256(getattr(bundle, name)).hexdigest()
              for name in runtime.EXPECTED_RAW_SHA256}
    pins = runtime.AuditPins(
        model_session_dates_sha256=canonical_session_dates_sha256(dates[-416:]),
        ticker_list_sha256=canonical_ticker_list_sha256(tickers),
        preregistration_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
    )
    return (FrozenFixtureClient(rows, dates, content, providers), bundle, hashes,
            s07, pins)


class SelectOnlyProposalRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.client, cls.bundle, cls.hashes, cls.s07, cls.pins) = fixture()

    def assemble(self, client=None, bundle=None, pins=None):
        with patch.dict(runtime.EXPECTED_RAW_SHA256, self.hashes, clear=True):
            return runtime.assemble_v5_proposal(
                client or self.client, artifacts=bundle or self.bundle,
                s07_artifacts=self.s07,
                observed_at_utc=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
                runtime_git_commit=RUNTIME_GIT_COMMIT,
                pins=pins or self.pins, page_size=5000,
            )

    def test_exact_audit_only_assembly_and_zero_output_boundary(self):
        result = self.assemble()
        self.assertEqual(result.status, "AUDIT_ONLY_PROPOSAL_ASSEMBLED_AUTHORITY_PENDING")
        self.assertEqual(result.panel_shape, (474, 416))
        self.assertEqual(result.proposal.status, "APPROVAL_REQUIRED")
        self.assertEqual(result.proposal.selections, ())
        self.assertFalse(result.execution_authorized)
        self.assertTrue(result.s07_readback_fresh)
        self.assertEqual(
            (result.database_writes, result.selection_runs, result.model_runs,
             result.predictions, result.recommendations, result.orders,
             result.downstream_outputs), (0, 0, 0, 0, 0, 0, 0),
        )
        self.assertEqual(self.client.write_count, 0)
        self.assertTrue(all(" ".join(sql.split()).startswith("SELECT ")
                            for sql, _ in self.client.calls))

    def test_artifact_tamper_fails_before_database(self):
        client = FrozenFixtureClient(
            self.client.rows, self.client.dates, self.client.content, self.client.providers,
        )
        bad = replace(self.bundle, selector_v7=self.bundle.selector_v7 + b"tamper")
        before = len(client.calls)
        with patch.dict(runtime.EXPECTED_RAW_SHA256, self.hashes, clear=True):
            with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "artifact bytes differ"):
                runtime.assemble_v5_proposal(
                    client, artifacts=bad, s07_artifacts=self.s07,
                    observed_at_utc=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
                    runtime_git_commit=RUNTIME_GIT_COMMIT,
                    pins=self.pins,
                )
        self.assertEqual(len(client.calls), before)

    def test_calendar_pin_drift_fails_closed(self):
        with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "calendar/ticker"):
            self.assemble(pins=replace(self.pins, model_session_dates_sha256="0" * 64))

    def test_row_count_drift_fails_closed(self):
        client = FrozenFixtureClient(
            self.client.rows[:-1], self.client.dates, self.client.content,
            self.client.providers,
        )
        with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "fresh row content"):
            self.assemble(client=client)

    def test_s07_artifact_tamper_fails_before_database(self):
        client = FrozenFixtureClient(
            self.client.rows, self.client.dates, self.client.content, self.client.providers,
        )
        bad = replace(self.s07, current_readback=self.s07.current_readback + b" ")
        with patch.dict(runtime.EXPECTED_RAW_SHA256, self.hashes, clear=True):
            with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "contradict"):
                runtime.assemble_v5_proposal(
                    client, artifacts=self.bundle, s07_artifacts=bad,
                    observed_at_utc=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
                    runtime_git_commit=RUNTIME_GIT_COMMIT,
                    pins=self.pins,
                )
        self.assertEqual(client.calls, [])

    def test_stale_s07_readback_remains_unsigned(self):
        with patch.dict(runtime.EXPECTED_RAW_SHA256, self.hashes, clear=True):
            result = runtime.assemble_v5_proposal(
                self.client, artifacts=self.bundle, s07_artifacts=self.s07,
                observed_at_utc=datetime(2026, 8, 28, 13, tzinfo=timezone.utc),
                runtime_git_commit=RUNTIME_GIT_COMMIT,
                pins=self.pins, page_size=5000,
            )
        self.assertFalse(result.s07_readback_fresh)
        self.assertFalse(result.execution_authorized)
        self.assertIn("FRESH_ROOT_OWNED", result.unresolved_authority_gate)

    def test_runtime_git_commit_must_match_verified_s07_source(self):
        with patch.dict(runtime.EXPECTED_RAW_SHA256, self.hashes, clear=True):
            with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "contradict"):
                runtime.assemble_v5_proposal(
                    self.client, artifacts=self.bundle, s07_artifacts=self.s07,
                    observed_at_utc=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
                    runtime_git_commit="e" * 40, pins=self.pins,
                )

    def test_runtime_git_commit_format_fails_before_database(self):
        before = len(self.client.calls)
        with patch.dict(runtime.EXPECTED_RAW_SHA256, self.hashes, clear=True):
            with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "Git commit format"):
                runtime.assemble_v5_proposal(
                    self.client, artifacts=self.bundle, s07_artifacts=self.s07,
                    observed_at_utc=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
                    runtime_git_commit="not-a-commit", pins=self.pins,
                )
        self.assertEqual(len(self.client.calls), before)

    def test_fresh_readback_hash_rotation_is_dynamically_bound(self):
        readback = json.loads(self.s07.current_readback)
        readback["observed_at_utc"] = "2026-08-28T11:59:00+00:00"
        readback_raw = json.dumps(readback, sort_keys=True).encode()
        verification = json.loads(self.s07.independent_verification)
        verification["artifact_file_sha256"] = hashlib.sha256(readback_raw).hexdigest()
        verification_raw = json.dumps(verification, sort_keys=True).encode()
        rotated = replace(
            self.s07, current_readback=readback_raw,
            independent_verification=verification_raw,
        )
        with patch.dict(runtime.EXPECTED_RAW_SHA256, self.hashes, clear=True):
            result = runtime.assemble_v5_proposal(
                self.client, artifacts=self.bundle, s07_artifacts=rotated,
                observed_at_utc=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
                runtime_git_commit=RUNTIME_GIT_COMMIT,
                pins=self.pins, page_size=5000,
            )
        self.assertTrue(result.s07_readback_fresh)
        self.assertEqual(result.s07_reconstruction_sha256,
                         hashlib.sha256(readback_raw).hexdigest())
        self.assertEqual(result.s07_independent_verification_sha256,
                         hashlib.sha256(verification_raw).hexdigest())

    def test_arbitrary_select_is_rejected(self):
        guarded = runtime._GuardedCaptureClient(
            self.client, dataset_version="dataset-fixture", snapshot_id="snapshot-fixture",
            page_size=5000,
        )
        with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "allowlist"):
            guarded.execute("SELECT random()", [])

    def test_forged_next_page_cursor_is_rejected(self):
        guarded = runtime._GuardedCaptureClient(
            self.client, dataset_version="dataset-fixture", snapshot_id="snapshot-fixture",
            page_size=5000,
        )
        guarded.execute(runtime.FIRST_PAGE_SQL, ["snapshot-fixture", 5000])
        with self.assertRaisesRegex(runtime.SelectOnlyAssemblyError, "arguments"):
            guarded.execute(runtime.NEXT_PAGE_SQL,
                            ["snapshot-fixture", "ZZZ", "ZZZ", "1900-01-01", 5000])

    def test_canonical_artifact_hashes_match_ad7_bundle(self):
        artifacts = runtime.load_canonical_artifacts(ROOT)
        actual = {name: hashlib.sha256(getattr(artifacts, name)).hexdigest()
                  for name in runtime.EXPECTED_RAW_SHA256}
        self.assertEqual(actual, runtime.EXPECTED_RAW_SHA256)

    def test_runtime_has_no_persistence_model_or_operational_call_surface(self):
        tree = ast.parse(Path(runtime.__file__).read_text(encoding="utf-8"))
        forbidden_imports = {"pymc", "arviz", "turso_read_pipeline", "subprocess"}
        forbidden_calls = {
            "write_text", "write_bytes", "unlink", "mkdir", "rename",
            "remove", "rmdir", "system", "popen",
        }
        imports = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
        self.assertTrue(forbidden_imports.isdisjoint(imports))
        self.assertTrue(forbidden_calls.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
