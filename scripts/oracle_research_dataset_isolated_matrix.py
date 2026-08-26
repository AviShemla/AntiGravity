"""Fail-closed plan and evidence contract for an isolated Turso matrix.

This module never creates or destroys a database, obtains a token, opens a
network connection, or applies SQL.  It validates the exact reviewed migration,
constructs non-secret command vectors, and evaluates evidence returned by an
injected non-production matrix adapter.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.apply_atomic_migration import parse_atomic_bundle


MIGRATION_PATH = ROOT / "migrations" / "20260826_oracle_research_dataset_versions_additive.sql"
EXPECTED_MIGRATION_ID = "20260826_oracle_research_dataset_versions_additive"
EXPECTED_SCHEMA_VERSION = 1
EXPECTED_STATEMENT_COUNT = 26
EXPECTED_MIGRATION_SHA256 = "d21aa91b356666c6509e234a74f3041130fc1e4ae62455086aa86b2b18e6e01e"
EXPECTED_SOURCE_COMMIT = "cf8345c30e2c8264cbb7140bef3b397a7799e488"
EXPECTED_PRODUCTION_NAME = "theoracle"
EXPECTED_PRODUCTION_ID = "019f09f6-0701-72e9-aad2-c64996ae63e1"
BRANCH_NAME = re.compile(
    r"^theoracle-codex-oracle-rd-20260826t(?:[01][0-9]|2[0-3])[0-5][0-9]z-[0-9a-f]{6}$"
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


EXPECTED_SCHEMA_OBJECTS = (
    "idx_oracle_research_dataset_event_order",
    "idx_oracle_research_dataset_frozen_identity",
    "idx_oracle_research_dataset_source_session",
    "idx_oracle_research_one_freeze_event",
    "idx_oracle_research_provider_binding",
    "oracle_research_dataset_events",
    "oracle_research_dataset_provider_lineage",
    "oracle_research_dataset_versions",
    "trg_oracle_research_events_no_delete",
    "trg_oracle_research_events_no_update",
    "trg_oracle_research_feature_no_delete",
    "trg_oracle_research_feature_no_insert",
    "trg_oracle_research_feature_no_update",
    "trg_oracle_research_freeze_event_staging_only",
    "trg_oracle_research_frozen_version_no_update",
    "trg_oracle_research_lineage_no_delete",
    "trg_oracle_research_lineage_no_insert_after_freeze",
    "trg_oracle_research_lineage_no_update",
    "trg_oracle_research_revoke_event_frozen_only",
    "trg_oracle_research_source_lineage_no_delete",
    "trg_oracle_research_source_lineage_no_insert",
    "trg_oracle_research_source_lineage_no_update",
    "trg_oracle_research_source_metadata_no_delete",
    "trg_oracle_research_source_metadata_no_update",
    "trg_oracle_research_version_no_delete",
    "trg_oracle_research_version_staging_insert_only",
)


BEHAVIOR_ASSERTION_IDS = (
    "migration_apply_event_exact",
    "staging_insert_allowed",
    "direct_frozen_insert_rejected",
    "staging_provider_binding_allowed",
    "freeze_event_requires_staging",
    "freeze_transition_exactly_one",
    "duplicate_freeze_event_rejected",
    "revoke_requires_frozen",
    "frozen_version_update_rejected",
    "version_delete_rejected",
    "provider_insert_after_freeze_rejected",
    "provider_update_rejected",
    "provider_delete_rejected",
    "event_update_rejected",
    "event_delete_rejected",
    "bound_source_metadata_update_rejected",
    "bound_source_metadata_delete_rejected",
    "bound_feature_insert_rejected",
    "bound_feature_update_rejected",
    "bound_feature_delete_rejected",
    "bound_source_lineage_insert_rejected",
    "bound_source_lineage_update_rejected",
    "bound_source_lineage_delete_rejected",
    "unbound_source_fixture_remains_mutable",
    "injected_ddl_failure_rolled_back",
    "ambiguous_apply_requires_exact_readback",
)


@dataclass(frozen=True)
class TemporaryBranchApproval:
    approval_id: str
    create_branch: bool
    issue_ephemeral_credential: bool
    apply_schema_to_branch: bool
    run_fixture_writes: bool
    append_logical_rollback: bool
    destroy_branch_after_evidence: bool

    def validate(self) -> None:
        if not IDENTIFIER.fullmatch(self.approval_id):
            raise ValueError("Temporary-branch approval ID is missing or invalid.")
        required = (
            self.create_branch,
            self.issue_ephemeral_credential,
            self.apply_schema_to_branch,
            self.run_fixture_writes,
            self.append_logical_rollback,
            self.destroy_branch_after_evidence,
        )
        if not all(type(value) is bool and value for value in required):
            raise ValueError("Temporary-branch approval does not cover the full matrix lifecycle.")


@dataclass(frozen=True)
class IsolatedBranchIdentity:
    branch_name: str
    branch_id: str
    parent_name: str
    parent_id: str

    def validate(self) -> None:
        if not BRANCH_NAME.fullmatch(self.branch_name):
            raise ValueError("Isolated branch name does not match the governed pattern.")
        if not IDENTIFIER.fullmatch(self.branch_id):
            raise ValueError("Isolated branch ID is missing or invalid.")
        if self.parent_name != EXPECTED_PRODUCTION_NAME:
            raise ValueError("Isolated branch parent name is not the governed production parent.")
        if self.parent_id != EXPECTED_PRODUCTION_ID:
            raise ValueError("Isolated branch parent ID is not the governed production parent.")
        if self.branch_name == self.parent_name or self.branch_id == self.parent_id:
            raise ValueError("Isolated branch resolves to production.")


@dataclass(frozen=True)
class CommandVector:
    purpose: str
    argv: tuple[str, ...]
    sensitive_stdout: bool = False
    destructive: bool = False


@dataclass(frozen=True)
class PreBranchIntent:
    intent_id: str
    source_commit: str
    created_at_utc: str
    branch_name: str
    parent_name: str
    parent_id: str
    approval: TemporaryBranchApproval
    migration_sha256: str
    migration_id: str
    schema_version: int
    statement_count: int
    commands: tuple[CommandVector, ...]


@dataclass(frozen=True)
class IsolatedMatrixPlan:
    plan_id: str
    source_commit: str
    created_at_utc: str
    branch: IsolatedBranchIdentity
    approval: TemporaryBranchApproval
    migration_sha256: str
    migration_id: str
    schema_version: int
    statement_count: int
    apply_event_id: str
    rollback_event_id: str
    commands: tuple[CommandVector, ...]
    behavior_assertion_ids: tuple[str, ...]


@dataclass(frozen=True)
class IsolatedMatrixReadback:
    branch_name: str
    branch_id: str
    migration_sha256: str
    statement_count: int
    schema_objects: tuple[str, ...]
    apply_event_id: str
    apply_event_count: int
    assertion_results: dict[str, bool]
    rollback_event_id: str
    rollback_parent_event_id: str
    rollback_event_count: int
    fixture_version_rows: int
    fixture_provider_rows: int
    fixture_event_rows: int
    failed_ddl_probe_rows: int
    production_fingerprint_before: str
    production_fingerprint_after: str
    production_oracle_object_count_before: int
    production_oracle_object_count_after: int


class IsolatedMatrixAdapter(Protocol):
    """External branch adapter; implementations must never target production."""

    def run(self, plan: IsolatedMatrixPlan) -> IsolatedMatrixReadback: ...


def _canonical_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Plan timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact_identity(raw: bytes) -> tuple[str, int, int, str]:
    migration = parse_atomic_bundle(raw)
    digest = hashlib.sha256(raw).hexdigest()
    observed = (
        migration.migration_id,
        migration.schema_version,
        len(migration.statements),
        digest,
    )
    expected = (
        EXPECTED_MIGRATION_ID,
        EXPECTED_SCHEMA_VERSION,
        EXPECTED_STATEMENT_COUNT,
        EXPECTED_MIGRATION_SHA256,
    )
    if observed != expected:
        raise ValueError("Oracle migration identity differs from the reviewed artifact.")
    return observed


def _command_vectors(
    branch: IsolatedBranchIdentity,
    *,
    apply_event_id: str,
    approval_id: str,
) -> tuple[CommandVector, ...]:
    cli = "/home/codexops/.turso/turso"
    python = "/opt/antigravity/venv/bin/python"
    evidence = json.dumps(
        {
            "approval_id": approval_id,
            "branch_name": branch.branch_name,
            "parent_database_id": branch.parent_id,
            "scope": "isolated-oracle-research-dataset-matrix",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        CommandVector("create_branch", (cli, "db", "branch", branch.parent_name, branch.branch_name)),
        CommandVector("read_branch_identity", (cli, "db", "show", branch.branch_name)),
        CommandVector(
            "create_one_day_branch_token",
            (cli, "db", "tokens", "create", branch.branch_name, "--expiration", "1d"),
            sensitive_stdout=True,
        ),
        CommandVector(
            "check_atomic_artifact",
            (python, "scripts/apply_atomic_migration.py", str(MIGRATION_PATH.relative_to(ROOT))),
        ),
        CommandVector(
            "apply_atomic_artifact_to_isolated_branch",
            (
                python,
                "scripts/apply_atomic_migration.py",
                str(MIGRATION_PATH.relative_to(ROOT)),
                "--apply",
                "--expected-sha256",
                EXPECTED_MIGRATION_SHA256,
                "--event-id",
                apply_event_id,
                "--actor",
                "codexops",
                "--target-database-id",
                branch.branch_id,
                "--target-environment",
                "isolated",
                "--evidence-json",
                evidence,
            ),
        ),
        CommandVector(
            "destroy_branch_after_evidence_commit",
            (cli, "db", "destroy", branch.branch_name, "--yes"),
            destructive=True,
        ),
    )


def _pre_branch_command_vectors(branch_name: str) -> tuple[CommandVector, ...]:
    cli = "/home/codexops/.turso/turso"
    return (
        CommandVector("create_branch", (cli, "db", "branch", EXPECTED_PRODUCTION_NAME, branch_name)),
        CommandVector("read_branch_identity", (cli, "db", "show", branch_name)),
        CommandVector(
            "create_one_day_branch_token",
            (cli, "db", "tokens", "create", branch_name, "--expiration", "1d"),
            sensitive_stdout=True,
        ),
    )


def build_pre_branch_intent(
    *,
    migration_bytes: bytes,
    branch_name: str,
    approval: TemporaryBranchApproval,
    source_commit: str,
    created_at: datetime,
) -> PreBranchIntent:
    approval.validate()
    if not BRANCH_NAME.fullmatch(branch_name):
        raise ValueError("Isolated branch name does not match the governed pattern.")
    if branch_name == EXPECTED_PRODUCTION_NAME:
        raise ValueError("Isolated branch name resolves to production.")
    if source_commit != EXPECTED_SOURCE_COMMIT:
        raise ValueError("Pre-branch source commit differs from the reviewed baseline.")
    migration_id, schema_version, statement_count, digest = _artifact_identity(migration_bytes)
    timestamp = _canonical_utc(created_at)
    identity = json.dumps(
        {
            "approval_id": approval.approval_id,
            "branch_name": branch_name,
            "created_at_utc": timestamp,
            "migration_id": migration_id,
            "migration_sha256": digest,
            "parent_id": EXPECTED_PRODUCTION_ID,
            "parent_name": EXPECTED_PRODUCTION_NAME,
            "schema_version": schema_version,
            "source_commit": source_commit,
            "statement_count": statement_count,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return PreBranchIntent(
        intent_id=f"oracle-rd-pre-branch-intent-{suffix}",
        source_commit=source_commit,
        created_at_utc=timestamp,
        branch_name=branch_name,
        parent_name=EXPECTED_PRODUCTION_NAME,
        parent_id=EXPECTED_PRODUCTION_ID,
        approval=approval,
        migration_sha256=digest,
        migration_id=migration_id,
        schema_version=schema_version,
        statement_count=statement_count,
        commands=_pre_branch_command_vectors(branch_name),
    )


def bind_branch_identity(
    intent: PreBranchIntent,
    *,
    migration_bytes: bytes,
    branch_id: str,
    parent_name: str,
    parent_id: str,
) -> IsolatedMatrixPlan:
    intent.approval.validate()
    try:
        created_at = datetime.strptime(intent.created_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ValueError("Pre-branch intent timestamp is not canonical UTC seconds.") from exc
    rebuilt_intent = build_pre_branch_intent(
        migration_bytes=migration_bytes,
        branch_name=intent.branch_name,
        approval=intent.approval,
        source_commit=intent.source_commit,
        created_at=created_at,
    )
    if rebuilt_intent != intent:
        raise ValueError("Pre-branch intent identity or command scope was modified.")
    observed_artifact = _artifact_identity(migration_bytes)
    expected_artifact = (
        intent.migration_id,
        intent.schema_version,
        intent.statement_count,
        intent.migration_sha256,
    )
    if observed_artifact != expected_artifact:
        raise ValueError("Branch binding artifact differs from the pre-branch intent.")
    if intent.source_commit != EXPECTED_SOURCE_COMMIT:
        raise ValueError("Branch binding source commit differs from the reviewed baseline.")
    branch = IsolatedBranchIdentity(
        branch_name=intent.branch_name,
        branch_id=branch_id,
        parent_name=parent_name,
        parent_id=parent_id,
    )
    branch.validate()
    plan = build_isolated_matrix_plan(
        migration_bytes=migration_bytes,
        branch=branch,
        approval=intent.approval,
        source_commit=intent.source_commit,
        created_at=created_at,
    )
    if (
        plan.branch.branch_name != intent.branch_name
        or plan.branch.parent_name != intent.parent_name
        or plan.branch.parent_id != intent.parent_id
        or plan.approval != intent.approval
        or plan.created_at_utc != intent.created_at_utc
    ):
        raise ValueError("Bound matrix plan changed the approved pre-branch scope.")
    return plan


def build_isolated_matrix_plan(
    *,
    migration_bytes: bytes,
    branch: IsolatedBranchIdentity,
    approval: TemporaryBranchApproval,
    source_commit: str,
    created_at: datetime,
) -> IsolatedMatrixPlan:
    branch.validate()
    approval.validate()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Matrix source commit must be an exact Git SHA-1.")
    migration_id, schema_version, statement_count, digest = _artifact_identity(migration_bytes)
    timestamp = _canonical_utc(created_at)
    suffix = hashlib.sha256(
        f"{branch.branch_id}|{digest}|{timestamp}".encode("utf-8")
    ).hexdigest()[:16]
    plan_id = f"oracle-rd-matrix-plan-{suffix}"
    apply_event_id = f"evt-oracle-rd-apply-{suffix}"
    rollback_event_id = f"evt-oracle-rd-rollback-{suffix}"
    return IsolatedMatrixPlan(
        plan_id=plan_id,
        source_commit=source_commit,
        created_at_utc=timestamp,
        branch=branch,
        approval=approval,
        migration_sha256=digest,
        migration_id=migration_id,
        schema_version=schema_version,
        statement_count=statement_count,
        apply_event_id=apply_event_id,
        rollback_event_id=rollback_event_id,
        commands=_command_vectors(
            branch,
            apply_event_id=apply_event_id,
            approval_id=approval.approval_id,
        ),
        behavior_assertion_ids=BEHAVIOR_ASSERTION_IDS,
    )


def validate_isolated_matrix_readback(
    plan: IsolatedMatrixPlan,
    readback: IsolatedMatrixReadback,
) -> None:
    identity = (
        readback.branch_name,
        readback.branch_id,
        readback.migration_sha256,
        readback.statement_count,
    )
    expected_identity = (
        plan.branch.branch_name,
        plan.branch.branch_id,
        plan.migration_sha256,
        plan.statement_count,
    )
    if identity != expected_identity:
        raise ValueError("Matrix readback identity differs from the approved plan.")
    if tuple(sorted(readback.schema_objects)) != EXPECTED_SCHEMA_OBJECTS:
        raise ValueError("Matrix schema object readback is incomplete or unexpected.")
    if readback.apply_event_id != plan.apply_event_id or readback.apply_event_count != 1:
        raise ValueError("Matrix APPLY event readback is not exact.")
    if set(readback.assertion_results) != set(plan.behavior_assertion_ids):
        raise ValueError("Matrix behavioral assertion set is incomplete or unexpected.")
    failed = sorted(key for key, passed in readback.assertion_results.items() if passed is not True)
    if failed:
        raise ValueError("Matrix behavioral assertions failed: " + ", ".join(failed))
    if (
        readback.rollback_event_id != plan.rollback_event_id
        or readback.rollback_parent_event_id != plan.apply_event_id
        or readback.rollback_event_count != 1
    ):
        raise ValueError("Matrix logical rollback event is missing or mismatched.")
    residues = (
        readback.fixture_version_rows,
        readback.fixture_provider_rows,
        readback.fixture_event_rows,
        readback.failed_ddl_probe_rows,
    )
    if residues != (0, 0, 0, 0):
        raise ValueError("Matrix rollback left fixture or failed-DDL residue.")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", readback.production_fingerprint_before)
        or readback.production_fingerprint_before != readback.production_fingerprint_after
        or readback.production_oracle_object_count_before != 0
        or readback.production_oracle_object_count_after != 0
    ):
        raise ValueError("Production readback changed or contains Oracle matrix objects.")


def execute_with_adapter(
    plan: IsolatedMatrixPlan,
    adapter: IsolatedMatrixAdapter,
) -> IsolatedMatrixReadback:
    """Run only through an explicitly supplied non-production adapter."""
    plan.branch.validate()
    plan.approval.validate()
    readback = adapter.run(plan)
    validate_isolated_matrix_readback(plan, readback)
    return readback


def _preflight_payload(plan: IsolatedMatrixPlan) -> dict[str, object]:
    return {
        "plan_id": plan.plan_id,
        "branch_name": plan.branch.branch_name,
        "branch_id": plan.branch.branch_id,
        "parent_name": plan.branch.parent_name,
        "parent_id": plan.branch.parent_id,
        "migration_id": plan.migration_id,
        "migration_sha256": plan.migration_sha256,
        "schema_version": plan.schema_version,
        "statement_count": plan.statement_count,
        "behavior_assertion_count": len(plan.behavior_assertion_ids),
        "commands": [
            {
                "purpose": command.purpose,
                "argv": list(command.argv),
                "sensitive_stdout": command.sensitive_stdout,
                "destructive": command.destructive,
            }
            for command in plan.commands
        ],
        "no_changes": True,
    }


def _pre_branch_payload(intent: PreBranchIntent) -> dict[str, object]:
    return {
        "phase": "PRE_BRANCH_INTENT",
        "intent_id": intent.intent_id,
        "approval_id": intent.approval.approval_id,
        "source_commit": intent.source_commit,
        "created_at_utc": intent.created_at_utc,
        "branch_name": intent.branch_name,
        "parent_name": intent.parent_name,
        "parent_id": intent.parent_id,
        "migration_id": intent.migration_id,
        "migration_sha256": intent.migration_sha256,
        "schema_version": intent.schema_version,
        "statement_count": intent.statement_count,
        "commands": [
            {
                "purpose": command.purpose,
                "argv": list(command.argv),
                "sensitive_stdout": command.sensitive_stdout,
                "destructive": command.destructive,
            }
            for command in intent.commands
        ],
        "no_changes": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch-name", required=True)
    parser.add_argument("--branch-id")
    parser.add_argument("--parent-name")
    parser.add_argument("--parent-id")
    parser.add_argument("--intent-id")
    parser.add_argument("--intent-created-at-utc")
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    approval = TemporaryBranchApproval(
        approval_id=args.approval_id,
        create_branch=True,
        issue_ephemeral_credential=True,
        apply_schema_to_branch=True,
        run_fixture_writes=True,
        append_logical_rollback=True,
        destroy_branch_after_evidence=True,
    )
    if args.intent_created_at_utc:
        try:
            created_at = datetime.strptime(
                args.intent_created_at_utc, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise SystemExit("--intent-created-at-utc must be canonical UTC seconds.") from exc
    else:
        created_at = datetime.now(timezone.utc)
    intent = build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name=args.branch_name,
        approval=approval,
        source_commit=args.source_commit,
        created_at=created_at,
    )
    binding_values = (args.branch_id, args.parent_name, args.parent_id)
    if not any(binding_values):
        if args.intent_id or args.intent_created_at_utc:
            raise SystemExit("Intent identity arguments are valid only during branch binding.")
        print(json.dumps(_pre_branch_payload(intent), sort_keys=True, separators=(",", ":")))
        return 0
    if not all(binding_values) or not args.intent_id or not args.intent_created_at_utc:
        raise SystemExit(
            "Binding requires --branch-id, --parent-name, --parent-id, --intent-id, "
            "and --intent-created-at-utc from the preserved pre-branch intent."
        )
    if args.intent_id != intent.intent_id:
        raise SystemExit("Branch binding does not match the preserved pre-branch intent ID.")
    plan = bind_branch_identity(
        intent,
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_id=args.branch_id,
        parent_name=args.parent_name,
        parent_id=args.parent_id,
    )
    print(json.dumps(_preflight_payload(plan), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
