from datetime import date
import unittest

import pandas as pd

from canonical_market_history import CanonicalReconciliation
from feature_recompute_plan import plan_feature_recomputation
from model_lineage import LineageError


def reconciliation(*, appended=(), revised=(), unchanged=()):
    return CanonicalReconciliation(
        history=pd.DataFrame(),
        appended_keys=tuple(appended),
        revised_keys=tuple(revised),
        unchanged_keys=tuple(unchanged),
    )


class FeatureRecomputePlanTests(unittest.TestCase):
    def test_latest_append_recomputes_only_latest_output_session(self):
        result = plan_feature_recomputation(
            reconciliation(appended=(("AAA", "2026-08-24"),)),
            available_sessions=("2026-08-21", "2026-08-24"),
        )
        self.assertTrue(result.has_changes)
        self.assertEqual(result.cross_market_write_sessions, (date(2026, 8, 24),))
        self.assertEqual(result.ticker_plans[0].write_sessions, (date(2026, 8, 24),))
        self.assertTrue(result.ticker_plans[0].requires_full_input_history)

    def test_revision_rewrites_only_changed_and_later_sessions(self):
        result = plan_feature_recomputation(
            reconciliation(revised=(("AAA", "2026-08-20"),)),
            available_sessions=("2026-08-19", "2026-08-20", "2026-08-21"),
        )
        expected = (date(2026, 8, 20), date(2026, 8, 21))
        self.assertEqual(result.ticker_plans[0].write_sessions, expected)
        self.assertEqual(result.cross_market_write_sessions, expected)

    def test_multiple_tickers_preserve_independent_first_change(self):
        result = plan_feature_recomputation(
            reconciliation(
                appended=(("BBB", "2026-08-21"),),
                revised=(("AAA", "2026-08-20"),),
            ),
            available_sessions=("2026-08-19", "2026-08-20", "2026-08-21"),
        )
        self.assertEqual([plan.ticker for plan in result.ticker_plans], ["AAA", "BBB"])
        self.assertEqual(
            result.ticker_plans[1].write_sessions, (date(2026, 8, 21),)
        )
        self.assertEqual(
            result.cross_market_write_sessions,
            (date(2026, 8, 20), date(2026, 8, 21)),
        )

    def test_no_change_is_noop(self):
        result = plan_feature_recomputation(
            reconciliation(unchanged=(("AAA", "2026-08-21"),)),
            available_sessions=("2026-08-21",),
        )
        self.assertFalse(result.has_changes)
        self.assertEqual(result.ticker_plans, ())
        self.assertEqual(result.unchanged_keys, (("AAA", "2026-08-21"),))

    def test_changed_date_missing_from_calendar_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "absent from the calendar"):
            plan_feature_recomputation(
                reconciliation(revised=(("AAA", "2026-08-20"),)),
                available_sessions=("2026-08-21",),
            )


if __name__ == "__main__":
    unittest.main()
