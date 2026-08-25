import unittest
from datetime import date, datetime, timezone

from model_lineage import LineageError
from stock_scorecard_reader import load_stock_evidence_for_etf


class Result:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class FakeDB:
    def __init__(self, run_rows, score_rows, input_rows=None):
        self.run_rows = run_rows
        self.score_rows = score_rows
        self.input_rows = input_rows if input_rows is not None else [
            ["MARKET_FEATURES", "market-1", "m" * 64, "m" * 64,
             "2026-08-20", "2026-08-21T03:00:00+00:00", "VALIDATED"],
            ["STOCK_UNIVERSE", "universe-1", "u" * 64, "u" * 64,
             "2026-08-20", "2026-08-21T03:30:00+00:00", "VALIDATED"],
        ]
        self.calls = []

    def execute(self, query, args):
        self.calls.append((query, args))
        if "FROM model_runs" in query:
            return Result(
                ["run_id", "source_session_date", "completed_at_utc"],
                self.run_rows,
            )
        if "FROM model_scorecards" in query:
            return Result(
                [
                    "ticker", "posterior_probability", "posterior_probability_std",
                    "expected_return", "expected_return_std", "expected_risk",
                    "recommendation", "proposed_allocation", "quarantine_reason", "created_at_utc",
                ],
                self.score_rows,
            )
        if "FROM model_run_inputs" in query:
            return Result(
                ["input_role", "snapshot_id", "snapshot_checksum_sha256",
                 "source_checksum_sha256", "source_session_date", "available_at_utc", "status"],
                self.input_rows,
            )
        raise AssertionError("Unexpected query")


class StockScorecardReaderTests(unittest.TestCase):
    cutoff = datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)

    def valid_db(self):
        return FakeDB(
            [["stock_run_1", "2026-08-20", "2026-08-21T04:00:00+00:00"]],
            [
                ["AAPL", 0.65, 0.04, 1.2, 0.6, 2.4, "NO_TRADE", 0.0, "RESEARCH_ONLY;PROMOTION_DISABLED;ACTION_LANES_NO_TRADE;UNIT_CONTRACT=statistical-units-v1", "2026-08-21T04:01:00+00:00"],
                ["MSFT", 0.58, 0.05, 0.8, 0.5, 1.8, "NO_TRADE", 0.0, "RESEARCH_ONLY;PROMOTION_DISABLED;ACTION_LANES_NO_TRADE;UNIT_CONTRACT=statistical-units-v1", "2026-08-21T04:01:00+00:00"],
            ],
        )

    def test_reads_matching_real_persona_from_new_tables_only(self):
        db = self.valid_db()
        batch = load_stock_evidence_for_etf(
            db,
            etf_persona="ETF_Neutral",
            prediction_date=date(2026, 8, 21),
            etf_cutoff_utc=self.cutoff,
            expected_market_snapshot_id="market-1",
            constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
        )
        self.assertEqual(batch.stock_persona, "Neutral")
        self.assertEqual(batch.run_id, "stock_run_1")
        self.assertEqual(len(batch.evidence), 2)
        self.assertEqual(batch.available_at_utc, datetime(2026, 8, 21, 4, 0, tzinfo=timezone.utc))
        self.assertIn("MAX(score.created_at_utc)", db.calls[0][0])
        queries = " ".join(query for query, _ in db.calls)
        self.assertNotIn("etf_scorecards_master", queries)
        self.assertNotIn("csv", queries.lower())

    def test_empty_new_table_fails_closed(self):
        db = FakeDB([], [])
        with self.assertRaisesRegex(LineageError, "No completed stock model run"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Dynamic",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"NVDA": 0.4},
            )
        self.assertEqual(len(db.calls), 1)

    def test_missing_uncertainty_fails_closed(self):
        db = self.valid_db()
        db.score_rows[0][2] = None
        with self.assertRaisesRegex(LineageError, "uncertainty"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )

    def test_future_scorecard_fails_closed(self):
        db = self.valid_db()
        db.score_rows[0][9] = "2026-08-21T05:01:00+00:00"
        with self.assertRaisesRegex(LineageError, "after the ETF cutoff"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Conservative",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )

    def test_fictional_stock_persona_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "Unsupported ETF persona"):
            load_stock_evidence_for_etf(
                self.valid_db(),
                etf_persona="Stock",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35},
            )

    def test_missing_return_uncertainty_fails_closed(self):
        db = self.valid_db()
        db.score_rows[0][4] = None
        with self.assertRaisesRegex(LineageError, "expected-return uncertainty"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )

    def test_missing_model_input_lineage_fails_closed(self):
        db = self.valid_db()
        db.input_rows = []
        with self.assertRaisesRegex(LineageError, "lacks exact market/universe"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )

    def test_different_stock_market_snapshot_fails_closed(self):
        db = self.valid_db()
        with self.assertRaisesRegex(LineageError, "different market snapshots"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="other-market",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )


    def test_missing_requested_constituent_fails_closed(self):
        db = self.valid_db()
        db.score_rows = db.score_rows[:1]
        with self.assertRaisesRegex(LineageError, "ticker lineage is incomplete"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )

    def test_actionable_stock_scorecard_fails_closed(self):
        db = self.valid_db()
        db.score_rows[0][6] = "BUY"
        with self.assertRaisesRegex(LineageError, "is not NO_TRADE"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )

    def test_missing_research_unit_marker_fails_closed(self):
        db = self.valid_db()
        db.score_rows[0][8] = "RESEARCH_ONLY;PROMOTION_DISABLED"
        with self.assertRaisesRegex(LineageError, "policy marker is incomplete"):
            load_stock_evidence_for_etf(
                db,
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 21),
                etf_cutoff_utc=self.cutoff,
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            )


if __name__ == "__main__":
    unittest.main()
