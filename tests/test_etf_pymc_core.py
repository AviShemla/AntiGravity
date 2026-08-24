import unittest
from datetime import date, datetime, timezone

import numpy as np

from etf_model_dataset import ETFModelDataset
from etf_prior_builder import PreparedETFStockPrior
from etf_pymc_core import summarize_etf_posterior, validate_etf_inputs
from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics
from stock_etf_interlock import ETFDirectionalPrior, StockPosteriorEvidence
from stock_scorecard_reader import StockEvidenceBatch


SOURCE = date(2026, 8, 21)
PREDICTION = date(2026, 8, 24)


def dataset(source=SOURCE):
    return ETFModelDataset(
        ticker="XLK", source_session_date=source, prediction_date=PREDICTION,
        feature_names=("return_lag1", "vix_lag1"),
        training_dates=tuple(date(2026, 7, day) for day in range(1, 5)),
        x_train=np.array([[-1.0, 0.5], [0.0, 0.2], [0.5, -0.2], [1.0, -0.5]]),
        y_direction=np.array([0, 0, 1, 1]),
        y_return_pct=np.array([-0.4, -0.1, 0.2, 0.5]),
        x_predict=np.array([[0.25, -0.1]]),
        train_mean=np.array([0.0, 0.0]), train_scale=np.array([1.0, 1.0]),
    )


def prepared(source=SOURCE, return_sigma=0.30):
    evidence = [StockPosteriorEvidence("AAPL", 0.65, 0.04, 0.20, 0.10, 0.65)]
    batch = StockEvidenceBatch(
        run_id="stock-run", stock_persona="Neutral", prediction_date=PREDICTION,
        source_session_date=source,
        available_at_utc=datetime(2026, 8, 22, 4, tzinfo=timezone.utc),
        market_snapshot_id="market-1", universe_snapshot_id="universe-1",
        evidence=evidence,
    )
    aggregate = ETFDirectionalPrior(
        mean_log_odds=0.6, sigma_log_odds=0.25,
        weighted_expected_return=0.20, expected_return_sigma=return_sigma,
        weight_coverage=0.65, contributor_count=1,
    )
    return PreparedETFStockPrior(batch, aggregate, ())


def diagnostics():
    return SamplerDiagnostics(1.01, 500, 300, 0.8, 0, 0.0, 4)


class ETFPosteriorCoreTests(unittest.TestCase):
    def test_summary_retains_stock_prior_and_predictive_uncertainty(self):
        result = summarize_etf_posterior(
            dataset=dataset(), stock_prior=prepared(),
            alpha_direction=np.array([0.4, 0.5, 0.6]),
            beta_direction=np.array([[0.2, 0.1], [0.1, 0.0], [0.3, -0.1]]),
            alpha_return=np.array([0.1, 0.2, 0.3]),
            beta_return=np.array([[0.1, 0.0], [0.2, 0.1], [0.0, -0.1]]),
            return_scale=np.array([0.6, 0.7, 0.8]),
            return_nu=np.array([8.0, 10.0, 12.0]), diagnostics=diagnostics(),
        )
        self.assertEqual(result.stock_direction_prior_mean_log_odds, 0.6)
        self.assertEqual(result.stock_return_prior_mean_pct, 0.20)
        self.assertGreater(result.probability_up_std, 0.0)
        self.assertGreater(result.predictive_risk_pct, result.expected_return_pct_std)

    def test_source_session_mismatch_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "source sessions do not match"):
            validate_etf_inputs(dataset(), prepared(date(2026, 8, 20)))

    def test_missing_return_prior_uncertainty_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "uncertainty must be positive"):
            validate_etf_inputs(dataset(), prepared(return_sigma=0.0))

    def test_single_class_history_fails_closed(self):
        item = dataset()
        invalid = ETFModelDataset(
            **{**item.__dict__, "y_direction": np.ones(len(item.y_direction), dtype=int)}
        )
        with self.assertRaisesRegex(LineageError, "only one class"):
            validate_etf_inputs(invalid, prepared())


if __name__ == "__main__":
    unittest.main()
