import unittest
from dataclasses import replace
from datetime import date, datetime, timezone

import numpy as np

from model_input_reader import InputSnapshot
from model_lineage import LineageError
from stock_model_input_reader import load_stock_model_market_frame


SOURCE_COLUMNS = (
    "ticker", "date", "close_price", "volume", "daily_return_pct",
    "rsi_14d", "adx_14d", "plus_di_14d", "minus_di_14d", "atr_14d",
    "sector_momentum_score", "vix_close", "tnx_trend_5d",
)
EXPECTED_COLUMNS = [
    "Ticker", "Date", "Close", "Volume", "Daily_Return_%", "RSI_14d",
    "ADX_14d", "Plus_DI_14d", "Minus_DI_14d", "ATR_14d",
    "Sector_Momentum_Score", "VIX_Close", "TNX_Trend_5d",
]


class Result:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = rows


class FakeDB:
    def __init__(self, rows, *, count_rows=None, count_tickers=None):
        self.rows = rows
        self.count_rows = len(rows) if count_rows is None else count_rows
        self.count_tickers = (
            len({row[0] for row in rows}) if count_tickers is None else count_tickers
        )
        self.queries = []
        self.page_queries = []
        self.count_calls = 0

    def execute(self, query, args):
        compact = " ".join(query.split())
        self.queries.append((compact, list(args)))
        if compact.startswith("SELECT COUNT(*) AS row_count"):
            self.count_calls += 1
            return Result(
                ["row_count", "ticker_count"],
                [[self.count_rows, self.count_tickers]],
            )
        if "FROM market_daily_features" in compact:
            self.page_queries.append((compact, list(args)))
            snapshot_id, last_ticker, _, last_date, page_size = args
            if snapshot_id != "market-1":
                return Result(SOURCE_COLUMNS, [])
            eligible = [
                row for row in sorted(self.rows, key=lambda item: (item[0], item[1]))
                if (row[0], row[1]) > (last_ticker, last_date)
            ]
            return Result(SOURCE_COLUMNS, eligible[:page_size])
        raise AssertionError(f"Unexpected query: {compact}")


def market_row(ticker, session, *, daily_return=0.5):
    return [
        ticker, session, 101.0, 1000.0, daily_return, 55.0, 24.0,
        18.0, 12.0, 2.0, 0.75, 17.0, 0.15,
    ]


def snapshot(*, rows=4, tickers=2, source=date(2026, 8, 20), checksum="a" * 64):
    return InputSnapshot(
        snapshot_id="market-1",
        dataset_type="MARKET_FEATURES",
        source_session_date=source,
        available_at_utc=datetime(2026, 8, 21, 4, 0, tzinfo=timezone.utc),
        provider="CANONICAL_EOD",
        code_version="reader-test",
        expected_row_count=rows,
        expected_ticker_count=tickers,
        source_checksum_sha256=checksum,
    )


class StockModelInputReaderTests(unittest.TestCase):
    def good_rows(self):
        return [
            market_row("BBB", "2026-08-20"),
            market_row("AAA", "2026-08-19"),
            market_row("BBB", "2026-08-19"),
            market_row("AAA", "2026-08-20"),
        ]

    def test_keyset_pages_exact_snapshot_and_returns_model_contract(self):
        db = FakeDB(self.good_rows())
        frame = load_stock_model_market_frame(
            db, snapshot(), required_tickers=["BBB", "aaa"], page_size=2
        )
        self.assertEqual(frame.columns.tolist(), EXPECTED_COLUMNS)
        self.assertEqual(
            list(zip(frame["Ticker"], frame["Date"].dt.strftime("%Y-%m-%d"))),
            [
                ("AAA", "2026-08-19"), ("AAA", "2026-08-20"),
                ("BBB", "2026-08-19"), ("BBB", "2026-08-20"),
            ],
        )
        self.assertEqual(db.count_calls, 2)
        self.assertGreaterEqual(len(db.page_queries), 2)
        for query, args in db.page_queries:
            self.assertIn("snapshot_id = ?", query)
            self.assertIn("ticker > ?", query)
            self.assertIn("date > ?", query)
            self.assertNotIn("OFFSET", query.upper())
            self.assertEqual(args[0], "market-1")
            self.assertLessEqual(args[-1], 1000)

    def test_wrong_snapshot_type_fails_closed(self):
        wrong = replace(snapshot(), dataset_type="STOCK_UNIVERSE")
        with self.assertRaisesRegex(LineageError, "MARKET_FEATURES"):
            load_stock_model_market_frame(
                FakeDB(self.good_rows()), wrong, required_tickers=["AAA"]
            )

    def test_missing_or_malformed_checksum_fails_closed(self):
        for checksum in (None, "A" * 64, "a" * 63):
            with self.subTest(checksum=checksum):
                with self.assertRaisesRegex(LineageError, "lowercase SHA-256"):
                    load_stock_model_market_frame(
                        FakeDB(self.good_rows()), snapshot(checksum=checksum),
                        required_tickers=["AAA"],
                    )

    def test_expected_row_count_mismatch_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "row count"):
            load_stock_model_market_frame(
                FakeDB(self.good_rows()), snapshot(rows=5), required_tickers=["AAA"]
            )

    def test_loaded_ticker_count_is_reconciled_even_if_aggregate_lies(self):
        rows = [market_row("AAA", "2026-08-19"), market_row("AAA", "2026-08-20")]
        db = FakeDB(rows, count_rows=2, count_tickers=2)
        with self.assertRaisesRegex(LineageError, "Loaded market tickers"):
            load_stock_model_market_frame(
                db, snapshot(rows=2, tickers=2), required_tickers=["AAA"]
            )

    def test_duplicate_ticker_date_key_fails_closed(self):
        rows = self.good_rows()
        rows[-1] = market_row("AAA", "2026-08-19")
        db = FakeDB(rows, count_rows=4, count_tickers=2)
        with self.assertRaisesRegex(LineageError, "duplicate ticker/session"):
            load_stock_model_market_frame(
                db, snapshot(), required_tickers=["AAA", "BBB"], page_size=10
            )

    def test_snapshot_max_must_equal_declared_source_session(self):
        stale = [
            market_row("AAA", "2026-08-18"), market_row("AAA", "2026-08-19"),
            market_row("BBB", "2026-08-18"), market_row("BBB", "2026-08-19"),
        ]
        with self.assertRaisesRegex(LineageError, "maximum session"):
            load_stock_model_market_frame(
                FakeDB(stale), snapshot(), required_tickers=["AAA", "BBB"]
            )

    def test_required_ticker_must_be_present(self):
        with self.assertRaisesRegex(LineageError, "lacks required tickers: CCC"):
            load_stock_model_market_frame(
                FakeDB(self.good_rows()), snapshot(),
                required_tickers=["AAA", "CCC"],
            )

    def test_non_finite_required_value_fails_closed(self):
        rows = self.good_rows()
        rows[0][4] = np.inf
        with self.assertRaisesRegex(LineageError, "non-finite required fields"):
            load_stock_model_market_frame(
                FakeDB(rows), snapshot(), required_tickers=["AAA", "BBB"]
            )

    def test_page_size_is_strictly_bounded(self):
        for size in (0, 1001, True):
            with self.subTest(size=size):
                with self.assertRaisesRegex(LineageError, "page size"):
                    load_stock_model_market_frame(
                        FakeDB(self.good_rows()), snapshot(),
                        required_tickers=["AAA"], page_size=size,
                    )


if __name__ == "__main__":
    unittest.main()
