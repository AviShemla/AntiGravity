import hashlib
import io
import json
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from model_lineage import LineageError
from scripts.oracle_research_dataset_isolated_matrix import (
    BEHAVIOR_ASSERTION_IDS,
    EXPECTED_PRODUCTION_ID,
    EXPECTED_PRODUCTION_NAME,
    EXPECTED_SCHEMA_OBJECTS,
    EXPECTED_SOURCE_COMMIT,
    MIGRATION_PATH,
    IsolatedBranchIdentity,
    TemporaryBranchApproval,
    _pre_branch_payload,
    build_pre_branch_intent,
    build_isolated_matrix_plan,
    execute_with_adapter,
)
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    APPLY_READBACK_SQL,
    PRODUCTION_LEDGER_SQL,
    PRODUCTION_SCHEMA_SQL,
    RESIDUE_READBACK_SQL,
    ROLLBACK_READBACK_SQL,
    SCHEMA_READBACK_SQL,
    BranchIdentityProof,
    CLI,
    CliResult,
    IsolatedMatrixExecutionAdapter,
    MatrixCredentials,
    TursoMatrixBranch,
    _env_file,
    _probe_sql,
    build_redacted_evidence,
    derive_branch_identity_from_cli,
    exact_cleanup_command,
    load_pre_branch_intent,
    main,
    validate_credentials,
)
from turso_read_pipeline import PipelineResult


def plan():
    return build_isolated_matrix_plan(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch=IsolatedBranchIdentity(
            "theoracle-codex-oracle-rd-20260826t1700z-a1b2c3",
            "01a-disposable-matrix",
            "theoracle",
            EXPECTED_PRODUCTION_ID,
        ),
        approval=TemporaryBranchApproval(
            "avi-six-action-matrix-20260826", True, True, True, True, True, True
        ),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc),
    )


def intent():
    return build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name="theoracle-codex-oracle-rd-20260826t1700z-a1b2c3",
        approval=TemporaryBranchApproval(
            "avi-six-action-matrix-20260826", True, True, True, True, True, True
        ),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc),
    )


def proof(**changes):
    values = {
        "proof_source": "turso-cli-v1.0.32-db-show-text",
        "branch_name": plan().branch.branch_name,
        "branch_id": plan().branch.branch_id,
        "parent_name": "theoracle",
        "parent_id": EXPECTED_PRODUCTION_ID,
        "observed_at_utc": "2026-08-26T16:59:00Z",
        "branch_show_sha256": "a" * 64,
        "production_show_sha256": "b" * 64,
    }
    values.update(changes)
    return BranchIdentityProof(**values)


def _show(name, database_id, *, parent=None):
    lines = [
        f"Name:               {name}",
        f"URL:                libsql://{name}.turso.io",
        f"ID:                 {database_id}",
        "Group:              default",
    ]
    if parent is not None:
        lines.append(f"Parent:             {parent}")
    lines.extend(
        [
            "Locations:          aws-eu-west-1",
            "Size:               1.9 GB",
            "Archived:           No",
            "Bytes Synced:       0 B",
            "Is Schema:          No",
            "Type:               SQLite",
            "Delete Protection:  No",
            "",
            "Database Instances:",
            "NAME              TYPE        LOCATION",
            "aws-eu-west-1     primary     aws-eu-west-1",
            "",
        ]
    )
    return "\n".join(lines)


class Cli:
    def __init__(self, branch_stdout=None, production_stdout=None):
        self.calls = []
        self.branch_stdout = branch_stdout or _show(
            intent().branch_name, "01a-disposable-matrix", parent=EXPECTED_PRODUCTION_NAME
        )
        self.production_stdout = production_stdout or _show(
            EXPECTED_PRODUCTION_NAME, EXPECTED_PRODUCTION_ID
        )
        self.returncode = 0
        self.stderr = ""
        self.returned_argv = None

    def run(self, argv):
        self.calls.append(argv)
        stdout = self.branch_stdout if argv[-1] == intent().branch_name else self.production_stdout
        return CliResult(
            self.returned_argv or argv,
            self.returncode,
            stdout,
            self.stderr,
        )


