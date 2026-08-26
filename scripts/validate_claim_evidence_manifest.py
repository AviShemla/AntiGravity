#!/usr/bin/env python3
"""Fail-closed semantic validator for AntiGravity claim evidence manifests."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from scripts.evidence_binding import load_bound_json

STATES = {"DESIGNED", "IMPLEMENTED", "TESTED", "DEPLOYED", "OBSERVED", "VERIFIED", "FAILED", "UNVERIFIED"}
STRONG_TERMS = ("fixed", "handled", "complete", "working", "healthy")


def _timestamp(value: Any, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be an ISO-8601 timestamp")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} must be an ISO-8601 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include a timezone")
        return None
    return parsed.astimezone(timezone.utc)


def _nonempty(mapping: Any, field: str, errors: list[str]) -> None:
    if not isinstance(mapping, dict) or not isinstance(mapping.get(field), str) or not mapping[field].strip():
        errors.append(f"{field} evidence is required")


def _bound(ref: Any, root: Path | None, label: str, errors: list[str]) -> dict[str, Any] | None:
    artifact, error = load_bound_json(ref, root)
    if error:
        errors.append(f"{label}: {error}")
        return None
    return artifact


def validate_manifest(manifest: Any, *, now: datetime | None = None, evidence_root: Path | None = None, schema_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    schema_file = schema_path or Path(__file__).resolve().parents[1] / "schemas" / "claim_evidence_manifest.schema.json"
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        schema_errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda error: list(error.path))
        errors.extend(f"schema: {error.message}" for error in schema_errors)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"schema could not be loaded: {exc}")
    required = {"schema_version", "claim_id", "claim_text", "state", "prior_claim_issue", "artifact", "behavioral_proof", "runtime", "independent_readback", "observed_at", "fresh_until", "contradictions"}
    missing = sorted(required - manifest.keys())
    errors.extend(f"missing required field: {name}" for name in missing)
    if missing:
        return errors
    if manifest["schema_version"] != "1.0":
        errors.append("schema_version must be 1.0")
    state = manifest["state"]
    if state not in STATES:
        errors.append(f"unknown state: {state!r}")
    _nonempty(manifest, "claim_id", errors)
    _nonempty(manifest, "claim_text", errors)
    artifact = manifest["artifact"]
    for field in ("identity", "version", "digest"):
        _nonempty(artifact, field, errors)
    proof = manifest["behavioral_proof"]
    runtime = manifest["runtime"]
    readback = manifest["independent_readback"]
    contradictions = manifest["contradictions"]
    if not isinstance(contradictions, list) or any(not isinstance(item, str) or not item.strip() for item in contradictions):
        errors.append("contradictions must be a list of non-empty strings")
        contradictions = []
    observed = _timestamp(manifest["observed_at"], "observed_at", errors)
    fresh = _timestamp(manifest["fresh_until"], "fresh_until", errors)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed and fresh and fresh < observed:
        errors.append("fresh_until precedes observed_at")
    strong = any(re.search(rf"\b{re.escape(term)}\b", str(manifest["claim_text"]), re.IGNORECASE) for term in STRONG_TERMS)
    verified_chain = state == "VERIFIED" or strong
    if strong and state != "VERIFIED":
        errors.append("strong completion/health language requires state VERIFIED")
    if contradictions and state not in {"FAILED", "UNVERIFIED"}:
        errors.append("contradictions force state FAILED or UNVERIFIED")
    if state in {"TESTED", "DEPLOYED", "OBSERVED"}:
        if not isinstance(proof, dict) or proof.get("result") != "PASS" or proof.get("exit_code") != 0:
            errors.append(f"{state} requires passing executable behavioral proof")
    if state in {"DEPLOYED", "OBSERVED"}:
        if not isinstance(runtime, dict) or not runtime.get("applicable"):
            errors.append(f"{state} requires an applicable runtime/deployment identity")
        else:
            for field in ("identity", "evidence_ref"):
                _nonempty(runtime, field, errors)
    if state == "OBSERVED":
        if not isinstance(readback, dict) or readback.get("result") != "PASS":
            errors.append("OBSERVED requires passing independent readback")
        if fresh and fresh < current:
            errors.append("OBSERVED evidence is stale")
    if verified_chain:
        if contradictions:
            errors.append("VERIFIED claims cannot contain contradictions")
        if not isinstance(proof, dict) or proof.get("result") != "PASS" or proof.get("exit_code") != 0:
            errors.append("VERIFIED requires passing executable behavioral proof")
        _nonempty(proof, "command", errors)
        if not isinstance(readback, dict) or readback.get("result") != "PASS":
            errors.append("VERIFIED requires passing independent readback")
        _nonempty(readback, "command", errors)
        if fresh and fresh < current:
            errors.append("VERIFIED evidence is stale")
        if isinstance(runtime, dict) and runtime.get("applicable"):
            if not runtime.get("production_path_proven"):
                errors.append("VERIFIED runtime claim requires production-path proof")
            _nonempty(runtime, "identity", errors)
    if manifest["prior_claim_issue"]:
        regression = manifest.get("regression")
        if not isinstance(regression, dict):
            errors.append("prior claimed issue requires regression evidence")
        else:
            if regression.get("original_failure_reproduced") is not True:
                errors.append("regression must reproduce the original failure")
            if regression.get("repaired_behavior_passed") is not True:
                errors.append("regression must pass after the repair")
            _nonempty(regression, "command", errors)
    collector = manifest.get("collector")
    if isinstance(collector, dict) and collector.get("narrative_is_proof") is not False:
        errors.append("collector narrative_is_proof must be false")
    if verified_chain:
        bound_proof = _bound(proof.get("evidence_ref") if isinstance(proof, dict) else None, evidence_root, "behavioral_proof", errors)
        if bound_proof and (
            bound_proof.get("evidence_type") != "behavioral_proof"
            or bound_proof.get("command") != proof.get("command")
            or bound_proof.get("exit_code") != proof.get("exit_code")
            or bound_proof.get("result") != proof.get("result")
        ):
            errors.append("behavioral_proof artifact does not match the manifest")
        bound_readback = _bound(readback.get("evidence_ref") if isinstance(readback, dict) else None, evidence_root, "independent_readback", errors)
        if bound_readback and (
            bound_readback.get("evidence_type") != "independent_readback"
            or bound_readback.get("command") != readback.get("command")
            or bound_readback.get("result") != readback.get("result")
        ):
            errors.append("independent_readback artifact does not match the manifest")
        if isinstance(runtime, dict) and runtime.get("applicable"):
            bound_runtime = _bound(runtime.get("evidence_ref"), evidence_root, "runtime", errors)
            if bound_runtime and (
                bound_runtime.get("evidence_type") != "runtime"
                or bound_runtime.get("identity") != runtime.get("identity")
                or bound_runtime.get("production_path_proven") != runtime.get("production_path_proven")
            ):
                errors.append("runtime artifact does not match the manifest")
    if manifest["prior_claim_issue"] and isinstance(manifest.get("regression"), dict):
        regression = manifest["regression"]
        bound_regression = _bound(regression.get("evidence_ref"), evidence_root, "regression", errors)
        if bound_regression and (
            bound_regression.get("evidence_type") != "regression"
            or bound_regression.get("command") != regression.get("command")
            or bound_regression.get("original_failure_reproduced") != regression.get("original_failure_reproduced")
            or bound_regression.get("repaired_behavior_passed") != regression.get("repaired_behavior_passed")
        ):
            errors.append("regression artifact does not match the manifest")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    errors = validate_manifest(manifest, evidence_root=args.evidence_root)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print(f"VALID: {manifest['claim_id']} state={manifest['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
