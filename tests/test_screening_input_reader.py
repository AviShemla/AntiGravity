import unittest

import pandas as pd

from screening_input_reader import (
    SCREENING_COLUMNS,
    build_return_matrix,
    build_screening_matrices,
    build_target_features,
)


class ScreeningInputReaderTests(unittest.TestCase):
    def frame(self):
        rows = []
        for ticker in ("AAA", "BBB"):
            for position, day in enumerate(pd.bdate_range("2026-01-01", periods=4)):
                row = {name: None for name in SCREENING_COLUMNS}
                row.update({
                    "ticker": ticker,
                    "date": day,
                    "daily_return_pct": float(position),
                    "daily_stdev": 1.0,
                    "rsi_14d": 50.0,
                    "atr_14d": 2.0,
                    "plus_di_14d": 20.0,
                    "minus_di_14d": 10.0,
                    "adx_14d": 25.0,
                    "ras_signal": "BUY",
                    "analyst_consensus": "Hold",
                    "analyst_upside_pct": 5.0,
                    "sector_momentum_score": 0.2,
                    "sector_regime": "BULL_REGIME",
                    "vix_close": 18.0,
                    "market_fear_level": "Complacency / Calm",
                    "tnx_trend_5d": 0.1,
                })
                rows.append(row)
        return pd.DataFrame(rows)

    def test_builds_cross_stock_returns_but_target_only_technical_features(self):
        returns, features = build_screening_matrices(self.frame(), "AAA")
        self.assertEqual(set(returns.columns), {"AAA", "BBB"})
        self.assertIn("AAA_RSI", features.columns)
        self.assertNotIn("BBB_RSI", features.columns)
        self.assertIn("VIX_CLOSE", features.columns)

    def test_reuses_one_return_matrix_for_multiple_targets(self):
        frame = self.frame()
        returns = build_return_matrix(frame)
        aaa = build_target_features(frame, "AAA", return_index=returns.index)
        bbb = build_target_features(frame, "BBB", return_index=returns.index)
        self.assertEqual(returns.shape, (4, 2))
        self.assertIn("AAA_RSI", aaa.columns)
        self.assertIn("BBB_RSI", bbb.columns)


if __name__ == "__main__":
    unittest.main()
