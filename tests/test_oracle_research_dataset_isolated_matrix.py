import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from scripts.oracle_research_dataset_isolated_matrix import (
    BEHAVIOR_ASSERTION_IDS,
    EXPECTED_MIGRATION_SHA256,
    EXPECTED_SCHEMA_OBJECTS,
    MIGRATION_PATH,
    IsolatedBranchIdentity,
    IsolatedMatrixReadback,
    TemporaryBranchApproval,
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
        source_commit="50f4acc7d68040934d65b0fb5baa304257f57b85",
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


def test_plan_rejects_production_alias_and_incomplete_approval():
    with pytest.raises(ValueError, match="resolves to production"):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch=branch(branch_id="019f09f6-0701-72e9-aad2-c64996ae63e1"),
            approval=approval(),
            source_commit="50f4acc7d68040934d65b0fb5baa304257f57b85",
            created_at=datetime.now(timezone.utc),
        )

    with pytest.raises(ValueError, match="governed pattern"):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch=branch(branch_name="theoracle-codex-oracle-rd-20260826t2460z-a1b2c3"),
            approval=approval(),
            source_commit="50f4acc7d68040934d65b0fb5baa304257f57b85",
            created_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValueError, match="full matrix lifecycle"):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes(),
            branch=branch(),
            approval=approval(destroy_branch_after_evidence=False),
            source_commit="50f4acc7d68040934d65b0fb5baa304257f57b85",
            created_at=datetime.now(timezone.utc),
        )


def test_artifact_drift_fails_closed():
    with pytest.raises(ValueError):
        build_isolated_matrix_plan(
            migration_bytes=MIGRATION_PATH.read_bytes() + b"\n",
            branch=branch(),
            approval=approval(),
            source_commit="50f4acc7d68040934d65b0fb5baa304257f57b85",
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
