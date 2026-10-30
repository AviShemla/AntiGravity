import unittest
from dataclasses import dataclass
from datetime import date

from model_lineage import LineageError
from oracle_research_dataset_content_reader import (
    FIRST_PAGE_SQL,
    NEXT_PAGE_SQL,
    PinnedMarketSnapshot,
    stream_pinned_market_content,
)
from oracle_research_dataset_serializers import MARKET_DAILY_FEATURE_COLUMNS


@dataclass(frozen=True)
class Result:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


def row(ticker, session, *, snapshot="snapshot-pinned", close=10.0):
    values = {column: None for column in MARKET_DAILY_FEATURE_COLUMNS}
    values.update(
        snapshot_id=snapshot,
        ticker=ticker,
        date=session,
        sector="Tech",
        open_price=close - 0.5,
        high_price=close + 1.0,
        low_price=close - 1.0,
        close_price=close,
        volume=1000.0,
    )
    return tuple(values[column] for column in MARKET_DAILY_FEATURE_COLUMNS)


ROWS = (
    row("AAA", "2026-08-24", close=10.0),
    row("AAA", "2026-08-25", close=10.5),
    row("BBB", "2026-08-23", close=20.0),
    row("BBB", "2026-08-25", close=21.0),
    row("CCC", "2026-08-25", close=30.0),
)
PIN = PinnedMarketSnapshot(
    snapshot_id="snapshot-pinned",
    source_checksum_sha256="a" * 64,
    source_session_date=date(2026, 8, 25),
    expected_row_count=len(ROWS),
    expected_ticker_count=3,
)


class KeysetClient:
    def __init__(self, rows=ROWS, *, columns=MARKET_DAILY_FEATURE_COLUMNS):
        self.source_rows = tuple(rows)
        self.columns = tuple(columns)
        self.calls = []
        self.maximum_returned = 0

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        snapshot = args[0]
        page_size = args[-1]
        candidates = [item for item in self.source_rows if item[0] == snapshot]
        if sql == FIRST_PAGE_SQL:
            self.assert_first_args(args)
        elif sql == NEXT_PAGE_SQL:
            ticker, repeated_ticker, session = args[1:4]
            if ticker != repeated_ticker:
                raise AssertionError("cursor ticker was not repeated exactly")
            candidates = [item for item in candidates if (item[1], item[2]) > (ticker, session)]
        else:
            raise AssertionError("unexpected SQL")
        page = tuple(candidates[:page_size])
        self.maximum_returned = max(self.maximum_returned, len(page))
        return Result(self.columns, page)

    @staticmethod
    def assert_first_args(args):
        if len(args) != 2:
            raise AssertionError("first page had cursor arguments")