def test_cli_identity_is_derived_from_two_exact_v1032_show_outputs():
    runner = Cli()
    observed = datetime(2026, 8, 26, 17, 1, tzinfo=timezone.utc)
    result = derive_branch_identity_from_cli(intent(), runner, observed_at=observed)
    assert runner.calls == [
        (CLI, "db", "show", intent().branch_name),
        (CLI, "db", "show", EXPECTED_PRODUCTION_NAME),
    ]
    assert result.branch_name == intent().branch_name
    assert result.branch_id == "01a-disposable-matrix"
    assert result.parent_name == EXPECTED_PRODUCTION_NAME
    assert result.parent_id == EXPECTED_PRODUCTION_ID
    assert len(result.branch_show_sha256) == 64
    assert len(result.production_show_sha256) == 64
    result.validate(
        IsolatedBranchIdentity(
            intent().branch_name,
            result.branch_id,
            EXPECTED_PRODUCTION_NAME,
            EXPECTED_PRODUCTION_ID,
        ),
        intent_created_at_utc=intent().created_at_utc,
        verified_at=observed,
    )


@pytest.mark.parametrize(
    "branch_output,production_output,match",
    [
        (
            _show(intent().branch_name, "01a-disposable-matrix", parent=EXPECTED_PRODUCTION_NAME)
            .replace("ID:                 01a-disposable-matrix", ""),
            None,
            "missing required",
        ),
        (
            _show(intent().branch_name, "01a-disposable-matrix", parent=EXPECTED_PRODUCTION_NAME)
            .replace(
                "ID:                 01a-disposable-matrix",
                "ID:                 01a-disposable-matrix\nID:                 duplicate",
            ),
            None,
            "duplicate field",
        ),
        (
            _show(intent().branch_name, "01a-disposable-matrix", parent=None),
            None,
            "missing required",
        ),
        (
            "hand-authored identity",
            None,
            "ambiguous header",
        ),
        (
            None,
            _show(EXPECTED_PRODUCTION_NAME, EXPECTED_PRODUCTION_ID, parent="unexpected"),
            "unexpectedly reports a parent",
        ),
    ],
)
def test_cli_identity_rejects_missing_duplicate_ambiguous_and_parent_drift(
    branch_output, production_output, match
):
    runner = Cli(branch_output, production_output)
    with pytest.raises(LineageError, match=match):
        derive_branch_identity_from_cli(
            intent(),
            runner,
            observed_at=datetime(2026, 8, 26, 17, 1, tzinfo=timezone.utc),
        )


def test_cli_identity_rejects_command_exit_stderr_argv_and_stale_time():
    observed = datetime(2026, 8, 26, 17, 1, tzinfo=timezone.utc)
    for attribute, value, match in (
        ("returncode", 1, "did not succeed"),
        ("stderr", "warning", "stderr"),
        ("returned_argv", (CLI, "db", "show", "other"), "command identity"),
    ):
        runner = Cli()
        setattr(runner, attribute, value)
        with pytest.raises(LineageError, match=match):
            derive_branch_identity_from_cli(intent(), runner, observed_at=observed)
    with pytest.raises(LineageError, match="predates"):
        derive_branch_identity_from_cli(
            intent(),
            Cli(),
            observed_at=datetime(2026, 8, 26, 16, 59, tzinfo=timezone.utc),
        )
    stale = proof(observed_at_utc="2026-08-26T17:00:00Z")
    with pytest.raises(LineageError, match="stale"):
        stale.validate(
            plan().branch,
            intent_created_at_utc=intent().created_at_utc,
            verified_at=datetime(2026, 8, 26, 17, 6, tzinfo=timezone.utc),
        )


