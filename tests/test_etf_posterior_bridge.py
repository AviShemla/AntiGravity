import unittest
from datetime import date, datetime, timezone

from etf_posterior_bridge import (
    ETF_RESEARCH_POLICY_MARKER,
    build_frozen_etf_research_evidence,
)
from etf_prior_builder import PreparedETFStockPrior
from etf_pymc_core import ETFPosteriorEvidence
from model_lineage import (
    AssetClass,
    ETFPrior,
    LineageError,
    ModelRun,
    Recommendation,
    RunStatus,
)
from sampler_qa import SamplerDiagnostics
from stock_etf_interlock import ETFDirectionalPrior, StockPosteriorEvidence
from stock_scorecard_reader import StockEvidenceBatch


SOURCE = date(2026, 8, 21)
PREDICTION = date(2026, 8, 24)
AVAILABLE = datetime(2026, 8, 22, 4, tzinfo=timezone.utc)


def diagnostics():
    return SamplerDiagnostics(1.01, 500.0, 300.0, 0.8, 0, 0.0, 4)


def etf_run():
    return ModelRun(
        run_id="etf-run",
        model_name="ETF_PYMC_XLK",
        asset_class=AssetClass.ETF,
        prediction_date=PREDICTION,
        source_session_date=SOURCE,
        as_of_timestamp_utc=datetime(2026, 8, 22, 5, tzinfo=timezone.utc),
        code_version="code-v1",
        config_version="config-v1",
        status=RunStatus.STARTED,
    )


def prepared():
    evidence = [
        StockPosteriorEvidence("AAPL", 0.65, 0.04, 1.2, 0.6, 0.65),
    ]
    batch = StockEvidenceBatch(
        run_id="stock-run",
        stock_persona="Neutral",
        prediction_date=PREDICTION,
        source_session_date=SOURCE,
        available_at_utc=AVAILABLE,
        market_snapshot_id="market-1",
        universe_snapshot_id="universe-1",
        evidence=evidence,
    )
    aggregate = ETFDirectionalPrior(
        mean_log_odds=0.6,
        sigma_log_odds=0.25,
        weighted_expected_return_pp=1.2,
        expected_return_sigma_pp=0.6,
        weight_coverage=0.65,
        contributor_count=1,
    )
    records = tuple(
        ETFPrior(
            prior_id=f"prior-{index}",
            etf_run_id="etf-run",
            prior_type=prior_type,
            source_run_id="stock-run",
            source_ticker=ticker,
            source_session_date=SOURCE,
            available_at_utc=AVAILABLE,
            constituent_weight=0.65,
            transformed_value=value,
            prior_sigma=sigma,
            transformation=transformation,
        )
        for index, (prior_type, ticker, value, sigma, transformation) in enumerate(
            (
                ("STOCK_POSTERIOR", "AAPL", 0.6, 0.25, "direction log-odds"),
                ("STOCK_POSTERIOR", "AAPL", 1.2, 0.6, "return percentage points"),
                ("SECTOR_AGGREGATE", None, 0.6, 0.25, "aggregate direction"),
                ("SECTOR_AGGREGATE", None, 1.2, 0.6, "aggregate return percentage points"),
            ),
            start=1,
        )
    )
    return PreparedETFStockPrior(batch, aggregate, records)


def posterior(return_prior=1.2):
    return ETFPosteriorEvidence(
        ticker="XLK",
        probability_up_mean=0.64,
        probability_up_std=0.04,
        probability_up_q05=0.56,
        probability_up_q95=0.72,
        expected_return_pp_mean=0.8,
        expected_return_pp_std=0.3,
        predictive_risk_pp=1.6,
        stock_direction_prior_mean_log_odds=0.6,
        stock_direction_prior_sigma_log_odds=0.25,
        stock_return_prior_mean_pp=return_prior,
        stock_return_prior_sigma_pp=0.6,
        stock_weight_coverage=0.65,
        stock_contributor_count=1,
        diagnostics=diagnostics(),
    )


class ETFPosteriorBridgeTests(unittest.TestCase):
    def test_retains_raw_posterior_and_forces_no_trade(self):
        raw = posterior()
        result = build_frozen_etf_research_evidence(
            etf_run=etf_run(),
            prepared_stock_prior=prepared(),
            posterior=raw,
            persona_name="ETF_Neutral",
        )
        self.assertIs(result.posterior, raw)
        self.assertEqual(result.scorecard.expected_return, 0.8)
        self.assertEqual(result.scorecard.expected_risk, 1.6)
        self.assertEqual(result.scorecard.recommendation, Recommendation.NO_TRADE)
        self.assertEqual(result.scorecard.proposed_allocation, 0.0)
        self.assertEqual(result.scorecard.quarantine_reason, ETF_RESEARCH_POLICY_MARKER)
        self.assertEqual(result.expected_return_unit, "percentage_points")
        self.assertEqual(len(result.stock_prior_lineage), 4)

    def test_incomplete_stock_prior_lineage_fails_closed(self):
        item = prepared()
        incomplete = PreparedETFStockPrior(
            item.stock_batch, item.aggregate, item.lineage_records[:-1]
        )
        with self.assertRaisesRegex(LineageError, "lineage is incomplete"):
            build_frozen_etf_research_evidence(
                etf_run=etf_run(),
                prepared_stock_prior=incomplete,
                posterior=posterior(),
                persona_name="ETF_Neutral",
            )

    def test_posterior_prior_mismatch_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "return prior differs"):
            build_frozen_etf_research_evidence(
                etf_run=etf_run(),
                prepared_stock_prior=prepared(),
                posterior=posterior(return_prior=0.012),
                persona_name="ETF_Neutral",
            )

    def test_non_etf_run_fails_closed(self):
        run = etf_run()
        invalid = ModelRun(**{**run.__dict__, "asset_class": AssetClass.STOCK})
        with self.assertRaisesRegex(LineageError, "requires an ETF model run"):
            build_frozen_etf_research_evidence(
                etf_run=invalid,
                prepared_stock_prior=prepared(),
                posterior=posterior(),
                persona_name="ETF_Neutral",
            )


if __name__ == "__main__":
    unittest.main()
