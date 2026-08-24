import unittest

from model_lineage import LineageError
from stock_lag_governance import (
    HORIZON_REVIEW_INTERVAL_SESSIONS,
    INITIAL_MAX_LAG_SESSIONS,
    INITIAL_STOCK_LAG_GOVERNANCE,
)


class StockLagGovernanceTests(unittest.TestCase):
    def test_current_contract_records_owner_approved_limits(self):
        self.assertEqual(INITIAL_MAX_LAG_SESSIONS, 7)
        self.assertEqual(HORIZON_REVIEW_INTERVAL_SESSIONS, 63)
        self.assertEqual(INITIAL_STOCK_LAG_GOVERNANCE.minimum_chain_depth, 1)
        self.assertEqual(INITIAL_STOCK_LAG_GOVERNANCE.maximum_chain_depth, 5)

    def test_nonconsecutive_lags_within_horizon_are_valid(self):
        INITIAL_STOCK_LAG_GOVERNANCE.validate_search(
            minimum_depth=1,
            maximum_depth=5,
            candidate_lags=(2, 5, 7),
            purge_sessions=7,
        )

    def test_lag_above_current_horizon_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "approved maximum horizon"):
            INITIAL_STOCK_LAG_GOVERNANCE.validate_search(
                minimum_depth=1,
                maximum_depth=5,
                candidate_lags=(1, 8),
                purge_sessions=8,
            )

    def test_review_is_due_only_after_63_new_completed_sessions(self):
        self.assertFalse(INITIAL_STOCK_LAG_GOVERNANCE.horizon_review_due(62))
        self.assertTrue(INITIAL_STOCK_LAG_GOVERNANCE.horizon_review_due(63))

    def test_negative_review_age_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "cannot be negative"):
            INITIAL_STOCK_LAG_GOVERNANCE.horizon_review_due(-1)


if __name__ == "__main__":
    unittest.main()
