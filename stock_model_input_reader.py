"""Canonical DB-only reader for validated stock-model market snapshots.

The reader accepts only an immutable MARKET_FEATURES snapshot selected by
model_input_reader.select_validated_snapshot. It has no file, SQLite,
Streamlit, cache, or network fallback.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import numpy as np
import pandas as pd

from model_input_reader import InputSnapshot, verify_snapshot_counts
from model_lineage import LineageError


_SOURCE_COLUMNS = (
    "ticker", "date", "close_price", "volume", "daily_return_pct",
    "rsi_14d", "adx_14d", "plus_di_14d", "minus_di_14d", "atr_14d",
    "sector_momentum_score", "vix_close", "tnx_trend_5d",
)
_COLUMN_RENAMES = {
    "ticker": "Ticker",
    "date": "Date",
    "close_price": "Close",
    "volume": "Volume",
    "daily_return_pct": "Daily_Return_%",
    "rsi_14d": "RSI_14d",
    "adx_14d": "ADX_14d",
    "plus_di_14d": "Plus_DI_14d",
    "minus_di_14d": "Minus_DI_14d",
    "atr_14d": "ATR_14d",
    "sector_momentum_score": "Sector_Momentum_Score",
    "vix_close": "VIX_Close",
    "tnx_trend_5d": "TNX_Trend_5d",
}
_MODEL_COLUMNS = tuple(_COLUMN_RENAMES[column] for column in _SOURCE_COLUMNS)
_FINITE_COLUMNS = tuple(column for column in _MODEL_COLUMNS if column not in {"Ticker", "Date"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _required_ticker_set(required_tickers: Iterable[str]) -> set[str]:
    if isinstance(required_tickers, (str, bytes)):
        raise LineageError("Required market tickers must be an iterable of ticker values.")
    tickers = {str(ticker).strip().upper() for ticker in required_tickers}
    if not tickers or "" in tickers:
        raise LineageError("Required market tickers cannot be empty or blank.")
    return tickers


def load_stock_model_market_frame(
    db,
    snapshot: InputSnapshot,
    *,
    required_tickers: Iterable[str],
    page_size: int = 500,
) -> pd.DataFrame:
    """Load and validate one exact Turso MARKET_FEATURES snapshot.

    Rows are read with bounded (ticker, date) keyset pagination and returned
    in deterministic Ticker, Date order using the column contract consumed by
    stock_model_dataset.build_stock_model_dataset.
    """
    if snapshot.dataset_type != "MARKET_FEATURES":
        raise LineageError("Stock-model market input requires a MARKET_FEATURES snapshot.")
    if not snapshot.source_checksum_sha256 or not _SHA256.fullmatch(
        snapshot.source_checksum_sha256
    ):
        raise LineageError("Market snapshot requires a lowercase SHA-256 checksum.")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 1000:
        raise LineageError("Market snapshot page size must be between 1 and 1000.")
    required = _required_ticker_set(required_tickers)

    verify_snapshot_counts(db, snapshot, table_name="market_daily_features")
    records: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str]] = set()
    cursor = ("", "")

    while True:
        result = db.execute(
            """
            SELECT ticker,date,close_price,volume,daily_return_pct,
                   rsi_14d,adx_14d,plus_di_14d,minus_di_14d,atr_14d,
                   sector_momentum_score,vix_close,tnx_trend_5d
            FROM market_daily_features
            WHERE snapshot_id = ?
              AND (ticker > ? OR (ticker = ? AND date > ?))
            ORDER BY ticker,date
            LIMIT ?
            """,
            [snapshot.snapshot_id, cursor[0], cursor[0], cursor[1], page_size],
        )
        if tuple(result.columns) != _SOURCE_COLUMNS:
            raise LineageError("Market snapshot query returned an unexpected column contract.")
        if len(result.rows) > page_size:
            raise LineageError("Market snapshot query exceeded its bounded page size.")
        if not result.rows:
            break

        for raw in result.rows:
            if len(raw) != len(_SOURCE_COLUMNS):
                raise LineageError("Market snapshot row has an unexpected column count.")
            row = dict(zip(_SOURCE_COLUMNS, raw))
            raw_ticker = str(row["ticker"]).strip()
            raw_date = str(row["date"]).strip()
            raw_key = (raw_ticker, raw_date)
            ticker = raw_ticker.upper()
            key = (ticker, raw_date)
            if key in seen_keys:
                raise LineageError("Market snapshot contains duplicate ticker/session keys.")
            if not raw_ticker or not raw_date or raw_key <= cursor:
                raise LineageError("Market snapshot keyset order is invalid or non-progressing.")
            seen_keys.add(key)
            records.append({
                _COLUMN_RENAMES[column]: (ticker if column == "ticker" else row[column])
                for column in _SOURCE_COLUMNS
            })
            cursor = raw_key
            if len(records) > snapshot.expected_row_count:
                raise LineageError("Market snapshot pagination exceeded the validated row count.")

        if len(result.rows) < page_size:
            break

    verify_snapshot_counts(db, snapshot, table_name="market_daily_features")
    if len(records) != snapshot.expected_row_count:
        raise LineageError("Loaded market rows do not match validated snapshot metadata.")

    frame = pd.DataFrame.from_records(records, columns=_MODEL_COLUMNS)
    if frame.empty:
        raise LineageError("Validated market snapshot contains no model rows.")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    if frame["Date"].isna().any():
        raise LineageError("Market snapshot contains invalid session dates.")
    for column in _FINITE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if not np.isfinite(frame[list(_FINITE_COLUMNS)].to_numpy(dtype=float)).all():
        raise LineageError("Market snapshot contains missing or non-finite required fields.")

    frame = frame.sort_values(["Ticker", "Date"], kind="stable").reset_index(drop=True)
    if frame.duplicated(["Ticker", "Date"]).any():
        raise LineageError("Market snapshot contains duplicate ticker/session keys.")
    if frame["Ticker"].nunique() != snapshot.expected_ticker_count:
        raise LineageError("Loaded market tickers do not match validated snapshot metadata.")
    latest_session = frame["Date"].max().date()
    if latest_session != snapshot.source_session_date:
        raise LineageError(
            "Market snapshot maximum session does not match its declared source session."
        )
    missing = sorted(required.difference(frame["Ticker"].unique()))
    if missing:
        raise LineageError("Market snapshot lacks required tickers: " + ", ".join(missing) + ".")
    return frame
