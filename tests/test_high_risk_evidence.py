from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.validate_high_risk_evidence import load_registry, validate_bundle

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
REGISTRY = load_registry(Path("governance/high_risk_rule_registry.json"))


def valid_bundle() -> dict:
    results = []
    for rule_id, rule in REGISTRY.items():
        result = {
            "id": rule_id,
            "checked_at": "2026-08-26T07:59:30Z",
            "contradictions": [],
            "evidence": {
                key: {"status": "PASS", "ref": f"evidence/{rule_id}/{key}.json"}
                for key in rule["required_evidence"]
            },
        }
        if rule["classification"] == "APPROVAL_GATED":
            result["approval"] = {"scoped": True, "ref": "approval/avi-001"}
        results.append(result)
    return {"rules": results}


class HighRiskEvidenceTests(unittest.TestCase):
    def test_full_fresh_primary_evidence_passes(self) -> None:
        self.assertEqual(validate_bundle(REGISTRY, valid_bundle(), now=NOW), [])

    def test_missing_rule_fails_closed(self) -> None:
        bundle = valid_bundle()
        bundle["rules"] = bundle["rules"][1:]
        self.assertTrue(any("missing enforced rule result" in error for error in validate_bundle(REGISTRY, bundle, now=NOW)))

    def test_false_positive_service_active_without_pid_is_blocked(self) -> None:
        bundle = valid_bundle()
        service = next(item for item in bundle["rules"] if item["id"] == "service.scheduler_liveness")
        del service["evidence"]["service.pid"]
        self.assertIn("service.scheduler_liveness: missing evidence service.pid", validate_bundle(REGISTRY, bundle, now=NOW))

    def test_false_positive_clean_scan_without_test_is_blocked(self) -> None:
        bundle = valid_bundle()
        source = next(item for item in bundle["rules"] if item["id"] == "production.forbidden_data_sources")
        del source["evidence"]["source_scan.test_result"]
        self.assertIn("production.forbidden_data_sources: missing evidence source_scan.test_result", validate_bundle(REGISTRY, bundle, now=NOW))

    def test_contradiction_blocks_even_when_every_check_passes(self) -> None:
        bundle = valid_bundle()
        bundle["rules"][0]["contradictions"] = ["readback does not match artifact"]
        self.assertTrue(any("contradictory evidence blocks" in error for error in validate_bundle(REGISTRY, bundle, now=NOW)))

    def test_stale_evidence_is_blocked(self) -> None:
        bundle = valid_bundle()
        trading = next(item for item in bundle["rules"] if item["id"] == "trading.execution_lock")
        trading["checked_at"] = "2026-08-26T07:58:00Z"
        self.assertTrue(any("trading.execution_lock: evidence is stale" in error for error in validate_bundle(REGISTRY, bundle, now=NOW)))

    def test_approval_gate_requires_scoped_approval(self) -> None:
        bundle = valid_bundle()
        trading = next(item for item in bundle["rules"] if item["id"] == "trading.execution_lock")
        del trading["approval"]
        self.assertIn("trading.execution_lock: explicit scoped approval evidence is required", validate_bundle(REGISTRY, bundle, now=NOW))


if __name__ == "__main__":
    unittest.main()
