"""Streaming canonical digests for immutable Oracle market research content.

The encoding is versioned UTF-8 JSON Lines.  Every scalar is explicitly typed,
including nulls, and REAL values use Python's locale-independent hexadecimal
representation of the finite IEEE-754 value.  Rows must arrive in canonical
``ticker,date`` order, so neither content nor ticker-universe hashing requires
materializing the full snapshot.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

from model_lineage import LineageError


MARKET_CONTENT_ENCODING = "oracle-market-daily-features-jsonl-v1"
TICKER_UNIVERSE_ENCODING = "oracle-market-ticker-universe-jsonl-v1"

MARKET_DAILY_FEATURE_COLUMNS = (
    "snapshot_id",
    "ticker",
    "date",
    "sector",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "adjusted_close",
    "volume",
    "dividends",
    "stock_splits",
    "daily_return_pct",
    "daily_stdev",
    "stdev_5d",
    "stdev_10d",
    "stdev_20d",
    "max_high_20d",
    "min_low_20d",
    "rsi_14d",
    "atr_14d",
    "plus_di_14d",
    "minus_di_14d",
    "adx_14d",
    "dynamic_stop_loss",
    "ras_signal",
    "analyst_consensus",
    "analyst_upside_pct",
    "sector_momentum_score",
    "sector_regime",
    "vix_close",
    "market_fear_level",
    "tnx_close",
    "tnx_lag1_return",
    "tnx_trend_5d",
)

_TEXT_COLUMNS = frozenset(
    {
        "snapshot_id",
        "ticker",
        "sector",
        "ras_signal",
        "analyst_consensus",
        "sector_regime",
        "market_fear_level",
    }
)
_DATE_COLUMNS = frozenset({"date"})
_REQUIRED_COLUMNS = frozenset({"snapshot_id", "ticker", "date", "close_price"})
_COLUMN_TYPES = tuple(
    "text" if column in _TEXT_COLUMNS else "date" if column in _DATE_COLUMNS else "real"
    for column in MARKET_DAILY_FEATURE_COLUMNS
)


def _json_line(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


_CONTENT_HEADER = _json_line(
    [MARKET_CONTENT_ENCODING, list(zip(MARKET_DAILY_FEATURE_COLUMNS, _COLUMN_TYPES))]
)
_TICKER_HEADER = _json_line([TICKER_UNIVERSE_ENCODING, ["ticker", "text"]])


def _encode_text(value: object, *, column: str, required: bool) -> list[object]:
    if value is None:
        if required:
            raise LineageError(f"Canonical market column {column} cannot be null.")
        return ["null"]
    if not isinstance(value, str):
        raise LineageError(f"Canonical market column {column} must be text or null.")
    if required and not value:
        raise LineageError(f"Canonical market column {column} cannot be blank.")
    return ["text", value]


def _encode_date(value: object, *, column: str, required: bool) -> list[object]:
    if value is None:
        if required:
            raise LineageError(f"Canonical market column {column} cannot be null.")
        return ["null"]
    if isinstance(value, datetime):
        raise LineageError(f"Canonical market column {column} must not contain a timestamp.")
    if isinstance(value, date):
        normalized = value.isoformat()
    elif isinstance(value, str):
        try:
            normalized = date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise LineageError(f"Canonical market column {column} is not an ISO date.") from exc
        if normalized != value:
            raise LineageError(f"Canonical market column {column} is not canonical YYYY-MM-DD.")
    else:
        raise LineageError(f"Canonical market column {column} must be an ISO date or null.")
    return ["date", normalized]


def _encode_real(value: object, *, column: str, required: bool) -> list[object]:
    if value is None:
        if required:
            raise LineageError(f"Canonical market column {column} cannot be null.")
        return ["null"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LineageError(f"Canonical market column {column} must be numeric or null.")
    number = float(value)
    if not math.isfinite(number):
        raise LineageError(f"Canonical market column {column} must be finite.")
    return ["real", number.hex()]


def canonical_market_daily_feature_row_bytes(row: Sequence[object]) -> bytes:
    """Encode one exact row in the fixed market feature column contract."""
    if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
        raise LineageError("Canonical market row must be a positional sequence.")
    if len(row) != len(MARKET_DAILY_FEATURE_COLUMNS):
        raise LineageError("Canonical market row width does not match the fixed column contract.")
    encoded: list[list[object]] = []
    for column, kind, value in zip(MARKET_DAILY_FEATURE_COLUMNS, _COLUMN_TYPES, row):
        required = column in _REQUIRED_COLUMNS
        if kind == "text":
            encoded.append(_encode_text(value, column=column, required=required))
        elif kind == "date":
            encoded.append(_encode_date(value, column=column, required=required))
        else:
            encoded.append(_encode_real(value, column=column, required=required))
    return _json_line(encoded)


@dataclass(frozen=True)
class MarketDatasetDigests:
    content_sha256: str
    ticker_universe_sha256: str
    row_count: int
    ticker_count: int
    snapshot_id: str
    first_session_date: date
    last_session_date: date
    content_encoding: str = MARKET_CONTENT_ENCODING
    ticker_universe_encoding: str = TICKER_UNIVERSE_ENCODING


class MarketDatasetStreamingDigester:
    """Incrementally hash canonical rows without retaining prior rows."""

    def __init__(self, columns: Sequence[str] = MARKET_DAILY_FEATURE_COLUMNS):
        if tuple(columns) != MARKET_DAILY_FEATURE_COLUMNS:
            raise LineageError("Market digest columns do not match the fixed canonical order.")
        self._content = hashlib.sha256(_CONTENT_HEADER)
        self._tickers = hashlib.sha256(_TICKER_HEADER)
        self._row_count = 0
        self._ticker_count = 0
        self._snapshot_id: str | None = None
        self._last_key: tuple[str, str] | None = None
        self._last_ticker: str | None = None
        self._first_session: date | None = None
        self._last_session: date | None = None
        self._finalized = False

    def update_rows(self, rows: Iterable[Sequence[object]]) -> int:
        """Hash a fetch chunk; ordering checks span every prior chunk."""
        if self._finalized:
            raise LineageError("Canonical market digester is already finalized.")
        added = 0
        for row in rows:
            encoded = canonical_market_daily_feature_row_bytes(row)
            snapshot = row[0]
            ticker = row[1]
            session_value = row[2]
            if not isinstance(snapshot, str) or not isinstance(ticker, str):
                raise LineageError("Canonical snapshot and ticker keys must be text.")
            if isinstance(session_value, datetime):
                raise LineageError("Canonical market session key must not be a timestamp.")
            if isinstance(session_value, date):
                session_text = session_value.isoformat()
            elif isinstance(session_value, str):
                session_text = session_value
            else:
                raise LineageError("Canonical market session key must be an ISO date.")
            if ticker != ticker.strip().upper():
                raise LineageError("Canonical market ticker must be normalized uppercase text.")
            session = date.fromisoformat(session_text)
            key = (ticker, session_text)
            if self._snapshot_id is None:
                self._snapshot_id = snapshot
            elif snapshot != self._snapshot_id:
                raise LineageError("Canonical market stream contains multiple snapshot IDs.")
            if self._last_key is not None and key <= self._last_key:
                raise LineageError("Canonical market rows are not strictly ordered by ticker,date.")
            if ticker != self._last_ticker:
                self._tickers.update(_json_line([["text", ticker]]))
                self._ticker_count += 1
                self._last_ticker = ticker
            self._content.update(encoded)
            self._row_count += 1
            added += 1
            self._last_key = key
            self._first_session = session if self._first_session is None else min(self._first_session, session)
            self._last_session = session if self._last_session is None else max(self._last_session, session)
        return added

    def finalize(self) -> MarketDatasetDigests:
        if self._finalized:
            raise LineageError("Canonical market digester is already finalized.")
        self._finalized = True
        if (
            self._row_count == 0
            or self._snapshot_id is None
            or self._first_session is None
            or self._last_session is None
        ):
            raise LineageError("Canonical market content cannot be empty.")
        return MarketDatasetDigests(
            content_sha256=self._content.hexdigest(),
            ticker_universe_sha256=self._tickers.hexdigest(),
            row_count=self._row_count,
            ticker_count=self._ticker_count,
            snapshot_id=self._snapshot_id,
            first_session_date=self._first_session,
            last_session_date=self._last_session,
        )


def digest_market_daily_feature_chunks(
    chunks: Iterable[Iterable[Sequence[object]]],
    *,
    columns: Sequence[str] = MARKET_DAILY_FEATURE_COLUMNS,
) -> MarketDatasetDigests:
    """Convenience wrapper for streamed database pages or other bounded chunks."""
    digester = MarketDatasetStreamingDigester(columns)
    for chunk in chunks:
        digester.update_rows(chunk)
    return digester.finalize()
