import hashlib
import json
import subprocess
from dataclasses import asdict, replace
from datetime import datetime, timezone

import pytest

from model_lineage import LineageError
from oracle_research_branch_cleanup_verifier import (
    BranchCleanupEvidence,
    verify_and_cleanup_bound_branch,
    verify_and_cleanup_isolated_branch,
)
from scripts.oracle_research_dataset_isolated_matrix import (
    BEHAVIOR_ASSERTION_IDS,
    EXPECTED_MIGRATION_SHA256,
    EXPECTED_PRODUCTION_ID,
    EXPECTED_SCHEMA_OBJECTS,
    EXPECTED_SOURCE_COMMIT,
    IsolatedBranchIdentity,
    IsolatedMatrixReadback,
    TemporaryBranchApproval,
    _pre_branch_payload,
    build_isolated_matrix_plan,
    build_pre_branch_intent,
)
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    CLI,
    PRODUCTION_LEDGER_SQL,
    PRODUCTION_SCHEMA_SQL,
    BranchIdentityProof,
    CliResult,
    _fingerprint,
    build_redacted_evidence,
)
from turso_read_pipeline import PipelineResult


NOW = datetime(2026, 8, 26, 17, 2, tzinfo=timezone.utc)
BRANCH = "theoracle-codex-oracle-rd-20260826t1700z-a1b2c3"
BRANCH_ID = "01a-disposable-matrix"


def approval():
    return TemporaryBranchApproval(
        "avi-six-action-matrix-20260826", True, True, True, True, True, True
    )


def intent():
    from scripts.oracle_research_dataset_isolated_matrix import MIGRATION_PATH

    return build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name=BRANCH,
        approval=approval(),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc),
    )


def identity(branch_id=BRANCH_ID):
    return IsolatedBranchIdentity(
        BRANCH, branch_id, "theoracle", EXPECTED_PRODUCTION_ID
    )


def proof(branch_id=BRANCH_ID):
    return BranchIdentityProof(
        "turso-cli-v1.0.32-db-show-text",
        BRANCH,
        branch_id,
        "theoracle",
        EXPECTED_PRODUCTION_ID,
        "2026-08-26T17:01:00Z",
        "a" * 64,
        "b" * 64,
    )


def show(name, database_id, parent=None):
    rows = [
        f"Name:               {name}",
        f"URL:                libsql://{name}.turso.io",
        f"ID:                 {database_id}",
        "Group:              default",
    ]
    if parent is not None:
        rows.append(f"Parent:             {parent}")
    rows += ["Type:               SQLite", "", "Database Instances:", ""]
    return "\n".join(rows)


class ProductionReader:
    def __init__(self, schema_rows=()):
        self.schema_rows = schema_rows
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        if sql == PRODUCTION_SCHEMA_SQL:
            return PipelineResult(("type", "name", "sql"), self.schema_rows)
        if sql == PRODUCTION_LEDGER_SQL:
            return PipelineResult(
                ("event_id", "migration_id", "schema_version", "artifact_sha256",
                 "operation", "parent_event_id", "actor", "target_database_id",
                 "evidence_json", "executed_at_utc"),
                (),
            )
        raise AssertionError("unexpected query")


class ChangingProductionReader(ProductionReader):
    def __init__(self):
        super().__init__()
        self.fingerprint_number = 0

    def execute(self, sql, args):
        if sql == PRODUCTION_SCHEMA_SQL:
            self.fingerprint_number += 1
            rows = () if self.fingerprint_number == 1 else (("table", "drift", "sql"),)
            return PipelineResult(("type", "name", "sql"), rows)
        return super().execute(sql, args)


