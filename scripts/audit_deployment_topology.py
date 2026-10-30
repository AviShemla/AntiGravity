"""Fail-closed Vultr path, unit, permission, and source-topology preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _systemd_properties(unit: str) -> dict[str, str]:
    raw = _run(
        "systemctl", "show", unit, "--no-pager",
        "-p", "LoadState", "-p", "ActiveState", "-p", "UnitFileState",
        "-p", "WorkingDirectory", "-p", "ExecStart",
    )
    return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)


def evaluate_topology(evidence: dict[str, object], operation: str) -> dict[str, bool]:
    checks = {
        "executed_from_canonical_worktree": evidence["cwd"] == evidence["canonical_worktree"],
        "git_root_matches": evidence["git_root"] == evidence["canonical_worktree"],
        "origin_matches": evidence["origin"] == evidence["canonical_origin"],
        "runtime_is_separate_non_git_tree": (
            evidence["runtime_exists"] and not evidence["runtime_has_git"]
        ),
        "python_runtime_exists": evidence["python_runtime_exists"],
        "unit_paths_match_manifest": not evidence["unit_path_failures"],
        "frozen_units_match_policy": not evidence["frozen_unit_failures"],
        "runtime_files_not_world_writable": not evidence["world_writable_runtime_files"],
    }
    if operation in {"deploy", "model-run"}:
        checks["runtime_matches_canonical_commit"] = not evidence["runtime_hash_mismatches"]
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "vultr_deployment_topology.json",
    )
    parser.add_argument(
        "--operation", choices=("audit", "code", "deploy", "model-run"), default="audit"
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    canonical = Path(manifest["canonical_worktree"]).resolve()
    runtime = Path(manifest["runtime_root"]).resolve()

    unit_evidence = {}
    unit_failures = []
    for unit, expected in manifest["units"].items():
        observed = _systemd_properties(unit)
        unit_evidence[unit] = observed
        if observed.get("LoadState") != "loaded":
            unit_failures.append({"unit": unit, "reason": "not_loaded"})
        if observed.get("WorkingDirectory") != expected["working_directory"]:
            unit_failures.append({"unit": unit, "reason": "working_directory"})
        for required in expected["exec_contains"]:
            if required not in observed.get("ExecStart", ""):
                unit_failures.append({"unit": unit, "reason": "exec_start", "missing": required})

    frozen_evidence = {}
    frozen_failures = []
    for unit, expected in manifest["frozen_units"].items():
        observed = _systemd_properties(unit)
        frozen_evidence[unit] = observed
        for key, expected_value in (
            ("ActiveState", expected["active_state"]),
            ("UnitFileState", expected["unit_file_state"]),
        ):
            if observed.get(key) != expected_value:
                frozen_failures.append(
                    {"unit": unit, "property": key, "expected": expected_value,
                     "observed": observed.get(key)}
                )

    mirrors = []
    mismatches = []
    world_writable = []
    for relative in manifest["runtime_mirrors"]:
        source = canonical / relative
        deployed = runtime / relative
        source_hash = _sha256(source)
        runtime_hash = _sha256(deployed)
        mode = deployed.stat().st_mode & 0o777 if deployed.exists() else None
        row = {
            "path": relative,
            "canonical_sha256": source_hash,
            "runtime_sha256": runtime_hash,
            "runtime_mode": f"{mode:03o}" if mode is not None else None,
            "matches": source_hash is not None and source_hash == runtime_hash,
        }
        mirrors.append(row)
        if not row["matches"]:
            mismatches.append(relative)
        if mode is not None and mode & 0o002:
            world_writable.append(relative)

    evidence = {
        "operation": args.operation,
        "cwd": str(Path.cwd().resolve()),
        "canonical_worktree": str(canonical),
        "canonical_origin": manifest["canonical_origin"],
        "git_root": _run("git", "-C", str(canonical), "rev-parse", "--show-toplevel"),
        "git_head": _run("git", "-C", str(canonical), "rev-parse", "HEAD"),
        "origin": _run("git", "-C", str(canonical), "remote", "get-url", "origin"),
        "worktree_status": _run("git", "-C", str(canonical), "status", "--short"),
        "runtime_root": str(runtime),
        "runtime_exists": runtime.is_dir(),
        "runtime_has_git": (runtime / ".git").exists(),
        "python_runtime_exists": Path(manifest["python_runtime"]).is_file(),
        "units": unit_evidence,
        "unit_path_failures": unit_failures,
        "frozen_units": frozen_evidence,
        "frozen_unit_failures": frozen_failures,
        "runtime_mirrors": mirrors,
        "runtime_hash_mismatches": mismatches,
        "world_writable_runtime_files": world_writable,
    }
    checks = evaluate_topology(evidence, args.operation)
    payload = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "evidence": evidence}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
