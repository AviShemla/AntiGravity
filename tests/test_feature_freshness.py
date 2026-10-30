import unittest

import numpy as np
import pandas as pd

from feature_freshness import bounded_forward_fill


class FeatureFreshnessTests(unittest.TestCase):
    def test_daily_feature_expires_after_five_rows(self):
        frame = pd.DataFrame({"VIX_CLOSE": [20.0] + [np.nan] * 6})
        filled = bounded_forward_fill(frame)
        self.assertEqual(filled.loc[5, "VIX_CLOSE"], 20.0)
        self.assertTrue(np.isnan(filled.loc[6, "VIX_CLOSE"]))

    def test_slow_analyst_feature_uses_explicit_longer_limit(self):
        frame = pd.DataFrame({"AAA_UPSIDE": [10.0] + [np.nan] * 10})
        filled = bounded_forward_fill(frame)
        self.assertEqual(filled.loc[10, "AAA_UPSIDE"], 10.0)

    def test_invalid_limits_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            bounded_forward_fill(pd.DataFrame({"x": [1.0]}), default_limit=0)


if __name__ == "__main__":
    unittest.main()
