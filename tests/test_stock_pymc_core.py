import unittest

import numpy as np

from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics
from stock_pymc_core import summarize_stock_posterior


def diagnostics():
    return SamplerDiagnostics(1.01, 500, 300, 0.8, 0, 0.0, 4)


class StockPosteriorSummaryTests(unittest.TestCase):
    def test_uncertainty_and_predictive_risk_are_preserved(self):
        result = summarize_stock_posterior(
            ticker="AAA", x_predict=np.array([[1.0, -1.0]]),
            alpha_direction=np.array([0.0, 0.2, -0.1]),
            beta_direction=np.array([[0.2, 0.1], [0.3, 0.0], [0.1, -0.1]]),
            alpha_return=np.array([0.1, 0.2, 0.0]),
            beta_return=np.array([[0.1, 0.0], [0.2, 0.1], [0.0, -0.1]]),
            return_scale=np.array([0.8, 0.9, 1.0]),
            return_nu=np.array([8.0, 10.0, 12.0]), diagnostics=diagnostics(),
        )
        self.assertGreater(result.probability_up_std, 0)
        self.assertLessEqual(result.probability_up_q05, result.probability_up_mean)
        self.assertGreaterEqual(result.probability_up_q95, result.probability_up_mean)
        self.assertGreater(result.predictive_risk_pp, result.expected_return_pp_std)

    def test_nonfinite_draw_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "non-finite"):
            summarize_stock_posterior(
                ticker="AAA", x_predict=np.array([[1.0]]),
                alpha_direction=np.array([0.0, np.nan]), beta_direction=np.array([[0.2], [0.3]]),
                alpha_return=np.array([0.1, 0.2]), beta_return=np.array([[0.1], [0.2]]),
                return_scale=np.array([0.8, 0.9]), return_nu=np.array([8.0, 10.0]),
                diagnostics=diagnostics(),
            )

    def test_student_t_without_finite_variance_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "nu > 2"):
            summarize_stock_posterior(
                ticker="AAA", x_predict=np.array([[1.0]]),
                alpha_direction=np.array([0.0, 0.1]), beta_direction=np.array([[0.2], [0.3]]),
                alpha_return=np.array([0.1, 0.2]), beta_return=np.array([[0.1], [0.2]]),
                return_scale=np.array([0.8, 0.9]), return_nu=np.array([2.0, 10.0]),
                diagnostics=diagnostics(),
            )


if __name__ == "__main__":
    unittest.main()
