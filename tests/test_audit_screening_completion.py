import unittest

from scripts.audit_screening_completion import build_completion_checks


class ScreeningCompletionAuditTests(unittest.TestCase):
    def evidence(self):
        return {
            "run": {
                "expected_ticker_count": 10,
                "status": "VALIDATED",
                "snapshot_status": "VALIDATED",
            },
            "config": {
                "outer_folds": 4,
                "eligibility_hypotheses": 10,
                "signal_lookback_sessions": 60,
                "signal_lookback_governance_status": "ENABLED",
                "window_semantics_contract_id": "screening-window-separation-v1-20260825",
                "candidate_lags": [2, 7],
                "lag_horizon_contract_id": "stock-lag-horizon-v1-20260824",
                "horizon_review_interval_sessions": 63,
                "purge_sessions": 7,
            },
            "results": {
                "result_count": 10,
                "distinct_tickers": 10,
                "evaluated_count": 8,
                "eligible_count": 3,
                "metric_missing_count": 0,
                "metric_bounds_violation_count": 0,
            },
            "folds": {
                "fold_count": 32,
                "fold_tickers": 8,
                "min_fold": 1,
                "max_fold": 4,
                "min_purge": 7,
                "max_purge": 7,
                "temporal_overlap_count": 0,
            },
            "downstream": {
                "model_runs": 0,
                "model_scorecards": 0,
                "etf_priors": 0,
            },
        }

    def test_positive_eligible_count_is_not_an_audit_failure(self):
        checks = build_completion_checks(**self.evidence())
        self.assertTrue(all(checks.values()))
        self.assertNotIn("no_eligible_candidates", checks)

    def test_purge_is_checked_against_lag_domain_not_chain_depth(self):
        evidence = self.evidence()
        evidence["config"]["purge_sessions"] = 5
        evidence["folds"]["min_purge"] = 5
        evidence["folds"]["max_purge"] = 5
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["configured_purge_covers_max_candidate_lag"])
        self.assertFalse(checks["fold_purge_covers_max_candidate_lag"])

    def test_invalid_or_duplicate_lag_domain_fails_closed(self):
        evidence = self.evidence()
        evidence["config"]["candidate_lags"] = [2, 2]
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["candidate_lag_domain_valid"])
        self.assertFalse(checks["configured_purge_covers_max_candidate_lag"])
        self.assertFalse(checks["fold_purge_covers_max_candidate_lag"])

    def test_candidate_above_approved_horizon_fails_contract_check(self):
        evidence = self.evidence()
        evidence["config"]["candidate_lags"] = [2, 8]
        evidence["config"]["purge_sessions"] = 8
        evidence["folds"]["min_purge"] = 8
        evidence["folds"]["max_purge"] = 8
        checks = build_completion_checks(**evidence)
        self.assertTrue(checks["candidate_lag_domain_valid"])
        self.assertFalse(checks["approved_lag_horizon_contract_matches"])

    def test_wrong_review_interval_fails_contract_check(self):
        evidence = self.evidence()
        evidence["config"]["horizon_review_interval_sessions"] = 62
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["approved_lag_horizon_contract_matches"])

    def test_missing_or_unknown_window_contract_fails_closed(self):
        evidence = self.evidence()
        evidence["config"]["window_semantics_contract_id"] = "legacy-ambiguous-window"
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["screening_window_contract_matches"])

    def test_governed_30_session_arm_is_explicitly_blocked(self):
        evidence = self.evidence()
        evidence["config"]["signal_lookback_sessions"] = 30
        evidence["config"]["signal_lookback_governance_status"] = (
            "BLOCKED_MIN_50_COMPLETE_PAIRS"
        )
        checks = build_completion_checks(**evidence)
        self.assertTrue(checks["screening_window_contract_matches"])
        self.assertFalse(checks["signal_discovery_capacity_feasible"])

    def test_unapproved_signal_lookback_fails_closed(self):
        evidence = self.evidence()
        evidence["config"]["signal_lookback_sessions"] = 45
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["screening_window_contract_matches"])

    def test_zero_evaluated_tickers_has_vacuous_fold_checks(self):
        evidence = self.evidence()
        evidence["results"]["evaluated_count"] = 0
        evidence["results"]["eligible_count"] = 0
        evidence["folds"].update({
            "fold_count": 0,
            "fold_tickers": 0,
            "min_fold": None,
            "max_fold": None,
            "min_purge": None,
            "max_purge": None,
            "temporal_overlap_count": None,
        })
        checks = build_completion_checks(**evidence)
        self.assertTrue(checks["fold_numbers_complete"])
        self.assertTrue(checks["fold_purge_covers_max_candidate_lag"])
        self.assertTrue(checks["no_temporal_overlap"])

    def test_eligible_count_cannot_exceed_evaluated_count(self):
        evidence = self.evidence()
        evidence["results"]["eligible_count"] = 9
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["eligibility_count_consistent"])

    def test_missing_baseline_metric_fails_completion(self):
        evidence = self.evidence()
        evidence["results"]["metric_missing_count"] = 1
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["evaluated_metrics_and_baselines_complete"])

    def test_out_of_range_probability_metric_fails_completion(self):
        evidence = self.evidence()
        evidence["results"]["metric_bounds_violation_count"] = 1
        checks = build_completion_checks(**evidence)
        self.assertFalse(checks["evaluated_probability_metrics_in_bounds"])


if __name__ == "__main__":
    unittest.main()
