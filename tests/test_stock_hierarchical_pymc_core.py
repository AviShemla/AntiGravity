import unittest
from datetime import date, timedelta

import numpy as np

from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics
from stock_hierarchical_pymc_core import (
    build_hierarchical_stock_dataset,
    summarize_hierarchical_stock_posteriors,
)
from stock_model_dataset import StockModelDataset


def dataset(ticker, edges, *, bad=False):
    dates = tuple(date(2026, 1, 1) + timedelta(days=i) for i in range(4))
    names = tuple(f"{name}_return_x_volume_ratio_lag{lag}" for name, lag in edges)
    x = np.arange(4 * len(names), dtype=float).reshape(4, len(names))
    if bad:
        x[0, 0] = np.nan
    return StockModelDataset(
        ticker=ticker, source_session_date=date(2026, 1, 4),
        prediction_date=date(2026, 1, 5), feature_names=names,
        training_dates=dates, x_train=x,
        y_direction=np.array([0, 1, 0, 1]),
        y_return_pp=np.array([-1.0, 1.0, -0.5, 0.5]),
        x_predict=np.ones((1, len(names))), train_mean=np.zeros(len(names)),
        train_scale=np.ones(len(names)),
    )


def diagnostics():
    return SamplerDiagnostics(1.01, 500, 300, 0.8, 0, 0.0, 4)


class HierarchicalStockTests(unittest.TestCase):
    def test_variable_depth_and_independent_lags_are_aligned(self):
        result = build_hierarchical_stock_dataset([
            dataset("AAA", [("L1", 7)]),
            dataset("BBB", [("L2", 2), ("L3", 5)]),
        ])
        self.assertEqual(result.x_train.shape, (2, 4, 5))
        self.assertEqual(result.edge_lags, ((7, None, None, None, None), (2, 5, None, None, None)))
        self.assertTrue(np.all(result.x_train[0, :, 1:] == 0))

    def test_lag_above_seven_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "lag 1-7"):
            build_hierarchical_stock_dataset([
                dataset("AAA", [("L1", 8)]), dataset("BBB", [("L2", 2)])
            ])

    def test_unique_multi_target_cohort_is_required(self):
        with self.assertRaisesRegex(LineageError, "two unique"):
            build_hierarchical_stock_dataset([dataset("AAA", [("L1", 1)])])
        with self.assertRaisesRegex(LineageError, "two unique"):
            build_hierarchical_stock_dataset([
                dataset("AAA", [("L1", 1)]), dataset("AAA", [("L2", 2)])
            ])

    def test_nonfinite_inputs_are_rejected(self):
        with self.assertRaisesRegex(LineageError, "non-finite"):
            build_hierarchical_stock_dataset([
                dataset("AAA", [("L1", 1)], bad=True), dataset("BBB", [("L2", 2)])
            ])

    def test_target_specific_posterior_uncertainty_is_preserved(self):
        data = build_hierarchical_stock_dataset([
            dataset("AAA", [("L1", 1)]), dataset("BBB", [("L2", 2), ("L3", 3)])
        ])
        zeros = np.zeros((3, 2, 5))
        results = summarize_hierarchical_stock_posteriors(
            data, alpha_direction=np.array([[0.0, 0.1], [0.2, -0.1], [-0.2, 0.3]]),
            beta_direction=zeros, alpha_return=np.array([[0.0, 0.1], [0.2, -0.1], [-0.1, 0.2]]),
            beta_return=zeros, return_scale=np.ones((3, 2)),
            return_nu=np.array([8.0, 10.0, 12.0]), diagnostics=diagnostics(),
        )
        self.assertEqual(set(results), {"AAA", "BBB"})
        self.assertGreater(results["AAA"].probability_up_std, 0)
        self.assertGreater(results["BBB"].predictive_risk_pp, 0)


if __name__ == "__main__":
    unittest.main()
