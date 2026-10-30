"""Bounded, read-only repeatability probe for raw market-provider responses."""

from __future__ import annotations

import argparse
from datetime import date
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data_provider import fetch_validated_daily_bars, resolve_tiingo_api_key
from scripts.rebuild_market_features_to_turso import provider_source_checksum


COLUMNS = [
    "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume",
    "Dividends", "Stock Splits",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", required=True, type=date.fromisoformat)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    parser.add_argument(
        "--provider", choices=("YAHOO_FINANCE", "TIINGO_EOD"), default="YAHOO_FINANCE"
    )
    parser.add_argument("--tiingo-token-file")
    args = parser.parse_args()
    tiingo_token = resolve_tiingo_api_key(args.tiingo_token_file)
    if args.provider == "TIINGO_EOD" and not tiingo_token:
        raise SystemExit("Tiingo provider requested without a token file.")

    evidence = {}
    for ticker in args.tickers:
        runs = []
        for _ in range(2):
            _, frame, provider, error = fetch_validated_daily_bars(
                ticker,
                args.source_session,
                "2021-08-01",
                tiingo_api_key=tiingo_token,
                yahoo_attempts=0 if args.provider == "TIINGO_EOD" else 3,
            )
            if frame is None:
                runs.append({"error": error})
            else:
                ordered = frame[COLUMNS].sort_values("Date").reset_index(drop=True)
                runs.append({
                    "provider": provider,
                    "rows": len(ordered),
                    "checksum": provider_source_checksum(ordered),
                    "dtypes": {column: str(ordered[column].dtype) for column in COLUMNS},
                    "frame": ordered,
                })
            time.sleep(args.pause_seconds)

        result = {
            "checksums": [run.get("checksum") for run in runs],
            "same_checksum": runs[0].get("checksum") == runs[1].get("checksum"),
        }
        if "frame" in runs[0] and "frame" in runs[1]:
            left = runs[0]["frame"]
            right = runs[1]["frame"]
            differences = left.ne(right) & ~(left.isna() & right.isna())
            result.update({
                "rows": [runs[0]["rows"], runs[1]["rows"]],
                "same_dtypes": runs[0]["dtypes"] == runs[1]["dtypes"],
                "same_values": left.equals(right),
                "different_cell_count": int(differences.sum().sum()),
                "dtypes": [runs[0]["dtypes"], runs[1]["dtypes"]],
            })
        evidence[ticker] = result

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
