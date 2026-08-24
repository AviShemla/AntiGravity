import math
import unittest

from model_lineage import LineageError
from stock_etf_interlock import (
    StockPosteriorEvidence,
    build_directional_prior,
    stock_persona_for,
)


class StockETFInterlockTests(unittest.TestCase):
    def evidence(self) -> list[StockPosteriorEvidence]:
        return [
            StockPosteriorEvidence("AAPL", 0.70, 0.04, 0.012, 0.006, 0.35),
            StockPosteriorEvidence("MSFT", 0.60, 0.05, 0.008, 0.005, 0.25),
            StockPosteriorEvidence("NVDA", 0.55, 0.06, 0.015, 0.009, 0.20),
        ]

    def test_personas_are_aligned_by_risk_mandate(self) -> None:
        self.assertEqual(stock_persona_for("ETF_Neutral"), "Neutral")
        self.assertEqual(stock_persona_for("ETF_Dynamic"), "Dynamic")
        with self.assertRaises(LineageError):
            stock_persona_for("Stock")

    def test_prior_is_finite_and_preserves_coverage(self) -> None:
        prior = build_directional_prior(
            self.evidence(), minimum_weight_coverage=0.60, calibrated_sigma_floor=0.20
        )
        self.assertTrue(math.isfinite(prior.mean_log_odds))
        self.assertGreaterEqual(prior.sigma_log_odds, 0.20)
        self.assertGreater(prior.expected_return_sigma, 0.0)
        self.assertAlmostEqual(prior.weight_coverage, 0.80)
        self.assertEqual(prior.contributor_count, 3)

    def test_missing_uncertainty_fails_closed(self) -> None:
        rows = self.evidence()
        rows[0] = StockPosteriorEvidence("AAPL", 0.70, None, 0.012, 0.006, 0.35)
        with self.assertRaisesRegex(LineageError, "uncertainty"):
            build_directional_prior(
                rows, minimum_weight_coverage=0.60, calibrated_sigma_floor=0.20
            )

    def test_insufficient_whale_coverage_fails_closed(self) -> None:
        with self.assertRaisesRegex(LineageError, "below required"):
            build_directional_prior(
                self.evidence(), minimum_weight_coverage=0.90, calibrated_sigma_floor=0.20
            )

    def test_weights_above_one_fail_closed(self) -> None:
        rows = self.evidence() + [
            StockPosteriorEvidence("AVGO", 0.60, 0.05, 0.010, 0.006, 0.30)
        ]
        with self.assertRaisesRegex(LineageError, "exceed"):
            build_directional_prior(
                rows, minimum_weight_coverage=0.60, calibrated_sigma_floor=0.20
            )

    def test_missing_return_uncertainty_fails_closed(self) -> None:
        rows = self.evidence()
        rows[0] = StockPosteriorEvidence("AAPL", 0.70, 0.04, 0.012, None, 0.35)
        with self.assertRaisesRegex(LineageError, "expected-return uncertainty"):
            build_directional_prior(
                rows, minimum_weight_coverage=0.60, calibrated_sigma_floor=0.20
            )


if __name__ == "__main__":
    unittest.main()
