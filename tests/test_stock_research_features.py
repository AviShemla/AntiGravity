from datetime import date
import unittest

import numpy as np
import pandas as pd

from model_lineage import LineageError
from predictive_screener import (
    FeatureSpec,
    FoldEvaluation,
    MetricSet,
    TickerEvaluation,
)
from stock_research_features import (
    build_market_regime_features,
    summarize_predictive_network,
)


def market_frame(days=45):
    dates = pd.bdate_range("2026-06-22", periods=days)
    rows = []
    for ordinal, (ticker, sector) in enumerate(
        [("AAA", "TECH"), ("BBB", "BANKS"), ("SPY", "BENCHMARK")]
    ):
        for position, session in enumerate(dates):
            direction = 1.0 if (position + ordinal) % 3 else -1.0
            rows.append({
                "Ticker": ticker,
                "Date": session,
                "Sector": sector,
                "Daily_Return_%": direction * (0.2 + ordinal * 0.1),
                "Volume": 1000.0 + ordinal * 50 + position,
                "Close": 100.0 + ordinal + position * 0.2 + direction * 0.05,
                "VIX_Close": 15.0 + position * 0.1,
            })
    return pd.DataFrame(rows), dates


def metrics():
    return MetricSet(accuracy=0.6, brier=0.2, log_loss=0.6, calibration_error=0.05)


def fold(number, edges):
    spec = FeatureSpec(
        depth=len(edges),
        lag_tickers=tuple(edge[0] for edge in edges),
        lag_sessions=tuple(edge[1] for edge in edges),
        technical_features=(),
    )
    return FoldEvaluation(
        fold_number=number,
        train_start_date="2025-01-02",
        train_end_date="2025-12-01",
        test_start_date="2025-12-08",
        test_end_date="2026-01-15",
        purge_sessions=7,
        spec=spec,
        model_metrics=metrics(),
        majority_accuracy=0.51,
        own_lag_metrics=metrics(),
        y_true=(0, 1),
        probabilities=(0.4, 0.6),
        own_lag_probabilities=(0.45, 0.55),
    )


class StockResearchFeatureTests(unittest.TestCase):
    def test_breadth_and_available_volatility_are_point_in_time(self):
        data, dates = market_frame()
        result = build_market_regime_features(
            data, source_session_date=dates[-1].date()
        )
        self.assertEqual(result.frame.index.max(), dates[-1])
        self.assertIn("breadth_advance_fraction", result.frame)
        self.assertIn("breadth_cross_sectional_return_dispersion", result.frame)
        self.assertIn("volatility_vix_acceleration_1d", result.frame)
        self.assertIn("volatility_vix_minus_SPY_realized_20d", result.frame)
        self.assertTrue(np.isfinite(result.frame.iloc[-1]).all())

    def test_term_structure_is_explicitly_unavailable_without_source_series(self):
        data, dates = market_frame()
        result = build_market_regime_features(
            data, source_session_date=dates[-1].date()
        )
        availability = {item.feature_name: item.available for item in result.availability}
        self.assertFalse(availability["VIX9D_Close"])
        self.assertFalse(availability["VIX3M_Close"])
        self.assertNotIn("volatility_vix9d_to_vix_ratio", result.frame)

    def test_term_structure_is_derived_only_from_explicit_series(self):
        data, dates = market_frame()
        data["VIX9D_Close"] = data["VIX_Close"] + 1.0
        data["VIX3M_Close"] = data["VIX_Close"] + 2.0
        result = build_market_regime_features(
            data, source_session_date=dates[-1].date()
        )
        self.assertIn("volatility_vix9d_to_vix_ratio", result.frame)
        self.assertIn("volatility_vix_to_vix3m_ratio", result.frame)

    def test_future_market_row_is_rejected(self):
        data, dates = market_frame()
        with self.assertRaisesRegex(LineageError, "future"):
            build_market_regime_features(
                data, source_session_date=dates[-2].date()
            )

    def test_vix_disagreement_is_rejected(self):
        data, dates = market_frame()
        mask = (data["Ticker"] == "AAA") & (data["Date"] == dates[-1])
        data.loc[mask, "VIX_Close"] += 1.0
        with self.assertRaisesRegex(LineageError, "VIX values disagree"):
            build_market_regime_features(
                data, source_session_date=dates[-1].date()
            )

    def test_predictive_network_reports_fold_stability_and_node_weights(self):
        evaluation = TickerEvaluation(
            ticker="TARGET",
            eligible=False,
            rejection_reasons=("RESEARCH_ONLY",),
            model_metrics=metrics(),
            majority_accuracy=0.51,
            own_lag_metrics=metrics(),
            accuracy_ci_low=0.4,
            accuracy_ci_high=0.7,
            final_spec=None,
            folds=(
                fold(1, (("AAA", 7), ("BBB", 2))),
                fold(2, (("AAA", 7), ("CCC", 5))),
            ),
        )
        summary = summarize_predictive_network([evaluation])
        edge = next(item for item in summary.edges if item.driver_ticker == "AAA")
        self.assertEqual(edge.lag_sessions, 7)
        self.assertEqual(edge.selection_frequency, 1.0)
        aaa = next(item for item in summary.nodes if item.ticker == "AAA")
        target = next(item for item in summary.nodes if item.ticker == "TARGET")
        self.assertEqual(aaa.stable_outgoing_weight, 1.0)
        self.assertEqual(target.stable_incoming_weight, 2.0)


if __name__ == "__main__":
    unittest.main()
