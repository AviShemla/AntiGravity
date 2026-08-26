import copy
import unittest

from scripts.audit_validated_replacement_snapshot import (
    APPROVAL_ACTOR,
    APPROVAL_AUDIT_HEAD,
    APPROVAL_AUDIT_SHA256,
    APPROVAL_EVIDENCE_ID,
    APPROVAL_EVENT_ID,
    APPROVAL_TIMESTAMP,
    EXPECTED_ROWS,
    EXPECTED_TICKERS,
    FIRST_DATE,
    PROVIDER_LINEAGE_SHA256,
    SCREENING_CODE_VERSION,
    SCREENING_CUTOFF,
    SCREENING_EXPECTATIONS,
    SNAPSHOT_CHECKSUM,
    SNAPSHOT_CODE_VERSION,
    SNAPSHOT_ID,
    SNAPSHOT_PROVIDER,
    SOURCE_SESSION,
    build_lifecycle_checks,
)


def passing_evidence():
    approval_notes = {
        "approval_id": APPROVAL_EVIDENCE_ID,
        "audit_check_count": 17,
        "audit_git_head": APPROVAL_AUDIT_HEAD,
        "audit_sha256": APPROVAL_AUDIT_SHA256,
        "audit_status": "PASS",
        "owner_approval": "Avi explicitly approved validation only",
        "snapshot_checksum_sha256": SNAPSHOT_CHECKSUM,
    }
    screening = []
    for run_id, (window, result_rows, result_tickers, eligible, fold_rows) in SCREENING_EXPECTATIONS.items():
        screening.append({
            "screening_run_id": run_id,
            "market_snapshot_id": SNAPSHOT_ID,
            "source_session_date": SOURCE_SESSION,
            "cutoff_utc": SCREENING_CUTOFF,
            "code_version": SCREENING_CODE_VERSION,
            "status": "VALIDATED",
            "result_rows": result_rows,
            "result_tickers": result_tickers,
            "eligible_count": eligible,
            "fold_rows": fold_rows,
            "config_json": {
                "signal_lookback_sessions": window,
                "training_window_sessions": 289,
                "test_sessions": 30,
                "outer_folds": 4,
                "min_oos_sessions": 120,
                "eligibility_hypotheses": EXPECTED_TICKERS,
                "candidate_lags": [1, 2, 3, 4, 5, 6, 7],
                "model_family": "selected_chain",
                "terminology": "predictive_lead_lag_not_causal_identification",
                "window_semantics_contract_id": "screening-window-separation-v1-20260825",
                "lag_horizon_contract_id": "stock-lag-horizon-v1-20260824",
            },
        })
    return {
        "snapshot": {
            "snapshot_rows": 1,
            "snapshot_id": SNAPSHOT_ID,
            "dataset_type": "MARKET_FEATURES",
            "source_session_date": SOURCE_SESSION,
            "provider": SNAPSHOT_PROVIDER,
            "code_version": SNAPSHOT_CODE_VERSION,
            "expected_row_count": EXPECTED_ROWS,
            "expected_ticker_count": EXPECTED_TICKERS,
            "source_checksum_sha256": SNAPSHOT_CHECKSUM,
            "status": "VALIDATED",
            "validation_notes": {
                "repair": "CANONICAL_OHLC_ENVELOPE",
                "repair_code_version": SNAPSHOT_CODE_VERSION,
                "provider_lineage_sha256": PROVIDER_LINEAGE_SHA256,
                "validation_state": "STAGING_NOT_VALIDATED",
            },
        },
        "counts": {
            "row_count": EXPECTED_ROWS,
            "ticker_count": EXPECTED_TICKERS,
            "first_date": FIRST_DATE,
            "last_date": SOURCE_SESSION,
        },
        "approval_events": [{
            "event_id": APPROVAL_EVENT_ID,
            "snapshot_id": SNAPSHOT_ID,
            "decision": "APPROVED",
            "approved_by": APPROVAL_ACTOR,
            "decided_at_utc": APPROVAL_TIMESTAMP,
            "snapshot_checksum_sha256": SNAPSHOT_CHECKSUM,
            "source_evidence_type": "MANUAL_RESEARCH_REVIEW",
            "source_evidence_id": APPROVAL_EVIDENCE_ID,
            "approval_notes": approval_notes,
            "created_at_utc": APPROVAL_TIMESTAMP,
        }],
        "provider": {
            "lineage_rows": 476,
            "ticker_count": 476,
            "checksum_sha256": PROVIDER_LINEAGE_SHA256,
            "summary": [
                {"provider": "TIINGO_EOD", "ticker_count": 24, "source_rows": 30_528,
                 "requested_min": SOURCE_SESSION, "requested_max": SOURCE_SESSION,
                 "first_min": "2021-08-02", "last_max": SOURCE_SESSION, "checksum_count": 24},
                {"provider": "YAHOO_FINANCE", "ticker_count": 452, "source_rows": 571_051,
                 "requested_min": SOURCE_SESSION, "requested_max": SOURCE_SESSION,
                 "first_min": "2021-08-02", "last_max": SOURCE_SESSION, "checksum_count": 452},
            ],
        },
        "screening_runs": screening,
        "downstream": {"model_runs": 0, "model_scorecards": 0, "etf_priors": 0},
    }


