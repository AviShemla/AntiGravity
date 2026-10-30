"""Canonical, streaming content identity for guarded market STAGING rows.

The digest excludes ``snapshot_id`` so it can deterministically define that
identifier.  It hashes the exact persisted column order after the writer's
``clean`` conversion, allowing an ordered database readback to reproduce the
same bytes independently.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence


ENCODING = "codex-market-staging-content-jsonl-v1"
STAGING_COLUMNS = (
    "ticker", "date", "sector", "open_price", "high_price", "low_price",
    "close_price", "adjusted_close", "volume", "dividends", "stock_splits",
    "daily_return_pct", "daily_stdev", "stdev_5d", "stdev_10d", "stdev_20d",
    "max_high_20d", "min_low_20d", "rsi_14d", "atr_14d", "plus_di_14d",
    "minus_di_14d", "adx_14d", "dynamic_stop_loss", "ras_signal",
    "analyst_consensus", "analyst_upside_pct", "sector_momentum_score",
    "sector_regime", "vix_close", "market_fear_level", "tnx_close",
    "tnx_lag1_return", "tnx_trend_5d",
)
TEXT_COLUMNS = frozenset({
    "ticker", "sector", "ras_signal", "analyst_consensus", "sector_regime",
    "market_fear_level",
})
DATE_COLUMNS = frozenset({"date"})
COLUMN_TYPES = tuple(
    "text" if name in TEXT_COLUMNS else "date" if name in DATE_COLUMNS else "real"
    for name in STAGING_COLUMNS
)


class StagingContentError(ValueError):
    pass


@dataclass(frozen=True)
class StagingContentAudit:
    content_sha256: str
    row_count: int
    ticker_count: int
    session_count: int
    first_date: str
    last_date: str
    ticker_sha256: str
    calendar_sha256: str


def _line(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


HEADER = _line([ENCODING, list(zip(STAGING_COLUMNS, COLUMN_TYPES))])


def _encode(value: object, kind: str, column: str) -> list[object]:
    if value is None:
        if column in {"ticker", "date"}:
            raise StagingContentError(f"{column} cannot be null")
        return ["null"]
    if kind == "text":
        if not isinstance(value, str):
            raise StagingContentError(f"{column} must be text or null")
        if column == "ticker" and (not value or value != value.strip().upper()):
            raise StagingContentError("ticker must be nonblank normalized uppercase text")
        return ["text", value]
    if kind == "date":
        if isinstance(value, datetime):
            normalized = value.date().isoformat()
        elif isinstance(value, date):
            normalized = value.isoformat()
        elif isinstance(value, str):
            try:
                normalized = date.fromisoformat(value).isoformat()
            except ValueError as exc:
                raise StagingContentError("date must be canonical YYYY-MM-DD") from exc
            if normalized != value:
                raise StagingContentError("date must be canonical YYYY-MM-DD")
        else:
            raise StagingContentError("date has unsupported type")
        return ["date", normalized]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StagingContentError(f"{column} must be numeric or null")
    number = float(value)
    if not math.isfinite(number):
        raise StagingContentError(f"{column} must be finite")
    # SQLite/libSQL REAL storage discards the sign bit of negative zero.
    # Canonicalize both the writer-side and readback-side representation to
    # the value that the database can reproduce independently.
    if number == 0.0:
        number = 0.0
    return ["real", number.hex()]


def canonical_row_bytes(row: Sequence[object]) -> bytes:
    if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
        raise StagingContentError("row must be a positional sequence")
    if len(row) != len(STAGING_COLUMNS):
        raise StagingContentError("row width differs from staging contract")
    return _line([_encode(value, kind, column) for column, kind, value in zip(STAGING_COLUMNS, COLUMN_TYPES, row)])


class StagingContentDigester:
    def __init__(self) -> None:
        self._digest = hashlib.sha256(HEADER)
        self._last_key: tuple[str, str] | None = None
        self.row_count = 0
        self.tickers: set[str] = set()
        self.dates: set[str] = set()

    def update(self, rows: Iterable[Sequence[object]]) -> int:
        added = 0
        for row in rows:
            encoded = canonical_row_bytes(row)
            ticker = str(row[0])
            raw_date = row[1]
            session = raw_date.date().isoformat() if isinstance(raw_date, datetime) else raw_date.isoformat() if isinstance(raw_date, date) else str(raw_date)
            key = (ticker, session)
            if self._last_key is not None and key <= self._last_key:
                raise StagingContentError("rows are not strictly ordered by ticker,date")
            self._digest.update(encoded)
            self._last_key = key
            self.row_count += 1
            self.tickers.add(ticker)
            self.dates.add(session)
            added += 1
        return added

    def hexdigest(self) -> str:
        if self.row_count == 0:
            raise StagingContentError("content cannot be empty")
        return self._digest.hexdigest()

    def finalize(self) -> StagingContentAudit:
        content_sha256 = self.hexdigest()
        tickers = tuple(sorted(self.tickers))
        dates = tuple(sorted(self.dates))
        return StagingContentAudit(
            content_sha256=content_sha256,
            row_count=self.row_count,
            ticker_count=len(tickers),
            session_count=len(dates),
            first_date=dates[0],
            last_date=dates[-1],
            ticker_sha256=hashlib.sha256(_line([ENCODING, "tickers", list(tickers)])).hexdigest(),
            calendar_sha256=hashlib.sha256(_line([ENCODING, "calendar", list(dates)])).hexdigest(),
        )


def digest_rows(rows: Iterable[Sequence[object]]) -> str:
    digester = StagingContentDigester()
    digester.update(rows)
    return digester.hexdigest()