class Runner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, argv):
        self.calls.append(argv)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def persisted_files(tmp_path, *, mutate=None, expected_reader=None):
    current_intent = intent()
    intent_path = tmp_path / "intent.json"
    intent_path.write_text(json.dumps(_pre_branch_payload(current_intent)), encoding="utf-8")
    reader = expected_reader or ProductionReader()
    fingerprint, count = _fingerprint(reader)
    matrix_plan = build_isolated_matrix_plan(
        migration_bytes=(
            __import__(
                "scripts.oracle_research_dataset_isolated_matrix",
                fromlist=["MIGRATION_PATH"],
            ).MIGRATION_PATH.read_bytes()
        ),
        branch=identity(),
        approval=approval(),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc),
    )
    readback = IsolatedMatrixReadback(
        BRANCH, BRANCH_ID, EXPECTED_MIGRATION_SHA256, matrix_plan.statement_count,
        EXPECTED_SCHEMA_OBJECTS, matrix_plan.apply_event_id, 1,
        {key: True for key in BEHAVIOR_ASSERTION_IDS},
        matrix_plan.rollback_event_id, matrix_plan.apply_event_id, 1,
        0, 0, 0, 0, fingerprint, fingerprint, count, count,
    )
    payload = build_redacted_evidence(
        matrix_plan, readback, intent=current_intent, proof=proof()
    )
    if mutate is not None:
        mutate(payload)
    evidence_path = tmp_path / "evidence.json"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    evidence_path.write_bytes(raw)
    return intent_path, evidence_path, hashlib.sha256(raw).hexdigest(), fingerprint, count


def normal_results(*, destroy=None, listing=None, branch_id=BRANCH_ID):
    destroy_argv = (CLI, "db", "destroy", BRANCH, "--yes")
    missing = f"Error: database {BRANCH} not found. List known databases using turso db list\n"
    return [
        CliResult((CLI, "db", "show", BRANCH), 0,
                  show(BRANCH, branch_id, "theoracle"), ""),
        CliResult((CLI, "db", "show", "theoracle"), 0,
                  show("theoracle", EXPECTED_PRODUCTION_ID), ""),
        destroy or CliResult(destroy_argv, 0, "Destroyed\n", ""),
        CliResult((CLI, "db", "show", BRANCH), 1, "", missing),
        listing or CliResult(
            (CLI, "db", "show", "theoracle", "--branches"), 0,
            "NAME TYPE GROUP URL\ntheoracle primary default libsql://theoracle.turso.io\n", ""
        ),
    ]


def execute(tmp_path, *, results=None, reader=None, mutate=None, expected_sha=None):
    intent_path, evidence_path, digest, _, _ = persisted_files(tmp_path, mutate=mutate)
    runner = Runner(normal_results() if results is None else results)
    result = verify_and_cleanup_isolated_branch(
        intent_path=intent_path,
        persisted_evidence_path=evidence_path,
        expected_persisted_evidence_sha256=expected_sha or digest,
        runner=runner,
        production_reader=reader or ProductionReader(),
        observed_at=NOW,
    )
    return result, runner


def test_success_uses_actual_absolute_cli_argv_once_and_returns_redacted_evidence(tmp_path):
    result, runner = execute(tmp_path)
    destroy = (CLI, "db", "destroy", BRANCH, "--yes")
    assert runner.calls == [
        (CLI, "db", "show", BRANCH),
        (CLI, "db", "show", "theoracle"),
        destroy,
        (CLI, "db", "show", BRANCH),
        (CLI, "db", "show", "theoracle", "--branches"),
    ]
    assert runner.calls.count(destroy) == 1
    assert isinstance(result, BranchCleanupEvidence)
    assert result.destroy_result == "ZERO_EXIT_PROVEN_BY_READBACK"
    assert BRANCH not in repr(result)
    assert BRANCH_ID not in repr(result)


@pytest.mark.parametrize("mode", ["empty", "timeout"])
def test_ambiguous_destroy_requires_both_exact_absence_readbacks(tmp_path, mode):
    destroy_argv = (CLI, "db", "destroy", BRANCH, "--yes")
    destroy = (
        CliResult(destroy_argv, 7, "", "")
        if mode == "empty"
        else subprocess.TimeoutExpired(destroy_argv, 30)
    )
    result, runner = execute(tmp_path, results=normal_results(destroy=destroy))
    assert result.destroy_result.startswith("AMBIGUOUS_")
    assert runner.calls.count(destroy_argv) == 1


def test_permission_network_parse_or_cli_destroy_error_does_not_reconcile(tmp_path):
    argv = (CLI, "db", "destroy", BRANCH, "--yes")
    for error in ("permission denied", "network unavailable", "parse error"):
        with pytest.raises(LineageError, match="permission, network, parse"):
            execute(
                tmp_path,
                results=normal_results(destroy=CliResult(argv, 1, "", error)),
            )