def test_preserved_intent_file_is_rebuilt_and_exactly_bound(tmp_path):
    payload = _pre_branch_payload(intent())
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_pre_branch_intent(path) == intent()
    for key, value in (
        ("intent_id", "oracle-rd-pre-branch-intent-0000000000000000"),
        ("approval_id", "different-approval"),
        ("created_at_utc", "2026-08-26T17:00:01Z"),
        ("source_commit", "0" * 40),
    ):
        changed = dict(payload)
        changed[key] = value
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(LineageError):
            load_pre_branch_intent(path)
    path.write_text('{"phase":"PRE_BRANCH_INTENT","phase":"duplicate"}', encoding="utf-8")
    with pytest.raises(LineageError, match="duplicate key"):
        load_pre_branch_intent(path)


class ProductionReader:
    def __init__(self):
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        assert sql.lstrip().upper().startswith("SELECT")
        if sql == PRODUCTION_SCHEMA_SQL:
            return PipelineResult(("type", "name", "sql"), ())
        if sql == PRODUCTION_LEDGER_SQL:
            return PipelineResult(
                ("event_id", "migration_id", "schema_version", "artifact_sha256",
                 "operation", "parent_event_id", "actor", "target_database_id",
                 "evidence_json", "executed_at_utc"),
                (),
            )
        raise AssertionError("unexpected production query")


class Branch:
    def __init__(self, matrix_plan):
        self.plan = matrix_plan
        self.applied = []
        self.probes = []
        self.rollback_plans = []

    def apply(self, received):
        self.applied.append(received)

    def run_probe(self, probe):
        self.probes.append(probe)
        return True

    def append_logical_rollback(self, received):
        self.rollback_plans.append(received)

    def select(self, sql, args):
        if sql == SCHEMA_READBACK_SQL:
            return PipelineResult(("name",), tuple((name,) for name in EXPECTED_SCHEMA_OBJECTS))
        if sql == APPLY_READBACK_SQL:
            return PipelineResult(("event_id", "event_count"), ((self.plan.apply_event_id, 1),))
        if sql == ROLLBACK_READBACK_SQL:
            return PipelineResult(
                ("event_id", "parent_event_id", "event_count"),
                ((self.plan.rollback_event_id, self.plan.apply_event_id, 1),),
            )
        if sql == RESIDUE_READBACK_SQL:
            return PipelineResult(("versions", "providers", "events", "ddl_probe"), ((0, 0, 0, 0),))
        raise AssertionError("unexpected branch query")


def test_adapter_executes_all_26_assertions_and_validates_complete_readback():
    matrix_plan = plan()
    branch = Branch(matrix_plan)
    production = ProductionReader()
    readback = execute_with_adapter(
        matrix_plan, IsolatedMatrixExecutionAdapter(branch, production)
    )
    assert branch.applied == [matrix_plan]
    assert branch.rollback_plans == [matrix_plan]
    assert len(branch.probes) == 24
    assert len(readback.assertion_results) == 26
    assert set(readback.assertion_results) == set(BEHAVIOR_ASSERTION_IDS)
    assert all(readback.assertion_results.values())
    assert len(production.calls) == 4
    assert all(sql.startswith("SELECT") for sql, _ in production.calls)
    assert readback.production_fingerprint_before == readback.production_fingerprint_after


def test_probe_failure_still_appends_logical_rollback_and_rereads_production():
    matrix_plan = plan()
    branch = Branch(matrix_plan)
    production = ProductionReader()

    def fail(_probe):
        raise RuntimeError("injected probe failure")

    branch.run_probe = fail
    with pytest.raises(RuntimeError, match="injected probe failure"):
        IsolatedMatrixExecutionAdapter(branch, production).run(matrix_plan)
    assert branch.rollback_plans == [matrix_plan]
    assert len(production.calls) == 4


def test_probe_contract_is_exact_and_every_fixture_action_is_rollback_scoped():
    probes = _probe_sql(plan())
    assert len(probes) == 24
    assert len({probe.assertion_id for probe in probes}) == 24
    assert {probe.assertion_id for probe in probes} == set(BEHAVIOR_ASSERTION_IDS) - {
        "migration_apply_event_exact",
        "ambiguous_apply_requires_exact_readback",
    }
    assert sum(probe.expect_error for probe in probes) == 20
    assert all(not probe.action_sql.lstrip().upper().startswith("SELECT") for probe in probes)


