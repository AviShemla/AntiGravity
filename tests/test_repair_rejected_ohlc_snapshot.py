from datetime import datetime, timezone
import json

import pandas as pd
import pytest

from scripts.rebuild_market_features_to_turso import content_checksum
from scripts.repair_rejected_ohlc_snapshot import (
    KNOWN_VIOLATIONS,
    NORMALIZATION_COMMIT,
    OriginalEvidence,
    SnapshotRepairError,
    apply_plan,
    build_insert_statements,
    build_plan,
    canonical_utc_seconds,
    existing_replacement,
    require_exact_original_metadata,
    require_exact_violation_set,
    validate_expected_evidence,
)
from scripts.stage_market_features_to_turso import COLUMN_MAP


def frame():
    values = []
    for ticker, base in (("DG", 100.0), ("ELV", 200.0), ("OTIS", 300.0), ("TPR", 400.0)):
        row = {}
        for source, _ in COLUMN_MAP:
            if source == "Ticker":
                row[source] = ticker
            elif source == "Date":
                row[source] = pd.Timestamp("2026-08-25")
            elif source == "Sector":
                row[source] = "Test"
            elif source == "Open":
                row[source] = base + 0.01
            elif source == "High":
                row[source] = base
            elif source == "Low":
                row[source] = base - 0.5
            elif source == "Close":
                row[source] = base - 0.2
            elif source in {
                "RAS_Signal", "Analyst_Consensus", "Sector_Regime",
                "Market_Fear_Level",
            }:
                row[source] = "TEST"
            else:
                row[source] = 0.0
        values.append(row)
    return pd.DataFrame(values)


def evidence(source):
    return OriginalEvidence(
        snapshot_id="market_features_2026-08-25_1234567890abcdef",
        status="STAGING",
        checksum=content_checksum(source),
        row_count=4,
        ticker_count=4,
        provider_lineage_count=6,
        provider_lineage_sha256="b" * 64,
        rejection_event_id="reject-20260825-ohlc",
    )


def plan():
    source = frame()
    return build_plan(
        source,
        evidence(source),
        code_version="a" * 40,
        available_at_utc="2026-08-26T04:00:00Z",
        production_approval_id="approval-20260826-ohlc-repair",
    )


def ok_execute(affected=None, baton=None):
    result = {"type": "ok"}
    if affected is not None:
        result["response"] = {
            "type": "execute",
            "result": {"affected_row_count": affected},
        }
    payload = {"results": [result]}
    if baton is not None:
        payload["baton"] = baton
    return payload


class QueryResult:
    def __init__(self, rows):
        self.rows = rows


class QueueReader:
    def __init__(self, rows):
        self.rows = list(rows)

    def execute(self, sql, args):
        return QueryResult(self.rows.pop(0))


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return FakeResponse(self.payloads.pop(0))


def test_build_plan_normalizes_exact_four_rows_and_links_rejected_evidence():
    source = frame()
    original = source.copy(deep=True)
    expected = evidence(source)

    repair = build_plan(
        source,
        expected,
        code_version="a" * 40,
        available_at_utc="2026-08-26T04:00:00Z",
        production_approval_id="approval-20260826-ohlc-repair",
    )

    pd.testing.assert_frame_equal(source, original)
    assert repair.replacement_checksum != expected.checksum
    assert repair.replacement_snapshot_id == (
        f"market_features_2026-08-25_{repair.replacement_checksum[:16]}"
    )
    notes = json.loads(repair.validation_notes)
    assert notes["supersedes_rejected_snapshot_id"] == expected.snapshot_id
    assert notes["supersedes_rejection_event_id"] == expected.rejection_event_id
    assert notes["normalization_commit"] == NORMALIZATION_COMMIT
    assert notes["production_approval_id"] == "approval-20260826-ohlc-repair"
    assert notes["validation_state"] == "STAGING_NOT_VALIDATED"


def test_plan_fails_when_original_rows_do_not_reproduce_checksum():
    source = frame()
    expected = evidence(source)
    source.loc[0, "Open"] += 1.0
    with pytest.raises(SnapshotRepairError, match="immutable original checksum"):
        build_plan(
            source,
            expected,
            code_version="a" * 40,
            available_at_utc="2026-08-26T04:00:00Z",
            production_approval_id="approval-20260826-ohlc-repair",
        )


def test_exact_known_violation_set_rejects_missing_extra_or_wrong_date():
    require_exact_violation_set([list(row) for row in KNOWN_VIOLATIONS])
    with pytest.raises(SnapshotRepairError, match="differs"):
        require_exact_violation_set([list(row) for row in KNOWN_VIOLATIONS[:-1]])
    with pytest.raises(SnapshotRepairError, match="differs"):
        require_exact_violation_set(
            [list(row) for row in KNOWN_VIOLATIONS]
            + [["AAA", "2026-08-25"]]
        )
    wrong = [list(row) for row in KNOWN_VIOLATIONS]
    wrong[0][1] = "2026-08-24"
    with pytest.raises(SnapshotRepairError, match="differs"):
        require_exact_violation_set(wrong)


