"""Audit-only Alpaca adjusted-bar candidate.

This module is deliberately not wired into production rebuilds. Corporate-action
evidence must be integrated and the complete controlled universe must pass a
credentialed bake-off before activation.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests


def resolve_alpaca_credentials(
    key_id_file: str | Path, secret_key_file: str | Path
) -> tuple[str, str]:
    values = []
    for label, raw_path in (("key ID", key_id_file), ("secret key", secret_key_file)):
        path = Path(raw_path)
        if not path.is_file():
            raise ValueError(f"Alpaca {label} file is missing: {path}")
        raw = path.read_text(encoding="utf-8")
        if len(raw.splitlines()) != 1:
            raise ValueError(f"Alpaca {label} file must contain exactly one line")
        value = raw.strip()
        if not 16 <= len(value) <= 256 or any(character.isspace() for character in value):
            raise ValueError(f"Alpaca {label} has an invalid format")
        values.append(value)
    return values[0], values[1]


def fetch_alpaca_adjusted_bars(
    ticker: str,
    source_session: date,
    start_date: str,
    *,
    key_id: str,
    secret_key: str,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch fully adjusted daily bars; corporate actions are intentionally separate."""
    if not key_id or not secret_key:
        raise ValueError("Alpaca credentials are unavailable")
    client = session or requests.Session()
    endpoint = f"https://data.alpaca.markets/v2/stocks/{ticker}/bars"
    params = {
        "timeframe": "1Day",
        "start": start_date,
        "end": (source_session + timedelta(days=1)).isoformat(),
        "adjustment": "all",
        "feed": "sip",
        "sort": "asc",
        "limit": 10000,
    }
    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    }
    rows = []
    for _ in range(20):
        response = client.get(endpoint, params=params, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Alpaca returned HTTP {response.status_code}")
        payload = response.json()
        page = payload.get("bars")
        if not isinstance(page, list):
            raise ValueError("Alpaca returned an invalid bars payload")
        rows.extend(page)
        page_token = payload.get("next_page_token")
        if not page_token:
            break
        params["page_token"] = page_token
    else:
        raise ValueError("Alpaca pagination exceeded the bounded page limit")
    if not rows:
        raise ValueError("Alpaca returned no adjusted bars")

    raw = pd.DataFrame(rows)
    required = {"t", "o", "h", "l", "c", "v"}
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise ValueError("Alpaca bars are missing fields: " + ", ".join(missing))
    close = pd.to_numeric(raw["c"], errors="coerce")
    return pd.DataFrame({
        "Date": pd.to_datetime(raw["t"], utc=True, errors="coerce").dt.tz_localize(None),
        "Open": pd.to_numeric(raw["o"], errors="coerce"),
        "High": pd.to_numeric(raw["h"], errors="coerce"),
        "Low": pd.to_numeric(raw["l"], errors="coerce"),
        "Close": close,
        "Adj Close": close,
        "Volume": pd.to_numeric(raw["v"], errors="coerce"),
    })
