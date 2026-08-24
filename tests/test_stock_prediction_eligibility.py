import unittest

from model_lineage import LineageError, Recommendation
from stock_prediction_eligibility import (
    DecisionContext,
    PredictionEvidence,
    compare_stock_prediction,
    shadow_vix_multiplier,
)


def context(**changes):
    values = {
        "snapshot_validated": True,
        "universe_approved": True,
        "source_date_aligned": True,
        "model_run_completed": True,
        "sampler_qa_passed": True,
        "research_promotion_approved": True,
        "available_capital": 10_000.0,
        "vix_close": 15.0,
        "round_trip_cost": 0.001,
    }
    values.update(changes)
    return DecisionContext(**values)


class StockPredictionEligibilityTests(unittest.TestCase):
    def test_raw_output_survives_failed_safety_gate(self):
        result = compare_stock_prediction(
            PredictionEvidence(0.72, 0.55, 0.84, 0.012, 0.02),
            context(snapshot_validated=False),
            persona_name="Neutral",
        )
        self.assertEqual(result.raw_model_signal, Recommendation.BUY)
        self.assertEqual(result.codex_action, Recommendation.NO_TRADE)
        self.assertEqual(result.balanced_action, Recommendation.NO_TRADE)
        self.assertEqual(result.rows[0].balanced_result, "REPORTED")
        self.assertEqual(result.hard_gate_failures, ("SNAPSHOT_NOT_VALIDATED",))
        self.assertEqual(result.shadow_allocation_fraction, 0.0)

    def test_strict_and_balanced_can_disagree_without_hiding_prediction(self):
        result = compare_stock_prediction(
            PredictionEvidence(0.64, 0.47, 0.78, 0.010, 0.02),
            context(),
            persona_name="Neutral",
        )
        self.assertEqual(result.raw_model_signal, Recommendation.HOLD)
        self.assertEqual(result.codex_action, Recommendation.HOLD)
        self.assertEqual(result.balanced_action, Recommendation.BUY)

    def test_legacy_flat_fallback_is_preserved_as_observed_behavior(self):
        result = compare_stock_prediction(
            PredictionEvidence(0.62, 0.51, 0.72, -0.001, 0.02),
            context(),
            persona_name="Neutral",
        )
        self.assertAlmostEqual(result.legacy_allocation_fraction, 0.10)
        self.assertEqual(result.ag_action, Recommendation.BUY)
        self.assertEqual(result.balanced_action, Recommendation.HOLD)
        self.assertEqual(result.shadow_allocation_fraction, 0.0)

    def test_conservative_has_no_flat_fallback(self):
        result = compare_stock_prediction(
            PredictionEvidence(0.70, 0.55, 0.82, -0.001, 0.02),
            context(),
            persona_name="Conservative",
        )
        self.assertEqual(result.legacy_allocation_fraction, 0.0)
        self.assertEqual(result.ag_action, Recommendation.HOLD)

    def test_unknown_dynamic_persona_requires_resolution(self):
        with self.assertRaisesRegex(LineageError, "resolved base persona"):
            compare_stock_prediction(
                PredictionEvidence(0.70, 0.55, 0.82, 0.01, 0.02),
                context(),
                persona_name="Dynamic",
            )

    def test_vix_is_continuous_shadow_sizing_not_a_hard_gate(self):
        self.assertEqual(shadow_vix_multiplier("Neutral", 20.0), 1.0)
        self.assertAlmostEqual(shadow_vix_multiplier("Neutral", 25.0), 0.625)
        self.assertEqual(shadow_vix_multiplier("Neutral", 30.0), 0.25)
        self.assertEqual(shadow_vix_multiplier("Neutral", 80.0), 0.25)
        result = compare_stock_prediction(
            PredictionEvidence(0.72, 0.55, 0.84, 0.03, 0.02),
            context(vix_close=31.0),
            persona_name="Neutral",
        )
        self.assertEqual(result.legacy_vix_multiplier, 0.0)
        self.assertEqual(result.shadow_vix_multiplier, 0.25)
        self.assertEqual(result.hard_gate_failures, ())

    def test_shadow_sizing_never_uses_flat_fallback(self):
        result = compare_stock_prediction(
            PredictionEvidence(0.70, 0.54, 0.82, 0.001, 0.02),
            context(round_trip_cost=0.002),
            persona_name="BallsForBrains",
        )
        self.assertEqual(result.legacy_allocation_fraction, 0.15)
        self.assertEqual(result.shadow_allocation_fraction, 0.0)


if __name__ == "__main__":
    unittest.main()
