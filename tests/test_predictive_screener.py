import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from model_lineage import LineageError
from predictive_screener import (
    FeatureSpec,
    MetricSet,
    ScreeningConfig,
    benjamini_hochberg_rejections,
    build_design_matrix,
    discover_feature_spec,
    eligibility_reasons,
    evaluate_ticker,
    expanding_windows,
    score_probabilities,
    signal_discovery_positions,
    wilson_interval,
)


class PredictiveScreenerTests(unittest.TestCase):
    def test_default_chain_depth_search_is_one_through_five(self):
        config = ScreeningConfig()
        self.assertEqual(config.min_depth, 1)
        self.assertEqual(config.max_depth, 5)
        config.validate()

    def test_bh_fdr_uses_the_largest_passing_rank(self):
        accepted = benjamini_hochberg_rejections(
            {"a": 0.001, "b": 0.02, "c": 0.04, "d": 0.20},
            false_discovery_rate=0.05,
        )
        self.assertEqual(accepted, ("a", "b"))

    def test_bh_fdr_rejects_invalid_pvalues(self):
        with self.assertRaisesRegex(LineageError, "invalid p-value"):
            benjamini_hochberg_rejections(
                {"bad": float("nan")}, false_discovery_rate=0.05
            )

    def test_discovery_supports_preregistered_bh_fdr(self):
        rng = np.random.default_rng(101)
        rows = 500
        driver = rng.normal(size=rows)
        target = np.roll(driver, 1) + rng.normal(scale=0.25, size=rows)
        returns = pd.DataFrame(
            {"TARGET": target, "DRIVER": driver, "NOISE": rng.normal(size=rows)}
        )
        spec = discover_feature_spec(
            ticker="TARGET",
            returns=returns,
            technical_features=pd.DataFrame(index=returns.index),
            train_positions=range(400),
            depth=1,
            familywise_alpha=0.05,
            max_technical_features=0,
            selection_method="bh_fdr",
        )
        self.assertIsNotNone(spec)
        self.assertEqual(spec.lag_tickers, ("DRIVER",))

    def test_walk_forward_has_embargo_and_no_overlap(self):
        config = ScreeningConfig(
            min_train_sessions=252,
            test_sessions=25,
            outer_folds=4,
            purge_sessions=5,
            min_oos_sessions=100,
        )
        windows = expanding_windows(pd.RangeIndex(400), config)
        self.assertEqual(len(windows), 4)
        for window in windows:
            self.assertLess(window.train_positions[-1], window.test_positions[0] - 5)
            self.assertTrue(set(window.train_positions).isdisjoint(window.test_positions))

    def test_rolling_walk_forward_uses_only_the_declared_recent_history(self):
        config = ScreeningConfig(
            min_train_sessions=252,
            training_window_sessions=140,
            test_sessions=25,
            outer_folds=4,
            purge_sessions=5,
            min_oos_sessions=100,
        )
        windows = expanding_windows(pd.RangeIndex(400), config)
        for window in windows:
            self.assertEqual(len(window.train_positions), 140)
            self.assertEqual(window.test_positions[0] - window.train_positions[-1], 6)

    def test_nested_inner_fold_capacity_is_rejected_preflight(self):
        config = ScreeningConfig(
            min_train_sessions=126,
            training_window_sessions=126,
            test_sessions=30,
            outer_folds=4,
            purge_sessions=7,
            min_oos_sessions=120,
            max_depth=5,
            candidate_lags=(1, 2, 3, 4, 5),
            min_fit_observations=126,
        )
        with self.assertRaisesRegex(
            LineageError,
            r"126 outer-train - 25 inner-test - 7 purge = 94 fit observations.*131",
        ):
            config.validate()

    def test_nested_inner_fold_capacity_accepts_exact_boundary(self):
        config = ScreeningConfig(
            min_train_sessions=168,
            training_window_sessions=168,
            test_sessions=30,
            outer_folds=4,
            purge_sessions=7,
            min_oos_sessions=120,
            max_depth=5,
            candidate_lags=(1, 2, 3, 4, 5),
            min_fit_observations=126,
        )
        config.validate()

    def test_supported_signal_windows_do_not_reduce_fitted_training(self):
        for signal_window in (30, 60, 126, 252):
            with self.subTest(signal_window=signal_window):
                config = ScreeningConfig(
                    min_train_sessions=289,
                    training_window_sessions=289,
                    signal_lookback_sessions=signal_window,
                    test_sessions=30,
                    outer_folds=2,
                    purge_sessions=7,
                    min_oos_sessions=60,
                    min_fit_observations=126,
                )
                config.validate()
                windows = expanding_windows(pd.RangeIndex(400), config)
                self.assertTrue(all(len(window.train_positions) == 289 for window in windows))

    def test_signal_window_must_fit_wholly_inside_inner_training(self):
        config = ScreeningConfig(
            min_train_sessions=168,
            training_window_sessions=168,
            signal_lookback_sessions=252,
            test_sessions=30,
            outer_folds=2,
            purge_sessions=7,
            min_oos_sessions=60,
            min_fit_observations=126,
        )
        with self.assertRaisesRegex(
            LineageError,
            "131 inner-fit observations are available but 252 signal sessions",
        ):
            config.validate()

    def test_unsupported_signal_window_is_rejected(self):
        config = ScreeningConfig(signal_lookback_sessions=45)
        with self.assertRaisesRegex(LineageError, "Signal lookback must be one of"):
            config.validate()

    def test_signal_discovery_positions_are_recent_and_exact(self):
        positions = signal_discovery_positions(range(100, 300), 30)
        np.testing.assert_array_equal(positions, np.arange(270, 300))

    def test_signal_discovery_positions_never_silently_truncate(self):
        with self.assertRaisesRegex(LineageError, "Only 29 discovery observations"):
            signal_discovery_positions(range(29), 30)

    def test_rolling_window_shorter_than_126_sessions_is_rejected(self):
        config = ScreeningConfig(
            min_train_sessions=126,
            training_window_sessions=60,
            test_sessions=25,
            outer_folds=4,
            min_oos_sessions=100,
        )
        with self.assertRaisesRegex(LineageError, "at least 126"):
            config.validate()

    def test_rejects_purge_shorter_than_max_lag(self):
        config = ScreeningConfig(purge_sessions=4)
        with self.assertRaisesRegex(LineageError, "Purge"):
            config.validate()

    def test_discovery_uses_only_supplied_training_positions(self):
        rng = np.random.default_rng(7)
        rows = 700
        driver = rng.normal(size=rows)
        target = np.roll(driver, 1) + rng.normal(scale=0.05, size=rows)
        returns = pd.DataFrame({"TARGET": target, "DRIVER": driver, "NOISE": rng.normal(size=rows)})
        technical = pd.DataFrame(index=returns.index)
        spec = discover_feature_spec(
            ticker="TARGET",
            returns=returns,
            technical_features=technical,
            train_positions=range(500),
            depth=1,
            familywise_alpha=0.01,
            max_technical_features=0,
        )
        self.assertIsNotNone(spec)
        self.assertEqual(spec.lag_tickers[0], "DRIVER")

        # Destroy the held-out relationship. A training-only selector must not change.
        mutated = returns.copy()
        mutated.loc[500:, "NOISE"] = mutated.loc[500:, "TARGET"].shift(-1)
        mutated_spec = discover_feature_spec(
            ticker="TARGET",
            returns=mutated,
            technical_features=technical,
            train_positions=range(500),
            depth=1,
            familywise_alpha=0.01,
            max_technical_features=0,
        )
        self.assertEqual(mutated_spec, spec)

    def test_discovery_supports_independent_nonconsecutive_target_relative_lags(self):
        rng = np.random.default_rng(303)
        rows = 700
        driver_a = rng.normal(size=rows)
        driver_b = rng.normal(size=rows)
        target = (
            1.8 * np.roll(driver_a, 7)
            + 1.4 * np.roll(driver_b, 2)
            + rng.normal(scale=0.20, size=rows)
        )
        returns = pd.DataFrame(
            {"TARGET": target, "A": driver_a, "B": driver_b}
        )
        spec = discover_feature_spec(
            ticker="TARGET",
            returns=returns,
            technical_features=pd.DataFrame(index=returns.index),
            train_positions=range(600),
            depth=2,
            familywise_alpha=0.01,
            max_technical_features=0,
            candidate_lags=(2, 7),
        )
        self.assertIsNotNone(spec)
        self.assertEqual(
            set(zip(spec.lag_tickers, spec.lag_sessions)),
            {("A", 7), ("B", 2)},
        )

    def test_bonferroni_family_is_not_weakened_after_first_selection(self):
        rng = np.random.default_rng(404)
        rows = 700
        strong = rng.normal(size=rows)
        medium = rng.normal(size=rows)
        target = np.roll(strong, 1) + 0.35 * np.roll(medium, 1)
        returns = pd.DataFrame(
            {"TARGET": target, "STRONG": strong, "MEDIUM": medium}
        )

        def controlled_pvalue(correlation, _samples):
            effect = abs(correlation)
            if effect > 0.80:
                return 0.001
            if effect > 0.20:
                return 0.020
            return 1.0

        with patch(
            "predictive_screener._normal_two_sided_pvalue_from_correlation",
            side_effect=controlled_pvalue,
        ):
            spec = discover_feature_spec(
                ticker="TARGET",
                returns=returns,
                technical_features=pd.DataFrame(index=returns.index),
                train_positions=range(600),
                depth=2,
                familywise_alpha=0.05,
                max_technical_features=0,
                candidate_lags=(1,),
            )
        # Three preregistered lag hypotheses imply alpha/3. The medium edge
        # (p=.02) must remain rejected after the strong edge is selected.
        self.assertIsNone(spec)

    def test_technical_selection_uses_the_same_lag_one_as_the_model(self):
        rng = np.random.default_rng(505)
        rows = 700
        driver = rng.normal(size=rows)
        contemporaneous_only = rng.normal(size=rows)
        target = (
            1.4 * np.roll(driver, 1)
            + 1.8 * contemporaneous_only
            + rng.normal(scale=0.15, size=rows)
        )
        returns = pd.DataFrame({"TARGET": target, "DRIVER": driver})
        technical = pd.DataFrame({"LEAKY_IF_UNSHIFTED": contemporaneous_only})
        spec = discover_feature_spec(
            ticker="TARGET",
            returns=returns,
            technical_features=technical,
            train_positions=range(600),
            depth=1,
            familywise_alpha=0.01,
            max_technical_features=1,
            candidate_lags=(1,),
        )
        self.assertIsNotNone(spec)
        self.assertEqual(spec.lag_tickers, ("DRIVER",))
        self.assertEqual(spec.technical_features, ())

    def test_feature_spec_rejects_mismatched_lag_sessions(self):
        with self.assertRaisesRegex(LineageError, "must agree"):
            FeatureSpec(
                depth=2,
                lag_tickers=("A", "B"),
                lag_sessions=(7,),
                technical_features=(),
            )

    def test_design_matrix_respects_lag_depth(self):
        returns = pd.DataFrame({"T": [1, 2, 3, 4], "A": [10, 11, 12, 13], "B": [20, 21, 22, 23]})
        technical = pd.DataFrame({"T_RSI": [30, 31, 32, 33]})
        spec = FeatureSpec(
            2, ("A", "B"), ("T_RSI",), lag_sessions=(3, 1)
        )
        X, y = build_design_matrix(ticker="T", returns=returns, technical_features=technical, spec=spec)
        self.assertTrue(pd.isna(X.loc[2, "return__A__lag3"]))
        self.assertEqual(X.loc[2, "return__B__lag1"], 21)
        self.assertEqual(X.loc[2, "technical__T_RSI__lag1"], 31)
        self.assertEqual(y.tolist(), [1.0, 1.0, 1.0, 1.0])

    def test_metrics_and_wilson_interval(self):
        metrics = score_probabilities([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
        self.assertEqual(metrics.accuracy, 1.0)
        self.assertLess(metrics.brier, 0.03)
        low, high = wilson_interval(80, 100)
        self.assertLess(low, 0.8)
        self.assertGreater(high, 0.8)

    def test_eligibility_is_fail_closed(self):
        config = ScreeningConfig(
            min_train_sessions=252,
            test_sessions=50,
            outer_folds=4,
            purge_sessions=5,
            min_oos_sessions=200,
        )
        model = MetricSet(0.60, 0.22, 0.64, 0.08)
        baseline = MetricSet(0.57, 0.24, 0.68, 0.07)
        reasons = eligibility_reasons(
            oos_sessions=200,
            successes=120,
            model=model,
            majority_accuracy=0.55,
            own_lag=baseline,
            config=config,
        )
        self.assertIn("ACCURACY_CI_DOES_NOT_BEAT_MAJORITY", reasons)

    def test_universe_search_uses_stricter_familywise_interval(self):
        model = MetricSet(0.65, 0.20, 0.60, 0.05)
        baseline = MetricSet(0.52, 0.25, 0.70, 0.05)
        single = ScreeningConfig(
            min_train_sessions=252,
            test_sessions=50,
            outer_folds=4,
            purge_sessions=5,
            min_oos_sessions=200,
            eligibility_hypotheses=1,
        )
        universe = ScreeningConfig(
            min_train_sessions=252,
            test_sessions=50,
            outer_folds=4,
            purge_sessions=5,
            min_oos_sessions=200,
            eligibility_hypotheses=459,
        )
        single_reasons = eligibility_reasons(
            oos_sessions=200,
            successes=130,
            model=model,
            majority_accuracy=0.52,
            own_lag=baseline,
            config=single,
        )
        universe_reasons = eligibility_reasons(
            oos_sessions=200,
            successes=130,
            model=model,
            majority_accuracy=0.52,
            own_lag=baseline,
            config=universe,
        )
        self.assertNotIn("ACCURACY_CI_DOES_NOT_BEAT_MAJORITY", single_reasons)
        self.assertIn("ACCURACY_CI_DOES_NOT_BEAT_MAJORITY", universe_reasons)

    def test_nested_evaluation_has_outer_fold_evidence(self):
        rng = np.random.default_rng(19)
        rows = 620
        driver = rng.normal(size=rows)
        target = 1.2 * np.roll(driver, 1) + rng.normal(scale=0.35, size=rows)
        returns = pd.DataFrame(
            {
                "TARGET": target,
                "DRIVER": driver,
                "A": np.roll(driver, 1) + rng.normal(scale=0.2, size=rows),
                "B": np.roll(driver, 1) + rng.normal(scale=0.2, size=rows),
            },
            index=pd.bdate_range("2024-01-01", periods=rows),
        )
        technical = pd.DataFrame(index=returns.index)
        config = ScreeningConfig(
            min_train_sessions=300,
            test_sessions=40,
            outer_folds=4,
            purge_sessions=5,
            min_oos_sessions=160,
            min_depth=1,
            max_depth=1,
            max_technical_features=0,
            familywise_alpha=0.01,
        )
        result = evaluate_ticker(
            ticker="TARGET",
            returns=returns,
            technical_features=technical,
            config=config,
        )
        self.assertEqual(len(result.folds), 4)
        self.assertEqual(sum(len(fold.y_true) for fold in result.folds), 160)
        self.assertGreater(result.model_metrics.accuracy, 0.75)
        self.assertIsNotNone(result.final_spec)

    def test_fixed_spec_is_reused_without_outer_feature_selection(self):
        rng = np.random.default_rng(31)
        rows = 420
        driver = rng.normal(size=rows)
        target = 1.1 * np.roll(driver, 1) + rng.normal(scale=0.45, size=rows)
        index = pd.bdate_range("2024-01-01", periods=rows)
        returns = pd.DataFrame({"TARGET": target, "DRIVER": driver}, index=index)
        technical = pd.DataFrame({"DRIVER_LAG_SOURCE": driver}, index=index)
        config = ScreeningConfig(
            min_train_sessions=252,
            training_window_sessions=252,
            test_sessions=30,
            outer_folds=4,
            purge_sessions=5,
            min_oos_sessions=120,
            min_depth=1,
            max_depth=1,
            max_technical_features=0,
        )
        fixed = FeatureSpec(
            depth=1,
            lag_tickers=("TARGET",),
            technical_features=("DRIVER_LAG_SOURCE",),
        )
        result = evaluate_ticker(
            ticker="TARGET",
            returns=returns,
            technical_features=technical,
            config=config,
            fixed_spec=fixed,
        )
        self.assertEqual(result.final_spec, fixed)
        self.assertTrue(all(fold.spec == fixed for fold in result.folds))
        self.assertGreater(result.model_metrics.accuracy, 0.70)

    def test_fixed_spec_fails_closed_when_a_column_is_missing(self):
        index = pd.bdate_range("2024-01-01", periods=400)
        returns = pd.DataFrame({"TARGET": np.linspace(-1, 1, 400)}, index=index)
        technical = pd.DataFrame(index=index)
        fixed = FeatureSpec(1, ("TARGET",), ("MISSING",))
        with self.assertRaisesRegex(LineageError, "MISSING"):
            evaluate_ticker(
                ticker="TARGET",
                returns=returns,
                technical_features=technical,
                config=ScreeningConfig(
                    min_train_sessions=252,
                    test_sessions=30,
                    outer_folds=4,
                    min_oos_sessions=120,
                ),
                fixed_spec=fixed,
            )


if __name__ == "__main__":
    unittest.main()
