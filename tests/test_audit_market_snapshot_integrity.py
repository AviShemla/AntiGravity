import unittest

from scripts.audit_market_snapshot_integrity import evaluate_checks


def passing_evidence():
    return {
        "source_session": "2026-08-24",
        "registry_id": "registry-1",
        "snapshot": {
            "row_count": 1,
            "source_session_date": "2026-08-24",
            "expected_row_count": 100,
            "expected_ticker_count": 2,
            "status": "STAGING",
        },
        "counts": {"row_count": 100, "ticker_count": 2, "null_key_or_sector_rows": 0},
        "ohlcv": {
            "null_rows": 0, "nonpositive_price_rows": 0, "high_violations": 0,
            "low_violations": 0, "negative_volume_rows": 0,
        },
        "features": {
            "null_critical_rows": 0, "negative_indicator_rows": 0,
            "bounded_indicator_violations": 0, "enum_violations": 0,
            "cross_market_nonpositive": 0,
        },
        "latest": {"latest_date": "2026-08-24", "latest_rows": 2, "latest_tickers": 2},
        "lineage": {"invalid_rows": 0, "invalid_providers": 0},
        "feature_tickers_without_lineage": [],
        "extra_lineage_tickers": ["^TNX", "^VIX"],
        "calendar": {"missing_sessions": [], "non_session_dates": []},
        "recent_130_exceptions": [],
        "screening_run_count": 0,
        "primary_key_present": True,
        "available_after_market_close": True,
        "rebuild_code_hash_matches": True,
        "registry": {
            "approved_registry_count": 1,
            "approved_registry_id": "registry-1",
            "missing_tickers": [],
            "unexpected_tickers": [],
        },
    }


class EvaluateChecksTests(unittest.TestCase):
    def test_complete_evidence_passes(self):
        checks = evaluate_checks(passing_evidence())
        self.assertTrue(all(checks.values()))

    def test_missing_recent_session_fails_closed(self):
        evidence = passing_evidence()
        evidence["recent_130_exceptions"] = [{"ticker": "SPY", "session_count": 129}]
        checks = evaluate_checks(evidence)
        self.assertFalse(checks["recent_130_complete"])

    def test_unexpected_lineage_ticker_fails_closed(self):
        evidence = passing_evidence()
        evidence["extra_lineage_tickers"] = ["^TNX", "^VIX", "STALE"]
        checks = evaluate_checks(evidence)
        self.assertFalse(checks["provider_lineage_exact"])

    def test_validated_snapshot_is_not_revalidated(self):
        evidence = passing_evidence()
        evidence["snapshot"]["status"] = "VALIDATED"
        checks = evaluate_checks(evidence)
        self.assertFalse(checks["one_staging_snapshot"])


if __name__ == "__main__":
    unittest.main()