class ValidatedReplacementLifecycleChecksTests(unittest.TestCase):
    def test_exact_validated_lifecycle_passes(self):
        checks = build_lifecycle_checks(passing_evidence())
        self.assertTrue(all(checks.values()), checks)

    def test_staging_state_is_not_accepted_by_validation_audit(self):
        evidence = passing_evidence()
        evidence["snapshot"]["status"] = "STAGING"
        self.assertFalse(build_lifecycle_checks(evidence)["snapshot_is_explicitly_validated"])

    def test_snapshot_checksum_count_and_provider_drift_fail_closed(self):
        mutations = (
            ("snapshot", "source_checksum_sha256", "0" * 64, "snapshot_checksum_and_counts_exact"),
            ("counts", "row_count", EXPECTED_ROWS - 1, "snapshot_checksum_and_counts_exact"),
            ("provider", "checksum_sha256", "0" * 64, "provider_lineage_exact"),
        )
        for group, key, value, check in mutations:
            with self.subTest(group=group, key=key):
                evidence = passing_evidence()
                evidence[group][key] = value
                self.assertFalse(build_lifecycle_checks(evidence)[check])

    def test_approval_must_be_single_validation_only_and_bound(self):
        evidence = passing_evidence()
        evidence["approval_events"].append(copy.deepcopy(evidence["approval_events"][0]))
        checks = build_lifecycle_checks(evidence)
        self.assertFalse(checks["single_validation_only_approval"])
        self.assertFalse(checks["approval_actor_and_evidence_bound"])
        mutations = (
            ("approved_by", "SomeoneElse", "single_validation_only_approval"),
            ("source_evidence_id", "other-evidence", "single_validation_only_approval"),
        )
        for key, value, check in mutations:
            with self.subTest(key=key):
                evidence = passing_evidence()
                evidence["approval_events"][0][key] = value
                self.assertFalse(build_lifecycle_checks(evidence)[check])
        evidence = passing_evidence()
        evidence["approval_events"][0]["approval_notes"]["owner_approval"] = "full production"
        self.assertFalse(build_lifecycle_checks(evidence)["approval_actor_and_evidence_bound"])

    def test_screening_set_counts_and_lineage_are_independent_gates(self):
        evidence = passing_evidence()
        evidence["screening_runs"].pop()
        self.assertFalse(build_lifecycle_checks(evidence)["screening_run_set_exact"])
        evidence = passing_evidence()
        evidence["screening_runs"][0]["result_rows"] -= 1
        self.assertFalse(build_lifecycle_checks(evidence)["screening_counts_exact"])
        evidence = passing_evidence()
        evidence["screening_runs"][0]["market_snapshot_id"] = "different-snapshot"
        self.assertFalse(build_lifecycle_checks(evidence)["screening_lineage_exact"])

    def test_any_model_or_etf_output_fails_closed(self):
        for key in ("model_runs", "model_scorecards", "etf_priors"):
            with self.subTest(key=key):
                evidence = passing_evidence()
                evidence["downstream"][key] = 1
                self.assertFalse(build_lifecycle_checks(evidence)["zero_model_and_etf_outputs"])


if __name__ == "__main__":
    unittest.main()
