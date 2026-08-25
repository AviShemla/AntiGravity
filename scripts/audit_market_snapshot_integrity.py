"""Read-only, fail-closed integrity audit for a staged market snapshot.

The auditor reads Turso directly, performs no status transition, and emits one
JSON document suitable for durable journal capture.  It intentionally excludes
analyst fields because the rebuilt provider snapshot does not source analyst
estimates.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys

import pandas as pd
import pandas_market_calendars as mcal
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from turso_read_pipeline import TursoReadPipeline
from scripts.rebuild_market_features_to_turso import (
    apply_approved_instrument_registry,
    apply_symbol_lifecycle,
    build_controlled_universe,
)


CRITICAL_FEATURE_COLUMNS = (
    "daily_return_pct", "daily_stdev", "stdev_5d", "stdev_10d", "stdev_20d",
    "max_high_20d", "min_low_20d", "rsi_14d", "atr_14d", "plus_di_14d",
    "minus_di_14d", "adx_14d", "dynamic_stop_loss", "ras_signal",
    "sector_momentum_score", "sector_regime", "vix_close", "market_fear_level",
    "tnx_close", "tnx_lag1_return", "tnx_trend_5d",
)


def evaluate_checks(evidence: dict[str, object]) -> dict[str, bool]:
    snapshot = evidence["snapshot"]
    counts = evidence["counts"]
    ohlcv = evidence["ohlcv"]
    features = evidence["features"]
    latest = evidence["latest"]
    lineage = evidence["lineage"]
    calendar = evidence["calendar"]
    return {
        "one_staging_snapshot": (
            snapshot["row_count"] == 1 and snapshot["status"] == "STAGING"
        ),
        "source_session_matches": snapshot["source_session_date"] == evidence["source_session"],
        "available_after_market_close": evidence["available_after_market_close"],
        "rebuild_code_hash_matches": evidence["rebuild_code_hash_matches"],
        "expected_counts_match": (
            counts["row_count"] == snapshot["expected_row_count"]
            and counts["ticker_count"] == snapshot["expected_ticker_count"]
        ),
        "keys_and_sector_complete": counts["null_key_or_sector_rows"] == 0,
        "ohlcv_complete": ohlcv["null_rows"] == 0,
        "ohlcv_sane": (
            ohlcv["nonpositive_price_rows"] == 0
            and ohlcv["high_violations"] == 0
            and ohlcv["low_violations"] == 0
            and ohlcv["negative_volume_rows"] == 0
        ),
        "critical_features_complete": features["null_critical_rows"] == 0,
        "indicators_sane": (
            features["negative_indicator_rows"] == 0
            and features["bounded_indicator_violations"] == 0
            and features["enum_violations"] == 0
            and features["cross_market_nonpositive"] == 0
        ),
        "latest_session_complete": (
            latest["latest_date"] == evidence["source_session"]
            and latest["latest_tickers"] == snapshot["expected_ticker_count"]
            and latest["latest_rows"] == snapshot["expected_ticker_count"]
        ),
        "provider_lineage_exact": (
            lineage["invalid_rows"] == 0
            and lineage["invalid_providers"] == 0
            and not evidence["feature_tickers_without_lineage"]
            and evidence["extra_lineage_tickers"] == ["^TNX", "^VIX"]
        ),
        "approved_registry_bound": (
            evidence["registry"]["approved_registry_count"] == 1
            and evidence["registry"]["approved_registry_id"] == evidence["registry_id"]
            and not evidence["registry"]["missing_tickers"]
            and not evidence["registry"]["unexpected_tickers"]
        ),
        "calendar_exact": (
            not calendar["missing_sessions"] and not calendar["non_session_dates"]
        ),
        "recent_130_complete": not evidence["recent_130_exceptions"],
        "no_downstream_screening": evidence["screening_run_count"] == 0,
        "primary_key_present": evidence["primary_key_present"],
    }


def _one(db, query: str, args: list[object]) -> dict[str, object]:
    result = db.execute(query, args)
    if len(result.rows) != 1:
        raise RuntimeError("Integrity query did not return exactly one row.")
    return dict(zip(result.columns, result.rows[0]))


def _rows(db, query: str, args: list[object]) -> list[dict[str, object]]:
    result = db.execute(query, args)
    return [dict(zip(result.columns, row)) for row in result.rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--source-session", required=True, type=date.fromisoformat)
    parser.add_argument("--universe-snapshot", required=True)
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--env-file", type=Path, default=Path("/opt/antigravity/.env"))
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()
    if not 10.0 <= args.timeout_seconds <= 300.0:
        raise SystemExit("Timeout must be between 10 and 300 seconds.")

    load_dotenv(args.env_file, override=True)
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    db = TursoReadPipeline(endpoint, token, timeout_seconds=args.timeout_seconds)
    sid = args.snapshot_id
    source_session = args.source_session.isoformat()

    snapshot = _one(
        db,
        "SELECT COUNT(*) AS row_count,MIN(source_session_date) AS source_session_date,"
        "MIN(expected_row_count) AS expected_row_count,"
        "MIN(expected_ticker_count) AS expected_ticker_count,MIN(status) AS status,"
        "MIN(available_at_utc) AS available_at_utc,MIN(code_version) AS code_version "
        "FROM model_input_snapshots WHERE snapshot_id=?",
        [sid],
    )
    counts = _one(
        db,
        "SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,"
        "SUM(CASE WHEN ticker IS NULL OR date IS NULL OR sector IS NULL THEN 1 ELSE 0 END) "
        "AS null_key_or_sector_rows FROM market_daily_features WHERE snapshot_id=?",
        [sid],
    )
    ohlcv = _one(
        db,
        "SELECT SUM(CASE WHEN open_price IS NULL OR high_price IS NULL OR low_price IS NULL "
        "OR close_price IS NULL OR adjusted_close IS NULL OR volume IS NULL THEN 1 ELSE 0 END) AS null_rows,"
        "SUM(CASE WHEN open_price<=0 OR high_price<=0 OR low_price<=0 OR close_price<=0 "
        "OR adjusted_close<=0 THEN 1 ELSE 0 END) AS nonpositive_price_rows,"
        "SUM(CASE WHEN high_price<open_price OR high_price<close_price OR high_price<low_price "
        "THEN 1 ELSE 0 END) AS high_violations,"
        "SUM(CASE WHEN low_price>open_price OR low_price>close_price OR low_price>high_price "
        "THEN 1 ELSE 0 END) AS low_violations,"
        "SUM(CASE WHEN volume<0 THEN 1 ELSE 0 END) AS negative_volume_rows "
        "FROM market_daily_features WHERE snapshot_id=?",
        [sid],
    )
    null_expression = " OR ".join(f"{column} IS NULL" for column in CRITICAL_FEATURE_COLUMNS)
    features = _one(
        db,
        f"SELECT SUM(CASE WHEN {null_expression} THEN 1 ELSE 0 END) AS null_critical_rows,"
        "SUM(CASE WHEN daily_stdev<0 OR stdev_5d<0 OR stdev_10d<0 OR stdev_20d<0 "
        "OR atr_14d<0 OR plus_di_14d<0 OR minus_di_14d<0 OR adx_14d<0 THEN 1 ELSE 0 END) "
        "AS negative_indicator_rows,"
        "SUM(CASE WHEN rsi_14d<0 OR rsi_14d>100 OR adx_14d>100 THEN 1 ELSE 0 END) "
        "AS bounded_indicator_violations,"
        "SUM(CASE WHEN ras_signal NOT IN ('BUY','SELL','HOLD') OR sector_regime NOT IN "
        "('BULL_REGIME','BEAR_REGIME') THEN 1 ELSE 0 END) AS enum_violations,"
        "SUM(CASE WHEN vix_close<=0 OR tnx_close<=0 THEN 1 ELSE 0 END) "
        "AS cross_market_nonpositive FROM market_daily_features WHERE snapshot_id=?",
        [sid],
    )
    latest = _one(
        db,
        "SELECT MAX(date) AS latest_date,SUM(CASE WHEN date=? THEN 1 ELSE 0 END) AS latest_rows,"
        "COUNT(DISTINCT CASE WHEN date=? THEN ticker END) AS latest_tickers "
        "FROM market_daily_features WHERE snapshot_id=?",
        [source_session, source_session, sid],
    )
    lineage = _one(
        db,
        "SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,"
        "SUM(CASE WHEN requested_source_session_date<>? OR last_available_date<>? "
        "OR source_row_count<252 OR source_checksum_sha256 IS NULL "
        "OR LENGTH(source_checksum_sha256)<>64 THEN 1 ELSE 0 END) AS invalid_rows,"
        "SUM(CASE WHEN provider NOT IN ('YAHOO_FINANCE','TIINGO_EOD') THEN 1 ELSE 0 END) "
        "AS invalid_providers FROM market_data_provider_lineage WHERE snapshot_id=?",
        [source_session, source_session, sid],
    )
    feature_tickers = {
        str(row["ticker"])
        for row in _rows(db, "SELECT DISTINCT ticker FROM market_daily_features WHERE snapshot_id=?", [sid])
    }
    lineage_tickers = {
        str(row["ticker"])
        for row in _rows(db, "SELECT ticker FROM market_data_provider_lineage WHERE snapshot_id=?", [sid])
    }
    observed_dates = [
        str(row["date"])
        for row in _rows(db, "SELECT DISTINCT date FROM market_daily_features WHERE snapshot_id=? ORDER BY date", [sid])
    ]
    if not observed_dates:
        raise RuntimeError("Snapshot has no feature dates.")
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=observed_dates[0], end_date=observed_dates[-1]
    )
    expected_dates = [pd.Timestamp(value).date().isoformat() for value in schedule.index]
    recent_dates = expected_dates[-130:]
    recent_exceptions = _rows(
        db,
        "SELECT ticker,COUNT(DISTINCT date) AS session_count FROM market_daily_features "
        "WHERE snapshot_id=? AND date>=? GROUP BY ticker HAVING session_count<>130 ORDER BY ticker",
        [sid, recent_dates[0]],
    )
    schema = _one(
        db,
        "SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table' "
        "AND name='market_daily_features' AND sql LIKE '%PRIMARY KEY (snapshot_id, ticker, date)%'",
        [],
    )
    screening = _one(
        db,
        "SELECT COUNT(*) AS count FROM predictive_screening_runs WHERE market_snapshot_id=?",
        [sid],
    )

    stock_universe = db.execute(
        "SELECT ticker,MAX(sector) AS sector FROM market_daily_features "
        "WHERE snapshot_id=? GROUP BY ticker ORDER BY ticker",
        [args.universe_snapshot],
    )
    etf_scorecards = db.execute(
        "SELECT DISTINCT ticker FROM etf_scorecards_master WHERE persona LIKE 'ETF_%' "
        "AND date=(SELECT MAX(date) FROM etf_scorecards_master WHERE persona LIKE 'ETF_%') "
        "ORDER BY ticker",
        [],
    )
    etf_ledgers = db.execute(
        "SELECT cl.holdings_json FROM capital_ledgers cl JOIN "
        "(SELECT persona,MAX(date) AS max_date FROM capital_ledgers "
        "WHERE persona LIKE 'ETF_%' GROUP BY persona) latest "
        "ON latest.persona=cl.persona AND latest.max_date=cl.date ORDER BY cl.persona",
        [],
    )
    etf_pending = db.execute(
        "SELECT target_holdings_json FROM pending_orders WHERE persona LIKE 'ETF_%' ORDER BY persona",
        [],
    )
    expected_universe = build_controlled_universe(
        stock_universe.rows, etf_scorecards.rows, etf_ledgers.rows, etf_pending.rows
    )
    lifecycle = db.execute(
        "SELECT ticker,event_type,effective_date,successor_ticker,sector "
        "FROM market_symbol_lifecycle_events WHERE effective_date<=? "
        "ORDER BY effective_date,event_id",
        [source_session],
    )
    expected_universe, lifecycle_replacements = apply_symbol_lifecycle(
        expected_universe, lifecycle.rows, source_session=args.source_session
    )
    registry_versions = db.execute(
        "SELECT registry_id FROM market_instrument_registry_versions WHERE status='APPROVED' "
        "ORDER BY evidence_as_of_date DESC,registry_id",
        [],
    )
    registry = db.execute(
        "SELECT registry_id,ticker,asset_class,sector,usage,minimum_history_rows "
        "FROM market_instrument_registry WHERE registry_id=? ORDER BY ticker",
        [args.registry_id],
    )
    expected_universe = apply_approved_instrument_registry(
        expected_universe, registry_versions.rows, registry.rows
    )
    expected_tickers = set(expected_universe)
    market_close = pd.Timestamp(schedule.iloc[-1]["market_close"])
    available_at = pd.Timestamp(str(snapshot["available_at_utc"]))
    if available_at.tzinfo is None:
        available_at = available_at.tz_localize("UTC")
    rebuild_path = ROOT / "scripts" / "rebuild_market_features_to_turso.py"
    rebuild_hash = hashlib.sha256(rebuild_path.read_bytes()).hexdigest()

    evidence = {
        "snapshot_id": sid,
        "source_session": source_session,
        "universe_snapshot": args.universe_snapshot,
        "registry_id": args.registry_id,
        "snapshot": snapshot,
        "counts": counts,
        "ohlcv": ohlcv,
        "features": features,
        "latest": latest,
        "lineage": lineage,
        "feature_tickers_without_lineage": sorted(feature_tickers - lineage_tickers),
        "extra_lineage_tickers": sorted(lineage_tickers - feature_tickers),
        "calendar": {
            "first": observed_dates[0],
            "last": observed_dates[-1],
            "observed_sessions": len(observed_dates),
            "expected_sessions": len(expected_dates),
            "missing_sessions": sorted(set(expected_dates) - set(observed_dates)),
            "non_session_dates": sorted(set(observed_dates) - set(expected_dates)),
        },
        "recent_130_start": recent_dates[0],
        "recent_130_exceptions": recent_exceptions,
        "screening_run_count": int(screening["count"]),
        "primary_key_present": int(schema["count"]) == 1,
        "available_after_market_close": available_at >= market_close,
        "market_close_utc": market_close.isoformat(),
        "available_at_utc": available_at.isoformat(),
        "rebuild_code_hash_matches": str(snapshot["code_version"]) == rebuild_hash,
        "current_rebuild_code_sha256": rebuild_hash,
        "registry": {
            "approved_registry_count": len(registry_versions.rows),
            "approved_registry_id": (
                str(registry_versions.rows[0][0]) if len(registry_versions.rows) == 1 else None
            ),
            "expected_ticker_count": len(expected_tickers),
            "actual_ticker_count": len(feature_tickers),
            "missing_tickers": sorted(expected_tickers - feature_tickers),
            "unexpected_tickers": sorted(feature_tickers - expected_tickers),
            "lifecycle_replacements": lifecycle_replacements,
        },
    }
    checks = evaluate_checks(evidence)
    payload = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "evidence": evidence}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
