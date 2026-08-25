import unittest
from datetime import date, datetime, timezone

from etf_prior_builder import prepare_etf_stock_prior
from model_lineage import AssetClass, LineageError, ModelRun, RunStatus


class Result:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class FakeDB:
    def __init__(self, source_session="2026-08-21"):
        self.source_session = source_session

    def execute(self, query, _args):
        if "FROM model_runs" in query:
            return Result(
                ["run_id", "source_session_date", "completed_at_utc"],
                [["stock-run", self.source_session, "2026-08-22T04:00:00+00:00"]],
            )
        if "FROM model_run_inputs" in query:
            return Result(
                ["input_role", "snapshot_id", "snapshot_checksum_sha256",
                 "source_checksum_sha256", "source_session_date", "available_at_utc", "status"],
                [
                    ["MARKET_FEATURES", "market-1", "m" * 64, "m" * 64,
                     self.source_session, "2026-08-22T03:00:00+00:00", "VALIDATED"],
                    ["STOCK_UNIVERSE", "universe-1", "u" * 64, "u" * 64,
                     self.source_session, "2026-08-22T03:30:00+00:00", "VALIDATED"],
                ],
            )
        if "FROM model_scorecards" in query:
            return Result(
                [
                    "ticker", "posterior_probability", "posterior_probability_std",
                    "expected_return", "expected_return_std", "expected_risk",
                    "recommendation", "proposed_allocation", "quarantine_reason", "created_at_utc",
                ],
                [
                    ["AAPL", 0.65, 0.04, 1.2, 0.6, 2.4, "NO_TRADE", 0.0, "RESEARCH_ONLY;PROMOTION_DISABLED;ACTION_LANES_NO_TRADE;UNIT_CONTRACT=statistical-units-v1", "2026-08-22T04:01:00+00:00"],
                    ["MSFT", 0.58, 0.05, 0.8, 0.5, 1.8, "NO_TRADE", 0.0, "RESEARCH_ONLY;PROMOTION_DISABLED;ACTION_LANES_NO_TRADE;UNIT_CONTRACT=statistical-units-v1", "2026-08-22T04:01:00+00:00"],
                ],
            )
        raise AssertionError("Unexpected query")


def etf_run(source_session=date(2026, 8, 21)):
    return ModelRun(
        run_id="etf-run",
        model_name="ETF_PYMC",
        asset_class=AssetClass.ETF,
        prediction_date=date(2026, 8, 24),
        source_session_date=source_session,
        as_of_timestamp_utc=datetime(2026, 8, 22, 5, 0, tzinfo=timezone.utc),
        code_version="test",
        config_version="test",
        status=RunStatus.STARTED,
    )


class ETFPriorBuilderTests(unittest.TestCase):
    def test_builds_constituent_and_aggregate_lineage(self):
        prepared = prepare_etf_stock_prior(
            FakeDB(),
            etf_run=etf_run(),
            etf_persona="ETF_Neutral",
            expected_market_snapshot_id="market-1",
            constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            minimum_weight_coverage=0.60,
            calibrated_sigma_floor=0.20,
        )
        self.assertEqual(prepared.stock_batch.stock_persona, "Neutral")
        self.assertEqual(prepared.aggregate.contributor_count, 2)
        self.assertEqual(len(prepared.lineage_records), 6)
        self.assertEqual(prepared.lineage_records[-2].prior_type, "SECTOR_AGGREGATE")
        self.assertEqual(prepared.lineage_records[-1].prior_type, "SECTOR_AGGREGATE")
        self.assertIn("expected return", prepared.lineage_records[-1].transformation)
        self.assertAlmostEqual(prepared.lineage_records[-1].constituent_weight, 0.65)

    def test_prior_ids_are_deterministic(self):
        kwargs = dict(
            db=FakeDB(),
            etf_run=etf_run(),
            etf_persona="ETF_Neutral",
            expected_market_snapshot_id="market-1",
            constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
            minimum_weight_coverage=0.60,
            calibrated_sigma_floor=0.20,
        )
        first = prepare_etf_stock_prior(**kwargs)
        second = prepare_etf_stock_prior(**kwargs)
        self.assertEqual(
            [item.prior_id for item in first.lineage_records],
            [item.prior_id for item in second.lineage_records],
        )

    def test_mismatched_stock_and_etf_source_sessions_fail_closed(self):
        with self.assertRaisesRegex(LineageError, "same source session"):
            prepare_etf_stock_prior(
                FakeDB(source_session="2026-08-20"),
                etf_run=etf_run(),
                etf_persona="ETF_Conservative",
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35, "MSFT": 0.30},
                minimum_weight_coverage=0.60,
                calibrated_sigma_floor=0.20,
            )


if __name__ == "__main__":
    unittest.main()
