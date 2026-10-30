import unittest

from model_lineage import Recommendation
from sampler_qa import SamplerDiagnostics
from stock_posterior_bridge import (
    compare_research_only_posterior,
    posterior_to_prediction_evidence,
)
from stock_prediction_eligibility import DecisionContext
from stock_pymc_core import StockPosteriorEvidence


def diagnostics():
    return SamplerDiagnostics(1.01, 500.0, 300.0, 0.8, 0, 0.0, 4)


def posterior():
    return StockPosteriorEvidence(
        ticker="NDAQ",
        probability_up_mean=0.72,
        probability_up_std=0.04,
        probability_up_q05=0.55,
        probability_up_q95=0.84,
        expected_return_pp_mean=1.25,
        expected_return_pp_std=0.30,
        predictive_risk_pp=2.50,
        diagnostics=diagnostics(),
    )


def context():
    return DecisionContext(
        snapshot_validated=True,
        universe_approved=True,
        source_date_aligned=True,
        model_run_completed=True,
        sampler_qa_passed=True,
        research_promotion_approved=True,
        available_capital=10_000.0,
        vix_close=18.0,
        round_trip_cost_bps=10.0,
    )


class StockPosteriorBridgeTests(unittest.TestCase):
    def test_percentage_point_evidence_is_not_rescaled(self):
        evidence = posterior_to_prediction_evidence(posterior())
        self.assertEqual(evidence.expected_return_pp, 1.25)
        self.assertEqual(evidence.expected_risk_pp, 2.50)

    def test_research_bridge_forces_no_trade_without_hiding_raw_signal(self):
        result = compare_research_only_posterior(
            posterior(), context(), persona_name="Neutral"
        )
        self.assertEqual(result.raw_model_signal, Recommendation.BUY)
        self.assertEqual(result.codex_action, Recommendation.NO_TRADE)
        self.assertEqual(result.balanced_action, Recommendation.NO_TRADE)
        self.assertIn(
            "RESEARCH_PROMOTION_NOT_APPROVED",
            result.hard_gate_failures,
        )


if __name__ == "__main__":
    unittest.main()
