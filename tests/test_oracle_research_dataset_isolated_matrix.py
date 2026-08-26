import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from scripts.oracle_research_dataset_isolated_matrix import (
    BEHAVIOR_ASSERTION_IDS,
    EXPECTED_MIGRATION_SHA256,
    EXPECTED_PRODUCTION_ID,
    EXPECTED_PRODUCTION_NAME,
    EXPECTED_SCHEMA_OBJECTS,
    EXPECTED_SOURCE_COMMIT,
    MIGRATION_PATH,
    IsolatedBranchIdentity,
    IsolatedMatrixReadback,
    TemporaryBranchApproval,
    bind_branch_identity,
    build_pre_branch_intent,
    build_isolated_matrix_plan,
    execute_with_adapter,
    validate_isolated_matrix_readback,
)


def approval(**changes):
    values = {
        "approval_id": "approval-temp-oracle-rd-20260826",
        "create_branch": True,
        "issue_ephemeral_credential": True,
        "apply_schema_to_branch": True,
        "run_fixture_writes": True,
        "append_logical_rollback": True,
        "destroy_branch_after_evidence": True,
    }
    values.update(changes)
    return TemporaryBranchApproval(**values)


def branch(**changes):
    values = {
        "branch_name": "theoracle-codex-oracle-rd-20260826t1430z-a1b2c3",
        "branch_id": "01a-test-isolated-branch",
        "parent_name": "theoracle",
        "parent_id": "019f09f6-0701-72e9-aad2-c64996ae63e1",
    }
    values.update(changes)
    return IsolatedBranchIdentity(**values)


def plan():
    return build_isolated_matrix_plan(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch=branch(),
        approval=approval(),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc),
    )


def pre_branch_intent():
    return build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name=branch().branch_name,
        approval=approval(),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc),
    )


def readback(p=None):
    p = p or plan()
    fingerprint = "f" * 64
    return IsolatedMatrixReadback(
        branch_name=p.branch.branch_name,
        branch_id=p.branch.branch_id,
        migration_sha256=p.migration_sha256,
        statement_count=p.statement_count,
        schema_objects=EXPECTED_SCHEMA_OBJECTS,
        apply_event_id=p.apply_event_id,
        apply_event_count=1,
        assertion_results={key: True for key in BEHAVIOR_ASSERTION_IDS},
        rollback_event_id=p.rollback_event_id,
        rollback_parent_event_id=p.apply_event_id,
        rollback_event_count=1,
        fixture_version_rows=0,
        fixture_provider_rows=0,
        fixture_event_rows=0,
        failed_ddl_probe_rows=0,
        production_fingerprint_before=fingerprint,
        production_fingerprint_after=fingerprint,
        production_oracle_object_count_before=0,
        production_oracle_object_count_after=0,
    )


def test_plan_pins_exact_artifact_and_emits_no_secret_value():
    result = plan()
    assert result.migration_sha256 == EXPECTED_MIGRATION_SHA256
    assert result.statement_count == 26
    assert len(result.behavior_assertion_ids) == 26
    payload = json.dumps([command.argv for command in result.commands])
    assert "TURSO_AUTH_TOKEN" not in payload
    token_command = next(c for c in result.commands if c.purpose == "create_one_day_branch_token")
    assert token_command.sensitive_stdout
    assert result.commands[-1].destructive


def test_pre_branch_intent_authorizes_identity_creation_before_branch_id_exists():
    intent = pre_branch_intent()
    assert intent.source_commit == EXPECTED_SOURCE_COMMIT
    assert intent.created_at_utc == "2026-08-26T14:30:00Z"
    assert intent.parent_name == EXPECTED_PRODUCTION_NAME
    assert intent.parent_id == EXPECTED_PRODUCTION_ID
    assert intent.migration_sha256 == EXPECTED_MIGRATION_SHA256
    assert intent.migration_id == "20260826_oracle_research_dataset_versions_additive"
    assert intent.schema_version == 1
    assert intent.statement_count == 26
    assert [command.purpose for command in intent.commands] == [
        "create_branch",
        "read_branch_identity",
        "create_one_day_branch_token",
    ]
    assert intent.commands[-1].sensitive_stdout
    assert all(not command.destructive for command in intent.commands)
    assert all("01a-test-isolated-branch" not in command.argv for command in intent.commands)


def test_bind_branch_identity_preserves_pre_branch_scope():
    intent = pre_branch_intent()
    result = bind_branch_identity(
        intent,
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_id="01a-test-isolated-branch",
        parent_name=EXPECTED_PRODUCTION_NAME,
        parent_id=EXPECTED_PRODUCTION_ID,
    )
    assert result.source_commit == intent.source_commit
    assert result.created_at_utc == intent.created_at_utc
    assert result.branch.branch_name == intent.branch_name
    assert result.branch.branch_id == "01a-test-isolated-branch"
    assert result.branch.parent_name == intent.parent_name
    assert result.branch.parent_id == intent.parent_id
    assert result.approval == intent.approval
    assert result.migration_sha256 == intent.migration_sha256


