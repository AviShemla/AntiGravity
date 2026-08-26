import unittest
from datetime import date, datetime

from model_lineage import LineageError
from oracle_research_dataset_serializers import (
    MARKET_DAILY_FEATURE_COLUMNS,
    MarketDatasetStreamingDigester,
    canonical_market_daily_feature_row_bytes,
    digest_market_daily_feature_chunks,
)


def row(ticker, session, *, close=10.5, snapshot="snapshot-1", sector="Tech"):
    values = {column: None for column in MARKET_DAILY_FEATURE_COLUMNS}
    values.update(
        snapshot_id=snapshot,
        ticker=ticker,
        date=session,
        sector=sector,
        open_price=10.0,
        high_price=11.0,
        low_price=9.0,
        close_price=close,
        adjusted_close=10.25,
        volume=1000,
        dividends=0,
        stock_splits=0.0,
        ras_signal="BUY",
        sector_regime="RISK_ON",
    )
    return tuple(values[column] for column in MARKET_DAILY_FEATURE_COLUMNS)


ROWS = (
    row("AAA", "2026-08-24"),
    row("AAA", "2026-08-25", close=10.75),
    row("BBB", "2026-08-24", close=20.0, sector=None),
)


class CanonicalMarketSerializerTests(unittest.TestCase):
    def test_golden_vector(self):
        result = digest_market_daily_feature_chunks([ROWS])
        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.ticker_count, 2)
        self.assertEqual(result.snapshot_id, "snapshot-1")
        self.assertEqual(result.first_session_date.isoformat(), "2026-08-24")
        self.assertEqual(result.last_session_date.isoformat(), "2026-08-25")
        self.assertEqual(
            result.content_sha256,
            "67f4e3054516527095560f1f27f4091a95d827131446caee8e31cb9b84e62d6a",
        )
        self.assertEqual(
            result.ticker_universe_sha256,
            "d7724a18957fadbe083eae17dd245da7c3caa536dd96e55400ea83be0d8cd0af",
        )

    def test_digest_is_independent_of_chunk_boundaries(self):
        together = digest_market_daily_feature_chunks([ROWS])
        split = digest_market_daily_feature_chunks([[ROWS[0]], [], ROWS[1:]])
        one_at_a_time = digest_market_daily_feature_chunks(([item] for item in ROWS))
        self.assertEqual(together, split)
        self.assertEqual(together, one_at_a_time)

    def test_content_tamper_changes_content_but_not_ticker_universe(self):
        original = digest_market_daily_feature_chunks([ROWS])
        tampered = digest_market_daily_feature_chunks(
            [[ROWS[0], row("AAA", "2026-08-25", close=10.750000000000002), ROWS[2]]]
        )
        self.assertNotEqual(original.content_sha256, tampered.content_sha256)
        self.assertEqual(original.ticker_universe_sha256, tampered.ticker_universe_sha256)

    def test_ticker_tamper_changes_both_digests(self):
        original = digest_market_daily_feature_chunks([ROWS])
        changed = digest_market_daily_feature_chunks(
            [[row("AAC", "2026-08-24"), row("AAC", "2026-08-25", close=10.75), ROWS[2]]]
        )
        self.assertNotEqual(original.content_sha256, changed.content_sha256)
        self.assertNotEqual(original.ticker_universe_sha256, changed.ticker_universe_sha256)

    def test_null_text_and_real_are_unambiguously_typed(self):
        null_sector = canonical_market_daily_feature_row_bytes(row("AAA", "2026-08-24", sector=None))
        text_null = canonical_market_daily_feature_row_bytes(row("AAA", "2026-08-24", sector="null"))
        self.assertNotEqual(null_sector, text_null)
        int_real = canonical_market_daily_feature_row_bytes(row("AAA", "2026-08-24", close=10))
        float_real = canonical_market_daily_feature_row_bytes(row("AAA", "2026-08-24", close=10.0))
        self.assertEqual(int_real, float_real)
        self.assertIn(b'"real","0x1.4000000000000p+3"', int_real)

    def test_nonfinite_and_null_required_real_fail_closed(self):
        for value in (float("nan"), float("inf"), float("-inf"), None):
            with self.subTest(value=value), self.assertRaises(LineageError):
                canonical_market_daily_feature_row_bytes(row("AAA", "2026-08-24", close=value))

    def test_order_duplicates_snapshot_and_ticker_normalization_fail_closed(self):
        invalid_streams = (
            [ROWS[1], ROWS[0]],
            [ROWS[0], ROWS[0]],
            [ROWS[0], row("AAA", "2026-08-25", snapshot="snapshot-2")],
            [row("aaa", "2026-08-24")],
        )
        for invalid in invalid_streams:
            with self.subTest(invalid=invalid), self.assertRaises(LineageError):
                digest_market_daily_feature_chunks([invalid])

    def test_column_order_row_width_date_and_empty_stream_fail_closed(self):
        with self.assertRaisesRegex(LineageError, "fixed canonical order"):
            MarketDatasetStreamingDigester(tuple(reversed(MARKET_DAILY_FEATURE_COLUMNS)))
        with self.assertRaisesRegex(LineageError, "row width"):
            canonical_market_daily_feature_row_bytes(ROWS[0][:-1])
        invalid_date = list(ROWS[0])
        invalid_date[2] = "2026-8-24"
        with self.assertRaises(LineageError):
            canonical_market_daily_feature_row_bytes(invalid_date)
        date_row = list(ROWS[0])
        date_row[2] = date(2026, 8, 24)
        self.assertEqual(
            digest_market_daily_feature_chunks([[date_row]]).first_session_date,
            date(2026, 8, 24),
        )
        date_row[2] = datetime(2026, 8, 24)
        with self.assertRaisesRegex(LineageError, "timestamp"):
            canonical_market_daily_feature_row_bytes(date_row)
        with self.assertRaisesRegex(LineageError, "cannot be empty"):
            digest_market_daily_feature_chunks([[]])

    def test_finalize_and_update_are_single_use(self):
        digester = MarketDatasetStreamingDigester()
        digester.update_rows(ROWS)
        digester.finalize()
        with self.assertRaisesRegex(LineageError, "already finalized"):
            digester.finalize()
        with self.assertRaisesRegex(LineageError, "already finalized"):
            digester.update_rows([])


if __name__ == "__main__":
    unittest.main()
