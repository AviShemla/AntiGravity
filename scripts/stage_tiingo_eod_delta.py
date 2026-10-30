#!/usr/bin/env python3
"""Stage a resumable Tiingo EOD evidence run without promoting model inputs.

The command derives the controlled universe entirely from Turso, fetches one
provider-native EOD revision per ticker, and checkpoints every accepted row.
It never creates or promotes a model-input snapshot and never invokes a model,
broker, order generator, or service-management command.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_data_provider import fetch_tiingo_revision_bars, resolve_tiingo_api_key
from market_eod_revision_writer import (
    complete_ingestion_run,
    prepare_revision_rows,
    stage_ingestion_run,
    stage_revision_batch,
)
from scripts.rebuild_market_features_to_turso import (
    apply_approved_instrument_registry,
    apply_symbol_lifecycle,
    build_controlled_universe,
)
from turso_read_pipeline import TursoReadPipeline


PROVIDER = "TIINGO_EOD"
MODE = "DAILY_DELTA"


def manifest_sha256(tickers: list[str]) -> str:
    canonical = "\n".join(sorted({str(value).strip().upper() for value in tickers}))
    if not canonical:
        raise ValueError("controlled universe is empty")
    return hashlib.sha256((canonical + "\n").encode("utf-8")).hexdigest()


def source_code_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_run_id(source_session: date, manifest_hash: str, code_hash: str) -> str:
    return (
        f"tiingo-delta-{source_session.isoformat()}-"
        f"{manifest_hash[:12]}-{code_hash[:12]}"
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def latest_validated_snapshot(reader: TursoReadPipeline, source_session: date) -> list[object]:
    rows = reader.execute(
        "SELECT snapshot_id,source_session_date,expected_ticker_count "
        "FROM model_input_snapshots WHERE dataset_type='MARKET_FEATURES' "
        "AND status='VALIDATED' AND source_session_date<=? "
        "ORDER BY source_session_date DESC,created_at_utc DESC LIMIT 1",
        [source_session.isoformat()],
    ).rows
    if len(rows) != 1:
        raise RuntimeError("exactly one latest validated market snapshot was not found")
    return list(rows[0])


def latest_stock_rows(reader: TursoReadPipeline, snapshot_id: str) -> list[list[object]]:
    """Read one indexed session instead of grouping the full feature history."""
    return [
        list(row)
        for row in reader.execute(
            "SELECT ticker,sector FROM market_daily_features "
            "WHERE snapshot_id=? AND date=(SELECT MAX(date) "
            "FROM market_daily_features WHERE snapshot_id=?) ORDER BY ticker",
            [snapshot_id, snapshot_id],
        ).rows
    ]


def controlled_universe(
    reader: TursoReadPipeline, source_session: date, snapshot_id: str
) -> tuple[list[str], str]:
    stock_rows = latest_stock_rows(reader, snapshot_id)
    etf_scorecards = reader.execute(
        "SELECT DISTINCT ticker FROM etf_scorecards_master "
        "WHERE persona LIKE 'ETF_%' ORDER BY ticker",
        [],
    ).rows
    etf_ledgers = reader.execute(
        "SELECT cl.holdings_json FROM capital_ledgers cl JOIN "
        "(SELECT persona,MAX(date) AS max_date FROM capital_ledgers "
        "WHERE persona LIKE 'ETF_%' GROUP BY persona) latest "
        "ON latest.persona=cl.persona AND latest.max_date=cl.date "
        "ORDER BY cl.persona",
        [],
    ).rows
    etf_pending = reader.execute(
        "SELECT target_holdings_json FROM pending_orders "
        "WHERE persona LIKE 'ETF_%' ORDER BY persona",
        [],
    ).rows
    universe = build_controlled_universe(
        stock_rows, etf_scorecards, etf_ledgers, etf_pending
    )
    lifecycle_rows = reader.execute(
        "SELECT ticker,event_type,effective_date,successor_ticker,sector "
        "FROM market_symbol_lifecycle_events WHERE effective_date<=? "
        "ORDER BY effective_date,event_id",
        [source_session.isoformat()],
    ).rows
    universe, _ = apply_symbol_lifecycle(
        universe, lifecycle_rows, source_session=source_session
    )
    registry_versions = reader.execute(
        "SELECT registry_id FROM market_instrument_registry_versions "
        "WHERE status='APPROVED' ORDER BY evidence_as_of_date DESC,registry_id",
        [],
    ).rows
    if len(registry_versions) != 1:
        raise RuntimeError("exactly one approved instrument registry is required")
    registry_id = str(registry_versions[0][0])
    registry_rows = reader.execute(
        "SELECT registry_id,ticker,asset_class,sector,usage,minimum_history_rows "
        "FROM market_instrument_registry WHERE registry_id=? ORDER BY ticker",
        [registry_id],
    ).rows
    universe = apply_approved_instrument_registry(
        universe, registry_versions, registry_rows
    )
    tickers = sorted(universe)
    if not tickers:
        raise RuntimeError("controlled universe is empty")
    return tickers, registry_id


def existing_run(reader: TursoReadPipeline, run_id: str) -> list[object] | None:
    rows = reader.execute(
        "SELECT available_at_utc,status,expected_ticker_count "
        "FROM market_eod_ingestion_runs WHERE run_id=?",
        [run_id],
    ).rows
    if len(rows) > 1:
        raise RuntimeError("ingestion run identity is duplicated")
    return None if not rows else list(rows[0])


def existing_tickers(reader: TursoReadPipeline, run_id: str) -> set[str]:
    return {
        str(row[0])
        for row in reader.execute(
            "SELECT ticker FROM market_eod_bar_revisions WHERE run_id=? ORDER BY ticker",
            [run_id],
        ).rows
    }


def complete_session_run(
    reader: TursoReadPipeline,
    source_session: date,
    expected_ticker_count: int,
) -> str | None:
    """Return a fully evidenced run for the session, independent of code hash."""
    rows = reader.execute(
        "SELECT r.run_id,COUNT(b.ticker) AS evidence_rows "
        "FROM market_eod_ingestion_runs r "
        "JOIN market_eod_bar_revisions b ON b.run_id=r.run_id "
        "WHERE r.provider=? AND r.ingestion_mode=? "
        "AND r.requested_source_session_date=? AND r.status='COMPLETE' "
        "AND r.expected_ticker_count=? "
        "GROUP BY r.run_id HAVING COUNT(b.ticker)=? "
        "ORDER BY MAX(r.completed_at_utc) DESC LIMIT 1",
        [
            PROVIDER,
            MODE,
            source_session.isoformat(),
            expected_ticker_count,
            expected_ticker_count,
        ],
    ).rows
    if len(rows) > 1:
        raise RuntimeError("complete session evidence lookup was not unique")
    return None if not rows else str(rows[0][0])


def core_counts(reader: TursoReadPipeline) -> dict[str, int]:
    return {
        table: int(reader.execute(f"SELECT COUNT(*) FROM {table}", []).rows[0][0])
        for table in ("pending_orders", "capital_ledgers", "model_runs", "model_scorecards")
    }


def fetch_one(
    ticker: str,
    source_session: date,
    api_key: str,
    *,
    attempts: int,
    retry_seconds: float,
    sleep_fn=time.sleep,
):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            frame = fetch_tiingo_revision_bars(
                ticker,
                source_session,
                source_session.isoformat(),
                api_key=api_key,
            )
            if len(frame) != 1:
                raise RuntimeError("provider did not return exactly one EOD row")
            actual_date = frame["Date"].iloc[0].date()
            if actual_date != source_session:
                raise RuntimeError("provider row does not match the requested session")
            return frame
        except Exception as exc:  # bounded retry; final failure leaves STAGING
            last_error = exc
            if attempt < attempts:
                sleep_fn(retry_seconds * attempt)
    assert last_error is not None
    raise RuntimeError(
        f"provider evidence failed for {ticker} after {attempts} attempts: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--tiingo-token-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--request-interval-seconds", type=float, default=76.0)
    parser.add_argument("--retry-seconds", type=float, default=90.0)
    parser.add_argument("--attempts", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_session = date.fromisoformat(args.source_session)
    if args.request_interval_seconds < 72.0:
        raise SystemExit("request interval must be at least 72 seconds")
    if args.retry_seconds < 30.0:
        raise SystemExit("retry delay must be at least 30 seconds")
    if not 1 <= args.attempts <= 6:
        raise SystemExit("attempts must be between 1 and 6")

    load_dotenv(args.env_file, override=False)
    raw_url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    reader = TursoReadPipeline(endpoint, token, timeout_seconds=30.0)
    snapshot_id, snapshot_session, snapshot_tickers = latest_validated_snapshot(
        reader, source_session
    )
    tickers, registry_id = controlled_universe(reader, source_session, str(snapshot_id))
    completed_session_run = complete_session_run(
        reader, source_session, len(tickers)
    )
    manifest_hash = manifest_sha256(tickers)
    code_hash = source_code_sha256([
        Path(__file__).resolve(),
        ROOT / "market_data_provider.py",
        ROOT / "market_eod_revision_writer.py",
    ])
    run_id = build_run_id(source_session, manifest_hash, code_hash)
    prior_run = existing_run(reader, run_id)
    staged = existing_tickers(reader, run_id)
    print(
        f"PRECHECK source_session={source_session.isoformat()} "
        f"universe_snapshot={snapshot_id} snapshot_session={snapshot_session} "
        f"snapshot_expected_tickers={snapshot_tickers} registry_id={registry_id} "
        f"controlled_tickers={len(tickers)} manifest_sha256={manifest_hash} "
        f"code_sha256={code_hash} run_id={run_id} staged={len(staged)} "
        f"apply={str(args.apply).lower()}",
        flush=True,
    )
    if completed_session_run is not None:
        print(
            f"ALREADY_COMPLETE_SESSION run_id={completed_session_run} "
            f"source_session={source_session.isoformat()} rows={len(tickers)}",
            flush=True,
        )
        return 0
    unexpected = staged.difference(tickers)
    if unexpected:
        raise RuntimeError("stored evidence contains tickers outside the controlled universe")
    if not args.apply:
        print("NO_WRITE_PREFLIGHT_OK", flush=True)
        return 0

    api_key = resolve_tiingo_api_key(args.tiingo_token_file)
    if api_key is None:
        raise RuntimeError("Tiingo credential unavailable")
    available_at = utc_now() if prior_run is None else str(prior_run[0])
    client = requests.Session()
    before = core_counts(reader)
    stage_ingestion_run(
        session=client,
        reader=reader,
        endpoint=endpoint,
        token=token,
        run_id=run_id,
        provider=PROVIDER,
        ingestion_mode=MODE,
        source_session=source_session,
        available_at_utc=available_at,
        code_version_sha256=code_hash,
        expected_ticker_count=len(tickers),
    )
    prior_run = existing_run(reader, run_id)
    if prior_run is None or int(prior_run[2]) != len(tickers):
        raise RuntimeError("stored parent run does not match the controlled universe")
    if str(prior_run[1]) == "COMPLETE":
        if len(staged) != len(tickers):
            raise RuntimeError("completed run is missing evidence")
        print(f"ALREADY_COMPLETE run_id={run_id} rows={len(staged)}", flush=True)
        return 0

    missing = [ticker for ticker in tickers if ticker not in staged]
    print(
        f"STAGING_START run_id={run_id} existing={len(staged)} missing={len(missing)}",
        flush=True,
    )
    for position, ticker in enumerate(missing, start=1):
        frame = fetch_one(
            ticker,
            source_session,
            api_key,
            attempts=args.attempts,
            retry_seconds=args.retry_seconds,
        )
        observed_at = utc_now()
        rows = prepare_revision_rows(
            frame,
            run_id=run_id,
            provider=PROVIDER,
            source_session=source_session,
            observed_at_utc=observed_at,
        )
        stage_revision_batch(
            session=client,
            reader=reader,
            endpoint=endpoint,
            token=token,
            run_id=run_id,
            rows=rows,
        )
        staged.add(ticker)
        print(
            f"STAGED ticker={ticker} progress={len(staged)}/{len(tickers)} "
            f"remaining={len(tickers) - len(staged)}",
            flush=True,
        )
        if position < len(missing):
            time.sleep(args.request_interval_seconds)

    complete_ingestion_run(
        session=client,
        reader=reader,
        endpoint=endpoint,
        token=token,
        run_id=run_id,
        source_session=source_session,
        completed_at_utc=utc_now(),
        expected_row_count=len(tickers),
    )
    after = core_counts(reader)
    if after != before:
        raise RuntimeError("protected production table counts changed during evidence staging")
    print(
        f"COMPLETE_EVIDENCE_ONLY run_id={run_id} rows={len(tickers)} "
        f"protected_counts_unchanged=true",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
