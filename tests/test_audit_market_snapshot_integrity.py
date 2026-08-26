import unittest

from scripts.audit_market_snapshot_integrity import (
    NORMALIZATION_COMMIT,
    REPAIR_BOOLEAN_KEYS,
    evaluate_checks,
    evaluate_creation_lineage,
)


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
        "creation_lineage": {"matches": True},
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


def valid_repair_notes():
    return {
        "repair": "CANONICAL_OHLC_ENVELOPE",
        "supersedes_rejected_snapshot_id": "market_features_2026-08-25_original",
        "supersedes_rejection_event_id": "reject-proof-20260826-original",
        "original_checksum_sha256": "a" * 64,
        "stored_rows_checksum_sha256": "b" * 64,
        "normalization_commit": NORMALIZATION_COMMIT,
        "repair_code_version": "c" * 40,
        "production_approval_id": "avi-approved-repair",
        "provider_lineage_sha256": "d" * 64,
        "validation_state": "STAGING_NOT_VALIDATED",
    }


def valid_repair_evidence():
    return {key: True for key in REPAIR_BOOLEAN_KEYS}


class CreationLineageTests(unittest.TestCase):
    def test_full_rebuild_requires_exact_script_hash(self):
        result = evaluate_creation_lineage(
            {"code_version": "e" * 64}, rebuild_hash="e" * 64, notes={}
        )
        self.assertEqual(result["creation_mode"], "FULL_REBUILD")
        self.assertTrue(result["matches"])

    def test_arbitrary_commit_is_not_accepted_as_full_rebuild(self):
        result = evaluate_creation_lineage(
            {"code_version": "c" * 40}, rebuild_hash="e" * 64, notes={}
        )
        self.assertFalse(result["matches"])

    def test_evidence_linked_repair_accepts_only_complete_contract(self):
        notes = valid_repair_notes()
        result = evaluate_creation_lineage(
            {"code_version": notes["repair_code_version"]},
            rebuild_hash="e" * 64, notes=notes,
            repair_evidence=valid_repair_evidence(),
        )
        self.assertEqual(result["creation_mode"], "EVIDENCE_LINKED_REPAIR")
        self.assertTrue(result["matches"])

    def test_arbitrary_commit_mismatch_fails_repair(self):
        notes = valid_repair_notes()
        evidence = valid_repair_evidence()
        evidence["snapshot_commit_matches_note"] = False
        result = evaluate_creation_lineage(
            {"code_version": "f" * 40}, rebuild_hash="e" * 64, notes=notes,
            repair_evidence=evidence,
        )
        self.assertFalse(result["matches"])

    def test_arbitrary_ancestor_commit_without_repair_tool_fails(self):
        notes = valid_repair_notes()
        notes["repair_code_version"] = "f" * 40
        evidence = valid_repair_evidence()
        evidence["repair_commit_records_tool"] = False
        result = evaluate_creation_lineage(
            {"code_version": notes["repair_code_version"]},
            rebuild_hash="e" * 64, notes=notes, repair_evidence=evidence,
        )
        self.assertFalse(result["matches"])

    def test_unknown_repair_mode_cannot_fall_back_to_rebuild(self):
        result = evaluate_creation_lineage(
            {"code_version": "e" * 64}, rebuild_hash="e" * 64,
            notes={"repair": "UNREVIEWED"},
        )
        self.assertEqual(result["creation_mode"], "INVALID_REPAIR")
        self.assertFalse(result["matches"])

    def test_unrecorded_extra_metadata_fails_repair(self):
        notes = valid_repair_notes()
        notes["unreviewed_override"] = "true"
        result = evaluate_creation_lineage(
            {"code_version": notes["repair_code_version"]},
            rebuild_hash="e" * 64, notes=notes,
            repair_evidence=valid_repair_evidence(),
        )
        self.assertFalse(result["matches"])

    def test_each_immutable_repair_link_fails_closed(self):
        notes = valid_repair_notes()
        for key in REPAIR_BOOLEAN_KEYS:
            with self.subTest(key=key):
                evidence = valid_repair_evidence()
                evidence[key] = False
                result = evaluate_creation_lineage(
                    {"code_version": notes["repair_code_version"]},
                    rebuild_hash="e" * 64, notes=notes,
                    repair_evidence=evidence,
                )
                self.assertFalse(result["matches"])

    def test_mismatched_recorded_hash_fails_repair(self):
        notes = valid_repair_notes()
        notes["stored_rows_checksum_sha256"] = "not-a-sha"
        result = evaluate_creation_lineage(
            {"code_version": notes["repair_code_version"]},
            rebuild_hash="e" * 64, notes=notes,
            repair_evidence=valid_repair_evidence(),
        )
        self.assertFalse(result["matches"])


if __name__ == "__main__":
    unittest.main()
