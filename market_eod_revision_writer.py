"""Fail-closed preparation and resumable writes for provider-native EOD evidence.

The module accepts in-memory provider evidence only. It has no CSV, Excel,
SQLite, or local-cache input path. It is not wired into the nightly pipeline.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime

import pandas as pd

from turso_read_pipeline import TursoReadPipeline, _encode_arg


ALLOWED_PROVIDERS = {"ALPACA_MARKET_DATA", "TIINGO_EOD", "YAHOO_FINANCE"}
REQUIRED_COLUMNS = (
    "Ticker", "Date", "Raw Open", "Raw High", "Raw Low", "Raw Close",
    "Raw Volume", "Adjusted Open", "Adjusted High", "Adjusted Low",
    "Adjusted Close", "Adjusted Volume", "Dividends", "Split Factor",
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,15}$")


def _finite_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def source_value_sha256(values: dict[str, object]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prepare_revision_rows(
    frame: pd.DataFrame,
    *,
    run_id: str,
    provider: str,
    source_session: date,
    observed_at_utc: str,
) -> list[list[object]]:
    if not IDENTIFIER.fullmatch(run_id):
        raise ValueError("run_id has an invalid format")
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError("provider is not approved")
    try:
        observed = datetime.fromisoformat(observed_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at_utc is invalid") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    missing = sorted(set(REQUIRED_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError("provider evidence is missing columns: " + ", ".join(missing))
    if frame.empty:
        raise ValueError("provider evidence is empty")

    parsed_dates = pd.to_datetime(frame["Date"], errors="coerce").dt.date
    if parsed_dates.isna().any():
        raise ValueError("provider evidence contains an invalid date")
    tickers = frame["Ticker"].astype(str).str.upper()
    if not tickers.map(lambda value: bool(TICKER.fullmatch(value))).all():
        raise ValueError("provider evidence contains an invalid ticker")
    keys = pd.DataFrame({"Ticker": tickers, "Date": parsed_dates})
    if keys.duplicated().any():
        raise ValueError("provider evidence contains duplicate ticker-date rows")
    if any(value > source_session for value in parsed_dates):
        raise ValueError("provider evidence contains a future row")

    rows: list[list[object]] = []
    for position, (_, raw_row) in enumerate(frame.iterrows(), start=1):
        ticker = tickers.iloc[position - 1]
        row_date = parsed_dates.iloc[position - 1].isoformat()
        numbers = {
            name: _finite_number(raw_row[name], f"row {position} {name}")
            for name in REQUIRED_COLUMNS[2:]
        }
        if numbers["Raw Volume"] < 0 or numbers["Adjusted Volume"] < 0:
            raise ValueError("provider evidence contains negative volume")
        if numbers["Dividends"] < 0 or numbers["Split Factor"] <= 0:
            raise ValueError("provider evidence contains an invalid corporate action")
        for prefix in ("Raw", "Adjusted"):
            if numbers[f"{prefix} High"] < max(
                numbers[f"{prefix} Open"], numbers[f"{prefix} Close"]
            ) or numbers[f"{prefix} Low"] > min(
                numbers[f"{prefix} Open"], numbers[f"{prefix} Close"]
            ):
                raise ValueError(f"provider evidence violates {prefix.lower()} OHLC")
        canonical = {
            "provider": provider,
            "ticker": ticker,
            "date": row_date,
            **{name: numbers[name] for name in REQUIRED_COLUMNS[2:]},
        }
        rows.append([
            run_id, provider, ticker, row_date,
            numbers["Raw Open"], numbers["Raw High"], numbers["Raw Low"],
            numbers["Raw Close"], numbers["Raw Volume"],
            numbers["Adjusted Open"], numbers["Adjusted High"],
            numbers["Adjusted Low"], numbers["Adjusted Close"],
            numbers["Adjusted Volume"], numbers["Dividends"],
            numbers["Split Factor"], source_value_sha256(canonical), observed_at_utc,
        ])
    return rows


def post_statements(session, endpoint: str, token: str, statements) -> None:
    payload = [{
        "type": "execute",
        "stmt": {"sql": sql, "args": [_encode_arg(value) for value in args]},
    } for sql, args in statements]
    payload.append({"type": "close"})
    response = session.post(
        endpoint,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"requests": payload},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Turso EOD revision write failed with HTTP {response.status_code}")
    results = response.json().get("results", [])
    if len(results) < len(statements) or any(
        item.get("type") != "ok" for item in results[:len(statements)]
    ):
        raise RuntimeError("Turso rejected an EOD revision statement")


def stage_revision_rows(
    *,
    session,
    reader: TursoReadPipeline,
    endpoint: str,
    token: str,
    run_id: str,
    rows: list[list[object]],
    batch_size: int = 250,
) -> int:
    """Resume INSERT OR IGNORE rows and prove the exact final count."""
    if not 1 <= batch_size <= 500:
        raise ValueError("batch_size must be between 1 and 500")
    if not rows or any(row[0] != run_id for row in rows):
        raise ValueError("rows do not belong to the requested run")
    expected = len(rows)
    existing = int(reader.execute(
        "SELECT COUNT(*) AS n FROM market_eod_bar_revisions WHERE run_id = ?",
        [run_id],
    ).rows[0][0])
    if existing > expected:
        raise RuntimeError("existing revision rows exceed the expected count")
    sql = (
        "INSERT OR IGNORE INTO market_eod_bar_revisions "
        "(run_id,provider,ticker,date,raw_open,raw_high,raw_low,raw_close,raw_volume,"
        "adjusted_open,adjusted_high,adjusted_low,adjusted_close,adjusted_volume,"
        "dividend_cash,split_factor,source_value_sha256,observed_at_utc) VALUES "
        + "(" + ",".join("?" for _ in range(18)) + ")"
    )
    for offset in range(0, expected, batch_size):
        post_statements(
            session, endpoint, token,
            [(sql, row) for row in rows[offset:offset + batch_size]],
        )
    final = int(reader.execute(
        "SELECT COUNT(*) AS n FROM market_eod_bar_revisions WHERE run_id = ?",
        [run_id],
    ).rows[0][0])
    if final != expected:
        raise RuntimeError("Turso revision count does not match provider evidence")
    return final
