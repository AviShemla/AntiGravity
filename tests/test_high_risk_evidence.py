from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.validate_high_risk_evidence import load_registry, validate_bundle

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
REGISTRY = load_registry(Path("governance/high_risk_rule_registry.json"))


def write_artifact(root: Path, name: str, payload: dict) -> dict:
    data = json.dumps(payload, sort_keys=True).encode()
    (root / name).write_bytes(data)
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}


def semantic_value(key: str):
    if key == "service.pid":
        return 4242
    if key == "service.checkpoint_age":
        return 20
    if key in {"source_scan.test_result", "recovery.tests"}:
        return 12
    if key == "recovery.secret_scan":
        return {"actionable_hits": 0}
    if key in {"git.clean", "runtime.hash_match", "snapshot.no_unauthorized_outputs", "model.spec_equivalent", "model.no_leakage", "trading.kill_switch", "trading.risk_gates", "trading.plan_unique", "trading.ledger_reconciled", "recovery.push_readback", "recovery.checkpoint_readback"}:
        return True
    return "verified-value"


def valid_bundle(root: Path) -> dict:
    results = []
    for rule_id, rule in REGISTRY.items():
        evidence = {}
        for index, key in enumerate(rule["required_evidence"]):
            payload = {"rule_id": rule_id, "evidence_key": key, "status": "PASS", "command": f"verify {rule_id} {key}", "exit_code": 0, "observed_at": "2026-08-26T07:59:30Z", "value": semantic_value(key)}
            evidence[key] = {"status": "PASS", "ref": write_artifact(root, f"{len(results)}-{index}.json", payload)}
        result = {"id": rule_id, "checked_at": "2026-08-26T07:59:30Z", "contradictions": [], "evidence": evidence}
        if rule["classification"] == "APPROVAL_GATED":
            result["approval"] = {"scoped": True, "ref": write_artifact(root, "approval.json", {"evidence_type": "approval", "authority": "Avi", "scoped": True})}
        results.append(result)
    return {"rules": results}


class HighRiskEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = valid_bundle(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def errors(self) -> list[str]:
        return validate_bundle(REGISTRY, self.bundle, now=NOW, evidence_root=self.root)

    def test_full_fresh_primary_evidence_passes(self) -> None:
        self.assertEqual(self.errors(), [])

    def test_missing_rule_fails_closed(self) -> None:
        self.bundle["rules"] = self.bundle["rules"][1:]
        self.assertTrue(any("missing enforced rule result" in error for error in self.errors()))

    def test_false_positive_service_active_without_pid_is_blocked(self) -> None:
        service = next(item for item in self.bundle["rules"] if item["id"] == "service.scheduler_liveness")
        item = service["evidence"]["service.pid"]
        item["ref"] = write_artifact(self.root, "bad-pid.json", {"rule_id": "service.scheduler_liveness", "evidence_key": "service.pid", "status": "PASS", "command": "systemctl show", "exit_code": 0, "observed_at": "2026-08-26T07:59:30Z", "value": 0})
        self.assertIn("service.scheduler_liveness: evidence service.pid artifact value fails semantic validation", self.errors())

    def test_false_positive_checkpoint_missing_is_blocked(self) -> None:
        service = next(item for item in self.bundle["rules"] if item["id"] == "service.scheduler_liveness")
        item = service["evidence"]["service.checkpoint"]
        item["ref"] = write_artifact(self.root, "bad-checkpoint.json", {"rule_id": "service.scheduler_liveness", "evidence_key": "service.checkpoint", "status": "PASS", "command": "read checkpoint", "exit_code": 0, "observed_at": "2026-08-26T07:59:30Z", "value": ""})
        self.assertIn("service.scheduler_liveness: evidence service.checkpoint artifact value fails semantic validation", self.errors())

    def test_false_positive_clean_scan_without_test_is_blocked(self) -> None:
        source = next(item for item in self.bundle["rules"] if item["id"] == "production.forbidden_data_sources")
        item = source["evidence"]["source_scan.test_result"]
        item["ref"] = write_artifact(self.root, "no-tests.json", {"rule_id": "production.forbidden_data_sources", "evidence_key": "source_scan.test_result", "status": "PASS", "command": "pytest", "exit_code": 0, "observed_at": "2026-08-26T07:59:30Z", "value": 0})
        self.assertIn("production.forbidden_data_sources: evidence source_scan.test_result artifact value fails semantic validation", self.errors())

    def test_contradiction_blocks_even_when_every_check_passes(self) -> None:
        self.bundle["rules"][0]["contradictions"] = ["readback does not match artifact"]
        self.assertTrue(any("contradictory evidence blocks" in error for error in self.errors()))

    def test_stale_evidence_is_blocked(self) -> None:
        trading = next(item for item in self.bundle["rules"] if item["id"] == "trading.execution_lock")
        trading["checked_at"] = "2026-08-26T07:58:00Z"
        self.assertTrue(any("trading.execution_lock: evidence is stale" in error for error in self.errors()))

    def test_approval_gate_requires_scoped_approval(self) -> None:
        trading = next(item for item in self.bundle["rules"] if item["id"] == "trading.execution_lock")
        del trading["approval"]
        self.assertIn("trading.execution_lock: explicit scoped approval evidence is required", self.errors())

    def test_reference_digest_mismatch_is_blocked(self) -> None:
        first = self.bundle["rules"][0]
        first_key = next(iter(first["evidence"]))
        first["evidence"][first_key]["ref"]["sha256"] = "0" * 64
        self.assertTrue(any("digest mismatch" in error for error in self.errors()))

    def test_reference_path_escape_is_blocked(self) -> None:
        first = self.bundle["rules"][0]
        first_key = next(iter(first["evidence"]))
        first["evidence"][first_key]["ref"]["path"] = "../outside.json"
        self.assertTrue(any("escapes the evidence root" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