def test_redacted_evidence_is_deterministic_hash_bound_and_secret_free():
    matrix_plan = plan()
    readback = execute_with_adapter(
        matrix_plan, IsolatedMatrixExecutionAdapter(Branch(matrix_plan), ProductionReader())
    )
    first = build_redacted_evidence(matrix_plan, readback)
    second = build_redacted_evidence(matrix_plan, readback)
    assert first == second
    claimed = first.pop("evidence_sha256")
    canonical = json.dumps(
        first, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    assert claimed == hashlib.sha256(canonical).hexdigest()
    serialized = json.dumps(first).lower()
    assert "auth_token" not in serialized
    assert "bearer" not in serialized
    assert "libsql://" not in serialized
    assert "/v2/pipeline" not in serialized


@pytest.mark.parametrize(
    "change,match",
    [
        ({"branch_id": EXPECTED_PRODUCTION_ID}, "differs"),
        ({"parent_id": "wrong"}, "differs"),
        ({"parent_name": "other"}, "differs"),
        ({"proof_source": "manual"}, "source"),
        ({"observed_at_utc": "not-time"}, "timestamp"),
    ],
)
def test_exact_branch_and_parent_proof_is_mandatory(change, match):
    with pytest.raises((LineageError, ValueError), match=match):
        proof(**change).validate(plan().branch)


def test_credentials_reject_production_target_shared_token_and_wrong_host():
    matrix_plan = plan()
    good = MatrixCredentials(
        f"libsql://{matrix_plan.branch.branch_name}.turso.io",
        "branch-token",
        "libsql://theoracle.turso.io",
        "production-read-token",
    )
    branch_endpoint, production_endpoint = validate_credentials(matrix_plan, proof(), good)
    assert matrix_plan.branch.branch_name in branch_endpoint
    assert branch_endpoint != production_endpoint
    cases = (
        MatrixCredentials("libsql://theoracle.turso.io", "branch", "libsql://theoracle.turso.io", "prod"),
        MatrixCredentials(good.branch_url, "same", good.production_url, "same"),
        MatrixCredentials("libsql://wrong.turso.io", "branch", good.production_url, "prod"),
        MatrixCredentials(good.branch_url, "", good.production_url, "prod"),
    )
    for value in cases:
        with pytest.raises(LineageError):
            validate_credentials(matrix_plan, proof(), value)


def test_cleanup_command_is_separate_exact_target_and_never_executes():
    command = exact_cleanup_command(proof())
    assert command == (
        "/home/codexops/.turso/turso",
        "db",
        "destroy",
        plan().branch.branch_name,
        "--yes",
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "proof.json"
        path.write_text(json.dumps(proof().__dict__), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            assert main(["cleanup-command", "--branch-proof-json", str(path)]) == 0
        payload = json.loads(output.getvalue())
        assert payload["command"] == list(command)
        assert payload["executed"] is False


def test_env_files_are_explicit_strict_and_do_not_read_process_environment():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "branch.env"
        path.write_text(
            "TURSO_ISOLATED_DATABASE_URL=libsql://branch.turso.io\n"
            "TURSO_ISOLATED_AUTH_TOKEN='secret-placeholder'\n",
            encoding="utf-8",
        )
        assert _env_file(path) == {
            "TURSO_ISOLATED_DATABASE_URL": "libsql://branch.turso.io",
            "TURSO_ISOLATED_AUTH_TOKEN": "secret-placeholder",
        }
        path.write_text("KEY=one\nKEY=two\n", encoding="utf-8")
        with pytest.raises(LineageError, match="duplicate"):
            _env_file(path)


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class TransactionSession:
    def __init__(self, rejected_sql=None):
        self.calls = []
        self.rejected_sql = rejected_sql
        self.counter = 0

    def post(self, endpoint, *, headers, json, timeout):
        self.calls.append((endpoint, headers, json, timeout))
        request = json["requests"][0]
        sql = request.get("stmt", {}).get("sql", "")
        self.counter += 1
        if sql == self.rejected_sql:
            result = {"type": "error", "error": {"message": "expected rejection"}}
        else:
            result = {
                "type": "ok",
                "response": {
                    "type": "execute",
                    "result": {"cols": [], "rows": [], "affected_row_count": 1},
                },
            }
        payload = {"results": [result]}
        if sql not in {"ROLLBACK", "COMMIT"}:
            payload["baton"] = f"baton-{self.counter}"
        return Response(payload)


class AtomicSession(TransactionSession):
    def post(self, endpoint, *, headers, json, timeout):
        self.calls.append((endpoint, headers, json, timeout))
        self.counter += 1
        results = [
            {
                "type": "ok",
                "response": {
                    "type": "execute",
                    "result": {"cols": [], "rows": [], "affected_row_count": 1},
                },
            }
            for _ in json["requests"]
        ]
        sql = json["requests"][0].get("stmt", {}).get("sql", "")
        payload = {"results": results}
        if sql not in {"ROLLBACK", "COMMIT"}:
            payload["baton"] = f"baton-{self.counter}"
        return Response(payload)


@pytest.mark.parametrize("expected_error", [False, True])
def test_concrete_turso_probe_uses_explicit_transaction_and_verified_rollback(expected_error):
    probe_item = next(
        probe for probe in _probe_sql(plan()) if probe.expect_error is expected_error
    )
    session = TransactionSession(probe_item.action_sql if expected_error else None)
    branch = TursoMatrixBranch(
        f"https://{plan().branch.branch_name}.turso.io/v2/pipeline",
        "injected-placeholder",
        session=session,
    )
    assert branch.run_probe(probe_item)
    sqls = [call[2]["requests"][0].get("stmt", {}).get("sql") for call in session.calls]
    assert sqls[0] == "BEGIN IMMEDIATE"
    assert sqls[-1] == "ROLLBACK"
    assert "COMMIT" not in sqls
    assert all(call[1]["Authorization"] == "Bearer injected-placeholder" for call in session.calls)


def test_logical_rollback_event_is_exact_append_and_separate_commit():
    session = TransactionSession()
    branch = TursoMatrixBranch(
        f"https://{plan().branch.branch_name}.turso.io/v2/pipeline",
        "injected-placeholder",
        session=session,
    )
    branch.append_logical_rollback(plan())
    sqls = [call[2]["requests"][0].get("stmt", {}).get("sql") for call in session.calls]
    assert sqls[0] == "BEGIN IMMEDIATE"
    assert "INSERT INTO schema_migration_events_v2" in sqls[1]
    assert sqls[-1] == "COMMIT"
    args = session.calls[1][2]["requests"][0]["stmt"]["args"]
    texts = [value.get("value") for value in args]
    assert plan().rollback_event_id in texts
    assert plan().apply_event_id in texts
    assert "ROLLBACK" in texts
    evidence = json.loads(texts[-2])
    assert evidence["logical_rollback"] is True
    assert evidence["apply_event_id"] == plan().apply_event_id


def test_concrete_apply_uses_one_atomic_26_statement_plus_ledger_transaction():
    session = AtomicSession()
    branch = TursoMatrixBranch(
        f"https://{plan().branch.branch_name}.turso.io/v2/pipeline",
        "injected-placeholder",
        session=session,
    )
    branch.apply(plan())
    assert len(session.calls) == 3
    begin, batch, commit = (call[2]["requests"] for call in session.calls)
    assert begin[0]["stmt"]["sql"] == "BEGIN IMMEDIATE"
    assert len(batch) == 27
    assert all(request["type"] == "execute" for request in batch)
    assert "INSERT INTO schema_migration_events_v2" in batch[-1]["stmt"]["sql"]
    assert commit[0]["stmt"]["sql"] == "COMMIT"