class ResearchContentReaderTests(unittest.TestCase):
    def test_streams_exact_rows_with_keyset_cursor_and_no_row_retention(self):
        client = KeysetClient()
        evidence = stream_pinned_market_content(client, pin=PIN, page_size=2)
        self.assertEqual(evidence.digests.row_count, 5)
        self.assertEqual(evidence.digests.ticker_count, 3)
        self.assertEqual(evidence.nonempty_page_count, 3)
        self.assertEqual(evidence.query_count, 4)
        self.assertEqual(evidence.maximum_page_rows, 2)
        self.assertEqual(evidence.retained_row_count, 0)
        self.assertFalse(hasattr(evidence, "rows"))
        self.assertEqual(client.maximum_returned, 2)
        self.assertEqual(client.calls[0], (FIRST_PAGE_SQL, ["snapshot-pinned", 2]))
        self.assertEqual(
            client.calls[1],
            (NEXT_PAGE_SQL, ["snapshot-pinned", "AAA", "AAA", "2026-08-25", 2]),
        )

    def test_digests_are_independent_of_fetch_page_boundaries(self):
        results = [
            stream_pinned_market_content(KeysetClient(), pin=PIN, page_size=size).digests
            for size in (1, 2, 3, 5, 10)
        ]
        self.assertTrue(all(result == results[0] for result in results[1:]))

    def test_cross_page_out_of_order_and_duplicate_cursor_fail_closed(self):
        class DuplicateClient(KeysetClient):
            def execute(self, sql, args):
                result = super().execute(sql, args)
                if sql == NEXT_PAGE_SQL and result.rows:
                    cursor_row = next(
                        item for item in self.source_rows if (item[1], item[2]) == (args[1], args[3])
                    )
                    return Result(result.columns, (cursor_row,) + result.rows[1:])
                return result

        with self.assertRaisesRegex(LineageError, "did not advance"):
            stream_pinned_market_content(DuplicateClient(), pin=PIN, page_size=2)

        class ReverseBoundaryClient(KeysetClient):
            def execute(self, sql, args):
                result = super().execute(sql, args)
                if sql == NEXT_PAGE_SQL and len(result.rows) > 1:
                    return Result(result.columns, tuple(reversed(result.rows)))
                return result

        with self.assertRaises(LineageError):
            stream_pinned_market_content(ReverseBoundaryClient(), pin=PIN, page_size=2)

    def test_missing_cursor_page_is_detected_by_pinned_count(self):
        class SkippingClient(KeysetClient):
            def execute(self, sql, args):
                result = super().execute(sql, args)
                if sql == NEXT_PAGE_SQL and result.rows:
                    return Result(result.columns, result.rows[1:])
                return result

        with self.assertRaisesRegex(LineageError, "row count"):
            stream_pinned_market_content(SkippingClient(), pin=PIN, page_size=2)

        class EarlyEmptyClient(KeysetClient):
            def execute(self, sql, args):
                if sql == NEXT_PAGE_SQL:
                    self.calls.append((sql, list(args)))
                    return Result(self.columns, ())
                return super().execute(sql, args)

        with self.assertRaisesRegex(LineageError, "row count"):
            stream_pinned_market_content(EarlyEmptyClient(), pin=PIN, page_size=2)

    def test_snapshot_and_column_mismatch_fail_closed(self):
        mismatched = list(ROWS)
        mismatched[2] = row("BBB", "2026-08-23", snapshot="other-snapshot")
        client = KeysetClient(mismatched)
        client.source_rows = tuple(mismatched)

        class LeakyClient(KeysetClient):
            def execute(self, sql, args):
                result = super().execute(sql, args)
                if sql == NEXT_PAGE_SQL and result.rows:
                    changed = list(result.rows[0])
                    changed[0] = "other-snapshot"
                    return Result(result.columns, (tuple(changed),) + result.rows[1:])
                return result

        with self.assertRaisesRegex(LineageError, "pinned snapshot ID"):
            stream_pinned_market_content(LeakyClient(), pin=PIN, page_size=2)
        with self.assertRaisesRegex(LineageError, "column contract"):
            stream_pinned_market_content(
                KeysetClient(columns=tuple(reversed(MARKET_DAILY_FEATURE_COLUMNS))),
                pin=PIN,
                page_size=2,
            )

    def test_extra_rows_ticker_count_and_source_session_fail_closed(self):
        extra = ROWS + (row("DDD", "2026-08-25"),)
        with self.assertRaisesRegex(LineageError, "beyond the pinned row count"):
            stream_pinned_market_content(KeysetClient(extra), pin=PIN, page_size=3)
        wrong_tickers = PinnedMarketSnapshot(
            **{**PIN.__dict__, "expected_ticker_count": 4}
        )
        with self.assertRaisesRegex(LineageError, "ticker count"):
            stream_pinned_market_content(KeysetClient(), pin=wrong_tickers, page_size=2)
        wrong_date = PinnedMarketSnapshot(
            **{**PIN.__dict__, "source_session_date": date(2026, 8, 26)}
        )
        with self.assertRaisesRegex(LineageError, "source session"):
            stream_pinned_market_content(KeysetClient(), pin=wrong_date, page_size=2)

    def test_page_bound_and_malformed_rows_fail_closed(self):
        class OversizedClient(KeysetClient):
            def execute(self, sql, args):
                return Result(self.columns, ROWS[:3])

        with self.assertRaisesRegex(LineageError, "exceeded"):
            stream_pinned_market_content(OversizedClient(), pin=PIN, page_size=2)

        class MalformedClient(KeysetClient):
            def execute(self, sql, args):
                return Result(self.columns, (ROWS[0][:-1],))

        with self.assertRaisesRegex(LineageError, "malformed boundary"):
            stream_pinned_market_content(MalformedClient(), pin=PIN, page_size=2)

    def test_invalid_pin_and_page_size_make_no_client_call(self):
        invalid_pins = (
            PinnedMarketSnapshot("", "a" * 64, date(2026, 8, 25), 5, 3),
            PinnedMarketSnapshot("snapshot", "bad", date(2026, 8, 25), 5, 3),
            PinnedMarketSnapshot("snapshot", "a" * 64, date(2026, 8, 25), 0, 3),
            PinnedMarketSnapshot("snapshot", "a" * 64, date(2026, 8, 25), 2, 3),
        )
        for pin in invalid_pins:
            with self.subTest(pin=pin):
                client = KeysetClient()
                with self.assertRaises(LineageError):
                    stream_pinned_market_content(client, pin=pin, page_size=2)
                self.assertEqual(client.calls, [])
        for size in (0, 10_001, True):
            client = KeysetClient()
            with self.subTest(size=size), self.assertRaises(LineageError):
                stream_pinned_market_content(client, pin=PIN, page_size=size)
            self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
