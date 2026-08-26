import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

from model_lineage import LineageError
from oracle_research_dataset_content_reader import (
    FIRST_PAGE_SQL,
    NEXT_PAGE_SQL,
    PinnedMarketSnapshot,
)
from oracle_research_dataset_serializers import MARKET_DAILY_FEATURE_COLUMNS
from scripts.audit_oracle_research_dataset_content import (
    COVERAGE_COLUMNS,
    COVERAGE_SQL,
    METADATA_COLUMNS,
    METADATA_SQL,
    PINNED_CONTENT,
    PinnedContentAuditContract,
    _client_from_environment,
    build_pinned_content_audit,
    main,
)


@dataclass(frozen=True)
class Result:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


def row(ticker, session, close):
    values = {column: None for column in MARKET_DAILY_FEATURE_COLUMNS}
    values.update(
        snapshot_id="snapshot-test",
        ticker=ticker,
        date=session,
        sector="Tech",
        open_price=close,
        high_price=close + 1,
        low_price=close - 1,
        close_price=close,
        volume=100,
    )
    return tuple(values[column] for column in MARKET_DAILY_FEATURE_COLUMNS)


ROWS = (
    row("AAA", "2026-08-24", 10.0),
    row("AAA", "2026-08-25", 10.5),
    row("BBB", "2026-08-25", 20.0),
)
CONTRACT = PinnedContentAuditContract(
    snapshot=PinnedMarketSnapshot(
        "snapshot-test", "b" * 64, date(2026, 8, 25), len(ROWS), 2
    ),
    dataset_type="MARKET_FEATURES",
    provider="YAHOO_FINANCE",
    code_version="c" * 40,
    first_session_date=date(2026, 8, 24),
)


class Client:
    def __init__(self, *, metadata_changes=None, coverage_changes=None):
        self.calls = []
        self.metadata_changes = metadata_changes or {}
        self.coverage_changes = coverage_changes or {}

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        if not sql.lstrip().upper().startswith("SELECT"):
            raise AssertionError("mutation attempted")
        if sql == METADATA_SQL:
            values = {
                "snapshot_id": "snapshot-test",
                "dataset_type": "MARKET_FEATURES",
                "source_session_date": "2026-08-25",
                "available_at_utc": "2026-08-26T07:30:00Z",
                "provider": "YAHOO_FINANCE",
                "code_version": "c" * 40,
                "source_checksum_sha256": "b" * 64,
                "expected_row_count": 3,
                "expected_ticker_count": 2,
                "status": "VALIDATED",
            }
            values.update(self.metadata_changes)
            return Result(METADATA_COLUMNS, (tuple(values[column] for column in METADATA_COLUMNS),))
        if sql == COVERAGE_SQL:
            values = {
                "row_count": 3,
                "ticker_count": 2,
                "first_session_date": "2026-08-24",
                "last_session_date": "2026-08-25",
            }
            values.update(self.coverage_changes)
            return Result(COVERAGE_COLUMNS, (tuple(values[column] for column in COVERAGE_COLUMNS),))
        if sql == FIRST_PAGE_SQL:
            candidates = ROWS
        elif sql == NEXT_PAGE_SQL:
            candidates = tuple(item for item in ROWS if (item[1], item[2]) > (args[1], args[3]))
        else:
            raise AssertionError("unexpected query")
        return Result(MARKET_DAILY_FEATURE_COLUMNS, tuple(candidates[: args[-1]]))


