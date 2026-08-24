from datetime import date
import unittest

import numpy as np
import pandas as pd

from model_input_reader import StockUniverseEntry
from model_lineage import LineageError
from stock_model_dataset import build_stock_model_dataset


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
        return StockUniverseEntry("AAA", 1, 0.6, 2, ("BBB", "CCC"))

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
        self.assertIn("BBB_return_x_volume_ratio_lag1", result.feature_names)
        self.assertIn("CCC_return_x_volume_ratio_lag2", result.feature_names)

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


if __name__ == "__main__":
    unittest.main()
