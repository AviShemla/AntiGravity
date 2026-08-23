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
    for ticker in args.tickers:
        lineage = db.execute(
            "SELECT provider,source_checksum_sha256 FROM market_data_provider_lineage "
            "WHERE snapshot_id=? AND ticker=?",
            [args.snapshot_id, ticker],
        ).rows
        if len(lineage) != 1:
            evidence[ticker] = {"error": "missing_or_duplicate_lineage"}
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
        common = staged.merge(fresh, on="Date", how="outer", suffixes=("_staged", "_fresh"), indicator=True)
        matched = common[common["_merge"] == "both"].copy()
        differing = {}
        first_difference = None
        for column in SOURCE_COLUMNS[1:]:
            left = pd.to_numeric(matched[column + "_staged"], errors="coerce").to_numpy(dtype=float)
            right = pd.to_numeric(matched[column + "_fresh"], errors="coerce").to_numpy(dtype=float)
            mask = ~np.isclose(left, right, rtol=0.0, atol=0.0, equal_nan=True)
            count = int(mask.sum())
            if count:
                finite = np.isfinite(left[mask]) & np.isfinite(right[mask])
                max_abs = float(np.max(np.abs(left[mask][finite] - right[mask][finite]))) if finite.any() else None
                rounded_counts = {
                    str(decimals): int((
                        ~np.isclose(
                            np.round(left, decimals),
                            np.round(right, decimals),
                            rtol=0.0,
                            atol=0.0,
                            equal_nan=True,
                        )
                    ).sum())
                    for decimals in (2, 3, 4, 5, 6, 8, 10, 12)
                }
                differing[column] = {
                    "count": count,
                    "max_abs_difference": max_abs,
                    "mismatch_count_after_rounding": rounded_counts,
                }
                candidate = matched.loc[mask, "Date"].min().date().isoformat()
                first_difference = min(first_difference, candidate) if first_difference else candidate

        evidence[ticker] = {
            "stored_provider": stored_provider,
            "fresh_provider": fresh_provider,
            "stored_source_checksum": stored_checksum,
            "staged_rows": len(staged),
            "fresh_rows": len(fresh),
            "matched_dates": len(matched),
            "staged_only_dates": int((common["_merge"] == "left_only").sum()),
            "fresh_only_dates": int((common["_merge"] == "right_only").sum()),
            "first_differing_date": first_difference,
            "differing_columns": differing,
        }

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