def test_expected_evidence_rejects_invalid_status_checksum_and_counts():
    source = frame()
    expected = evidence(source)
    validate_expected_evidence(expected)
    with pytest.raises(ValueError, match="status"):
        validate_expected_evidence(
            OriginalEvidence(**{**expected.__dict__, "status": "VALIDATED"})
        )
    with pytest.raises(ValueError, match="checksum"):
        validate_expected_evidence(
            OriginalEvidence(**{**expected.__dict__, "checksum": "bad"})
        )
    with pytest.raises(ValueError, match="positive"):
        validate_expected_evidence(
            OriginalEvidence(**{**expected.__dict__, "row_count": 0})
        )


def test_insert_contract_is_guarded_atomic_input_and_never_mutates_original():
    repair = plan()
    statements = build_insert_statements(repair)
    assert len(statements) == 3
    sql = "\n".join(statement for statement, _ in statements)
    upper = sql.upper()

    assert "INSERT INTO MODEL_INPUT_SNAPSHOTS" in upper
    assert "INSERT INTO MARKET_DATA_PROVIDER_LINEAGE" in upper
    assert "INSERT INTO MARKET_DAILY_FEATURES" in upper
    assert "MAX(OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE)" in upper
    assert "MIN(OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE)" in upper
    assert "DECISION='REJECTED'" in upper
    assert "STATUS=?" in upper
    assert "SOURCE_CHECKSUM_SHA256=?" in upper
    assert "COUNT(*)" in upper
    assert "COUNT(DISTINCT TICKER)" in upper
    assert "UPDATE " not in upper
    assert "DELETE " not in upper
    assert "DROP " not in upper
    assert "VALIDATED" not in upper
    for statement, args in statements:
        assert statement.count("?") == len(args)


def test_exact_original_metadata_requires_physical_counts_and_rejection_event():
    source = frame()
    expected = evidence(source)
    reader = QueueReader([
        [[
            "2026-08-25", expected.status, expected.checksum,
            expected.row_count, expected.ticker_count,
        ]],
        [[expected.row_count, expected.ticker_count]],
        [[expected.snapshot_id, "REJECTED", expected.checksum]],
    ])
    require_exact_original_metadata(reader, expected)

    mismatched = QueueReader([
        [[
            "2026-08-25", expected.status, expected.checksum,
            expected.row_count, expected.ticker_count,
        ]],
        [[expected.row_count - 1, expected.ticker_count]],
    ])
    with pytest.raises(SnapshotRepairError, match="physical counts"):
        require_exact_original_metadata(mismatched, expected)


def test_existing_replacement_is_idempotent_only_for_exact_staging_identity():
    repair = plan()
    exact = QueueReader([[
        [
            "2026-08-25", "STAGING", repair.replacement_checksum,
            repair.original.row_count, repair.original.ticker_count,
            repair.code_version, repair.validation_notes,
        ]
    ]])
    assert existing_replacement(exact, repair) is True
    assert existing_replacement(QueueReader([[]]), repair) is False

    conflict = QueueReader([[
        [
            "2026-08-25", "VALIDATED", repair.replacement_checksum,
            repair.original.row_count, repair.original.ticker_count,
            repair.code_version, repair.validation_notes,
        ]
    ]])
    with pytest.raises(SnapshotRepairError, match="conflicts"):
        existing_replacement(conflict, repair)


def test_apply_is_one_transaction_with_exact_affected_counts():
    repair = plan()
    applied = {
        "baton": "b2",
        "results": [
            ok_execute(1)["results"][0],
            ok_execute(repair.original.provider_lineage_count)["results"][0],
            ok_execute(repair.original.row_count)["results"][0],
        ],
    }
    session = FakeSession([
        ok_execute(baton="b1"),
        applied,
        ok_execute(),
    ])

    apply_plan(session, "https://test/v2/pipeline", "token", repair)

    sql_batches = [
        [request["stmt"]["sql"] for request in call[1]["json"]["requests"]]
        for call in session.calls
    ]
    assert sql_batches[0] == ["BEGIN IMMEDIATE"]
    assert sql_batches[-1] == ["COMMIT"]
    assert all("UPDATE " not in sql.upper() and "DELETE " not in sql.upper()
               for batch in sql_batches for sql in batch)


def test_apply_rolls_back_if_guard_or_copy_count_is_not_exact():
    repair = plan()
    applied = {
        "baton": "b2",
        "results": [
            ok_execute(0)["results"][0],
            ok_execute(repair.original.provider_lineage_count)["results"][0],
            ok_execute(repair.original.row_count)["results"][0],
        ],
    }
    session = FakeSession([
        ok_execute(baton="b1"),
        applied,
        ok_execute(),
    ])

    with pytest.raises(Exception, match="affected-row counts"):
        apply_plan(session, "https://test/v2/pipeline", "token", repair)

    sql = [
        request["stmt"]["sql"]
        for _, kwargs in session.calls
        for request in kwargs["json"]["requests"]
    ]
    assert "ROLLBACK" in sql
    assert "COMMIT" not in sql


def test_timestamp_is_canonical_and_requires_timezone():
    assert canonical_utc_seconds(
        datetime(2026, 8, 26, 4, 5, 6, 999, tzinfo=timezone.utc)
    ) == "2026-08-26T04:05:06Z"
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_utc_seconds(datetime(2026, 8, 26, 4, 5, 6))
