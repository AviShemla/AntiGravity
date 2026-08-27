"""Read-only audit for the single-owner ingestion successor topology."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence


class TopologyError(ValueError):
    """The unit topology can trigger a missing or duplicate successor."""


ON_SUCCESS_RE = re.compile(r"^\s*OnSuccess\s*=\s*(.*?)\s*$")


def _on_success_targets_text(text: str) -> tuple[str, ...]:
    targets: list[str] = []
    for line in text.splitlines():
        match = ON_SUCCESS_RE.match(line)
        if not match:
            continue
        targets.extend(item for item in match.group(1).split() if item)
    return tuple(targets)


def audit_topology_units(
    units: Mapping[str, str], manifest: Mapping[str, object]
) -> dict[str, object]:
    """Audit an in-memory unit-name-to-content mapping."""

    required = manifest.get("required_transitions")
    if not isinstance(required, list) or not required:
        raise TopologyError("manifest has no required transitions")
    selected = {
        name: text
        for name, text in units.items()
        if Path(name).suffix in {".service", ".target"}
    }
    if not selected:
        raise TopologyError("unit directory contains no auditable units")
    observed: dict[str, list[str]] = {}
    for name in sorted(selected):
        for target in _on_success_targets_text(selected[name]):
            observed.setdefault(target, []).append(name)

    transition_results: list[dict[str, str]] = []
    for index, transition in enumerate(required):
        if not isinstance(transition, Mapping):
            raise TopologyError(f"transition {index} is not an object")
        owner = str(transition.get("owner", ""))
        target = str(transition.get("target", ""))
        if not owner or not target:
            raise TopologyError(f"transition {index} is incomplete")
        owners = observed.get(target, [])
        if owners != [owner]:
            raise TopologyError(
                f"target {target!r} must have exactly owner {owner!r}; observed={owners!r}"
            )
        transition_results.append({"owner": owner, "target": target})

    baseline_target = str(manifest.get("baseline_successor", ""))
    baseline_owner = str(manifest.get("baseline_on_success_owner", ""))
    if not baseline_target or not baseline_owner:
        raise TopologyError("baseline single-owner declaration is incomplete")
    baseline_owners = observed.get(baseline_target, [])
    if baseline_owners != [baseline_owner]:
        raise TopologyError(
            "baseline successor must have exactly one declared OnSuccess owner"
        )
    return {
        "status": "PASS",
        "unit_count": len(selected),
        "transitions": transition_results,
        "baseline_successor": baseline_target,
        "baseline_on_success_owner": baseline_owner,
    }


def audit_topology(unit_dir: Path, manifest: Mapping[str, object]) -> dict[str, object]:
    """Read unit files then invoke the pure topology audit."""

    units = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(unit_dir.glob("*"))
        if path.suffix in {".service", ".target"}
    }
    return audit_topology_units(units, manifest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = audit_topology(args.unit_dir, manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"HANDOFF_TOPOLOGY_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["TopologyError", "audit_topology", "audit_topology_units", "main"]
