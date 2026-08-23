"""Validated end-of-day market-data providers for model-input rebuilds.

Yahoo is attempted first. Tiingo is attempted only when Yahoo cannot provide a
complete, valid source session and a rotated ``TIINGO_API_KEY`` is available in
the environment. Provider failures never cause bar synthesis or forward fill.
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from market_data_guard import validate_daily_bars


HistoryFetcher = Callable[[str, date, str], pd.DataFrame]


def resolve_tiingo_api_key(token_file: str | Path | None = None) -> str | None:
    """Load a Tiingo token from a secret file or, secondarily, the environment."""
    if token_file is not None:
        path = Path(token_file)
        if not path.is_file():
            raise ValueError(f"Tiingo token file is missing: {path}")
        raw = path.read_text(encoding="utf-8")
        if len(raw.splitlines()) != 1:
            raise ValueError("Tiingo token file must contain exactly one line")
        token = raw.strip()
    else:
        token = (os.environ.get("TIINGO_API_KEY") or "").strip()
    if not token:
        return None
    if not 20 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise ValueError("Tiingo token has an invalid format")
    return token


def fetch_yahoo_history(ticker: str, source_session: date, start_date: str) -> pd.DataFrame:
    api_ticker = ticker.replace(".", "-")
    end_exclusive = (source_session + timedelta(days=1)).isoformat()
    return yf.Ticker(api_ticker).history(
        start=start_date,
        end=end_exclusive,
        auto_adjust=False,
        actions=True,
        timeout=20,
    )


def normalize_yahoo_history(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    if "Date" in raw.columns:
        return raw.copy()
    frame = raw.reset_index()
    return frame.rename(columns={frame.columns[0]: "Date"})


def fetch_tiingo_history(
    ticker: str,
    source_session: date,
    start_date: str,
    *,
    api_key: str,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if not api_key:
        raise ValueError("Tiingo credential unavailable")
    api_ticker = ticker.replace(".", "-")
    client = session or requests.Session()
    response = client.get(
        f"https://api.tiingo.com/tiingo/daily/{api_ticker}/prices",
        params={"startDate": start_date, "endDate": source_session.isoformat()},
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Tiingo returned HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise ValueError("Tiingo returned an empty or invalid payload")
    frame = pd.DataFrame(payload)
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("Tiingo payload missing fields: " + ", ".join(missing))
    split_source = (
        frame["splitFactor"]
        if "splitFactor" in frame
        else pd.Series(1.0, index=frame.index)
    )
    split_factor = pd.to_numeric(split_source, errors="coerce").fillna(1.0)
    normalized = pd.DataFrame(
        {
            "Date": pd.to_datetime(frame["date"], utc=True, errors="coerce").dt.tz_localize(None),
            "Open": frame["open"],
            "High": frame["high"],
            "Low": frame["low"],
            "Close": frame["close"],
            "Adj Close": frame.get("adjClose", frame["close"]),
            "Volume": frame["volume"],
            "Dividends": frame.get("divCash", 0.0),
            "Stock Splits": np.where(split_factor == 1.0, 0.0, split_factor),
        }
    )
    return normalized


def fetch_tiingo_revision_bars(
    ticker: str,
    source_session: date,
    start_date: str,
    *,
    api_key: str,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch provider-native raw, adjusted, and corporate-action evidence."""
    if not api_key:
        raise ValueError("Tiingo credential unavailable")
    api_ticker = ticker.replace(".", "-")
    client = session or requests.Session()
    response = client.get(
        f"https://api.tiingo.com/tiingo/daily/{api_ticker}/prices",
        params={"startDate": start_date, "endDate": source_session.isoformat()},
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Tiingo returned HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise ValueError("Tiingo returned an empty or invalid payload")
    frame = pd.DataFrame(payload)
    required = {
        "date", "open", "high", "low", "close", "volume",
        "adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume",
        "divCash", "splitFactor",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("Tiingo revision payload missing fields: " + ", ".join(missing))
    dates = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    if dates.isna().any():
        raise ValueError("Tiingo revision payload contains an invalid date")
    return pd.DataFrame({
        "Ticker": ticker.upper(),
        "Date": dates.dt.tz_localize(None),
        "Raw Open": frame["open"],
        "Raw High": frame["high"],
        "Raw Low": frame["low"],
        "Raw Close": frame["close"],
        "Raw Volume": frame["volume"],
        "Adjusted Open": frame["adjOpen"],
        "Adjusted High": frame["adjHigh"],
        "Adjusted Low": frame["adjLow"],
        "Adjusted Close": frame["adjClose"],
        "Adjusted Volume": frame["adjVolume"],
        "Dividends": frame["divCash"],
        "Split Factor": frame["splitFactor"],
    })


def fetch_validated_daily_bars(
    ticker: str,
    source_session: date,
    start_date: str,
    *,
    tiingo_api_key: str | None,
    yahoo_fetcher: HistoryFetcher | None = None,
    tiingo_fetcher: HistoryFetcher | None = None,
    minimum_rows: int = 252,
    yahoo_attempts: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[str, pd.DataFrame | None, str | None, str | None]:
    """Return ticker, validated bars, provider, or a bounded error string."""
    if yahoo_attempts < 0 or yahoo_attempts > 5:
        raise ValueError("Yahoo attempts must be between 0 and 5")
    yahoo = yahoo_fetcher or fetch_yahoo_history
    failures: list[str] = []
    for attempt in range(yahoo_attempts):
        try:
            validated = validate_daily_bars(
                normalize_yahoo_history(yahoo(ticker, source_session, start_date)),
                ticker=ticker,
                source_session_date=source_session,
                minimum_rows=minimum_rows,
            )
            return ticker, validated, "YAHOO_FINANCE", None
        except Exception as exc:
            failures.append(f"YAHOO_FINANCE[{attempt + 1}]: {type(exc).__name__}: {exc}")
            if attempt + 1 < yahoo_attempts:
                sleep_fn(1.0 + attempt)

    if not tiingo_api_key:
        failures.append("TIINGO: credential unavailable")
        return ticker, None, None, "; ".join(failures)

    try:
        if tiingo_fetcher is None:
            raw = fetch_tiingo_history(
                ticker, source_session, start_date, api_key=tiingo_api_key
            )
        else:
            raw = tiingo_fetcher(ticker, source_session, start_date)
        validated = validate_daily_bars(
            raw,
            ticker=ticker,
            source_session_date=source_session,
            minimum_rows=minimum_rows,
        )
        return ticker, validated, "TIINGO_EOD", None
    except Exception as exc:
        failures.append(f"TIINGO: {type(exc).__name__}: {exc}")
        return ticker, None, None, "; ".join(failures)
