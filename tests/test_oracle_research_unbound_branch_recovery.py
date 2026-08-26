from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat

import pytest

from model_lineage import LineageError
from oracle_research_unbound_branch_recovery import (
    recover_created_unbound_branch,
    recover_with_ephemeral_turso_home,
)
from scripts.run_oracle_research_unbound_branch_recovery import (
    CONFIRMATION,
    run_recovery_cli,
)
from scripts.oracle_research_dataset_isolated_matrix import (
    EXPECTED_PRODUCTION_ID,
    EXPECTED_SOURCE_COMMIT,
    MIGRATION_PATH,
    TemporaryBranchApproval,
    _pre_branch_payload,
    build_pre_branch_intent,
)
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    CLI,
    PRODUCTION_LEDGER_SQL,
    PRODUCTION_SCHEMA_SQL,
    CliResult,
    _fingerprint,
)
from turso_read_pipeline import PipelineResult


NOW = datetime(2026, 8, 26, 19, 50, tzinfo=timezone.utc)
BRANCH = "theoracle-codex-oracle-rd-20260826t1945z-d530dc"
BRANCH_ID = "01a03f9c-2f01-74bb-8ba2-6b73aaf7b208"
APPROVAL = "avi-six-action-matrix-20260826"


def approval():
    return TemporaryBranchApproval(APPROVAL, True, True, True, True, True, True)


def intent():
    return build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name=BRANCH,
        approval=approval(),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 19, 45, tzinfo=timezone.utc),
    )


def show(name, database_id, parent=None):
    lines = [
        f"Name:               {name}",
        f"URL:                libsql://{name}.turso.io",
        f"ID:                 {database_id}",
        "Group:              default",
    ]
    if parent is not None:
        lines.append(f"Parent:             {parent}")
    lines += ["Type:               SQLite", "", "Database Instances:", ""]
    return "\n".join(lines)


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


class ProductionReader:
    def __init__(self, schema_generations=None):
        self.schema_generations = list(schema_generations or [(), (), ()])
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        if sql == PRODUCTION_SCHEMA_SQL:
            rows = self.schema_generations.pop(0)
            return PipelineResult(("type", "name", "sql"), rows)
        if sql == PRODUCTION_LEDGER_SQL:
            return PipelineResult(
                (
                    "event_id", "migration_id", "schema_version", "artifact_sha256",
                    "operation", "parent_event_id", "actor", "target_database_id",
                    "evidence_json", "executed_at_utc",
                ),
                (),
            )
        raise AssertionError("unexpected query")


def cli_results(*, branch_id=BRANCH_ID, destroy=None, listing=None):
    branch_show = CliResult(
        (CLI, "db", "show", BRANCH), 0, show(BRANCH, branch_id, "theoracle"), ""
    )
    production_show = CliResult(
        (CLI, "db", "show", "theoracle"),
        0,
        show("theoracle", EXPECTED_PRODUCTION_ID),
        "",
    )
    destroy_argv = (CLI, "db", "destroy", BRANCH, "--yes")
    missing = (
        f"Error: database {BRANCH} not found. "
        "List known databases using turso db list\n"
    )
    return [
        branch_show,
        production_show,
        branch_show,
        production_show,
        destroy or CliResult(destroy_argv, 0, "Destroyed\n", ""),
        CliResult((CLI, "db", "show", BRANCH), 1, "", missing),
        listing or CliResult(
            (CLI, "db", "show", "theoracle", "--branches"),
            0,
            "NAME TYPE GROUP URL\n"
            "theoracle-recovery-prelagv2-20260825t1225z SQLite default "
            "libsql://recovery.turso.io\n",
            "",
        ),
    ]


