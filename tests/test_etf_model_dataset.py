import unittest
from datetime import date

import numpy as np
import pandas as pd

from etf_model_dataset import build_etf_model_dataset
from model_lineage import LineageError


def market_frame(periods=90):
    dates = pd.bdate_range("2026-04-20", periods=periods)
    index = np.arange(periods, dtype=float)
    return pd.DataFrame(
        {
            "Ticker": "XLK",
            "Date": dates,
            "Daily_Return_%": np.sin(index / 4.0),
            "Volume": 1_000_000 + index * 1_000,
            "Close": 100 + index * 0.2,
            "RSI_14d": 45 + np.sin(index / 5.0) * 10,
            "ADX_14d": 20 + np.cos(index / 7.0) * 3,
            "Plus_DI_14d": 25 + np.sin(index / 6.0),
            "Minus_DI_14d": 20 + np.cos(index / 6.0),
            "ATR_14d": 2 + index * 0.001,
            "Sector_Momentum_Score": np.sin(index / 8.0),
            "VIX_Close": 18 + np.cos(index / 9.0),
            "TNX_Trend_5d": np.sin(index / 10.0),
        }
    )


class ETFModelDatasetTests(unittest.TestCase):
    def test_builds_thirty_session_leakage_safe_dataset(self):
        frame = market_frame()
        source = frame["Date"].iloc[-1].date()
        dataset = build_etf_model_dataset(
            frame, "xlk", source_session_date=source,
            prediction_date=pd.bdate_range(frame["Date"].iloc[-1], periods=2)[-1].date(),
        )
        self.assertEqual(dataset.ticker, "XLK")
        self.assertEqual(dataset.x_train.shape, (30, 9))
        self.assertEqual(dataset.x_predict.shape, (1, 9))
        self.assertTrue(np.isfinite(dataset.x_train).all())
        reconstructed = dataset.x_predict[0] * dataset.train_scale + dataset.train_mean
        self.assertAlmostEqual(reconstructed[0], frame["Daily_Return_%"].iloc[-1])
        self.assertLessEqual(max(dataset.training_dates), source)

    def test_future_observation_fails_closed(self):
        frame = market_frame()
        source = frame["Date"].iloc[-2].date()
        with self.assertRaisesRegex(LineageError, "after the declared source"):
            build_etf_model_dataset(
                frame, "XLK", source_session_date=source,
                prediction_date=frame["Date"].iloc[-1].date(),
            )

    def test_missing_etf_fails_closed(self):
        frame = market_frame()
        source = frame["Date"].iloc[-1].date()
        with self.assertRaisesRegex(LineageError, "absent"):
            build_etf_model_dataset(
                frame, "XLF", source_session_date=source,
                prediction_date=date(2026, 9, 1),
            )

    def test_short_lookback_is_rejected(self):
        frame = market_frame()
        source = frame["Date"].iloc[-1].date()
        with self.assertRaisesRegex(LineageError, "at least 30"):
            build_etf_model_dataset(
                frame, "XLK", source_session_date=source,
                prediction_date=date(2026, 9, 1), lookback_sessions=20,
            )


if __name__ == "__main__":
    unittest.main()
