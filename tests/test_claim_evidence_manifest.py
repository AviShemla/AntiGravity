from __future__ import annotations

import hashlib
import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.validate_claim_evidence_manifest import validate_manifest
from scripts.signed_attestation import claim_subject_digest, signing_payload

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)


def write_artifact(root: Path, name: str, payload: dict) -> dict:
    data = json.dumps(payload, sort_keys=True).encode()
    (root / name).write_bytes(data)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}


def verified_manifest(root: Path) -> dict:
    command = "pytest -q tests/test_provider.py"
    readback_command = "audit-provider-lineage --run 42"
    proof_ref = write_artifact(root, "proof.json", {"evidence_type": "behavioral_proof", "command": command, "exit_code": 0, "result": "PASS"})
    regression_ref = write_artifact(root, "regression.json", {"evidence_type": "regression", "command": command, "original_failure_reproduced": True, "repaired_behavior_passed": True})
    runtime_ref = write_artifact(root, "runtime.json", {"evidence_type": "runtime", "identity": "ingestion-run/42@abc123", "production_path_proven": True})
    readback_ref = write_artifact(root, "readback.json", {"evidence_type": "independent_readback", "command": readback_command, "result": "PASS"})
    return {
        "schema_version": "1.0", "claim_id": "provider-fallback-001",
        "claim_text": "Strict provider fallback is fixed and working", "state": "VERIFIED",
        "prior_claim_issue": True,
        "artifact": {"identity": "market_data_provider.py", "version": "abc123", "digest": "sha256:" + "1" * 64},
        "behavioral_proof": {"command": command, "exit_code": 0, "result": "PASS", "evidence_ref": proof_ref},
        "regression": {"original_failure_reproduced": True, "repaired_behavior_passed": True, "command": command, "evidence_ref": regression_ref},
        "runtime": {"applicable": True, "production_path_proven": True, "identity": "ingestion-run/42@abc123", "evidence_ref": runtime_ref},
        "independent_readback": {"command": readback_command, "result": "PASS", "evidence_ref": readback_ref},
        "observed_at": "2026-08-26T07:30:00Z", "fresh_until": "2026-08-26T09:30:00Z",
        "contradictions": [], "collector": {"identity": "independent-verifier", "narrative_is_proof": False},
    }


class ClaimEvidenceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = verified_manifest(self.root)
        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.registry = self.root / "authorities.json"
        self.registry.write_text(json.dumps({
            "schema_version": "1.0",
            "authorities": [{
                "id": "external-test-verifier", "enabled": True,
                "public_key_base64": base64.b64encode(public_key).decode(),
                "allowed_commands": {
                    "provider-production-path-v1": hashlib.sha256(self.manifest["behavioral_proof"]["command"].encode()).hexdigest()
                },
            }],
        }))
        self.ledger = self.root / "used-nonces.jsonl"
        self.sign_manifest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def sign_manifest(self, private_key: Ed25519PrivateKey | None = None) -> None:
        attestation = {
            "verifier_id": "external-test-verifier",
            "command_id": "provider-production-path-v1",
            "command_digest": hashlib.sha256(self.manifest["behavioral_proof"]["command"].encode()).hexdigest(),
            "issued_at": "2026-08-26T07:59:00Z",
            "expires_at": "2026-08-26T08:01:00Z",
            "nonce": "n" * 32,
            "subject_digest": claim_subject_digest(self.manifest),
            "artifact_digest": self.manifest["artifact"]["digest"],
            "runtime_identity": self.manifest["runtime"]["identity"],
        }
        attestation["signature"] = base64.b64encode((private_key or self.private_key).sign(signing_payload(attestation))).decode()
        self.manifest["attestation"] = attestation

    def errors(self, *, consume_nonce: bool = False) -> list[str]:
        return validate_manifest(
            self.manifest, now=NOW, evidence_root=self.root,
            authority_registry=self.registry, nonce_ledger=self.ledger,
            consume_nonce=consume_nonce,
        )

    def test_complete_verified_chain_passes(self) -> None:
        self.assertEqual(self.errors(), [])

    def test_unprovisioned_authority_registry_blocks_verified(self) -> None:
        empty = self.root / "empty-authorities.json"
        empty.write_text('{"schema_version":"1.0","authorities":[]}')
        errors = validate_manifest(
            self.manifest, now=NOW, evidence_root=self.root,
            authority_registry=empty, nonce_ledger=self.ledger,
            consume_nonce=False,
        )
        self.assertIn("verifier is not a unique enabled authority", errors)

    def test_self_signed_untrusted_attestation_fails(self) -> None:
        self.sign_manifest(Ed25519PrivateKey.generate())
        self.assertIn("attestation signature is invalid", self.errors())

    def test_fabricated_signature_fails(self) -> None:
        self.manifest["attestation"]["signature"] = base64.b64encode(b"fabricated").decode()
        self.assertIn("attestation signature is invalid", self.errors())

    def test_attestation_binds_artifact_and_runtime(self) -> None:
        self.manifest["attestation"]["runtime_identity"] = "different-runtime"
        self.manifest["attestation"]["signature"] = base64.b64encode(self.private_key.sign(signing_payload(self.manifest["attestation"]))).decode()
        self.assertIn("attestation does not bind the runtime identity", self.errors())

    def test_attestation_command_must_be_allowlisted(self) -> None:
        self.manifest["attestation"]["command_id"] = "unapproved-command"
        self.manifest["attestation"]["signature"] = base64.b64encode(self.private_key.sign(signing_payload(self.manifest["attestation"]))).decode()
        self.assertIn("attestation command is not allowlisted for this verifier", self.errors())

    def test_attestation_binds_exact_command(self) -> None:
        self.manifest["attestation"]["command_digest"] = "0" * 64
        self.manifest["attestation"]["signature"] = base64.b64encode(self.private_key.sign(signing_payload(self.manifest["attestation"]))).decode()
        self.assertIn("attestation does not bind the exact manifest command", self.errors())

    def test_nonce_not_consumed_when_other_manifest_check_fails(self) -> None:
        self.manifest["contradictions"] = ["known contradiction"]
        self.assertIn("contradictions force state FAILED or UNVERIFIED", self.errors(consume_nonce=True))
        self.manifest["contradictions"] = []
        self.assertEqual(self.errors(consume_nonce=True), [])

    def test_attestation_nonce_replay_is_blocked(self) -> None:
        self.assertEqual(self.errors(consume_nonce=True), [])
        self.assertIn("attestation nonce has already been consumed", self.errors(consume_nonce=True))

    def test_strong_language_without_verified_state_fails(self) -> None:
        self.manifest["state"] = "TESTED"
        self.assertIn("strong completion/health language requires state VERIFIED", self.errors())

    def test_incomplete_is_not_false_positive_complete_language(self) -> None:
        self.manifest["claim_text"] = "Implementation remains incomplete"
        self.manifest["state"] = "IMPLEMENTED"
        self.assertEqual(self.errors(), [])

    def test_tested_state_requires_behavioral_proof(self) -> None:
        self.manifest["claim_text"] = "Provider fallback has test evidence"
        self.manifest["state"] = "TESTED"
        self.manifest["behavioral_proof"]["result"] = "NOT_RUN"
        self.assertIn("TESTED requires passing executable behavioral proof", self.errors())

    def test_contradiction_forces_failed_or_unverified(self) -> None:
        self.manifest["contradictions"] = ["runtime readback disagrees with test"]
        errors = self.errors()
        self.assertIn("contradictions force state FAILED or UNVERIFIED", errors)
        self.assertIn("VERIFIED claims cannot contain contradictions", errors)

    def test_prior_issue_requires_regression_reproduction(self) -> None:
        self.manifest["regression"]["original_failure_reproduced"] = False
        self.assertIn("regression must reproduce the original failure", self.errors())

    def test_applicable_runtime_requires_production_path_proof(self) -> None:
        self.manifest["runtime"]["production_path_proven"] = False
        self.assertIn("VERIFIED runtime claim requires production-path proof", self.errors())

    def test_stale_verified_evidence_fails(self) -> None:
        self.manifest["fresh_until"] = "2026-08-26T07:59:59Z"
        self.assertIn("VERIFIED evidence is stale", self.errors())

    def test_collector_narrative_cannot_be_proof(self) -> None:
        self.manifest["collector"]["narrative_is_proof"] = True
        self.assertIn("collector narrative_is_proof must be false", self.errors())

    def test_nonexistent_reference_fails(self) -> None:
        self.manifest["behavioral_proof"]["evidence_ref"]["path"] = "missing.json"
        self.assertTrue(any("cannot be read" in error for error in self.errors()))

    def test_digest_mismatch_fails(self) -> None:
        self.manifest["behavioral_proof"]["evidence_ref"]["sha256"] = "0" * 64
        self.assertIn("behavioral_proof: evidence ref digest mismatch", self.errors())

    def test_bound_artifact_must_match_manifest(self) -> None:
        self.manifest["behavioral_proof"]["command"] = "echo fabricated"
        self.assertIn("behavioral_proof artifact does not match the manifest", self.errors())

    def test_schema_rejects_additional_property(self) -> None:
        self.manifest["fabricated"] = True
        self.assertTrue(any("Additional properties are not allowed" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
