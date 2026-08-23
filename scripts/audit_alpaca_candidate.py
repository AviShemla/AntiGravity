"""Read-only repeatability audit for the Alpaca market-data candidate.

This script does not write Turso, alter production files, or activate Alpaca.
Credentials are read from root-controlled one-line files and are never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date

import pandas as pd

from alpaca_candidate_provider import (
    fetch_alpaca_adjusted_bars,
    resolve_alpaca_credentials,
)


TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,15}$")


def frame_checksum(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="raise").dt.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    records = normalized.to_dict(orient="records")
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare_frames(first: pd.DataFrame, second: pd.DataFrame) -> dict[str, object]:
    same_columns = list(first.columns) == list(second.columns)
    same_dtypes = first.dtypes.astype(str).tolist() == second.dtypes.astype(str).tolist()
    same_values = first.equals(second)
    return {
        "rows_first": len(first),
        "rows_second": len(second),
        "same_columns": same_columns,
        "same_dtypes": same_dtypes,
        "same_values": same_values,
        "checksum_first": frame_checksum(first),
        "checksum_second": frame_checksum(second),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-id-file", required=True)
    parser.add_argument("--secret-key-file", required=True)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--start-date", default="2021-09-01")
    parser.add_argument("--tickers", nargs="+", required=True)
    args = parser.parse_args()

    source_session = date.fromisoformat(args.source_session)
    key_id, secret_key = resolve_alpaca_credentials(
        args.key_id_file, args.secret_key_file
    )
    results = []
    all_repeatable = True
    for raw_ticker in args.tickers:
        ticker = raw_ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(ticker):
            raise ValueError(f"Invalid ticker: {raw_ticker!r}")
        first = fetch_alpaca_adjusted_bars(
            ticker,
            source_session,
            args.start_date,
            key_id=key_id,
            secret_key=secret_key,
        )
        second = fetch_alpaca_adjusted_bars(
            ticker,
            source_session,
            args.start_date,
            key_id=key_id,
            secret_key=secret_key,
        )
        comparison = compare_frames(first, second)
        repeatable = bool(
            comparison["same_columns"]
            and comparison["same_dtypes"]
            and comparison["same_values"]
            and comparison["checksum_first"] == comparison["checksum_second"]
        )
        all_repeatable = all_repeatable and repeatable
        results.append({"ticker": ticker, "repeatable": repeatable, **comparison})

    print(json.dumps({
        "provider": "ALPACA_MARKET_DATA_CANDIDATE",
        "source_session": source_session.isoformat(),
        "start_date": args.start_date,
        "all_repeatable": all_repeatable,
        "results": results,
    }, sort_keys=True))
    return 0 if all_repeatable else 1


if __name__ == "__main__":
    raise SystemExit(main())
