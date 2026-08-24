import unittest
from dataclasses import replace
from datetime import date, datetime, timezone

from model_lineage import LineageError
from stock_model_preflight import build_stock_model_preflight


class Result:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class FakeDB:
    source = "2026-08-20"

    def __init__(
        self,
        *,
        universe_exists=True,
        approval_decision="APPROVED",
        approval_type="PREDICTIVE_SCREENING",
        screening_snapshot="market-1",
        eligible_lags=("BBB", "CCC"),
        stale_ticker=None,
        missing_ticker=None,
        bad_ticker=None,
    ):
        self.universe_exists = universe_exists
        self.approval_decision = approval_decision
        self.approval_type = approval_type
        self.screening_snapshot = screening_snapshot
        self.eligible_lags = eligible_lags
        self.stale_ticker = stale_ticker
        self.missing_ticker = missing_ticker
        self.bad_ticker = bad_ticker

    @staticmethod
    def snapshot_columns():
        return [
            "snapshot_id", "dataset_type", "source_session_date", "available_at_utc",
            "provider", "code_version", "expected_row_count", "expected_ticker_count",
            "source_checksum_sha256",
        ]

    def execute(self, query, args):
        compact = " ".join(query.split())
        if "FROM model_input_snapshots" in compact:
            dataset_type = args[0]
            if dataset_type == "STOCK_UNIVERSE" and not self.universe_exists:
                return Result(self.snapshot_columns(), [])
            if dataset_type == "MARKET_FEATURES":
                row = [
                    "market-1", dataset_type, self.source, "2026-08-21T04:00:00+00:00",
                    "YAHOO", "market-v1", 1512, 3, "m" * 64,
                ]
            else:
                row = [
                    "universe-1", dataset_type, self.source, "2026-08-21T04:30:00+00:00",
                    "SCREENING", "universe-v1", 1, 1, "u" * 64,
                ]
            return Result(self.snapshot_columns(), [row])
        if "GROUP BY ticker" in compact:
            rows = []
            for ticker in ("AAA", "BBB", "CCC"):
                if ticker == self.missing_ticker:
                    continue
                latest = "2026-08-19" if ticker == self.stale_ticker else self.source
                bad = 1 if ticker == self.bad_ticker else 0
                rows.append([ticker, 504, "2024-08-20", latest, bad, 0])
            return Result(
                ["ticker", "row_count", "first_date", "latest_date",
                 "bad_close_rows", "bad_volume_rows"],
                rows,
            )
        if "COUNT(*) AS row_count" in compact and "market_daily_features" in compact:
            return Result(["row_count", "ticker_count"], [[1512, 3]])
        if "COUNT(*) AS row_count" in compact and "stock_universe_config" in compact:
            return Result(["row_count", "ticker_count"], [[1, 1]])
        if "FROM stock_universe_config" in compact:
            return Result(
                ["ticker", "selection_rank", "oos_accuracy", "causal_depth",
                 "lag1_ticker", "lag2_ticker", "lag3_ticker", "lag4_ticker", "lag5_ticker"],
                [["AAA", 1, 0.61, 2, "BBB", "CCC", None, None, None]],
            )
        if "FROM model_input_approval_events" in compact:
            if self.approval_decision is None:
                return Result(
                    ["event_id", "decision", "approved_by", "decided_at_utc",
                     "snapshot_checksum_sha256", "source_evidence_type", "source_evidence_id"],
                    [],
                )
            return Result(
                ["event_id", "decision", "approved_by", "decided_at_utc",
                 "snapshot_checksum_sha256", "source_evidence_type", "source_evidence_id"],
                [["approval-1", self.approval_decision, "owner",
                  "2026-08-21T04:45:00+00:00", "u" * 64,
                  self.approval_type, "screen-1"]],
            )
        if "FROM predictive_screening_runs" in compact:
            return Result(
                ["screening_run_id", "market_snapshot_id", "source_session_date", "status"],
                [["screen-1", self.screening_snapshot, self.source, "VALIDATED"]],
            )
        if "FROM predictive_screening_results" in compact:
            lag1, lag2 = self.eligible_lags
            return Result(
                ["ticker", "selected_depth", "lag1_ticker", "lag2_ticker",
                 "lag3_ticker", "lag4_ticker", "lag5_ticker"],
                [["AAA", 2, lag1, lag2, None, None, None]],
            )
        raise AssertionError(f"Unexpected query: {compact}")


class StockModelPreflightTests(unittest.TestCase):
    source = date(2026, 8, 20)
    prediction = date(2026, 8, 21)
    cutoff = datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)

    def run_preflight(self, db):
        return build_stock_model_preflight(
            db,
            source_session_date=self.source,
            prediction_date=self.prediction,
            cutoff_utc=self.cutoff,
            minimum_history_sessions=252,
        )

    def test_complete_exact_evidence_passes(self):
        evidence = self.run_preflight(FakeDB())
        self.assertEqual(evidence.market_snapshot.snapshot_id, "market-1")
        self.assertEqual(evidence.universe_snapshot.snapshot_id, "universe-1")
        self.assertEqual(evidence.screening_run_id, "screen-1")
        self.assertEqual(evidence.required_market_tickers, ("AAA", "BBB", "CCC"))

    def test_missing_universe_fails_closed_before_model(self):
        with self.assertRaisesRegex(LineageError, "No validated STOCK_UNIVERSE"):
            self.run_preflight(FakeDB(universe_exists=False))

    def test_missing_approval_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "no approval decision"):
            self.run_preflight(FakeDB(approval_decision=None))

    def test_revoked_approval_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "REVOKED, not APPROVED"):
            self.run_preflight(FakeDB(approval_decision="REVOKED"))

    def test_manual_approval_without_screening_evidence_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "not backed by predictive-screening"):
            self.run_preflight(FakeDB(approval_type="MANUAL_RESEARCH_REVIEW"))

    def test_screening_market_snapshot_mismatch_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "different market snapshot"):
            self.run_preflight(FakeDB(screening_snapshot="other-market"))

    def test_modified_lag_chain_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "differ from approved screening"):
            self.run_preflight(FakeDB(eligible_lags=("BBB", "DDD")))

    def test_stale_required_ticker_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "BBB market history is stale"):
            self.run_preflight(FakeDB(stale_ticker="BBB"))

    def test_missing_required_ticker_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "lacks required tickers: CCC"):
            self.run_preflight(FakeDB(missing_ticker="CCC"))

    def test_bad_market_row_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "AAA contains invalid"):
            self.run_preflight(FakeDB(bad_ticker="AAA"))

    def test_source_must_precede_prediction(self):
        with self.assertRaisesRegex(LineageError, "must precede"):
            build_stock_model_preflight(
                FakeDB(), source_session_date=self.source, prediction_date=self.source,
                cutoff_utc=self.cutoff,
            )


if __name__ == "__main__":
    unittest.main()
