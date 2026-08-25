from datetime import date
import unittest

import numpy as np
import pandas as pd

from model_input_reader import StockUniverseEntry
from model_lineage import LineageError
from stock_model_dataset import build_stock_model_dataset
from stock_research_features import build_market_regime_features


def frame(days=90):
    dates = pd.bdate_range("2026-04-20", periods=days)
    rows = []
    for offset, ticker in enumerate(["AAA", "BBB", "CCC"]):
        for i, day in enumerate(dates):
            close = 100 + offset + i * 0.1
            rows.append({
                "Ticker": ticker, "Date": day, "Daily_Return_%": (i % 7) - 3 + offset * 0.1,
                "Volume": 1000 + i * 10 + offset, "Close": close,
                "RSI_14d": 40 + i % 20, "ADX_14d": 20 + i % 10,
                "Plus_DI_14d": 25 + i % 5, "Minus_DI_14d": 18 + i % 3,
                "ATR_14d": 2 + i * 0.001, "Sector_Momentum_Score": 0.1 + i * 0.001,
                "VIX_Close": 15 + i * 0.01, "TNX_Trend_5d": -0.1 + i * 0.001,
            })
    return pd.DataFrame(rows), dates


class StockModelDatasetTests(unittest.TestCase):
    def entry(self):
        return StockUniverseEntry(
            "AAA", 1, 0.6, 2, ("BBB", "CCC"), lag_sessions=(7, 2)
        )

    def test_prediction_uses_completed_source_without_fake_outcome(self):
        data, dates = frame()
        result = build_stock_model_dataset(
            data, self.entry(), source_session_date=dates[-1].date(),
            prediction_date=(dates[-1] + pd.offsets.BDay(1)).date(), lookback_sessions=30,
        )
        self.assertEqual(result.x_train.shape[0], 30)
        self.assertEqual(result.x_predict.shape, (1, len(result.feature_names)))
        self.assertEqual(result.training_dates[-1], dates[-1].date())
        self.assertTrue(np.isfinite(result.x_predict).all())

    def test_lag_chain_is_depth_specific(self):
        data, dates = frame()
        result = build_stock_model_dataset(
            data, self.entry(), source_session_date=dates[-1].date(),
            prediction_date=(dates[-1] + pd.offsets.BDay(1)).date(), lookback_sessions=30,
        )
        self.assertIn("BBB_return_x_volume_ratio_lag7", result.feature_names)
        self.assertIn("CCC_return_x_volume_ratio_lag2", result.feature_names)
        self.assertNotIn("BBB_return_x_volume_ratio_lag1", result.feature_names)

    def test_missing_close_is_rejected_before_atr_ratio(self):
        data, dates = frame()
        data = data.drop(columns=["Close"])
        with self.assertRaisesRegex(LineageError, "Close"):
            build_stock_model_dataset(
                data, self.entry(), source_session_date=dates[-1].date(),
                prediction_date=(dates[-1] + pd.offsets.BDay(1)).date(),
                lookback_sessions=30,
            )

    def test_future_observation_is_rejected(self):
        data, dates = frame()
        with self.assertRaisesRegex(LineageError, "after the declared source"):
            build_stock_model_dataset(
                data, self.entry(), source_session_date=dates[-2].date(),
                prediction_date=dates[-1].date(), lookback_sessions=30,
            )

    def test_missing_chain_ticker_is_rejected(self):
        data, dates = frame()
        data = data[data["Ticker"] != "CCC"]
        with self.assertRaisesRegex(LineageError, "absent"):
            build_stock_model_dataset(
                data, self.entry(), source_session_date=dates[-1].date(),
                prediction_date=(dates[-1] + pd.offsets.BDay(1)).date(), lookback_sessions=30,
            )

    def test_research_features_are_lagged_for_training_and_use_source_for_prediction(self):
        data, dates = frame()
        data["Sector"] = data["Ticker"].map({"AAA": "TECH", "BBB": "BANKS", "CCC": "TECH"})
        research = build_market_regime_features(
            data, source_session_date=dates[-1].date(), benchmark_ticker="AAA"
        ).frame
        required = ("breadth_advance_fraction", "volatility_vix_change_1d")
        result = build_stock_model_dataset(
            data,
            self.entry(),
            source_session_date=dates[-1].date(),
            prediction_date=(dates[-1] + pd.offsets.BDay(1)).date(),
            lookback_sessions=30,
            research_features=research,
            required_research_features=required,
        )
        self.assertIn("research_breadth_advance_fraction_lag1", result.feature_names)
        self.assertIn("research_volatility_vix_change_1d_lag1", result.feature_names)
        self.assertTrue(np.isfinite(result.x_predict).all())

    def test_required_research_feature_is_fail_closed(self):
        data, dates = frame()
        with self.assertRaisesRegex(LineageError, "not supplied"):
            build_stock_model_dataset(
                data,
                self.entry(),
                source_session_date=dates[-1].date(),
                prediction_date=(dates[-1] + pd.offsets.BDay(1)).date(),
                lookback_sessions=30,
                required_research_features=("breadth_advance_fraction",),
            )


if __name__ == "__main__":
    unittest.main()