def artifacts(tmp_path: Path, *, terminal_mutation=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    current = intent()
    intent_path = tmp_path / "intent.json"
    intent_path.write_text(
        json.dumps(_pre_branch_payload(current), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    intent_sha = hashlib.sha256(intent_path.read_bytes()).hexdigest()
    terminal = {
        "artifact_source_commit": current.source_commit,
        "branch_id": None,
        "cleanup": None,
        "cleanup_failure_type": "CleanupError",
        "cleanup_identity_state": "UNRESOLVED_EXHAUSTED",
        "cleanup_reconciliation_diagnostic": {
            "attempt_count": 25,
            "outcome": "UNRESOLVED_EXHAUSTED",
        },
        "create": {
            "ambiguous": False,
            "argv": [CLI, "db", "branch", "theoracle", BRANCH],
            "returncode": 0,
            "stderr_sha256": "a" * 64,
            "stdout_sha256": "b" * 64,
        },
        "evidence_contract": "oracle-isolated-matrix-lifecycle-terminal-v1",
        "execution_evidence_path": None,
        "executor_git_commit": "d" * 40,
        "failure_evidence_file_sha256": None,
        "intent_evidence_sha256": intent_sha,
        "intent_id": current.intent_id,
        "matrix_evidence_file_sha256": None,
        "primary_failure_type": "IdentityContradiction",
    }
    if terminal_mutation:
        terminal_mutation(terminal)
    terminal_path = tmp_path / "terminal.json"
    terminal_path.write_text(
        json.dumps(terminal, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    terminal_sha = hashlib.sha256(terminal_path.read_bytes()).hexdigest()
    return intent_path, intent_sha, terminal_path, terminal_sha


def execute(tmp_path, *, runner=None, reader=None, terminal_mutation=None, **changes):
    intent_path, intent_sha, terminal_path, terminal_sha = artifacts(
        tmp_path, terminal_mutation=terminal_mutation
    )
    expected_reader = ProductionReader([()])
    fingerprint, count = _fingerprint(expected_reader)
    arguments = {
        "intent_path": intent_path,
        "expected_intent_file_sha256": intent_sha,
        "terminal_path": terminal_path,
        "expected_terminal_file_sha256": terminal_sha,
        "expected_approval_id": APPROVAL,
        "expected_branch_name": BRANCH,
        "expected_branch_id": BRANCH_ID,
        "expected_production_fingerprint": fingerprint,
        "expected_production_object_count": count,
        "pre_cleanup_evidence_path": tmp_path / "pre-cleanup.json",
        "final_evidence_path": tmp_path / "final.json",
        "runner": runner or Runner(cli_results()),
        "production_reader": reader or ProductionReader(),
        "observed_at": NOW,
    }
    arguments.update(changes)
    return recover_created_unbound_branch(**arguments), arguments


def test_exact_recovery_persists_atomic_sanitized_pre_and_final_evidence(tmp_path):
    result, arguments = execute(tmp_path)
    runner = arguments["runner"]
    destroy = (CLI, "db", "destroy", BRANCH, "--yes")
    assert runner.calls.count(destroy) == 1
    assert len(runner.calls) == 7
    assert result.cleanup.destroy_result == "ZERO_EXIT_PROVEN_BY_READBACK"
    assert result.cleanup.branch_show_readback == "EXACT_OBSERVED_NOT_FOUND"
    assert result.cleanup.parent_branch_list_readback == "EXACT_NAME_ABSENCE"
    for key in ("pre_cleanup_evidence_path", "final_evidence_path"):
        path = arguments[key]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload)
        assert "libsql://" not in serialized
        assert "token" not in serialized.lower()
        assert "response_bodies_included\": true" not in serialized.lower()
    pre = json.loads(arguments["pre_cleanup_evidence_path"].read_text())
    assert pre["intent_file_sha256"] == result.intent_file_sha256
    assert pre["terminal_file_sha256"] == result.terminal_file_sha256
    assert pre["branch_identity"]["branch_id"] == BRANCH_ID
    final = json.loads(arguments["final_evidence_path"].read_text())
    assert final == asdict(result)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda x: x.__setitem__("branch_id", "unbound-was-not-null"), "branch_id"),
        (lambda x: x["create"].__setitem__("returncode", 1), "exact creation"),
        (lambda x: x.__setitem__("primary_failure_type", "Other"), "primary_failure_type"),
        (lambda x: x.__setitem__("intent_evidence_sha256", "f" * 64), "intent_evidence"),
    ],
)
def test_terminal_contract_mismatch_fails_before_any_cli_call(tmp_path, mutation, match):
    runner = Runner([])
    with pytest.raises(LineageError, match=match):
        execute(tmp_path, runner=runner, terminal_mutation=mutation)
    assert runner.calls == []
    assert not (tmp_path / "pre-cleanup.json").exists()


def test_external_intent_or_terminal_hash_mismatch_fails_before_cli(tmp_path):
    intent_path, intent_sha, terminal_path, terminal_sha = artifacts(tmp_path)
    expected_reader = ProductionReader([()])
    fingerprint, count = _fingerprint(expected_reader)
    base = dict(
        intent_path=intent_path,
        expected_intent_file_sha256=intent_sha,
        terminal_path=terminal_path,
        expected_terminal_file_sha256=terminal_sha,
        expected_approval_id=APPROVAL,
        expected_branch_name=BRANCH,
        expected_branch_id=BRANCH_ID,
        expected_production_fingerprint=fingerprint,
        expected_production_object_count=count,
        pre_cleanup_evidence_path=tmp_path / "pre.json",
        final_evidence_path=tmp_path / "final.json",
        runner=Runner([]),
        production_reader=ProductionReader(),
        observed_at=NOW,
    )
    for field in ("expected_intent_file_sha256", "expected_terminal_file_sha256"):
        changed = dict(base)
        changed[field] = "0" * 64
        with pytest.raises(LineageError, match="SHA-256 differs"):
            recover_created_unbound_branch(**changed)


def test_fresh_same_name_with_different_branch_id_fails_before_pre_evidence_or_destroy(tmp_path):
    runner = Runner(cli_results(branch_id="different-branch-id")[:2])
    with pytest.raises(LineageError, match="Fresh branch ID differs"):
        execute(tmp_path, runner=runner)
    assert len(runner.calls) == 2
    assert not (tmp_path / "pre-cleanup.json").exists()


def test_approval_and_exact_branch_name_are_pinned_before_cli(tmp_path):
    for field, value, match in (
        ("expected_approval_id", "different-approval", "approval ID differs"),
        ("expected_branch_name", "theoracle-codex-oracle-rd-20260826t1946z-aabbcc", "target differs"),
    ):
        runner = Runner([])
        with pytest.raises(LineageError, match=match):
            execute(tmp_path / field, runner=runner, **{field: value})
        assert runner.calls == []


def test_production_fingerprint_mismatch_fails_before_pre_evidence_and_destroy(tmp_path):
    runner = Runner(cli_results()[:2])
    reader = ProductionReader([(("table", "drift", "sql"),)])
    with pytest.raises(LineageError, match="production fingerprint"):
        execute(tmp_path, runner=runner, reader=reader)
    assert len(runner.calls) == 2
    assert not (tmp_path / "pre-cleanup.json").exists()


def test_post_destroy_production_drift_fails_closed_with_pre_evidence_retained(tmp_path):
    reader = ProductionReader([(), (), (("table", "drift", "sql"),)])
    with pytest.raises(LineageError, match="Post-destroy production fingerprint"):
        execute(tmp_path, reader=reader)
    assert (tmp_path / "pre-cleanup.json").exists()
    assert not (tmp_path / "final.json").exists()


def test_destroy_permission_error_never_attempts_absence_reconciliation(tmp_path):
    destroy_argv = (CLI, "db", "destroy", BRANCH, "--yes")
    results = cli_results(
        destroy=CliResult(destroy_argv, 1, "", "permission denied")
    )
    runner = Runner(results[:5])
    with pytest.raises(LineageError, match="permission, network, parse"):
        execute(tmp_path, runner=runner)
    assert runner.calls[-1] == destroy_argv
    assert runner.calls.count(destroy_argv) == 1
    assert (tmp_path / "pre-cleanup.json").exists()
    assert not (tmp_path / "final.json").exists()


def test_existing_pre_cleanup_target_blocks_destroy(tmp_path):
    pre = tmp_path / "pre-cleanup.json"
    pre.write_text("preserve", encoding="utf-8")
    runner = Runner(cli_results()[:2])
    with pytest.raises(LineageError, match="already exists"):
        execute(tmp_path, runner=runner, pre_cleanup_evidence_path=pre)
    assert len(runner.calls) == 2
    assert pre.read_text() == "preserve"


def test_ephemeral_wrapper_constructs_injected_runner_inside_hardened_home(
    tmp_path, monkeypatch
):
    events = []

    @contextmanager
    def fake_home(path, *, expected_owner_uid, temp_root):
        events.append(("enter", path, expected_owner_uid, temp_root))
        yield tmp_path / "home"
        events.append(("exit",))

    marker = object()

    def fake_recovery(**kwargs):
        events.append(("recover", kwargs["runner"], kwargs["production_reader"]))
        return marker

    monkeypatch.setattr(
        "oracle_research_unbound_branch_recovery.ephemeral_turso_home", fake_home
    )
    monkeypatch.setattr(
        "oracle_research_unbound_branch_recovery.recover_created_unbound_branch",
        fake_recovery,
    )
    runner = object()
    reader = object()
    result = recover_with_ephemeral_turso_home(
        turso_settings_path=tmp_path / "settings.json",
        turso_settings_owner_uid=123,
        runner_factory=lambda: runner,
        production_reader=reader,
        temp_root=tmp_path,
        observed_at=NOW,
    )
    assert result is marker
    assert events[0][0] == "enter"
    assert events[1] == ("recover", runner, reader)
    assert events[2] == ("exit",)


def cli_fixture(tmp_path: Path):
    intent_path, intent_sha, terminal_path, terminal_sha = artifacts(tmp_path)
    production_env = tmp_path / "production.env"
    production_env.write_text("test-only", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text("test-only", encoding="utf-8")
    expected_reader = ProductionReader([()])
    fingerprint, count = _fingerprint(expected_reader)
    args = [
        "--intent-json", str(intent_path),
        "--intent-file-sha256", intent_sha,
        "--terminal-json", str(terminal_path),
        "--terminal-file-sha256", terminal_sha,
        "--approval-id", APPROVAL,
        "--branch-name", BRANCH,
        "--branch-id", BRANCH_ID,
        "--production-fingerprint-sha256", fingerprint,
        "--production-object-count", str(count),
        "--production-env-file", str(production_env),
        "--turso-settings-file", str(settings),
        "--turso-settings-owner-uid", "123",
        "--pre-cleanup-evidence-json", str(tmp_path / "cli-pre.json"),
        "--final-evidence-json", str(tmp_path / "cli-final.json"),
        "--confirm-exact-cleanup", CONFIRMATION,
    ]
    return args, fingerprint


def replace_cli_arg(args, flag, value):
    changed = list(args)
    changed[changed.index(flag) + 1] = value
    return changed


def direct_recovery_wrapper(**kwargs):
    kwargs.pop("turso_settings_path")
    kwargs.pop("turso_settings_owner_uid")
    runner = kwargs.pop("runner_factory")()
    return recover_created_unbound_branch(runner=runner, **kwargs)


def execute_cli(tmp_path, *, args=None, runner=None, reader=None):
    generated, _ = cli_fixture(tmp_path)
    selected_args = generated if args is None else args
    selected_runner = runner or Runner(cli_results())
    selected_reader = reader or ProductionReader()
    result = run_recovery_cli(
        selected_args,
        now=lambda tz: NOW,
        credentials_loader=lambda path: (
            "libsql://theoracle.example",
            "test-only-token",
            "https://theoracle.example/v2/pipeline",
        ),
        production_reader_factory=lambda endpoint, token: selected_reader,
        cli_runner_factory=lambda: selected_runner,
        recovery_wrapper=direct_recovery_wrapper,
    )
    return result, selected_runner


def test_cli_requires_every_identity_hash_and_confirmation_without_defaults(tmp_path):
    args, _ = cli_fixture(tmp_path)
    index = args.index("--branch-id")
    del args[index:index + 2]
    with pytest.raises(SystemExit):
        execute_cli(tmp_path, args=args, runner=Runner([]))


def test_cli_full_behavior_reaches_one_exact_cleanup_and_writes_both_evidence_files(tmp_path):
    result, runner = execute_cli(tmp_path)
    destroy = (CLI, "db", "destroy", BRANCH, "--yes")
    assert runner.calls.count(destroy) == 1
    assert result.cleanup.production_oracle_object_count == 0
    assert (tmp_path / "cli-pre.json").exists()
    assert (tmp_path / "cli-final.json").exists()


def test_cli_wrong_branch_id_fails_before_destroy(tmp_path):
    args, _ = cli_fixture(tmp_path)
    args = replace_cli_arg(args, "--branch-id", "different-branch-id")
    runner = Runner(cli_results()[:2])
    with pytest.raises(LineageError, match="Fresh branch ID differs"):
        execute_cli(tmp_path, args=args, runner=runner)
    assert all(call[1:3] != ("db", "destroy") for call in runner.calls)


def test_cli_wrong_bound_hash_fails_before_any_cli_call(tmp_path):
    args, _ = cli_fixture(tmp_path)
    args = replace_cli_arg(args, "--terminal-file-sha256", "0" * 64)
    runner = Runner([])
    with pytest.raises(LineageError, match="SHA-256 differs"):
        execute_cli(tmp_path, args=args, runner=runner)
    assert runner.calls == []


def test_cli_wrong_production_fingerprint_fails_before_destroy(tmp_path):
    args, fingerprint = cli_fixture(tmp_path)
    wrong = "f" * 64 if fingerprint != "f" * 64 else "e" * 64
    args = replace_cli_arg(args, "--production-fingerprint-sha256", wrong)
    runner = Runner(cli_results()[:2])
    with pytest.raises(LineageError, match="production fingerprint"):
        execute_cli(tmp_path, args=args, runner=runner)
    assert all(call[1:3] != ("db", "destroy") for call in runner.calls)


def test_cli_existing_evidence_target_fails_before_credentials_or_cli(tmp_path):
    args, _ = cli_fixture(tmp_path)
    pre = tmp_path / "cli-pre.json"
    pre.write_text("preserve", encoding="utf-8")
    credential_calls = []
    with pytest.raises(LineageError, match="already exists"):
        run_recovery_cli(
            args,
            now=lambda tz: NOW,
            credentials_loader=lambda path: credential_calls.append(path),
            cli_runner_factory=lambda: Runner([]),
            recovery_wrapper=direct_recovery_wrapper,
        )
    assert credential_calls == []
    assert pre.read_text(encoding="utf-8") == "preserve"
