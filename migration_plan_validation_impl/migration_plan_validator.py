"""Fail-closed validator for a machine-readable Codex Oracle migration plan.

The validator deliberately does not execute plan actions.  It proves that a
plan contains the minimum graph, evidence, safety, liveness, recovery, and
ownership information needed by a separate orchestrator.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_VERSION = "codex-oracle-migration-plan/v1"
TARGET_ARCHITECTURE = "CODEX_CONTROLLED_TURSO_BACKED_ORACLE"
EVIDENCE_STAGES = (
    "DESIGNED",
    "IMPLEMENTED",
    "TESTED",
    "DEPLOYED",
    "OBSERVED",
    "VERIFIED",
)
ACTION_CLASSES = {"SAFE_NOW", "DEPENDENCY_BLOCKED", "APPROVAL_REQUIRED"}
TRANSITION_EVENTS = ("on_success", "on_failure", "on_stalled")
EVIDENCE_GATES = ("test", "observe", "readback")
BASE_SUCCESSOR_CHECKS = frozenset(
    {"evidence_preserved", "no_duplicate_writer", "safety_invariants_hold"}
)
SUCCESS_COMPLETION_CHECK = "completion_independently_read_back"

FORBIDDEN_AUTOMATIC_CAPABILITIES = frozenset(
    {
        "TRADING",
        "RECOMMENDATION_CREATION",
        "ORDER_CREATION",
        "EMAIL_SEND",
        "SNIPER_ACTIVATION",
        "SNAPSHOT_VALIDATION",
        "SNAPSHOT_PROMOTION",
        "PRODUCTION_SCHEMA_APPLICATION",
        "SAFEGUARD_WEAKENING",
    }
)
REQUIRED_DISABLED_SERVICES = {
    "ag-sniper.service",
    "antigravity-nightly.timer",
    "antigravity-qa-watchdog.timer",
}
FORBIDDEN_PRODUCTION_SOURCES = frozenset(
    {"CSV", "EXCEL", "SQLITE", "STREAMLIT"}
)
ALLOWED_SOURCE_KINDS = frozenset({"TURSO", "ISOLATED_FIXTURE"})


@dataclass(frozen=True, order=True)
class ValidationIssue:
    """One deterministic validation failure."""

    path: str
    code: str
    message: str


class PlanValidationError(ValueError):
    """Raised by :func:`assert_valid_plan` when validation fails."""

    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues = tuple(issues)
        details = "; ".join(
            f"{issue.path} [{issue.code}] {issue.message}" for issue in self.issues
        )
        super().__init__(f"invalid Codex Oracle migration plan: {details}")


class _Collector:
    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add(self, path: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, code, message))

    def require_keys(
        self, value: Any, keys: Iterable[str], path: str
    ) -> Mapping[str, Any] | None:
        if not isinstance(value, Mapping):
            self.add(path, "TYPE", "must be an object")
            return None
        for key in keys:
            if key not in value:
                self.add(f"{path}.{key}", "REQUIRED", "field is required")
        return value


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_nonempty_string(item) for item in value)


def _validate_action(
    action: Any,
    path: str,
    collector: _Collector,
    *,
    automatic_context: bool,
) -> None:
    obj = collector.require_keys(
        action,
        ("id", "capability", "description", "automatic", "approval_ref"),
        path,
    )
    if obj is None:
        return
    for key in ("id", "capability", "description"):
        if key in obj and not _nonempty_string(obj[key]):
            collector.add(f"{path}.{key}", "TYPE", "must be a non-empty string")
    if "automatic" in obj and not isinstance(obj["automatic"], bool):
        collector.add(f"{path}.automatic", "TYPE", "must be boolean")
    capability = obj.get("capability")
    is_automatic = obj.get("automatic") is True or automatic_context
    if capability in FORBIDDEN_AUTOMATIC_CAPABILITIES and is_automatic:
        collector.add(
            f"{path}.capability",
            "UNSAFE_AUTOMATION",
            f"{capability} may never be automatic",
        )
    approval_ref = obj.get("approval_ref")
    if capability in FORBIDDEN_AUTOMATIC_CAPABILITIES:
        if not _nonempty_string(approval_ref):
            collector.add(
                f"{path}.approval_ref",
                "APPROVAL_REQUIRED",
                "unsafe capability requires an explicit scoped approval reference",
            )
    elif approval_ref is not None and not _nonempty_string(approval_ref):
        collector.add(
            f"{path}.approval_ref", "TYPE", "must be null or a non-empty string"
        )


def _validate_action_list(
    value: Any,
    path: str,
    collector: _Collector,
    *,
    automatic_context: bool,
    require_nonempty: bool = True,
) -> None:
    if not isinstance(value, list):
        collector.add(path, "TYPE", "must be an array")
        return
    if require_nonempty and not value:
        collector.add(path, "EMPTY", "must contain at least one action")
    seen: set[str] = set()
    for index, action in enumerate(value):
        action_path = f"{path}[{index}]"
        _validate_action(
            action, action_path, collector, automatic_context=automatic_context
        )
        if isinstance(action, Mapping) and _nonempty_string(action.get("id")):
            action_id = action["id"]
            if action_id in seen:
                collector.add(f"{action_path}.id", "DUPLICATE", "action ID is repeated")
            seen.add(action_id)


def _validate_progress(value: Any, path: str, collector: _Collector) -> None:
    obj = collector.require_keys(value, ("numerator", "denominator", "unit"), path)
    if obj is None:
        return
    numerator = obj.get("numerator")
    denominator = obj.get("denominator")
    if isinstance(numerator, bool) or not isinstance(numerator, int):
        collector.add(f"{path}.numerator", "TYPE", "must be an integer")
    if isinstance(denominator, bool) or not isinstance(denominator, int):
        collector.add(f"{path}.denominator", "TYPE", "must be an integer")
    if isinstance(numerator, int) and not isinstance(numerator, bool) and numerator < 0:
        collector.add(f"{path}.numerator", "RANGE", "must be non-negative")
    if (
        isinstance(denominator, int)
        and not isinstance(denominator, bool)
        and denominator <= 0
    ):
        collector.add(f"{path}.denominator", "RANGE", "must be greater than zero")
    if (
        isinstance(numerator, int)
        and not isinstance(numerator, bool)
        and isinstance(denominator, int)
        and not isinstance(denominator, bool)
        and denominator > 0
        and numerator > denominator
    ):
        collector.add(path, "RANGE", "numerator cannot exceed denominator")
    if not _nonempty_string(obj.get("unit")):
        collector.add(f"{path}.unit", "TYPE", "must be a non-empty string")


def _validate_gate(
    value: Any, path: str, collector: _Collector
) -> Mapping[str, Any] | None:
    obj = collector.require_keys(
        value, ("required", "satisfied", "evidence_refs"), path
    )
    if obj is None:
        return None
    for key in ("required", "satisfied"):
        if key in obj and not isinstance(obj[key], bool):
            collector.add(f"{path}.{key}", "TYPE", "must be boolean")
    refs = obj.get("evidence_refs")
    if not _string_list(refs):
        collector.add(f"{path}.evidence_refs", "TYPE", "must be string array")
    if obj.get("satisfied") is True and not refs:
        collector.add(
            f"{path}.evidence_refs",
            "EVIDENCE_MISSING",
            "a satisfied gate needs at least one evidence reference",
        )
    if obj.get("required") is False:
        collector.add(path, "GATE_WEAKENED", "all evidence gates must be required")
    return obj


def _validate_data_sources(value: Any, path: str, collector: _Collector) -> None:
    if not isinstance(value, list) or not value:
        collector.add(path, "TYPE", "must be a non-empty array")
        return
    for index, source in enumerate(value):
        source_path = f"{path}[{index}]"
        obj = collector.require_keys(source, ("kind", "scope"), source_path)
        if obj is None:
            continue
        kind = obj.get("kind")
        scope = obj.get("scope")
        if kind not in ALLOWED_SOURCE_KINDS:
            collector.add(
                f"{source_path}.kind",
                "SOURCE_FORBIDDEN",
                "only TURSO or ISOLATED_FIXTURE is allowed",
            )
        if scope not in {"PRODUCTION", "RESEARCH", "ISOLATED_TEST"}:
            collector.add(f"{source_path}.scope", "ENUM", "invalid source scope")
        if scope in {"PRODUCTION", "RESEARCH"} and kind != "TURSO":
            collector.add(
                source_path,
                "TURSO_REQUIRED",
                "production and research data must use Turso",
            )
        if kind == "ISOLATED_FIXTURE" and scope != "ISOLATED_TEST":
            collector.add(
                source_path,
                "FIXTURE_SCOPE",
                "fixtures are allowed only for isolated tests",
            )


def _validate_filesystem_boundary(value: Any, path: str, collector: _Collector) -> None:
    obj = collector.require_keys(
        value,
        (
            "allowed_write_roots",
            "resolved_targets_verified",
            "broad_recursive_actions_forbidden",
        ),
        path,
    )
    if obj is None:
        return
    roots = obj.get("allowed_write_roots")
    if not _string_list(roots) or not roots:
        collector.add(
            f"{path}.allowed_write_roots",
            "TYPE",
            "must be a non-empty string array",
        )
    elif len(set(roots)) != len(roots):
        collector.add(
            f"{path}.allowed_write_roots", "DUPLICATE", "write root repeated"
        )
    for key in ("resolved_targets_verified", "broad_recursive_actions_forbidden"):
        if obj.get(key) is not True:
            collector.add(f"{path}.{key}", "REQUIRED_TRUE", "must be true")


def _validate_recovery(value: Any, path: str, collector: _Collector) -> None:
    obj = collector.require_keys(
        value,
        (
            "max_checkpoint_age_seconds",
            "progress_marker",
            "stalled_state",
            "preserve_evidence",
            "prevent_duplicate_retry",
            "resume_from_checkpoint",
            "actions",
        ),
        path,
    )
    if obj is None:
        return
    max_age = obj.get("max_checkpoint_age_seconds")
    if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age <= 0:
        collector.add(
            f"{path}.max_checkpoint_age_seconds",
            "RANGE",
            "must be a positive integer",
        )
    if not _nonempty_string(obj.get("progress_marker")):
        collector.add(f"{path}.progress_marker", "TYPE", "must be non-empty")
    if obj.get("stalled_state") != "STALLED":
        collector.add(
            f"{path}.stalled_state",
            "ENUM",
            "stale progress must classify as STALLED",
        )
    for key in ("preserve_evidence", "prevent_duplicate_retry", "resume_from_checkpoint"):
        if obj.get(key) is not True:
            collector.add(f"{path}.{key}", "REQUIRED_TRUE", "must be true")
    _validate_action_list(
        obj.get("actions"),
        f"{path}.actions",
        collector,
        automatic_context=True,
    )


def _validate_successor_gate(
    value: Any,
    path: str,
    collector: _Collector,
    *,
    event: str,
) -> None:
    obj = collector.require_keys(
        value,
        ("condition", "required_evidence", "safety_checks"),
        path,
    )
    if obj is None:
        return
    if not _nonempty_string(obj.get("condition")):
        collector.add(f"{path}.condition", "TYPE", "must be a non-empty string")
    if not _string_list(obj.get("required_evidence")) or not obj.get(
        "required_evidence"
    ):
        collector.add(
            f"{path}.required_evidence",
            "TYPE",
            "must be a non-empty string array",
        )
    checks = obj.get("safety_checks")
    if not _string_list(checks):
        collector.add(f"{path}.safety_checks", "TYPE", "must be a string array")
        return
    required = set(BASE_SUCCESSOR_CHECKS)
    if event == "on_success":
        required.add(SUCCESS_COMPLETION_CHECK)
    missing = required - set(checks)
    if missing:
        collector.add(
            f"{path}.safety_checks",
            "SUCCESSOR_GATE_WEAKENED",
            f"missing required checks: {', '.join(sorted(missing))}",
        )


def _validate_autofix(value: Any, path: str, collector: _Collector) -> None:
    obj = collector.require_keys(
        value,
        (
            "enabled",
            "reversible",
            "idempotent",
            "max_attempts",
            "preconditions",
            "actions",
            "post_fix_tests",
        ),
        path,
    )
    if obj is None:
        return
    if not isinstance(obj.get("enabled"), bool):
        collector.add(f"{path}.enabled", "TYPE", "must be boolean")
    for key in ("reversible", "idempotent"):
        if obj.get(key) is not True:
            collector.add(f"{path}.{key}", "REQUIRED_TRUE", "must be true")
    attempts = obj.get("max_attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        collector.add(f"{path}.max_attempts", "RANGE", "must be a positive integer")
    if not _string_list(obj.get("preconditions")) or not obj.get("preconditions"):
        collector.add(
            f"{path}.preconditions", "TYPE", "must be a non-empty string array"
        )
    _validate_action_list(
        obj.get("actions"),
        f"{path}.actions",
        collector,
        automatic_context=True,
        require_nonempty=obj.get("enabled") is True,
    )
    if not _string_list(obj.get("post_fix_tests")) or not obj.get("post_fix_tests"):
        collector.add(
            f"{path}.post_fix_tests", "TYPE", "must be a non-empty string array"
        )


def _validate_rollback(value: Any, path: str, collector: _Collector) -> None:
    obj = collector.require_keys(
        value,
        ("trigger", "actions", "verification", "data_loss_allowed"),
        path,
    )
    if obj is None:
        return
    if not _nonempty_string(obj.get("trigger")):
        collector.add(f"{path}.trigger", "TYPE", "must be non-empty")
    _validate_action_list(
        obj.get("actions"),
        f"{path}.actions",
        collector,
        automatic_context=True,
    )
    if not _string_list(obj.get("verification")) or not obj.get("verification"):
        collector.add(
            f"{path}.verification", "TYPE", "must be a non-empty string array"
        )
    if obj.get("data_loss_allowed") is not False:
        collector.add(
            f"{path}.data_loss_allowed", "REQUIRED_FALSE", "must be false"
        )


def _validate_safety(plan: Mapping[str, Any], collector: _Collector) -> None:
    path = "$.safety"
    obj = collector.require_keys(
        plan.get("safety"),
        (
            "production_source_of_truth",
            "forbidden_production_sources",
            "forbidden_automatic_capabilities",
            "approval_required_capabilities",
            "hard_gates_not_waivable",
            "service_invariants",
        ),
        path,
    )
    if obj is None:
        return
    if obj.get("production_source_of_truth") != "TURSO":
        collector.add(
            f"{path}.production_source_of_truth",
            "TURSO_REQUIRED",
            "must be TURSO",
        )
    forbidden_sources = obj.get("forbidden_production_sources")
    if not _string_list(forbidden_sources) or set(forbidden_sources) != set(
        FORBIDDEN_PRODUCTION_SOURCES
    ):
        collector.add(
            f"{path}.forbidden_production_sources",
            "EXACT_SET",
            "must contain exactly CSV, EXCEL, SQLITE, and STREAMLIT",
        )
    forbidden_caps = obj.get("forbidden_automatic_capabilities")
    if not _string_list(forbidden_caps) or set(forbidden_caps) != set(
        FORBIDDEN_AUTOMATIC_CAPABILITIES
    ):
        collector.add(
            f"{path}.forbidden_automatic_capabilities",
            "EXACT_SET",
            "must contain the complete forbidden automatic capability set",
        )
    approvals = obj.get("approval_required_capabilities")
    if not _string_list(approvals) or not FORBIDDEN_AUTOMATIC_CAPABILITIES.issubset(
        set(approvals or [])
    ):
        collector.add(
            f"{path}.approval_required_capabilities",
            "APPROVAL_SET",
            "must include every forbidden automatic capability",
        )
    if obj.get("hard_gates_not_waivable") is not True:
        collector.add(
            f"{path}.hard_gates_not_waivable", "REQUIRED_TRUE", "must be true"
        )
    invariants = obj.get("service_invariants")
    if not isinstance(invariants, list):
        collector.add(f"{path}.service_invariants", "TYPE", "must be an array")
        return
    by_name: dict[str, Mapping[str, Any]] = {}
    for index, invariant in enumerate(invariants):
        item_path = f"{path}.service_invariants[{index}]"
        item = collector.require_keys(invariant, ("name", "active_state", "enabled"), item_path)
        if item is None:
            continue
        name = item.get("name")
        if not _nonempty_string(name):
            collector.add(f"{item_path}.name", "TYPE", "must be non-empty")
            continue
        if name in by_name:
            collector.add(f"{item_path}.name", "DUPLICATE", "service repeated")
        by_name[name] = item
    if set(by_name) != REQUIRED_DISABLED_SERVICES:
        collector.add(
            f"{path}.service_invariants",
            "EXACT_SERVICES",
            "must contain exactly the three required disabled legacy services",
        )
    for name in REQUIRED_DISABLED_SERVICES & set(by_name):
        invariant = by_name[name]
        if invariant.get("active_state") != "inactive":
            collector.add(
                f"{path}.service_invariants[{name}].active_state",
                "SAFETY_STATE",
                "must be inactive",
            )
        if invariant.get("enabled") is not False:
            collector.add(
                f"{path}.service_invariants[{name}].enabled",
                "SAFETY_STATE",
                "must be false",
            )


def _validate_stage(
    stage: Any,
    index: int,
    collector: _Collector,
) -> None:
    path = f"$.stages[{index}]"
    obj = collector.require_keys(
        stage,
        (
            "id",
            "title",
            "owner",
            "action_class",
            "evidence_stage",
            "dependencies",
            "progress",
            "data_sources",
            "filesystem_boundary",
            "operations",
            "evidence_gates",
            "autofix",
            "rollback",
            "liveness",
            "successors",
            "successor_gates",
        ),
        path,
    )
    if obj is None:
        return
    for key in ("id", "title", "owner"):
        if not _nonempty_string(obj.get(key)):
            collector.add(f"{path}.{key}", "TYPE", "must be a non-empty string")
    if obj.get("action_class") not in ACTION_CLASSES:
        collector.add(f"{path}.action_class", "ENUM", "invalid action class")
    evidence_stage = obj.get("evidence_stage")
    if evidence_stage not in EVIDENCE_STAGES:
        collector.add(f"{path}.evidence_stage", "ENUM", "invalid evidence stage")
    if not _string_list(obj.get("dependencies")):
        collector.add(f"{path}.dependencies", "TYPE", "must be a string array")
    elif len(set(obj["dependencies"])) != len(obj["dependencies"]):
        collector.add(f"{path}.dependencies", "DUPLICATE", "dependency repeated")
    _validate_progress(obj.get("progress"), f"{path}.progress", collector)
    _validate_data_sources(obj.get("data_sources"), f"{path}.data_sources", collector)
    _validate_filesystem_boundary(
        obj.get("filesystem_boundary"), f"{path}.filesystem_boundary", collector
    )
    _validate_action_list(
        obj.get("operations"),
        f"{path}.operations",
        collector,
        automatic_context=obj.get("action_class") == "SAFE_NOW",
    )

    gates = collector.require_keys(obj.get("evidence_gates"), EVIDENCE_GATES, f"{path}.evidence_gates")
    validated_gates: dict[str, Mapping[str, Any] | None] = {}
    if gates is not None:
        for gate_name in EVIDENCE_GATES:
            validated_gates[gate_name] = _validate_gate(
                gates.get(gate_name),
                f"{path}.evidence_gates.{gate_name}",
                collector,
            )
    if evidence_stage in EVIDENCE_STAGES:
        rank = EVIDENCE_STAGES.index(evidence_stage)
        required_by_rank = {
            "test": rank >= EVIDENCE_STAGES.index("TESTED"),
            "observe": rank >= EVIDENCE_STAGES.index("OBSERVED"),
            "readback": rank >= EVIDENCE_STAGES.index("VERIFIED"),
        }
        for gate_name, must_be_satisfied in required_by_rank.items():
            if must_be_satisfied and (
                not validated_gates.get(gate_name)
                or validated_gates[gate_name].get("satisfied") is not True
            ):
                collector.add(
                    f"{path}.evidence_gates.{gate_name}.satisfied",
                    "EVIDENCE_STAGE_CONTRADICTION",
                    f"{evidence_stage} requires this gate to be satisfied",
                )

    _validate_autofix(obj.get("autofix"), f"{path}.autofix", collector)
    _validate_rollback(obj.get("rollback"), f"{path}.rollback", collector)
    _validate_recovery(obj.get("liveness"), f"{path}.liveness", collector)

    successors = collector.require_keys(
        obj.get("successors"), TRANSITION_EVENTS, f"{path}.successors"
    )
    if successors is not None:
        for event in TRANSITION_EVENTS:
            value = successors.get(event)
            if value is not None and not _nonempty_string(value):
                collector.add(
                    f"{path}.successors.{event}",
                    "TYPE",
                    "must be null or a non-empty stage ID",
                )
    successor_gates = collector.require_keys(
        obj.get("successor_gates"), TRANSITION_EVENTS, f"{path}.successor_gates"
    )
    if successor_gates is not None:
        for event in TRANSITION_EVENTS:
            _validate_successor_gate(
                successor_gates.get(event),
                f"{path}.successor_gates.{event}",
                collector,
                event=event,
            )


def _validate_graph(plan: Mapping[str, Any], collector: _Collector) -> None:
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages:
        return
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, stage in enumerate(stages):
        if not isinstance(stage, Mapping) or not _nonempty_string(stage.get("id")):
            continue
        stage_id = stage["id"]
        if stage_id in by_id:
            collector.add(f"$.stages[{index}].id", "DUPLICATE", "stage ID is repeated")
        else:
            by_id[stage_id] = stage

    for stage_id, stage in by_id.items():
        for dependency in stage.get("dependencies", []) if isinstance(stage.get("dependencies"), list) else []:
            if dependency not in by_id:
                collector.add(
                    f"$.stages[{stage_id}].dependencies",
                    "UNKNOWN_STAGE",
                    f"unknown dependency {dependency!r}",
                )
            if dependency == stage_id:
                collector.add(
                    f"$.stages[{stage_id}].dependencies",
                    "SELF_DEPENDENCY",
                    "stage cannot depend on itself",
                )
        successors = stage.get("successors")
        if isinstance(successors, Mapping):
            for event in TRANSITION_EVENTS:
                target = successors.get(event)
                if target is not None and target not in by_id:
                    collector.add(
                        f"$.stages[{stage_id}].successors.{event}",
                        "UNKNOWN_STAGE",
                        f"unknown successor {target!r}",
                    )

    # Dependencies must be acyclic. Successor transitions are runtime routing
    # and may intentionally retry the current stage after a checkpoint repair.
    colors: dict[str, int] = {stage_id: 0 for stage_id in by_id}

    def visit(stage_id: str, trail: tuple[str, ...]) -> None:
        if colors[stage_id] == 1:
            collector.add(
                "$.stages",
                "DEPENDENCY_CYCLE",
                " -> ".join((*trail, stage_id)),
            )
            return
        if colors[stage_id] == 2:
            return
        colors[stage_id] = 1
        dependencies = by_id[stage_id].get("dependencies", [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if dependency in by_id:
                    visit(dependency, (*trail, stage_id))
        colors[stage_id] = 2

    for stage_id in by_id:
        if colors[stage_id] == 0:
            visit(stage_id, ())

    ownership = plan.get("successor_ownership")
    if not isinstance(ownership, Mapping):
        return
    referenced_targets = {
        target
        for stage in by_id.values()
        if isinstance(stage.get("successors"), Mapping)
        for target in (stage["successors"].get(event) for event in TRANSITION_EVENTS)
        if target is not None
    }
    if set(ownership) != referenced_targets:
        collector.add(
            "$.successor_ownership",
            "OWNERSHIP_COVERAGE",
            "must define exactly one owner for every referenced successor stage",
        )
    for target, owner in ownership.items():
        if target not in by_id:
            collector.add(
                f"$.successor_ownership.{target}",
                "UNKNOWN_STAGE",
                "ownership target is not a stage",
            )
        if not _nonempty_string(owner):
            collector.add(
                f"$.successor_ownership.{target}",
                "OWNER_REQUIRED",
                "must name exactly one non-empty owner",
            )
        elif target in by_id and owner != by_id[target].get("owner"):
            collector.add(
                f"$.successor_ownership.{target}",
                "OWNER_MISMATCH",
                "must equal the successor stage owner",
            )


def validate_plan(plan: Any) -> tuple[ValidationIssue, ...]:
    """Return deterministic validation issues; an empty tuple means valid."""

    collector = _Collector()
    obj = collector.require_keys(
        plan,
        (
            "contract_version",
            "plan_id",
            "target_architecture",
            "safety",
            "stages",
            "successor_ownership",
        ),
        "$",
    )
    if obj is None:
        return tuple(sorted(collector.issues))
    if obj.get("contract_version") != CONTRACT_VERSION:
        collector.add("$.contract_version", "CONTRACT", f"must be {CONTRACT_VERSION}")
    if not _nonempty_string(obj.get("plan_id")):
        collector.add("$.plan_id", "TYPE", "must be a non-empty string")
    if obj.get("target_architecture") != TARGET_ARCHITECTURE:
        collector.add(
            "$.target_architecture", "TARGET", f"must be {TARGET_ARCHITECTURE}"
        )
    stages = obj.get("stages")
    if not isinstance(stages, list) or not stages:
        collector.add("$.stages", "TYPE", "must be a non-empty array")
    else:
        for index, stage in enumerate(stages):
            _validate_stage(stage, index, collector)
    if not isinstance(obj.get("successor_ownership"), Mapping):
        collector.add("$.successor_ownership", "TYPE", "must be an object")
    _validate_safety(obj, collector)
    _validate_graph(obj, collector)
    return tuple(sorted(set(collector.issues)))


def assert_valid_plan(plan: Any) -> None:
    """Raise :class:`PlanValidationError` unless *plan* satisfies the contract."""

    issues = validate_plan(plan)
    if issues:
        raise PlanValidationError(issues)


def validation_report(plan: Any) -> dict[str, Any]:
    """Return a JSON-serializable structural validation report."""

    issues = validate_plan(plan)
    return {
        "contract_version": CONTRACT_VERSION,
        "valid": not issues,
        "issue_count": len(issues),
        "issues": [
            {"path": issue.path, "code": issue.code, "message": issue.message}
            for issue in issues
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one JSON plan without executing any plan operation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="path to the migration plan JSON")
    args = parser.parse_args(argv)
    try:
        with args.plan.open("r", encoding="utf-8") as handle:
            plan = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report = {
            "contract_version": CONTRACT_VERSION,
            "valid": False,
            "issue_count": 1,
            "issues": [
                {
                    "path": "$",
                    "code": "PLAN_READ_FAILED",
                    "message": f"{type(exc).__name__}: unable to read valid JSON",
                }
            ],
        }
        print(json.dumps(report, sort_keys=True))
        return 2
    report = validation_report(plan)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["valid"] else 2


__all__ = [
    "ACTION_CLASSES",
    "CONTRACT_VERSION",
    "EVIDENCE_STAGES",
    "FORBIDDEN_AUTOMATIC_CAPABILITIES",
    "FORBIDDEN_PRODUCTION_SOURCES",
    "PlanValidationError",
    "REQUIRED_DISABLED_SERVICES",
    "TARGET_ARCHITECTURE",
    "ValidationIssue",
    "assert_valid_plan",
    "main",
    "validate_plan",
    "validation_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