def test_missing_show_contract_is_byte_exact(tmp_path):
    cases = [
        CliResult((CLI, "db", "show", BRANCH), 0, "", ""),
        CliResult((CLI, "db", "show", BRANCH), 1, "unexpected", ""),
        CliResult((CLI, "db", "show", BRANCH), 1, "",
                  f"Error: database {BRANCH} not found.\n"),
    ]
    for missing in cases:
        results = normal_results()
        results[3] = missing
        with pytest.raises(LineageError, match="observed CLI contract"):
            execute(tmp_path, results=results)


@pytest.mark.parametrize(
    "stdout,stderr",
    [
        ("", ""),
        ("NAME TYPE GROUP\n", ""),
        ("NAME TYPE GROUP URL\nbad row\n", ""),
        (f"NAME TYPE GROUP URL\n{BRANCH} branch default libsql://b.turso.io\n", ""),
        ("NAME TYPE GROUP URL\n", "warning"),
    ],
)
def test_parent_human_table_is_strict_and_branch_name_must_be_absent(
    tmp_path, stdout, stderr
):
    argv = (CLI, "db", "show", "theoracle", "--branches")
    listing = CliResult(argv, 0, stdout, stderr)
    with pytest.raises(LineageError):
        execute(tmp_path, results=normal_results(listing=listing))


def test_evidence_file_and_embedded_sha_are_verified_before_cli_or_fingerprint(tmp_path):
    intent_path, evidence_path, digest, _, _ = persisted_files(tmp_path)
    runner = Runner([])
    reader = ProductionReader()
    with pytest.raises(LineageError, match="file SHA-256 differs"):
        verify_and_cleanup_isolated_branch(
            intent_path=intent_path, persisted_evidence_path=evidence_path,
            expected_persisted_evidence_sha256="f" * 64, runner=runner,
            production_reader=reader, observed_at=NOW,
        )
    assert runner.calls == []
    assert reader.calls == []

    payload = json.loads(evidence_path.read_text())
    payload["source_commit"] = "0" * 40
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    changed = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    with pytest.raises(LineageError, match="payload SHA-256 differs"):
        verify_and_cleanup_isolated_branch(
            intent_path=intent_path, persisted_evidence_path=evidence_path,
            expected_persisted_evidence_sha256=changed, runner=runner,
            production_reader=reader, observed_at=NOW,
        )


def test_rehashed_evidence_identity_tamper_is_rejected_before_cli(tmp_path):
    intent_path, evidence_path, _, _, _ = persisted_files(tmp_path)
    payload = json.loads(evidence_path.read_text())
    payload["source_commit"] = "0" * 40
    unsigned = dict(payload)
    unsigned.pop("evidence_sha256")
    payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned, ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode()
    ).hexdigest()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    evidence_path.write_bytes(raw)
    runner = Runner([])
    reader = ProductionReader()
    with pytest.raises(LineageError, match="source commit differs"):
        verify_and_cleanup_isolated_branch(
            intent_path=intent_path, persisted_evidence_path=evidence_path,
            expected_persisted_evidence_sha256=hashlib.sha256(raw).hexdigest(),
            runner=runner, production_reader=reader, observed_at=NOW,
        )
    assert runner.calls == []
    assert reader.calls == []


def test_unclassified_runner_exception_is_redacted_and_rejected(tmp_path):
    class ExplodingRunner:
        def __init__(self, results):
            self.results = list(results)
            self.calls = []

        def run(self, argv):
            self.calls.append(argv)
            if len(self.calls) == 3:
                raise RuntimeError("secret adapter detail")
            return self.results.pop(0)

    intent_path, evidence_path, digest, _, _ = persisted_files(tmp_path)
    initial = normal_results()
    runner = ExplodingRunner([initial[0], initial[1]])
    with pytest.raises(LineageError, match="runner failed without exact") as error:
        verify_and_cleanup_isolated_branch(
            intent_path=intent_path, persisted_evidence_path=evidence_path,
            expected_persisted_evidence_sha256=digest, runner=runner,
            production_reader=ProductionReader(), observed_at=NOW,
        )
    assert "secret" not in str(error.value)
    assert len(runner.calls) == 3


