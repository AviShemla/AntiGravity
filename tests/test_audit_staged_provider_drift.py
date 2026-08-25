import unittest

import pandas as pd

from scripts.audit_staged_provider_drift import assess_provider_match


def frame(adjusted_close_delta=0.0, close_delta=0.0):
    return pd.DataFrame({
        "Date": pd.to_datetime(["2026-08-21", "2026-08-24"]),
        "Open": [100.0, 101.0],
        "High": [102.0, 103.0],
        "Low": [99.0, 100.0],
        "Close": [101.0, 102.0 + close_delta],
        "Adj Close": [100.5, 101.5 + adjusted_close_delta],
        "Volume": [1000.0, 1100.0],
        "Dividends": [0.0, 0.0],
        "Stock Splits": [0.0, 0.0],
    })


class AssessProviderMatchTests(unittest.TestCase):
    def test_sub_mill_adjusted_close_serialization_passes(self):
        evidence, passed = assess_provider_match(
            stored_provider="YAHOO_FINANCE",
            fresh_provider="YAHOO_FINANCE",
            staged=frame(),
            fresh=frame(adjusted_close_delta=0.00024),
        )
        self.assertTrue(passed)
        self.assertEqual(evidence["tolerance_failures"], {})

    def test_economically_meaningful_adjusted_close_change_fails(self):
        _, passed = assess_provider_match(
            stored_provider="YAHOO_FINANCE",
            fresh_provider="YAHOO_FINANCE",
            staged=frame(),
            fresh=frame(adjusted_close_delta=0.01),
        )
        self.assertFalse(passed)

    def test_raw_close_change_fails(self):
        _, passed = assess_provider_match(
            stored_provider="YAHOO_FINANCE",
            fresh_provider="YAHOO_FINANCE",
            staged=frame(),
            fresh=frame(close_delta=1e-6),
        )
        self.assertFalse(passed)

    def test_provider_change_fails(self):
        _, passed = assess_provider_match(
            stored_provider="YAHOO_FINANCE",
            fresh_provider="TIINGO_EOD",
            staged=frame(),
            fresh=frame(),
        )
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
