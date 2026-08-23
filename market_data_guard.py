"""Fail-closed market-session and daily-bar validation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from model_lineage import LineageError


def last_completed_nyse_session(now_utc: datetime, *, settlement_delay_minutes: int = 30) -> date:
    if now_utc.tzinfo is None:
        raise LineageError("Market-session clock must be timezone-aware.")
    if settlement_delay_minutes < 0:
        raise LineageError("Settlement delay cannot be negative.")
    import pandas_market_calendars as mcal

    now_utc = now_utc.astimezone(timezone.utc)
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(
        start_date=(now_utc.date() - timedelta(days=14)).isoformat(),
        end_date=now_utc.date().isoformat(),
    )
    if schedule.empty:
        raise LineageError("NYSE calendar returned no recent sessions.")
    cutoff = now_utc - timedelta(minutes=settlement_delay_minutes)
    closes = pd.to_datetime(schedule["market_close"], utc=True)
    completed = schedule.loc[closes <= cutoff]
    if completed.empty:
        raise LineageError("No NYSE session completed before the guarded cutoff.")
    return pd.Timestamp(completed.index[-1]).date()


def validate_daily_bars(
    frame: pd.DataFrame,
    *,
    ticker: str,
    source_session_date: date,
    minimum_rows: int = 252,
    ohlc_relative_tolerance: float = 0.0005,
) -> pd.DataFrame:
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise LineageError(f"{ticker} bars are missing required columns: {', '.join(missing)}.")
    if not 0.0 <= ohlc_relative_tolerance <= 0.001:
        raise LineageError("OHLC relative tolerance must be between zero and 10 basis points.")
    clean = frame.copy()
    clean["Date"] = pd.to_datetime(clean["Date"], errors="coerce").dt.tz_localize(None)
    if clean["Date"].isna().any():
        raise LineageError(f"{ticker} has invalid session dates.")
    if clean["Date"].duplicated().any():
        raise LineageError(f"{ticker} has duplicate daily sessions.")
    clean = clean.sort_values("Date").reset_index(drop=True)
    if len(clean) < minimum_rows:
        raise LineageError(f"{ticker} has only {len(clean)} daily bars; {minimum_rows} required.")
    if clean["Date"].max().date() != source_session_date:
        raise LineageError(
            f"{ticker} latest bar is {clean['Date'].max().date()}, expected {source_session_date}."
        )
    if (clean["Date"].dt.date > source_session_date).any():
        raise LineageError(f"{ticker} contains a bar after the source session.")
    numeric = clean[["Open", "High", "Low", "Close", "Volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if not np.isfinite(numeric.to_numpy()).all():
        raise LineageError(f"{ticker} has non-finite OHLCV data.")
    if (numeric[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise LineageError(f"{ticker} has non-positive OHLC data.")
    if (numeric["Volume"] < 0).any():
        raise LineageError(f"{ticker} has negative volume.")
    tolerance = numeric[["Open", "High", "Low", "Close"]].abs().max(axis=1) * ohlc_relative_tolerance
    invalid = (
        (numeric["High"] + tolerance < numeric["Low"])
        | (numeric["High"] + tolerance < numeric["Open"])
        | (numeric["High"] + tolerance < numeric["Close"])
        | (numeric["Low"] - tolerance > numeric["Open"])
        | (numeric["Low"] - tolerance > numeric["Close"])
    )
    if invalid.any():
        first_bad = clean.loc[invalid, "Date"].iloc[0].date()
        raise LineageError(f"{ticker} has invalid OHLC bounds on {first_bad}.")
    clean[["Open", "High", "Low", "Close", "Volume"]] = numeric
    return clean