@pytest.mark.parametrize(
    "change,match",
    [
        ({"branch_id": EXPECTED_PRODUCTION_ID}, "resolves to production"),
        ({"parent_name": "other"}, "parent name"),
        ({"parent_id": "other-id"}, "parent ID"),
    ],
)
def test_bind_branch_identity_rejects_mismatched_readback(change, match):
    values = {
        "branch_id": "01a-test-isolated-branch",
        "parent_name": EXPECTED_PRODUCTION_NAME,
        "parent_id": EXPECTED_PRODUCTION_ID,
    }
    values.update(change)
    with pytest.raises(ValueError, match=match):
        bind_branch_identity(
            pre_branch_intent(),
            migration_bytes=MIGRATION_PATH.read_bytes(),
            **values,
        )


def test_pre_branch_and_binding_reject_drift():
    with pytest.raises(ValueError, match="reviewed baseline"):
        build_pre_branch_intent(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch_name=branch().branch_name,
            approval=approval(),
            source_commit="0" * 40,
            created_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValueError):
        bind_branch_identity(
            pre_branch_intent(),
            migration_bytes=MIGRATION_PATH.read_bytes() + b"\n",
            branch_id="01a-test-isolated-branch",
            parent_name=EXPECTED_PRODUCTION_NAME,
            parent_id=EXPECTED_PRODUCTION_ID,
        )
    with pytest.raises(ValueError, match="identity or command scope"):
        bind_branch_identity(
            replace(pre_branch_intent(), intent_id="oracle-rd-pre-branch-intent-0000000000000000"),
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch_id="01a-test-isolated-branch",
            parent_name=EXPECTED_PRODUCTION_NAME,
            parent_id=EXPECTED_PRODUCTION_ID,
        )


def test_pre_branch_intent_id_binds_approval_and_source_scope():
    expected = pre_branch_intent()
    different_approval = build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name=branch().branch_name,
        approval=approval(approval_id="approval-temp-oracle-rd-20260826-b"),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc),
    )
    assert different_approval.intent_id != expected.intent_id


def test_plan_rejects_production_alias_and_incomplete_approval():
    with pytest.raises(ValueError, match="resolves to production"):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch=branch(branch_id="019f09f6-0701-72e9-aad2-c64996ae63e1"),
            approval=approval(),
            source_commit=EXPECTED_SOURCE_COMMIT,
            created_at=datetime.now(timezone.utc),
        )

    with pytest.raises(ValueError, match="governed pattern"):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch=branch(branch_name="theoracle-codex-oracle-rd-20260826t2460z-a1b2c3"),
            approval=approval(),
            source_commit=EXPECTED_SOURCE_COMMIT,
            created_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValueError, match="full matrix lifecycle"):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch=branch(),
            approval=approval(destroy_branch_after_evidence=False),
            source_commit=EXPECTED_SOURCE_COMMIT,
            created_at=datetime.now(timezone.utc),
        )


def test_artifact_drift_fails_closed():
    with pytest.raises(ValueError):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes() + b"\n",
            branch=branch(),
            approval=approval(),
            source_commit=EXPECTED_SOURCE_COMMIT,
            created_at=datetime.now(timezone.utc),
        )


def test_complete_readback_passes_and_adapter_is_injectable():
    matrix_plan = plan()
    evidence = readback(matrix_plan)
    validate_isolated_matrix_readback(matrix_plan, evidence)

    class Adapter:
        def run(self, received):
            assert received == matrix_plan
            return evidence

    assert execute_with_adapter(matrix_plan, Adapter()) == evidence


@pytest.mark.parametrize(
    "change,match",
    [
        ({"fixture_event_rows": 1}, "residue"),
        ({"production_fingerprint_after": "e" * 64}, "Production"),
        ({"rollback_event_count": 0}, "rollback"),
        ({"schema_objects": EXPECTED_SCHEMA_OBJECTS[:-1]}, "schema object"),
    ],
)
def test_incomplete_or_contradictory_readback_fails_closed(change, match):
    matrix_plan = plan()
    with pytest.raises(ValueError, match=match):
        validate_isolated_matrix_readback(matrix_plan, replace(readback(matrix_plan), **change))


def test_any_failed_behavior_assertion_fails_closed():
    matrix_plan = plan()
    results = {key: True for key in BEHAVIOR_ASSERTION_IDS}
    results[BEHAVIOR_ASSERTION_IDS[-1]] = False
    with pytest.raises(ValueError, match="assertions failed"):
        validate_isolated_matrix_readback(
            matrix_plan,
            replace(readback(matrix_plan), assertion_results=results),
        )
