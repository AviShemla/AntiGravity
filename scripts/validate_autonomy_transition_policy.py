#!/usr/bin/env python3
"""Fail closed unless the successor-work autonomy policy is complete."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TRIGGERS = {"BLOCKED", "STALLED", "FAILED", "NO_QUALIFYING_OUTPUT"}
CLASSIFICATIONS = {"SAFE_NOW", "DEPENDENCY_BLOCKED", "APPROVAL_REQUIRED"}
REQUIREMENTS = {
    "enumerate_successors",
    "launch_all_independent_safe_now",
    "parallelize_when_independent",
    "preserve_safety_gates",
    "require_persistent_worker_for_continuity_claim",
    "require_durable_checkpoint_for_long_job",
    "stop_only_when_no_safe_now_remains",
    "report_unlaunched_safe_work_as_incident",
}


def validate_policy(policy: object) -> list[str]:
    if not isinstance(policy, dict):
        return ["policy must be an object"]
    errors = []
    if policy.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if set(policy.get("trigger_states", [])) != TRIGGERS:
        errors.append("trigger_states must contain the complete governed set")
    if set(policy.get("successor_classifications", [])) != CLASSIFICATIONS:
        errors.append("successor_classifications must contain the complete governed set")
    requirements = policy.get("requirements")
    if not isinstance(requirements, dict):
        errors.append("requirements must be an object")
    else:
        if set(requirements) != REQUIREMENTS:
            errors.append("requirements keys must match the governed set")
        for name in REQUIREMENTS:
            if requirements.get(name) is not True:
                errors.append(f"requirement {name} must be true")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "policy", type=Path,
        nargs="?", default=Path("governance/autonomy_transition_policy.json"),
    )
    args = parser.parse_args()
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}")
        return 2
    errors = validate_policy(policy)
    if errors:
        for error in errors:
            print(f"BLOCKED: {error}")
        return 1
    print("VALID: successor-work autonomy transition policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
