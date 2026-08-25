"""Read-only, bounded comparison of staged raw bars to fresh provider bars."""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data_provider import fetch_validated_daily_bars, resolve_tiingo_api_key
from turso_read_pipeline import TursoReadPipeline


DB_COLUMNS = [
    "date", "open_price", "high_price", "low_price", "close_price",
    "adjusted_close", "volume", "dividends", "stock_splits",
]
SOURCE_COLUMNS = [
    "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume",
    "Dividends", "Stock Splits",
]

ABSOLUTE_TOLERANCES = {
    "Open": 1e-9,
    "High": 1e-9,
    "Low": 1e-9,
    "Close": 1e-9,
    # Yahoo may re-serialize adjustment factors between requests.  Half of a
    # tenth of a cent is still twenty times tighter than one-cent execution
    # precision and blocks economically meaningful revisions.
    "Adj Close": 5e-4,
    "Volume": 0.0,
    "Dividends": 0.0,
    "Stock Splits": 0.0,
}


def assess_provider_match(
    *,
    stored_provider: str,
    fresh_provider: str,
    staged: pd.DataFrame,
    fresh: pd.DataFrame,
) -> tuple[dict[str, object], bool]:
    common = staged.merge(
        fresh, on="Date", how="outer", suffixes=("_staged", "_fresh"), indicator=True
    )
    matched = common[common["_merge"] == "both"].copy()
    staged_only = common[common["_merge"] == "left_only"]
    fresh_only = common[common["_merge"] == "right_only"]
    first_staged = staged["Date"].min()
    late_fresh_only = fresh_only[fresh_only["Date"] >= first_staged]
    differing = {}
    tolerance_failures = {}
    first_difference = None
    for column in SOURCE_COLUMNS[1:]:
        left = pd.to_numeric(matched[column + "_staged"], errors="coerce").to_numpy(dtype=float)
        right = pd.to_numeric(matched[column + "_fresh"], errors="coerce").to_numpy(dtype=float)
        exact_mask = ~np.isclose(left, right, rtol=0.0, atol=0.0, equal_nan=True)
        tolerance = ABSOLUTE_TOLERANCES[column]
        tolerance_mask = ~np.isclose(
            left, right, rtol=0.0, atol=tolerance, equal_nan=True
        )
        count = int(exact_mask.sum())
        failure_count = int(tolerance_mask.sum())
        if count:
            finite = np.isfinite(left[exact_mask]) & np.isfinite(right[exact_mask])
            max_abs = (
                float(np.max(np.abs(left[exact_mask][finite] - right[exact_mask][finite])))
                if finite.any()
                else None
            )
            differing[column] = {
                "exact_mismatch_count": count,
                "absolute_tolerance": tolerance,
                "tolerance_failure_count": failure_count,
                "max_abs_difference": max_abs,
            }
            candidate = matched.loc[exact_mask, "Date"].min().date().isoformat()
            first_difference = min(first_difference, candidate) if first_difference else candidate
        if failure_count:
            tolerance_failures[column] = failure_count

    checks = {
        "provider_unchanged": stored_provider == fresh_provider,
        "no_staged_only_dates": staged_only.empty,
        "fresh_only_dates_are_warmup_only": late_fresh_only.empty,
        "all_staged_dates_matched": len(matched) == len(staged),
        "values_within_tolerance": not tolerance_failures,
    }
    evidence = {
        "stored_provider": stored_provider,
        "fresh_provider": fresh_provider,
        "staged_rows": len(staged),
        "fresh_rows": len(fresh),
        "matched_dates": len(matched),
        "staged_only_dates": int(len(staged_only)),
        "fresh_only_dates": int(len(fresh_only)),
        "fresh_only_on_or_after_first_staged": int(len(late_fresh_only)),
        "first_differing_date": first_difference,
        "differing_columns": differing,
        "tolerance_failures": tolerance_failures,
        "checks": checks,
    }
    return evidence, all(checks.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--source-session", required=True, type=date.fromisoformat)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--tiingo-token-file")
    args = parser.parse_args()

    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    db = TursoReadPipeline(endpoint, token, timeout_seconds=30.0)
    tiingo_token = resolve_tiingo_api_key(args.tiingo_token_file)

    evidence = {}
    overall_pass = True
    for ticker in args.tickers:
        lineage = db.execute(
            "SELECT provider,source_checksum_sha256 FROM market_data_provider_lineage "
            "WHERE snapshot_id=? AND ticker=?",
            [args.snapshot_id, ticker],
        ).rows
        if len(lineage) != 1:
            evidence[ticker] = {"error": "missing_or_duplicate_lineage"}
            overall_pass = False
            continue
        stored_provider, stored_checksum = map(str, lineage[0])
        yahoo_attempts = 0 if stored_provider == "TIINGO_EOD" else 3
        _, fresh, fresh_provider, error = fetch_validated_daily_bars(
            ticker,
            args.source_session,
            "2021-08-01",
            tiingo_api_key=tiingo_token,
            yahoo_attempts=yahoo_attempts,
        )
        if fresh is None:
            evidence[ticker] = {"error": error, "stored_provider": stored_provider}
            overall_pass = False
            continue

        result = db.execute(
            "SELECT " + ",".join(DB_COLUMNS) + " FROM market_daily_features "
            "WHERE snapshot_id=? AND ticker=? ORDER BY date",
            [args.snapshot_id, ticker],
        )
        staged = pd.DataFrame(result.rows, columns=SOURCE_COLUMNS)
        staged["Date"] = pd.to_datetime(staged["Date"], errors="raise")
        fresh = fresh[SOURCE_COLUMNS].copy()
        fresh["Date"] = pd.to_datetime(fresh["Date"], errors="raise").dt.tz_localize(None)
        ticker_evidence, ticker_pass = assess_provider_match(
            stored_provider=stored_provider,
            fresh_provider=str(fresh_provider),
            staged=staged,
            fresh=fresh,
        )
        ticker_evidence["stored_source_checksum"] = stored_checksum
        ticker_evidence["status"] = "PASS" if ticker_pass else "FAIL"
        evidence[ticker] = ticker_evidence
        overall_pass = overall_pass and ticker_pass

    print(json.dumps({"status": "PASS" if overall_pass else "FAIL", "tickers": evidence}, indent=2, sort_keys=True))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
