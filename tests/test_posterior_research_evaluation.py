import math
import unittest
from dataclasses import replace
from datetime import date, timedelta

from model_lineage import LineageError
from posterior_research_evaluation import (
    EvaluationConfig,
    PosteriorOutcome,
    evaluate_hierarchical_posteriors,
)


class PosteriorResearchEvaluationTests(unittest.TestCase):
    config = EvaluationConfig("run-1", "neutral-paper", 100.0, calibration_bins=2)
    start = date(2026, 8, 3)

    def row(self, day, *, leaf="AAA", path=("Technology", "AAA"), probability=0.8,
            q05=0.2, q95=0.9, expected=1.0, realized=1.0, allocation=0.5):
        prediction = self.start + timedelta(days=day)
        return PosteriorOutcome(
            leaf, path, prediction, prediction - timedelta(days=1),
            probability, q05, q95, expected, 0.25, realized, allocation,
        )

    def test_calibration_and_return_error_are_exact(self):
        rows = (
            self.row(0, probability=0.8, realized=2.0, expected=1.0),
            self.row(1, probability=0.2, realized=-2.0, expected=-1.0),
            self.row(2, probability=0.6, realized=-2.0, expected=-1.0),
            self.row(3, probability=0.4, realized=2.0, expected=1.0),
        )
        root = evaluate_hierarchical_posteriors(rows, self.config).nodes[0]
        self.assertEqual(root.calibration.observations, 4)
        self.assertAlmostEqual(root.calibration.accuracy, 0.5)
        self.assertAlmostEqual(root.calibration.brier_score, 0.2)
        self.assertAlmostEqual(root.calibration.calibration_error, 0.2)
        self.assertAlmostEqual(root.calibration.expected_return_mae_pp, 1.0)
        self.assertAlmostEqual(root.calibration.expected_return_rmse_pp, 1.0)
        self.assertAlmostEqual(
            root.calibration.log_loss,
            -(math.log(0.8) + math.log(0.8) + math.log(0.4) + math.log(0.4)) / 4.0,
            places=12,
        )

    def test_turnover_cost_compounding_and_drawdown_are_exact(self):
        rows = (
            self.row(0, realized=10.0, allocation=1.0),
            self.row(1, realized=-20.0, allocation=1.0),
            self.row(2, realized=5.0, allocation=0.0),
        )
        metrics = evaluate_hierarchical_posteriors(rows, self.config).nodes[0].performance
        self.assertEqual(metrics.sessions, 3)
        self.assertAlmostEqual(metrics.gross_turnover, 2.0)
        self.assertAlmostEqual(metrics.transaction_cost_pp_sum, 1.0)
        self.assertAlmostEqual(metrics.gross_total_return, -0.12)
        self.assertAlmostEqual(metrics.net_total_return, -0.12838)
        self.assertAlmostEqual(metrics.max_drawdown, 0.204)

    def test_emits_root_and_every_hierarchy_prefix(self):
        rows = (
            self.row(0, leaf="AAA", path=("Technology", "Semiconductors", "AAA"), allocation=0.5),
            self.row(0, leaf="BBB", path=("Technology", "Software", "BBB"), allocation=0.5),
        )
        paths = [node.hierarchy_path for node in evaluate_hierarchical_posteriors(rows, self.config).nodes]
        self.assertEqual(paths, [
            (), ("Technology",), ("Technology", "Semiconductors"),
            ("Technology", "Software"), ("Technology", "Semiconductors", "AAA"),
            ("Technology", "Software", "BBB"),
        ])

    def test_rejects_duplicate_incomplete_or_overallocated_panel(self):
        duplicate = self.row(0)
        with self.assertRaisesRegex(LineageError, "duplicate"):
            evaluate_hierarchical_posteriors((duplicate, duplicate), self.config)
        with self.assertRaisesRegex(LineageError, "complete leaf/date panel"):
            evaluate_hierarchical_posteriors((
                self.row(0, leaf="AAA"),
                self.row(0, leaf="BBB", path=("Other", "BBB")),
                self.row(1, leaf="AAA"),
            ), self.config)
        with self.assertRaisesRegex(LineageError, "gross allocation"):
            evaluate_hierarchical_posteriors((
                self.row(0, leaf="AAA", allocation=0.6),
                self.row(0, leaf="BBB", path=("Other", "BBB"), allocation=-0.6),
            ), self.config)

    def test_rejects_invalid_or_nonfinite_posterior_evidence(self):
        invalid_rows = (
            replace(self.row(0), probability_up=float("nan")),
            replace(self.row(0), probability_q05=0.9),
            replace(self.row(0), source_session_date=self.start),
            replace(self.row(0), signed_allocation=1.01),
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(LineageError):
                    evaluate_hierarchical_posteriors((row,), self.config)

    def test_has_no_production_io_or_model_dependency(self):
        source = open("posterior_research_evaluation.py", encoding="utf-8").read().lower()
        for forbidden in ("turso", "sqlite", "read_csv", "read_excel", "pymc", "requests", "pending_orders"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