class ContentAuditCliTests(unittest.TestCase):
    def test_production_contract_pins_the_exact_reviewed_snapshot(self):
        self.assertEqual(
            PINNED_CONTENT.snapshot.snapshot_id,
            "market_features_2026-08-25_5b1044ee45605a3d",
        )
        self.assertEqual(PINNED_CONTENT.snapshot.expected_row_count, 586_710)
        self.assertEqual(PINNED_CONTENT.snapshot.expected_ticker_count, 474)
        self.assertEqual(PINNED_CONTENT.snapshot.source_session_date, date(2026, 8, 25))
        self.assertEqual(PINNED_CONTENT.first_session_date, date(2021, 9, 8))

    def test_exact_select_contract_and_deterministic_row_free_evidence(self):
        client = Client()
        first = build_pinned_content_audit(client, contract=CONTRACT, page_size=2)
        second = build_pinned_content_audit(Client(), contract=CONTRACT, page_size=2)
        self.assertEqual(first, second)
        self.assertEqual(client.calls[0], (METADATA_SQL, ["snapshot-test"]))
        self.assertEqual(client.calls[1], (COVERAGE_SQL, ["snapshot-test"]))
        self.assertEqual(client.calls[2], (FIRST_PAGE_SQL, ["snapshot-test", 2]))
        self.assertEqual(
            client.calls[3],
            (NEXT_PAGE_SQL, ["snapshot-test", "AAA", "AAA", "2026-08-25", 2]),
        )
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql, _ in client.calls))
        self.assertTrue(first["read_only"])
        def keys(value):
            if isinstance(value, dict):
                return set(value).union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value)) if value else set()
            return set()
        self.assertNotIn("rows", keys(first))
        self.assertNotIn(ROWS[0], first.values())
        self.assertNotIn("token", json.dumps(first).lower())
        digest_material = dict(first)
        evidence_hash = digest_material.pop("evidence_sha256")
        canonical = json.dumps(
            digest_material, ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(evidence_hash, hashlib.sha256(canonical).hexdigest())

    def test_page_size_changes_stats_but_not_canonical_digests(self):
        one = build_pinned_content_audit(Client(), contract=CONTRACT, page_size=1)
        three = build_pinned_content_audit(Client(), contract=CONTRACT, page_size=3)
        self.assertEqual(one["canonical_content"], three["canonical_content"])
        self.assertNotEqual(one["pagination"], three["pagination"])

    def test_metadata_mismatch_stops_before_coverage_or_content(self):
        changes = (
            {"snapshot_id": "other"},
            {"source_checksum_sha256": "d" * 64},
            {"source_session_date": "2026-08-24"},
            {"expected_row_count": 4},
            {"expected_ticker_count": 3},
            {"provider": "TIINGO_EOD"},
            {"code_version": "d" * 40},
            {"status": "STAGING"},
        )
        for change in changes:
            with self.subTest(change=change):
                client = Client(metadata_changes=change)
                with self.assertRaisesRegex(LineageError, "pinned identity"):
                    build_pinned_content_audit(client, contract=CONTRACT, page_size=2)
                self.assertEqual(len(client.calls), 1)

    def test_coverage_mismatch_stops_before_content_pages(self):
        changes = (
            {"row_count": 2},
            {"ticker_count": 1},
            {"first_session_date": "2026-08-23"},
            {"last_session_date": "2026-08-24"},
        )
        for change in changes:
            with self.subTest(change=change):
                client = Client(coverage_changes=change)
                with self.assertRaisesRegex(LineageError, "coverage"):
                    build_pinned_content_audit(client, contract=CONTRACT, page_size=2)
                self.assertEqual(len(client.calls), 2)

    def test_invalid_metadata_shape_and_availability_fail_closed(self):
        class WrongColumns(Client):
            def execute(self, sql, args):
                result = super().execute(sql, args)
                if sql == METADATA_SQL:
                    return Result(tuple(reversed(result.columns)), result.rows)
                return result

        with self.assertRaisesRegex(LineageError, "column contract"):
            build_pinned_content_audit(WrongColumns(), contract=CONTRACT)
        with self.assertRaisesRegex(LineageError, "timezone-aware"):
            build_pinned_content_audit(
                Client(metadata_changes={"available_at_utc": "2026-08-26T07:30:00"}),
                contract=CONTRACT,
            )

    def test_cli_injected_client_prints_json_without_environment_or_secrets(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(
                ["--page-size", "2"],
                injected_client=Client(),
                injected_contract=CONTRACT,
            )
        self.assertEqual(status, 0)
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["snapshot"]["snapshot_id"], "snapshot-test")
        self.assertNotIn("credential", output.getvalue().lower())
        self.assertNotIn("endpoint", output.getvalue().lower())

    def test_env_file_loader_builds_bounded_read_pipeline_without_printing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "TURSO_DATABASE_URL=libsql://example.invalid\n"
                + "TURSO_AUTH_" + "TOKEN=" + "unit_test_placeholder\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                client = _client_from_environment(path, timeout_seconds=5.0)
                self.assertEqual(type(client).__name__, "TursoReadPipeline")
                self.assertNotIn("unit_test_placeholder", repr(client))
            with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
                LineageError, "unavailable"
            ):
                _client_from_environment(Path(directory) / "missing", timeout_seconds=5.0)


if __name__ == "__main__":
    unittest.main()
