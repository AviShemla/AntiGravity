import unittest

from dashboard_data_contract import approved_pending_row, normalize_benchmark, resolve_model_alias_collisions


class DashboardBenchmarkTests(unittest.TestCase):
    def test_missing_benchmark_is_null_not_flat(self):
        result = normalize_benchmark(["2026-08-20", "2026-08-21"], [])
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertEqual(result.values, (None, None))

    def test_no_future_backfill(self):
        result = normalize_benchmark(
            ["2026-08-19", "2026-08-20", "2026-08-21"],
            [{"date": "2026-08-20", "close_price": 100}, {"date": "2026-08-21", "close_price": 110}],
        )
        self.assertEqual(result.values, (None, 10000.0, 11000.0))

    def test_forward_fill_after_first_evidence(self):
        result = normalize_benchmark(
            ["2026-08-20", "2026-08-21", "2026-08-22"],
            [{"date": "2026-08-20", "close_price": 100}, {"date": "2026-08-22", "close_price": 105}],
        )
        self.assertEqual(result.values, (10000.0, 10000.0, 10500.0))


class DashboardPendingTests(unittest.TestCase):
    def setUp(self):
        self.pending = {
            "persona": "Neutral",
            "date": "2026-08-24",
            "target_cash": 10000.0,
            "target_total_equity": 10000.0,
            "target_holdings_json": "{}",
            "daily_pnl_json": "{}",
            "executed_intraday_trades_json": "{}",
        }

    def test_legacy_pending_fails_closed_without_plan(self):
        row, status = approved_pending_row(self.pending, None)
        self.assertIsNone(row)
        self.assertEqual(status, "EXECUTION_LINEAGE_UNAVAILABLE")

    def test_hash_mismatch_fails_closed(self):
        plan = {
            "persona": "Neutral",
            "target_date": "2026-08-24",
            "qa_status": "VALIDATED",
            "approval_decision": "APPROVED",
            "consumed_plan_id": None,
            "pending_payload_sha256": "wrong",
        }
        row, status = approved_pending_row(self.pending, plan)
        self.assertIsNone(row)
        self.assertEqual(status, "PLAN_PAYLOAD_HASH_MISMATCH")


class DashboardArenaTests(unittest.TestCase):
    def test_canonical_prod_wins_over_legacy_alias(self):
        rows, collisions = resolve_model_alias_collisions(
            [
                {"date": "2026-08-11", "model_name": "Prod", "total_equity": 9700},
                {"date": "2026-08-11", "model_name": "PROD_Bayesian_SV", "total_equity": 9400},
            ],
            {"Prod": "Prod", "PROD_Bayesian_SV": "Prod"},
            {"PROD_Bayesian_SV": 0, "Prod": 1},
        )
        self.assertEqual(rows[0]["total_equity"], 9400)
        self.assertEqual(len(collisions), 1)


if __name__ == "__main__":
    unittest.main()
