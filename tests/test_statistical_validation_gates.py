import inspect
import unittest

import statistical_validation_gates
from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics
from statistical_validation_gates import (
    CalibrationEvidence,
    ComparativeEvidence,
    CostDrawdownEvidence,
    LineageEvidence,
    WalkForwardEvidence,
    build_ag_codex_comparison_table,
    evaluate_statistical_validation,
)
from stock_prediction_eligibility import (
    DecisionContext,
    PredictionEvidence,
    compare_stock_prediction,
)


def prediction():
    return PredictionEvidence(
        probability_up_mean=0.64,
        probability_up_q05=0.53,
        probability_up_q95=0.74,
        expected_return_pp=1.2,
        expected_risk_pp=2.4,
    )


def diagnostics():
    return SamplerDiagnostics(
        max_rhat=1.01,
        min_ess_bulk=500.0,
        min_ess_tail=300.0,
        min_bfmi=0.80,
        divergences=0,
        tree_depth_saturation_fraction=0.0,
        chains=4,
    )


def walk_forward():
    return WalkForwardEvidence(
        fold_count=5,
        oos_observation_count=63,
        embargo_sessions=1,
        train_test_overlap_count=0,
    )


def calibration():
    return CalibrationEvidence(
        model_brier=0.20,
        naive_brier=0.25,
        model_log_loss=0.60,
        naive_log_loss=0.69,
        expected_calibration_error=0.06,
    )


def comparative():
    return ComparativeEvidence(
        model_net_return_pp=8.0,
        simple_baseline_net_return_pp=3.0,
        arena_median_net_return_pp=5.0,
        model_max_drawdown_pp=8.0,
        arena_median_max_drawdown_pp=10.0,
    )


def costs():
    return CostDrawdownEvidence(
        gross_return_pp=10.0,
        total_transaction_cost_pp=2.0,
        net_return_pp=8.0,
        stress_net_return_pp=4.0,
        turnover_fraction=0.30,
        max_drawdown_pp=8.0,
    )


def lineage(*, stock_prior=None):
    return LineageEvidence(
        exact_market_snapshot_id="market-1",
        exact_universe_snapshot_id="universe-1",
        exact_model_run_id="run-1",
        source_session_aligned=True,
        input_checksums_match=True,
        point_in_time_features_only=True,
        provider_lineage_complete=True,
        stock_prior_lineage_complete=stock_prior,
    )


def stock_context():
    return DecisionContext(
        snapshot_validated=True,
        universe_approved=True,
        source_date_aligned=True,
        model_run_completed=True,
        sampler_qa_passed=True,
        research_promotion_approved=False,
        available_capital=0.0,
        vix_close=18.0,
        round_trip_cost_bps=10.0,
    )


