import unittest
from datetime import datetime

import pandas as pd

from scripts.audit_alpaca_candidate import compare_frames, frame_checksum


def sample_frame(close=11.0):
    return pd.DataFrame({
        "Date": [datetime(2026, 8, 21)],
        "Open": [10.0],
        "High": [12.0],
        "Low": [9.0],
        "Close": [close],
        "Adj Close": [close],
        "Volume": [100],
    })


class AlpacaCandidateAuditTests(unittest.TestCase):
    def test_checksum_and_comparison_are_stable(self):
        first = sample_frame()
        second = sample_frame()
        self.assertEqual(frame_checksum(first), frame_checksum(second))
        comparison = compare_frames(first, second)
        self.assertTrue(comparison["same_values"])
        self.assertEqual(comparison["checksum_first"], comparison["checksum_second"])

    def test_comparison_detects_changed_value(self):
        comparison = compare_frames(sample_frame(), sample_frame(close=11.1))
        self.assertFalse(comparison["same_values"])
        self.assertNotEqual(comparison["checksum_first"], comparison["checksum_second"])


if __name__ == "__main__":
    unittest.main()
