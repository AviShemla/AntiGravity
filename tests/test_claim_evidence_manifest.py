from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.validate_claim_evidence_manifest import validate_manifest

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)


def verified_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "claim_id": "provider-fallback-001",
        "claim_text": "Strict provider fallback is fixed and working",
        "state": "VERIFIED",
        "prior_claim_issue": True,
        "artifact": {"identity": "market_data_provider.py", "version": "abc123", "digest": "sha256:123"},
        "behavioral_proof": {"command": "pytest -q tests/test_provider.py", "exit_code": 0, "result": "PASS", "evidence_ref": "evidence/test.log"},
        "regression": {"original_failure_reproduced": True, "repaired_behavior_passed": True, "command": "pytest -q tests/test_provider.py", "evidence_ref": "evidence/regression.log"},
        "runtime": {"applicable": True, "production_path_proven": True, "identity": "ingestion-run/42@abc123", "evidence_ref": "evidence/runtime.json"},
        "independent_readback": {"command": "audit-provider-lineage --run 42", "result": "PASS", "evidence_ref": "evidence/readback.json"},
        "observed_at": "2026-08-26T07:30:00Z",
        "fresh_until": "2026-08-26T09:30:00Z",
        "contradictions": [],
        "collector": {"identity": "independent-verifier", "narrative_is_proof": False},
    }


class ClaimEvidenceManifestTests(unittest.TestCase):
    def test_complete_verified_chain_passes(self) -> None:
        self.assertEqual(validate_manifest(verified_manifest(), now=NOW), [])

    def test_strong_language_without_verified_state_fails(self) -> None:
        manifest = verified_manifest()
        manifest["state"] = "TESTED"
        self.assertIn("strong completion/health language requires state VERIFIED", validate_manifest(manifest, now=NOW))

    def test_incomplete_is_not_false_positive_complete_language(self) -> None:
        manifest = verified_manifest()
        manifest["claim_text"] = "Implementation remains incomplete"
        manifest["state"] = "IMPLEMENTED"
        self.assertEqual(validate_manifest(manifest, now=NOW), [])

    def test_tested_state_requires_behavioral_proof(self) -> None:
        manifest = verified_manifest()
        manifest["claim_text"] = "Provider fallback has test evidence"
        manifest["state"] = "TESTED"
        manifest["behavioral_proof"]["result"] = "NOT_RUN"
        self.assertIn("TESTED requires passing executable behavioral proof", validate_manifest(manifest, now=NOW))

    def test_contradiction_forces_failed_or_unverified(self) -> None:
        manifest = verified_manifest()
        manifest["contradictions"] = ["runtime readback disagrees with test"]
        errors = validate_manifest(manifest, now=NOW)
        self.assertIn("contradictions force state FAILED or UNVERIFIED", errors)
        self.assertIn("VERIFIED claims cannot contain contradictions", errors)

    def test_prior_issue_requires_regression_reproduction(self) -> None:
        manifest = verified_manifest()
        manifest["regression"]["original_failure_reproduced"] = False
        self.assertIn("regression must reproduce the original failure", validate_manifest(manifest, now=NOW))

    def test_applicable_runtime_requires_production_path_proof(self) -> None:
        manifest = verified_manifest()
        manifest["runtime"]["production_path_proven"] = False
        self.assertIn("VERIFIED runtime claim requires production-path proof", validate_manifest(manifest, now=NOW))

    def test_stale_verified_evidence_fails(self) -> None:
        manifest = verified_manifest()
        manifest["fresh_until"] = "2026-08-26T07:59:59Z"
        self.assertIn("VERIFIED evidence is stale", validate_manifest(manifest, now=NOW))

    def test_collector_narrative_cannot_be_proof(self) -> None:
        manifest = verified_manifest()
        manifest["collector"]["narrative_is_proof"] = True
        self.assertIn("collector narrative_is_proof must be false", validate_manifest(manifest, now=NOW))


if __name__ == "__main__":
    unittest.main()