def test_fresh_identity_name_reuse_or_different_id_blocks_destroy(tmp_path):
    results = normal_results(branch_id="different-id")
    runner = Runner(results)
    intent_path, evidence_path, digest, _, _ = persisted_files(tmp_path)
    with pytest.raises(LineageError, match="Fresh branch identity differs"):
        verify_and_cleanup_isolated_branch(
            intent_path=intent_path, persisted_evidence_path=evidence_path,
            expected_persisted_evidence_sha256=digest, runner=runner,
            production_reader=ProductionReader(), observed_at=NOW,
        )
    assert (CLI, "db", "destroy", BRANCH, "--yes") not in runner.calls


def test_production_fingerprint_mismatch_before_blocks_destroy(tmp_path):
    intent_path, evidence_path, digest, _, _ = persisted_files(tmp_path)
    runner = Runner(normal_results())
    changed = ProductionReader((("table", "drift", "sql"),))
    with pytest.raises(LineageError, match="Pre-destroy production"):
        verify_and_cleanup_isolated_branch(
            intent_path=intent_path, persisted_evidence_path=evidence_path,
            expected_persisted_evidence_sha256=digest, runner=runner,
            production_reader=changed, observed_at=NOW,
        )
    assert (CLI, "db", "destroy", BRANCH, "--yes") not in runner.calls


def test_production_fingerprint_or_count_mismatch_after_rejects_cleanup_evidence(tmp_path):
    with pytest.raises(LineageError, match="Post-destroy production"):
        execute(tmp_path, reader=ChangingProductionReader())


def bound_failure_files(tmp_path):
    current_intent = intent()
    intent_path = tmp_path / "intent.json"
    intent_path.write_text(json.dumps(_pre_branch_payload(current_intent)), encoding="utf-8")
    payload = {
        "evidence_contract": "oracle-isolated-matrix-lifecycle-failure-v1",
        "intent_id": current_intent.intent_id,
        "artifact_source_commit": current_intent.source_commit,
        "executor_git_commit": "39dc9dcdc07ad3a2b02354d1bca1ae4ae92031eb",
        "branch_identity": asdict(proof()),
        "primary_failure_type": "RuntimeError",
    }
    evidence_path = tmp_path / "failure.json"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    evidence_path.write_bytes(raw)
    return current_intent, intent_path, evidence_path, hashlib.sha256(raw).hexdigest()


def test_bound_failure_cleanup_binds_durable_sha_and_uses_same_strong_proof(tmp_path):
    _, intent_path, evidence_path, digest = bound_failure_files(tmp_path)
    reader = ProductionReader()
    fingerprint, count = _fingerprint(reader)
    runner = Runner(normal_results())
    result = verify_and_cleanup_bound_branch(
        intent_path=intent_path,
        identity_proof=proof(),
        durable_evidence_path=evidence_path,
        expected_durable_evidence_sha256=digest,
        expected_production_fingerprint=fingerprint,
        expected_production_object_count=count,
        runner=runner,
        production_reader=reader,
        observed_at=NOW,
    )
    assert result.persisted_evidence_file_sha256 == digest
    assert result.branch_show_readback == "EXACT_OBSERVED_NOT_FOUND"
    assert result.parent_branch_list_readback == "EXACT_NAME_ABSENCE"
    assert runner.calls.count((CLI, "db", "destroy", BRANCH, "--yes")) == 1


def test_bound_failure_cleanup_rejects_well_formed_wrong_durable_sha_before_cli(tmp_path):
    _, intent_path, evidence_path, _ = bound_failure_files(tmp_path)
    runner = Runner(normal_results())
    with pytest.raises(LineageError, match="file SHA-256 differs"):
        verify_and_cleanup_bound_branch(
            intent_path=intent_path,
            identity_proof=proof(),
            durable_evidence_path=evidence_path,
            expected_durable_evidence_sha256="0" * 64,
            expected_production_fingerprint="a" * 64,
            expected_production_object_count=0,
            runner=runner,
            production_reader=ProductionReader(),
            observed_at=NOW,
        )
    assert runner.calls == []
