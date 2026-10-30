import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import numpy as np

from model_lineage import LineageError, Recommendation
from sampler_qa import SamplerDiagnostics
from stock_hierarchical_cohort import (
    CohortDecisionLane,
    FrozenCohortTarget,
    HierarchicalCohortConfig,
    run_hierarchical_cohort_research,
)
from stock_model_dataset import StockModelDataset
from stock_prediction_eligibility import DecisionContext
from stock_pymc_core import StockPosteriorEvidence


def diagnostics():
    return SamplerDiagnostics(1.01, 500.0, 300.0, 0.8, 0, 0.0, 4)


class HierarchicalCohortResearchTests(unittest.TestCase):
    source = date(2026, 8, 25)
    prediction = date(2026, 8, 26)
    timestamp = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)

    def dataset(self, ticker, lag_ticker="SPY", *, source=None, prediction=None):
        return StockModelDataset(
            ticker=ticker,
            source_session_date=source or self.source,
            prediction_date=prediction or self.prediction,
            feature_names=(f"{lag_ticker}_return_x_volume_ratio_lag2",),
            training_dates=(self.source - timedelta(days=2), self.source - timedelta(days=1), self.source),
            x_train=np.asarray([[-1.0], [0.0], [1.0]]),
            y_direction=np.asarray([0, 1, 0]),
            y_return_pp=np.asarray([-1.0, 0.5, -0.2]),
            x_predict=np.asarray([[0.25]]),
            train_mean=np.asarray([0.0]),
            train_scale=np.asarray([1.0]),
        )

    def context(self, *, promotion=True):
        return DecisionContext(
            snapshot_validated=True,
            universe_approved=True,
            source_date_aligned=True,
            model_run_completed=True,
            sampler_qa_passed=True,
            research_promotion_approved=promotion,
            available_capital=10_000.0,
            vix_close=18.0,
            price_available=True,
            round_trip_cost_bps=10.0,
        )

    def target(self, ticker):
        return FrozenCohortTarget(
            dataset=self.dataset(ticker),
            decision_lanes=(CohortDecisionLane("Neutral", "Neutral", self.context()),),
        )

    def posterior(self, ticker):
        return StockPosteriorEvidence(
            ticker=ticker,
            probability_up_mean=0.72,
            probability_up_std=0.04,
            probability_up_q05=0.60,
            probability_up_q95=0.82,
            expected_return_pp_mean=1.2,
            expected_return_pp_std=0.3,
            predictive_risk_pp=2.0,
            diagnostics=diagnostics(),
        )

    def config(self):
        return HierarchicalCohortConfig(
            "hierarchical-run-1", self.source, self.prediction, self.timestamp
        )

    def test_builds_cohort_and_existing_comparison_audit_records(self):
        targets = (self.target("AAA"), self.target("BBB"))
        fitter = Mock(return_value={ticker: self.posterior(ticker) for ticker in ("AAA", "BBB")})
        result = run_hierarchical_cohort_research(
            targets, self.config(), posterior_fitter=fitter
        )
        fitter.assert_called_once()
        self.assertEqual(result.hierarchical_dataset.tickers, ("AAA", "BBB"))
        self.assertEqual(tuple(item.ticker for item in result.targets), ("AAA", "BBB"))
        for item in result.targets:
            decision = item.decisions[0]
            self.assertIs(decision.comparison.raw_model_signal, Recommendation.BUY)
            self.assertIs(decision.comparison.codex_action, Recommendation.NO_TRADE)
            self.assertIs(decision.comparison.balanced_action, Recommendation.NO_TRADE)
            self.assertGreater(len(decision.audit_records.criteria), 0)
            self.assertEqual(decision.audit_records.decision.values[1], "hierarchical-run-1")

    def test_empty_and_one_target_cohorts_fail_before_fitter(self):
        for targets in ((), (self.target("AAA"),)):
            fitter = Mock()
            with self.subTest(target_count=len(targets)):
                with self.assertRaisesRegex(LineageError, "at least two"):
                    run_hierarchical_cohort_research(
                        targets, self.config(), posterior_fitter=fitter
                    )
                fitter.assert_not_called()

    def test_dataset_lineage_mismatch_fails_before_fitter(self):
        mismatched = FrozenCohortTarget(
            self.dataset("BBB", source=self.source - timedelta(days=1)),
            (CohortDecisionLane("Neutral", "Neutral", self.context()),),
        )
        fitter = Mock()
        with self.assertRaisesRegex(LineageError, "lineage does not match"):
            run_hierarchical_cohort_research(
                (self.target("AAA"), mismatched), self.config(), posterior_fitter=fitter
            )
        fitter.assert_not_called()

    def test_no_or_incomplete_posterior_outputs_fail_closed(self):
        targets = (self.target("AAA"), self.target("BBB"))
        with self.assertRaisesRegex(LineageError, "no posterior outputs"):
            run_hierarchical_cohort_research(
                targets, self.config(), posterior_fitter=lambda data: {}
            )
        with self.assertRaisesRegex(LineageError, "coverage mismatch"):
            run_hierarchical_cohort_research(
                targets,
                self.config(),
                posterior_fitter=lambda data: {"AAA": self.posterior("AAA")},
            )

    def test_research_promotion_is_forced_closed_in_comparison_and_audit(self):
        targets = (self.target("AAA"), self.target("BBB"))
        result = run_hierarchical_cohort_research(
            targets,
            self.config(),
            posterior_fitter=lambda data: {
                ticker: self.posterior(ticker) for ticker in data.tickers
            },
        )
        for item in result.targets:
            decision = item.decisions[0]
            self.assertIn(
                "RESEARCH_PROMOTION_NOT_APPROVED",
                decision.comparison.hard_gate_failures,
            )
            self.assertIs(decision.comparison.codex_action, Recommendation.NO_TRADE)
            self.assertIs(decision.comparison.balanced_action, Recommendation.NO_TRADE)
            audit_values = decision.audit_records.decision.values
            self.assertIn("RESEARCH_PROMOTION_NOT_APPROVED", json.loads(audit_values[20]))
            self.assertEqual(audit_values[21], 0)

    def test_posterior_payload_ticker_mismatch_fails_closed(self):
        targets = (self.target("AAA"), self.target("BBB"))
        with self.assertRaisesRegex(LineageError, "payload ticker"):
            run_hierarchical_cohort_research(
                targets,
                self.config(),
                posterior_fitter=lambda data: {
                    "AAA": self.posterior("WRONG"),
                    "BBB": self.posterior("BBB"),
                },
            )

    def test_invalid_posterior_payload_type_fails_closed(self):
        targets = (self.target("AAA"), self.target("BBB"))
        with self.assertRaisesRegex(LineageError, "invalid posterior payload"):
            run_hierarchical_cohort_research(
                targets,
                self.config(),
                posterior_fitter=lambda data: {
                    "AAA": object(), "BBB": self.posterior("BBB"),
                },
            )

    def test_module_has_no_external_io_or_real_fitter_dependency(self):
        source = open("stock_hierarchical_cohort.py", encoding="utf-8").read().lower()
        for forbidden in (
            "turso", "sqlite", "read_csv", "read_excel", "requests",
            "pending_orders", "fit_hierarchical_stock_posteriors",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