class StatisticalValidationGateTests(unittest.TestCase):
    def test_stock_evidence_passes_all_measurable_gates(self):
        raw = prediction()
        result = evaluate_statistical_validation(
            raw_prediction=raw,
            diagnostics=diagnostics(),
            walk_forward=walk_forward(),
            calibration=calibration(),
            comparative=comparative(),
            costs=costs(),
            lineage=lineage(),
            asset_class="STOCK",
        )
        self.assertIs(result.raw_prediction, raw)
        self.assertTrue(result.research_visible)
        self.assertTrue(result.hard_gate_passed)
        self.assertTrue(result.shadow_sizing_eligible)
        self.assertEqual(result.comparative_sizing_multiplier, 1.0)
        self.assertEqual(len(result.gates), 7)

    def test_etf_requires_complete_stock_prior_lineage(self):
        result = evaluate_statistical_validation(
            raw_prediction=prediction(),
            diagnostics=diagnostics(),
            walk_forward=walk_forward(),
            calibration=calibration(),
            comparative=comparative(),
            costs=costs(),
            lineage=lineage(stock_prior=None),
            asset_class="ETF",
        )
        self.assertTrue(result.research_visible)
        self.assertFalse(result.hard_gate_passed)
        self.assertFalse(result.shadow_sizing_eligible)
        self.assertEqual(result.comparative_sizing_multiplier, 0.0)
        self.assertIn("IMMUTABLE_LINEAGE_FAILED", result.hard_failures)

    def test_comparative_misses_reduce_sizing_without_hiding_posterior(self):
        weak = ComparativeEvidence(
            model_net_return_pp=2.0,
            simple_baseline_net_return_pp=3.0,
            arena_median_net_return_pp=5.0,
            model_max_drawdown_pp=12.0,
            arena_median_max_drawdown_pp=10.0,
        )
        raw = prediction()
        result = evaluate_statistical_validation(
            raw_prediction=raw,
            diagnostics=diagnostics(),
            walk_forward=walk_forward(),
            calibration=calibration(),
            comparative=weak,
            costs=costs(),
            lineage=lineage(),
            asset_class="STOCK",
        )
        self.assertTrue(result.hard_gate_passed)
        self.assertTrue(result.shadow_sizing_eligible)
        self.assertEqual(len(result.sizing_warnings), 2)
        self.assertEqual(result.comparative_sizing_multiplier, 0.25)
        self.assertIs(result.raw_prediction, raw)

    def test_bad_calibration_blocks_sizing_but_retains_raw_evidence(self):
        bad = CalibrationEvidence(
            model_brier=0.27,
            naive_brier=0.25,
            model_log_loss=0.72,
            naive_log_loss=0.69,
            expected_calibration_error=0.14,
        )
        raw = prediction()
        result = evaluate_statistical_validation(
            raw_prediction=raw,
            diagnostics=diagnostics(),
            walk_forward=walk_forward(),
            calibration=bad,
            comparative=comparative(),
            costs=costs(),
            lineage=lineage(),
            asset_class="STOCK",
        )
        self.assertTrue(result.research_visible)
        self.assertIs(result.raw_prediction, raw)
        self.assertFalse(result.shadow_sizing_eligible)
        self.assertIn("PROBABILITY_CALIBRATION_FAILED", result.hard_failures)

    def test_cost_arithmetic_must_reconcile_exactly(self):
        inconsistent = CostDrawdownEvidence(
            **{**costs().__dict__, "net_return_pp": 7.9}
        )
        result = evaluate_statistical_validation(
            raw_prediction=prediction(),
            diagnostics=diagnostics(),
            walk_forward=walk_forward(),
            calibration=calibration(),
            comparative=comparative(),
            costs=inconsistent,
            lineage=lineage(),
            asset_class="STOCK",
        )
        self.assertIn("COST_DRAWDOWN_FAILED", result.hard_failures)

    def test_ag_codex_table_preserves_existing_rows_and_adds_review_gates(self):
        raw = prediction()
        validation = evaluate_statistical_validation(
            raw_prediction=raw,
            diagnostics=diagnostics(),
            walk_forward=walk_forward(),
            calibration=calibration(),
            comparative=comparative(),
            costs=costs(),
            lineage=lineage(),
            asset_class="STOCK",
        )
        comparison = compare_stock_prediction(
            raw,
            stock_context(),
            persona_name="Neutral",
        )
        table = build_ag_codex_comparison_table(
            raw_prediction=raw,
            validation_review=validation,
            existing_comparison=comparison,
        )
        self.assertEqual(table.rows[: len(comparison.rows)], comparison.rows)
        self.assertEqual(table.rows[-2].criterion, "Statistical validation")
        self.assertEqual(table.rows[-1].criterion, "Baseline and Arena sizing")
        self.assertIn("multiplier=1.000000", table.rows[-1].codex_result)

    def test_table_rejects_mismatched_prediction(self):
        raw = prediction()
        validation = evaluate_statistical_validation(
            raw_prediction=raw,
            diagnostics=diagnostics(),
            walk_forward=walk_forward(),
            calibration=calibration(),
            comparative=comparative(),
            costs=costs(),
            lineage=lineage(),
            asset_class="STOCK",
        )
        other = PredictionEvidence(**{**raw.__dict__, "expected_return_pp": 0.1})
        comparison = compare_stock_prediction(
            raw,
            stock_context(),
            persona_name="Neutral",
        )
        with self.assertRaisesRegex(LineageError, "different predictions"):
            build_ag_codex_comparison_table(
                raw_prediction=other,
                validation_review=validation,
                existing_comparison=comparison,
            )

    def test_package_has_no_forbidden_production_data_dependency(self):
        source = inspect.getsource(statistical_validation_gates).lower()
        for forbidden in ("read_csv", "read_excel", "sqlite3", "streamlit"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
