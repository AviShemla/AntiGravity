import unittest
from datetime import date

from quarantine_policy import (
    QuarantinePolicyError,
    blocked_tickers,
    strike_counts_after_reset,
)


class QuarantinePolicyTests(unittest.TestCase):
    def test_pre_reset_losses_do_not_requarantine_symbol(self):
        rows = [
            ("2026-08-19", '{"AAA": -2.0}'),
            ("2026-08-20", '{"AAA": -3.0}'),
            ("2026-08-21", '{"AAA": 1.0}'),
        ]
        counts = strike_counts_after_reset(
            rows, effective_session_date=date(2026, 8, 21)
        )
        self.assertEqual(counts, {})
        self.assertEqual(blocked_tickers(counts), {})

    def test_post_reset_strikes_are_counted(self):
        rows = [
            ("2026-08-21", '{"AAA": -1, "BBB": 2}'),
            ("2026-08-24", '{"AAA": -1}'),
            ("2026-08-25", '{"AAA": -1, "BBB": -1}'),
        ]
        counts = strike_counts_after_reset(
            rows, effective_session_date=date(2026, 8, 21)
        )
        self.assertEqual(counts, {"AAA": 3, "BBB": 1})
        self.assertEqual(blocked_tickers(counts), {"AAA": 3})

    def test_duplicate_session_is_rejected(self):
        with self.assertRaisesRegex(QuarantinePolicyError, "Duplicate"):
            strike_counts_after_reset(
                [("2026-08-21", "{}"), ("2026-08-21", "{}")],
                effective_session_date=date(2026, 8, 21),
            )

    def test_invalid_pnl_is_rejected(self):
        with self.assertRaisesRegex(QuarantinePolicyError, "Invalid"):
            strike_counts_after_reset(
                [("2026-08-21", "not-json")],
                effective_session_date=date(2026, 8, 21),
            )


if __name__ == "__main__":
    unittest.main()
