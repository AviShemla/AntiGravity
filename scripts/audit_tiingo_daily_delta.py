"""Read-only proof of Tiingo's multi-symbol daily delta endpoint."""

from __future__ import annotations

import argparse
from datetime import date
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data_provider import resolve_tiingo_api_key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", required=True, type=date.fromisoformat)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--tiingo-token-file", required=True)
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    token = resolve_tiingo_api_key(args.tiingo_token_file)
    params = {} if args.latest else {
        "tickers": ",".join(args.tickers),
        "startDate": args.source_session.isoformat(),
        "endDate": args.source_session.isoformat(),
    }
    response = requests.get(
        "https://api.tiingo.com/tiingo/daily/prices",
        params=params,
        headers={"Authorization": f"Token {token}", "Accept": "application/json"},
        timeout=30,
    )
    evidence = {"http_status": response.status_code}
    if response.status_code == 200:
        evidence["content_type"] = response.headers.get("Content-Type")
        evidence["content_bytes"] = len(response.content)
        try:
            payload = response.json()
        except ValueError:
            evidence["error"] = "provider_returned_non_json_success"
            evidence["response_prefix"] = response.text[:160]
            print(json.dumps(evidence, indent=2, sort_keys=True))
            return 1
        rows = payload if isinstance(payload, list) else []
        requested = {ticker.upper() for ticker in args.tickers}
        selected = [row for row in rows if str(row.get("ticker", "")).upper() in requested]
        evidence.update({
            "total_row_count": len(rows),
            "selected_row_count": len(selected),
            "selected_tickers": sorted({str(row.get("ticker", "")) for row in selected}),
            "missing_requested_tickers": sorted(
                requested.difference(str(row.get("ticker", "")).upper() for row in selected)
            ),
            "selected_dates": sorted({str(row.get("date", "")) for row in selected}),
            "fields": sorted(selected[0]) if selected else [],
        })
    else:
        evidence["error"] = "provider_request_failed"
        evidence["provider_detail"] = response.text[:300]
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
