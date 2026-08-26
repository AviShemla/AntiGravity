#!/usr/bin/env python3
"""Guarded, idempotent replacement for a rejected canonical OHLC snapshot.

Read-only preflight is the default. Applying creates a new STAGING snapshot in
one rollback-capable transaction. The rejected snapshot, its rows, checksum,
provider lineage, and rejection event are never updated or deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_atomic_migration import (
    AtomicMigrationError,
    _post_pipeline,
    _require_baton,
    _rollback_connection,
    verify_pipeline_results,
)
from scripts.rebuild_market_features_to_turso import (
    content_checksum,
    normalize_ohlc_envelope,
    provider_lineage_checksum,
)
from scripts.stage_market_features_to_turso import COLUMN_MAP
from turso_read_pipeline import TursoReadPipeline, _encode_arg


SOURCE_SESSION = "2026-08-25"
KNOWN_VIOLATIONS = (
    ("DG", SOURCE_SESSION),
    ("ELV", SOURCE_SESSION),
    ("OTIS", SOURCE_SESSION),
    ("TPR", SOURCE_SESSION),
)
NORMALIZATION_COMMIT = "94244420fe1d6093cbbaad408b601fd8b77032be"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SNAPSHOT_ID = re.compile(r"^market_features_[A-Za-z0-9_.:-]{16,160}$")
EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,160}$")

DB_COLUMNS = tuple(target for _, target in COLUMN_MAP)
SOURCE_COLUMNS = tuple(source for source, _ in COLUMN_MAP)
NUMERIC_SOURCES = tuple(
    source for source in SOURCE_COLUMNS
    if source not in {
        "Ticker", "Date", "Sector", "RAS_Signal", "Analyst_Consensus",
        "Sector_Regime", "Market_Fear_Level",
    }
)
OHLC_VIOLATION_SQL = (
    "(open_price IS NULL OR high_price IS NULL OR low_price IS NULL "
    "OR close_price IS NULL OR "
    "high_price <> MAX(open_price,high_price,low_price,close_price) OR "
    "low_price <> MIN(open_price,high_price,low_price,close_price))"
)


@dataclass(frozen=True)
class OriginalEvidence:
    snapshot_id: str
    status: str
    checksum: str
    row_count: int
    ticker_count: int
    provider_lineage_count: int
    provider_lineage_sha256: str
    rejection_event_id: str


@dataclass(frozen=True)
class RepairPlan:
    original: OriginalEvidence
    replacement_snapshot_id: str
    replacement_checksum: str
    code_version: str
    available_at_utc: str
    validation_notes: str


class SnapshotRepairError(RuntimeError):
    """Raised when immutable evidence does not satisfy the repair contract."""


def canonical_utc_seconds(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Repair timestamp must be timezone-aware.")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_expected_evidence(expected: OriginalEvidence) -> None:
    if not SNAPSHOT_ID.fullmatch(expected.snapshot_id):
        raise ValueError("Original snapshot id has an invalid format.")
    if expected.status not in {"STAGING", "REJECTED"}:
        raise ValueError("Expected original status must be STAGING or REJECTED.")
    if not SHA256.fullmatch(expected.checksum):
        raise ValueError("Original checksum must be a lowercase SHA-256.")
    if expected.row_count <= 0 or expected.ticker_count <= 0:
        raise ValueError("Expected snapshot counts must be positive.")
    if expected.provider_lineage_count <= 0:
        raise ValueError("Expected provider-lineage count must be positive.")
    if not SHA256.fullmatch(expected.provider_lineage_sha256):
        raise ValueError("Provider-lineage checksum must be a lowercase SHA-256.")
    if not EVENT_ID.fullmatch(expected.rejection_event_id):
        raise ValueError("Rejection event id has an invalid format.")


def require_exact_original_metadata(reader: TursoReadPipeline, expected: OriginalEvidence) -> None:
    rows = reader.execute(
        "SELECT source_session_date,status,source_checksum_sha256,"
        "expected_row_count,expected_ticker_count "
        "FROM model_input_snapshots WHERE snapshot_id=?",
        [expected.snapshot_id],
    ).rows
    wanted = [
        SOURCE_SESSION, expected.status, expected.checksum,
        expected.row_count, expected.ticker_count,
    ]
    if len(rows) != 1 or list(rows[0]) != wanted:
        raise SnapshotRepairError("Original snapshot metadata does not match the reviewed evidence.")

    actual = reader.execute(
        "SELECT COUNT(*),COUNT(DISTINCT ticker) FROM market_daily_features "
        "WHERE snapshot_id=?",
        [expected.snapshot_id],
    ).rows
    if len(actual) != 1 or [int(actual[0][0]), int(actual[0][1])] != [
        expected.row_count, expected.ticker_count,
    ]:
        raise SnapshotRepairError("Original snapshot physical counts do not match metadata.")

    rejection = reader.execute(
        "SELECT snapshot_id,decision,snapshot_checksum_sha256 "
        "FROM model_input_approval_events WHERE event_id=?",
        [expected.rejection_event_id],
    ).rows
    if len(rejection) != 1 or list(rejection[0]) != [
        expected.snapshot_id, "REJECTED", expected.checksum,
    ]:
        raise SnapshotRepairError("Checksum-matched rejection evidence is missing or mismatched.")


def require_exact_violation_set(rows: list[list[object]]) -> None:
    observed = tuple(sorted((str(row[0]), str(row[1])) for row in rows))
    if observed != KNOWN_VIOLATIONS:
        raise SnapshotRepairError(
            f"OHLC violation set differs from the reviewed four-row set: {observed!r}"
        )


def read_and_verify_provider_lineage(
    reader: TursoReadPipeline, expected: OriginalEvidence
) -> list[list[object]]:
    rows = [
        list(row) for row in reader.execute(
            "SELECT ticker,provider,requested_source_session_date,"
            "first_available_date,last_available_date,source_row_count,"
            "source_checksum_sha256 FROM market_data_provider_lineage "
            "WHERE snapshot_id=? ORDER BY ticker",
            [expected.snapshot_id],
        ).rows
    ]
    if len(rows) != expected.provider_lineage_count:
        raise SnapshotRepairError("Provider-lineage count does not match reviewed evidence.")
    if provider_lineage_checksum(rows) != expected.provider_lineage_sha256:
        raise SnapshotRepairError("Provider-lineage checksum does not match reviewed evidence.")
    return rows


def read_snapshot_frame(
    reader: TursoReadPipeline, snapshot_id: str, *, page_size: int = 4000
) -> pd.DataFrame:
    if not 100 <= page_size <= 10000:
        raise ValueError("Snapshot read page size must be between 100 and 10000.")
    rows: list[list[object]] = []
    last_ticker = ""
    last_date = ""
    columns_sql = ",".join(DB_COLUMNS)
    while True:
        page = reader.execute(
            f"SELECT {columns_sql} FROM market_daily_features WHERE snapshot_id=? "
            "AND (ticker>? OR (ticker=? AND date>?)) "
            f"ORDER BY ticker,date LIMIT {page_size}",
            [snapshot_id, last_ticker, last_ticker, last_date],
        ).rows
        if not page:
            break
        rows.extend(list(row) for row in page)
        last_ticker = str(page[-1][0])
        last_date = str(page[-1][1])
        if len(page) < page_size:
            break
    frame = pd.DataFrame(rows, columns=SOURCE_COLUMNS)
    if frame.empty:
        raise SnapshotRepairError("Original snapshot contains no feature rows.")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
    for column in NUMERIC_SOURCES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


def require_normalization_ancestry(code_version: str) -> None:
    if not GIT_SHA.fullmatch(code_version):
        raise ValueError("Expected code version must be a lowercase 40-character Git SHA.")
    if git_head() != code_version:
        raise SnapshotRepairError("Cloud worktree HEAD differs from the reviewed code version.")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status.stdout.strip():
        raise SnapshotRepairError("Cloud worktree is not clean at the reviewed code version.")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", NORMALIZATION_COMMIT, code_version],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise SnapshotRepairError("Reviewed OHLC normalization commit is not an ancestor.")


def build_plan(
    frame: pd.DataFrame,
    expected: OriginalEvidence,
    *,
    code_version: str,
    available_at_utc: str,
    production_approval_id: str,
) -> RepairPlan:
    validate_expected_evidence(expected)
    if not EVENT_ID.fullmatch(production_approval_id):
        raise ValueError("Production approval id has an invalid format.")
    if len(frame) != expected.row_count:
        raise SnapshotRepairError("In-memory original row count differs from reviewed evidence.")
    if int(frame["Ticker"].nunique()) != expected.ticker_count:
        raise SnapshotRepairError("In-memory original ticker count differs from reviewed evidence.")
    reconstructed_checksum = content_checksum(frame)
    if reconstructed_checksum != expected.checksum:
        raise SnapshotRepairError(
            "Stored original rows cannot reproduce the immutable original checksum."
        )
    normalized = normalize_ohlc_envelope(frame)
    replacement_checksum = content_checksum(normalized)
    if replacement_checksum == expected.checksum:
        raise SnapshotRepairError("OHLC normalization produced no checksum change.")
    replacement_id = (
        f"market_features_{SOURCE_SESSION}_{replacement_checksum[:16]}"
    )
    notes = json.dumps(
        {
            "repair": "CANONICAL_OHLC_ENVELOPE",
            "supersedes_rejected_snapshot_id": expected.snapshot_id,
            "supersedes_rejection_event_id": expected.rejection_event_id,
            "original_checksum_sha256": expected.checksum,
            "normalization_commit": NORMALIZATION_COMMIT,
            "repair_code_version": code_version,
            "production_approval_id": production_approval_id,
            "provider_lineage_sha256": expected.provider_lineage_sha256,
            "validation_state": "STAGING_NOT_VALIDATED",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return RepairPlan(
        original=expected,
        replacement_snapshot_id=replacement_id,
        replacement_checksum=replacement_checksum,
        code_version=code_version,
        available_at_utc=available_at_utc,
        validation_notes=notes,
    )


def _args(values: list[object]) -> list[dict]:
    return [_encode_arg(value) for value in values]


def build_insert_statements(plan: RepairPlan) -> list[tuple[str, list[object]]]:
    original = plan.original
    known_tickers = [ticker for ticker, _ in KNOWN_VIOLATIONS]
    exact_known_predicate = (
        f"ticker IN ({','.join('?' for _ in known_tickers)}) AND date=? "
        f"AND {OHLC_VIOLATION_SQL}"
    )
    parent_sql = f"""
        INSERT INTO model_input_snapshots
        (snapshot_id,dataset_type,source_session_date,available_at_utc,provider,
         code_version,source_checksum_sha256,expected_row_count,
         expected_ticker_count,status,validation_notes,created_at_utc)
        SELECT ?,'MARKET_FEATURES',?,?,provider,?,?,?,?, 'STAGING',?,?
        FROM model_input_snapshots original
        WHERE original.snapshot_id=? AND original.source_session_date=?
          AND original.status=? AND original.source_checksum_sha256=?
          AND original.expected_row_count=? AND original.expected_ticker_count=?
          AND (SELECT COUNT(*) FROM market_daily_features WHERE snapshot_id=?)=?
          AND (SELECT COUNT(DISTINCT ticker) FROM market_daily_features
               WHERE snapshot_id=?)=?
          AND (SELECT COUNT(*) FROM market_data_provider_lineage
               WHERE snapshot_id=?)=?
          AND (SELECT COUNT(*) FROM market_daily_features
               WHERE snapshot_id=? AND {OHLC_VIOLATION_SQL})=4
          AND (SELECT COUNT(*) FROM market_daily_features
               WHERE snapshot_id=? AND {exact_known_predicate})=4
          AND EXISTS (
              SELECT 1 FROM model_input_approval_events
              WHERE event_id=? AND snapshot_id=? AND decision='REJECTED'
                AND snapshot_checksum_sha256=?
          )
    """
    parent_args: list[object] = [
        plan.replacement_snapshot_id,
        SOURCE_SESSION,
        plan.available_at_utc,
        plan.code_version,
        plan.replacement_checksum,
        original.row_count,
        original.ticker_count,
        plan.validation_notes,
        plan.available_at_utc,
        original.snapshot_id,
        SOURCE_SESSION,
        original.status,
        original.checksum,
        original.row_count,
        original.ticker_count,
        original.snapshot_id,
        original.row_count,
        original.snapshot_id,
        original.ticker_count,
        original.snapshot_id,
        original.provider_lineage_count,
        original.snapshot_id,
        original.snapshot_id,
        *known_tickers,
        SOURCE_SESSION,
        original.rejection_event_id,
        original.snapshot_id,
        original.checksum,
    ]
    lineage_sql = """
        INSERT INTO market_data_provider_lineage
        (snapshot_id,ticker,provider,requested_source_session_date,
         first_available_date,last_available_date,source_row_count,
         source_checksum_sha256,created_at_utc)
        SELECT ?,ticker,provider,requested_source_session_date,
               first_available_date,last_available_date,source_row_count,
               source_checksum_sha256,?
        FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker
    """
    high = "MAX(open_price,high_price,low_price,close_price)"
    low = "MIN(open_price,high_price,low_price,close_price)"
    feature_sql = f"""
        INSERT INTO market_daily_features
        (snapshot_id,{','.join(DB_COLUMNS)})
        SELECT ?,ticker,date,sector,open_price,{high},{low},close_price,
               adjusted_close,volume,dividends,stock_splits,daily_return_pct,
               daily_stdev,stdev_5d,stdev_10d,stdev_20d,max_high_20d,
               min_low_20d,rsi_14d,atr_14d,plus_di_14d,minus_di_14d,adx_14d,
               dynamic_stop_loss,ras_signal,analyst_consensus,
               analyst_upside_pct,sector_momentum_score,sector_regime,vix_close,
               market_fear_level,tnx_close,tnx_lag1_return,tnx_trend_5d
        FROM market_daily_features WHERE snapshot_id=? ORDER BY ticker,date
    """
    return [
        (parent_sql, parent_args),
        (
            lineage_sql,
            [
                plan.replacement_snapshot_id,
                plan.available_at_utc,
                original.snapshot_id,
            ],
        ),
        (
            feature_sql,
            [plan.replacement_snapshot_id, original.snapshot_id],
        ),
    ]


def _affected_rows(result: dict) -> int:
    try:
        return int(result["response"]["result"]["affected_row_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AtomicMigrationError("Turso omitted a statement affected-row count.") from exc


def apply_plan(session, endpoint: str, token: str, plan: RepairPlan) -> None:
    begin = _post_pipeline(
        session,
        endpoint,
        token,
        [{"type": "execute", "stmt": {"sql": "BEGIN IMMEDIATE", "args": []}}],
        timeout=45.0,
    )
    verify_pipeline_results(begin, 1)
    baton = _require_baton(begin)
    statements = build_insert_statements(plan)
    requests_ = [
        {"type": "execute", "stmt": {"sql": sql, "args": _args(args)}}
        for sql, args in statements
    ]
    try:
        applied = _post_pipeline(
            session, endpoint, token, requests_, baton=baton, timeout=180.0
        )
        baton = _require_baton(applied)
        verify_pipeline_results(applied, len(requests_))
        affected = [_affected_rows(item) for item in applied["results"][:3]]
        expected = [
            1,
            plan.original.provider_lineage_count,
            plan.original.row_count,
        ]
        if affected != expected:
            raise AtomicMigrationError(
                f"Repair affected-row counts differ from contract: {affected!r}"
            )
        committed = _post_pipeline(
            session,
            endpoint,
            token,
            [{"type": "execute", "stmt": {"sql": "COMMIT", "args": []}}],
            baton=baton,
            timeout=180.0,
        )
        verify_pipeline_results(committed, 1)
    except Exception as exc:
        try:
            _rollback_connection(session, endpoint, token, baton)
        except Exception as rollback_exc:
            raise AtomicMigrationError(
                f"Snapshot repair failed and rollback was not verified: {rollback_exc}"
            ) from exc
        raise


def existing_replacement(
    reader: TursoReadPipeline, plan: RepairPlan
) -> bool:
    rows = reader.execute(
        "SELECT source_session_date,status,source_checksum_sha256,"
        "expected_row_count,expected_ticker_count,code_version,validation_notes "
        "FROM model_input_snapshots WHERE snapshot_id=?",
        [plan.replacement_snapshot_id],
    ).rows
    if not rows:
        return False
    wanted = [
        SOURCE_SESSION,
        "STAGING",
        plan.replacement_checksum,
        plan.original.row_count,
        plan.original.ticker_count,
        plan.code_version,
        plan.validation_notes,
    ]
    if len(rows) != 1 or list(rows[0]) != wanted:
        raise SnapshotRepairError("Existing replacement identity conflicts with the repair plan.")
    return True


def verify_replacement(reader: TursoReadPipeline, plan: RepairPlan) -> None:
    if not existing_replacement(reader, plan):
        raise SnapshotRepairError("Replacement snapshot is missing after staging.")
    count_rows = reader.execute(
        "SELECT COUNT(*),COUNT(DISTINCT ticker) FROM market_daily_features "
        "WHERE snapshot_id=?",
        [plan.replacement_snapshot_id],
    ).rows
    if len(count_rows) != 1 or [int(count_rows[0][0]), int(count_rows[0][1])] != [
        plan.original.row_count, plan.original.ticker_count,
    ]:
        raise SnapshotRepairError("Replacement physical counts do not match the repair plan.")
    invalid = int(reader.execute(
        f"SELECT COUNT(*) FROM market_daily_features WHERE snapshot_id=? "
        f"AND {OHLC_VIOLATION_SQL}",
        [plan.replacement_snapshot_id],
    ).rows[0][0])
    if invalid != 0:
        raise SnapshotRepairError("Replacement snapshot still violates exact OHLC.")
    lineage = reader.execute(
        "SELECT ticker,provider,requested_source_session_date,"
        "first_available_date,last_available_date,source_row_count,"
        "source_checksum_sha256 FROM market_data_provider_lineage "
        "WHERE snapshot_id=? ORDER BY ticker",
        [plan.replacement_snapshot_id],
    ).rows
    rows = [list(row) for row in lineage]
    if (
        len(rows) != plan.original.provider_lineage_count
        or provider_lineage_checksum(rows)
        != plan.original.provider_lineage_sha256
    ):
        raise SnapshotRepairError("Replacement provider lineage differs from original evidence.")
    stored_frame = read_snapshot_frame(reader, plan.replacement_snapshot_id)
    if content_checksum(stored_frame) != plan.replacement_checksum:
        raise SnapshotRepairError("Replacement readback checksum differs from staged identity.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-snapshot-id", required=True)
    parser.add_argument(
        "--expected-original-status",
        required=True,
        choices=("STAGING", "REJECTED"),
    )
    parser.add_argument("--expected-original-checksum", required=True)
    parser.add_argument("--expected-row-count", required=True, type=int)
    parser.add_argument("--expected-ticker-count", required=True, type=int)
    parser.add_argument("--expected-provider-lineage-count", required=True, type=int)
    parser.add_argument("--expected-provider-lineage-sha256", required=True)
    parser.add_argument("--expected-rejection-event-id", required=True)
    parser.add_argument("--expected-code-version", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--production-approval-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected = OriginalEvidence(
        snapshot_id=args.original_snapshot_id,
        status=args.expected_original_status,
        checksum=args.expected_original_checksum,
        row_count=args.expected_row_count,
        ticker_count=args.expected_ticker_count,
        provider_lineage_count=args.expected_provider_lineage_count,
        provider_lineage_sha256=args.expected_provider_lineage_sha256,
        rejection_event_id=args.expected_rejection_event_id,
    )
    validate_expected_evidence(expected)
    require_normalization_ancestry(args.expected_code_version)

    from dotenv import load_dotenv
    import requests

    load_dotenv(args.env_file, override=False)
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    reader = TursoReadPipeline(endpoint, token, timeout_seconds=60.0)

    require_exact_original_metadata(reader, expected)
    violations = reader.execute(
        f"SELECT ticker,date FROM market_daily_features WHERE snapshot_id=? "
        f"AND {OHLC_VIOLATION_SQL} ORDER BY ticker,date",
        [expected.snapshot_id],
    ).rows
    require_exact_violation_set([list(row) for row in violations])
    read_and_verify_provider_lineage(reader, expected)
    original_frame = read_snapshot_frame(reader, expected.snapshot_id)
    plan = build_plan(
        original_frame,
        expected,
        code_version=args.expected_code_version,
        available_at_utc=canonical_utc_seconds(),
        production_approval_id=args.production_approval_id,
    )
    already_staged = existing_replacement(reader, plan)
    if already_staged:
        verify_replacement(reader, plan)
        print(
            f"ALREADY_STAGED_NOT_VALIDATED snapshot_id={plan.replacement_snapshot_id} "
            f"checksum={plan.replacement_checksum} idempotent=true"
        )
        return 0
    if not args.apply:
        print(json.dumps({
            "status": "PREFLIGHT_PASS_NO_WRITES",
            "original_snapshot_id": expected.snapshot_id,
            "replacement_snapshot_id": plan.replacement_snapshot_id,
            "replacement_checksum_sha256": plan.replacement_checksum,
            "row_count": expected.row_count,
            "ticker_count": expected.ticker_count,
            "provider_lineage_count": expected.provider_lineage_count,
            "known_ohlc_violations": [list(value) for value in KNOWN_VIOLATIONS],
            "normalization_commit": NORMALIZATION_COMMIT,
            "code_version": plan.code_version,
        }, sort_keys=True), flush=True)
        return 0
    apply_plan(requests.Session(), endpoint, token, plan)
    verify_replacement(reader, plan)
    print(
        f"STAGED_NOT_VALIDATED snapshot_id={plan.replacement_snapshot_id} "
        f"checksum={plan.replacement_checksum} supersedes={expected.snapshot_id} "
        "status=STAGING"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
