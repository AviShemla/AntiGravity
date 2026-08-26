"""Injected, read-only paginator for canonical Oracle research content digests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

from model_lineage import LineageError
from oracle_research_dataset_serializers import (
    MARKET_DAILY_FEATURE_COLUMNS,
    MarketDatasetDigests,
    MarketDatasetStreamingDigester,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COLUMNS_SQL = ",".join(MARKET_DAILY_FEATURE_COLUMNS)
FIRST_PAGE_SQL = (
    f"SELECT {_COLUMNS_SQL} FROM market_daily_features "
    "WHERE snapshot_id=? ORDER BY ticker,date LIMIT ?"
)
NEXT_PAGE_SQL = (
    f"SELECT {_COLUMNS_SQL} FROM market_daily_features "
    "WHERE snapshot_id=? AND (ticker>? OR (ticker=? AND date>?)) "
    "ORDER BY ticker,date LIMIT ?"
)


class InjectedReadOnlyClient(Protocol):
    def execute(self, sql: str, args: list[object]): ...


@dataclass(frozen=True)
class PinnedMarketSnapshot:
    snapshot_id: str
    source_checksum_sha256: str
    source_session_date: date
    expected_row_count: int
    expected_ticker_count: int


@dataclass(frozen=True)
class ResearchContentStreamEvidence:
    snapshot: PinnedMarketSnapshot
    digests: MarketDatasetDigests
    page_size: int
    nonempty_page_count: int
    query_count: int
    maximum_page_rows: int
    retained_row_count: int = 0


def _validate_pin(pin: PinnedMarketSnapshot) -> None:
    if not isinstance(pin.snapshot_id, str) or not pin.snapshot_id.strip():
        raise LineageError("Pinned market snapshot ID is required.")
    if not _SHA256.fullmatch(pin.source_checksum_sha256):
        raise LineageError("Pinned market snapshot checksum must be lowercase SHA-256.")
    if not isinstance(pin.source_session_date, date):
        raise LineageError("Pinned market source session must be a date.")
    for value, label in (
        (pin.expected_row_count, "row"),
        (pin.expected_ticker_count, "ticker"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise LineageError(f"Pinned market expected {label} count must be positive.")
    if pin.expected_ticker_count > pin.expected_row_count:
        raise LineageError("Pinned market ticker count cannot exceed row count.")


def _result_page(result: object, *, page_size: int) -> Sequence[Sequence[object]]:
    columns = getattr(result, "columns", None)
    rows = getattr(result, "rows", None)
    if not isinstance(columns, (list, tuple)) or tuple(columns) != MARKET_DAILY_FEATURE_COLUMNS:
        raise LineageError("Research content page returned a non-canonical column contract.")
    if not isinstance(rows, (list, tuple)):
        raise LineageError("Research content page rows must be a bounded sequence.")
    if len(rows) > page_size:
        raise LineageError("Research content page exceeded the requested bound.")
    return rows


def stream_pinned_market_content(
    client: InjectedReadOnlyClient,
    *,
    pin: PinnedMarketSnapshot,
    page_size: int = 4000,
) -> ResearchContentStreamEvidence:
    """Stream one pinned snapshot through the canonical digester.

    The client is injected and must expose only an ``execute`` method.  This
    module contains no endpoint, credential, environment, or connection logic.
    A terminal empty page is required even after an exactly full final page,
    preventing silent acceptance of rows beyond the pinned count.
    """
    _validate_pin(pin)
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 10_000:
        raise LineageError("Research content page size must be between 1 and 10000.")

    digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
    last_key: tuple[str, str] | None = None
    nonempty_pages = 0
    query_count = 0
    maximum_page_rows = 0
    observed_rows = 0

    while True:
        if last_key is None:
            sql = FIRST_PAGE_SQL
            args: list[object] = [pin.snapshot_id, page_size]
        else:
            sql = NEXT_PAGE_SQL
            args = [pin.snapshot_id, last_key[0], last_key[0], last_key[1], page_size]
        result = client.execute(sql, args)
        query_count += 1
        rows = _result_page(result, page_size=page_size)
        maximum_page_rows = max(maximum_page_rows, len(rows))
        if not rows:
            break
        nonempty_pages += 1
        if observed_rows + len(rows) > pin.expected_row_count:
            raise LineageError("Research content contains rows beyond the pinned row count.")

        first = rows[0]
        final = rows[-1]
        if len(first) != len(MARKET_DAILY_FEATURE_COLUMNS) or len(final) != len(
            MARKET_DAILY_FEATURE_COLUMNS
        ):
            raise LineageError("Research content page contains a malformed boundary row.")
        for row in rows:
            if len(row) != len(MARKET_DAILY_FEATURE_COLUMNS):
                raise LineageError("Research content page contains a malformed row.")
            if row[0] != pin.snapshot_id:
                raise LineageError("Research content row does not match the pinned snapshot ID.")
            if not isinstance(row[1], str) or not isinstance(row[2], str):
                raise LineageError("Research content cursor keys must be canonical text.")
        first_key = (first[1], first[2])
        next_key = (final[1], final[2])
        if last_key is not None and first_key <= last_key:
            raise LineageError("Research content page did not advance beyond its keyset cursor.")
        if next_key < first_key:
            raise LineageError("Research content page boundary is not ticker,date ordered.")

        digester.update_rows(rows)
        observed_rows += len(rows)
        if next_key == last_key:
            raise LineageError("Research content keyset cursor did not advance.")
        last_key = next_key

    if observed_rows != pin.expected_row_count:
        raise LineageError("Research content row count does not match the pinned snapshot.")
    digests = digester.finalize()
    if digests.snapshot_id != pin.snapshot_id:
        raise LineageError("Research content digest binds a different snapshot ID.")
    if digests.ticker_count != pin.expected_ticker_count:
        raise LineageError("Research content ticker count does not match the pinned snapshot.")
    if digests.last_session_date != pin.source_session_date:
        raise LineageError("Research content does not end at the pinned source session.")
    return ResearchContentStreamEvidence(
        snapshot=pin,
        digests=digests,
        page_size=page_size,
        nonempty_page_count=nonempty_pages,
        query_count=query_count,
        maximum_page_rows=maximum_page_rows,
    )
