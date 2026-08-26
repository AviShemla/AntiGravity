#!/usr/bin/env python3
"""Validate a high-risk AntiGravity rule evidence bundle against the registry."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_CLASSIFICATIONS = {"MACHINE_ENFORCED", "EVIDENCE_GATED", "APPROVAL_GATED", "ADVISORY"}


def _when(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1.0" or not isinstance(raw.get("rules"), list):
        raise ValueError("invalid rule registry")
    registry: dict[str, dict[str, Any]] = {}
    required = {"id", "classification", "risk", "exact_verifier", "required_evidence", "freshness_seconds", "blocking_scope", "override_authority", "recovery_action"}
    for rule in raw["rules"]:
        missing = required - rule.keys()
        if missing:
            raise ValueError(f"registry rule missing fields: {sorted(missing)}")
        if rule["id"] in registry:
            raise ValueError(f"duplicate rule id: {rule['id']}")
        if rule["classification"] not in VALID_CLASSIFICATIONS:
            raise ValueError(f"invalid classification for {rule['id']}")
        if not rule["required_evidence"] and rule["classification"] != "ADVISORY":
            raise ValueError(f"enforced rule has no evidence requirements: {rule['id']}")
        registry[rule["id"]] = rule
    return registry


def validate_bundle(registry: dict[str, dict[str, Any]], bundle: Any, *, now: datetime | None = None) -> list[str]:
    if not isinstance(bundle, dict) or not isinstance(bundle.get("rules"), list):
        return ["bundle must contain a rules array"]
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    seen: set[str] = set()
    for result in bundle["rules"]:
        if not isinstance(result, dict):
            errors.append("rule result must be an object")
            continue
        rule_id = result.get("id")
        if rule_id not in registry:
            errors.append(f"unknown rule id: {rule_id!r}")
            continue
        if rule_id in seen:
            errors.append(f"duplicate evidence for rule: {rule_id}")
            continue
        seen.add(rule_id)
        rule = registry[rule_id]
        evidence = result.get("evidence")
        if not isinstance(evidence, dict):
            errors.append(f"{rule_id}: evidence must be an object")
            continue
        contradictions = result.get("contradictions", [])
        if not isinstance(contradictions, list) or any(not isinstance(item, str) or not item.strip() for item in contradictions):
            errors.append(f"{rule_id}: contradictions must be non-empty strings")
        elif contradictions:
            errors.append(f"{rule_id}: contradictory evidence blocks the rule")
        try:
            checked_at = _when(result.get("checked_at"))
        except (ValueError, TypeError):
            errors.append(f"{rule_id}: invalid checked_at")
            continue
        age = (current - checked_at).total_seconds()
        if age < 0 or age > rule["freshness_seconds"]:
            errors.append(f"{rule_id}: evidence is stale or future-dated")
        for key in rule["required_evidence"]:
            item = evidence.get(key)
            if not isinstance(item, dict):
                errors.append(f"{rule_id}: missing evidence {key}")
                continue
            if item.get("status") != "PASS":
                errors.append(f"{rule_id}: evidence {key} is not PASS")
            if not isinstance(item.get("ref"), str) or not item["ref"].strip():
                errors.append(f"{rule_id}: evidence {key} has no primary reference")
        if rule["classification"] == "APPROVAL_GATED":
            approval = result.get("approval")
            if not isinstance(approval, dict) or not approval.get("scoped") or not approval.get("ref"):
                errors.append(f"{rule_id}: explicit scoped approval evidence is required")
    for rule_id, rule in registry.items():
        if rule["classification"] != "ADVISORY" and rule_id not in seen:
            errors.append(f"missing enforced rule result: {rule_id}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--registry", type=Path, default=Path("governance/high_risk_rule_registry.json"))
    args = parser.parse_args()
    try:
        registry = load_registry(args.registry)
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        errors = validate_bundle(registry, bundle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"BLOCKED: {error}", file=sys.stderr)
        return 1
    print(f"VALID: {len(registry)} enforced high-risk rules satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
