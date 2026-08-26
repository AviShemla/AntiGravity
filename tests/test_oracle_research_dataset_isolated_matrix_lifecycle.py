import json
import os
from pathlib import Path
import stat
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import subprocess

import pytest

from scripts.oracle_research_dataset_isolated_matrix import (
    BEHAVIOR_ASSERTION_IDS,
    EXPECTED_PRODUCTION_ID,
    EXPECTED_SOURCE_COMMIT,
    EXPECTED_MIGRATION_SHA256,
    EXPECTED_SCHEMA_OBJECTS,
    IsolatedMatrixReadback,
    MIGRATION_PATH,
    TemporaryBranchApproval,
    build_pre_branch_intent,
)
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    CLI,
    PRODUCTION_LEDGER_SQL,
    PRODUCTION_SCHEMA_SQL,
    _fingerprint,
    build_redacted_evidence,
)
from turso_read_pipeline import PipelineResult
from scripts.oracle_research_dataset_isolated_matrix_lifecycle import (
    EXPECTED_EXECUTOR_GIT_COMMIT,
    NOT_FOUND_TEMPLATE,
    CleanupError,
    CommandResult,
    LifecycleArtifacts,
    LifecycleError,
    IdentityPropagationPending,
    RepositoryGitIdentity,
    atomic_write_redacted_json,
    run_disposable_matrix_lifecycle,
)


from datetime import datetime, timedelta, timezone


NOW = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)
TOKEN = b"secret-lifecycle-test-token.value\n"


def intent():
    return build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name="theoracle-codex-oracle-rd-20260826t1755z-a1b2c3",
        approval=TemporaryBranchApproval(
            "avi-six-action-matrix-20260826", True, True, True, True, True, True
        ),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 17, 55, tzinfo=timezone.utc),
    )


def _show(name, database_id, *, parent=None):
    lines = [
        f"Name:               {name}",
        f"URL:                libsql://{name}-avishe.aws-eu-west-1.turso.io",
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
    return "\n".join(lines).encode()


class Git:
    def __init__(self, value=EXPECTED_EXECUTOR_GIT_COMMIT):
        self.value = value

    def head(self):
        return self.value


class Cli:
    def __init__(
        self,
        *,
        create="success",
        destroy="success",
        wrong_create_argv=False,
        identity_absent_shows=0,
        partial_identity_shows=0,
    ):
        self.exists = False
        self.branch_id = "01a-disposable-lifecycle"
        self.create_behavior = create
        self.destroy_behavior = destroy
        self.create_count = 0
        self.token_count = 0
        self.destroy_count = 0
        self.calls = []
        self.force_list_present = False
        self.malformed_show = False
        self.wrong_create_argv = wrong_create_argv
        self.identity_absent_shows = identity_absent_shows
        self.partial_identity_shows = partial_identity_shows
        self.branch_show_count = 0

    def result(self, argv, code=0, stdout=b"", stderr=b"", ambiguous=False):
        return CommandResult(tuple(argv), code, stdout, stderr, ambiguous)

    def run(self, argv, *, sensitive_stdout=False):
        argv = tuple(argv)
        self.calls.append((argv, sensitive_stdout))
        create = intent().commands[0].argv
        token = intent().commands[2].argv
        destroy = (CLI, "db", "destroy", intent().branch_name, "--yes")
        if argv == create:
            self.create_count += 1
            if self.create_behavior == "success":
                self.exists = True
                returned_argv = argv + ("unexpected",) if self.wrong_create_argv else argv
                return self.result(returned_argv, stdout=b"Created database\n")
            if self.create_behavior == "ambiguous_created":
                self.exists = True
                return self.result(argv, code=-1, ambiguous=True)
            return self.result(argv, code=1, stderr=b"create rejected\n")
        if argv == (CLI, "db", "show", intent().branch_name):
            self.branch_show_count += 1
            if self.exists:
                if self.identity_absent_shows > 0:
                    self.identity_absent_shows -= 1
                    return self.result(
                        argv,
                        code=1,
                        stderr=(NOT_FOUND_TEMPLATE.format(name=intent().branch_name) + "\n").encode(),
                    )
                if self.partial_identity_shows > 0:
                    self.partial_identity_shows -= 1
                    return self.result(
                        argv,
                        stdout=f"Name:               {intent().branch_name}\n".encode(),
                    )
                if self.malformed_show:
                    return self.result(argv, stdout=b"ambiguous identity\n")
                return self.result(
                    argv,
                    stdout=_show(intent().branch_name, self.branch_id, parent="theoracle"),
                )
            return self.result(
                argv,
                code=1,
                stderr=(NOT_FOUND_TEMPLATE.format(name=intent().branch_name) + "\n").encode(),
            )
        if argv == (CLI, "db", "show", "theoracle"):
            return self.result(argv, stdout=_show("theoracle", EXPECTED_PRODUCTION_ID))
        if argv == token:
            self.token_count += 1
            assert sensitive_stdout is True
            return self.result(argv, stdout=TOKEN)
        if argv == destroy:
            self.destroy_count += 1
            if self.destroy_behavior in {"success", "ambiguous_destroyed"}:
                self.exists = False
            if self.destroy_behavior == "ambiguous_destroyed":
                return self.result(argv, code=-1, ambiguous=True)
            if self.destroy_behavior == "failed_present":
                return self.result(argv, code=1, stderr=b"destroy rejected\n")
            return self.result(argv, stdout=b"Destroyed database\n")
        if argv == (CLI, "db", "show", "theoracle", "--branches"):
            present = self.exists or self.force_list_present
            rows = ["NAME TYPE GROUP URL"]
            if present:
                rows.append(
                    f"{intent().branch_name} SQLite default "
                    f"libsql://{intent().branch_name}-avishe.aws-eu-west-1.turso.io"
                )
            rows.append(
                "theoracle-recovery-prelagv2-20260825t1225z SQLite default "
                "libsql://theoracle-recovery-prelagv2-20260825t1225z-avishe.turso.io"
            )
            return self.result(argv, stdout=("\n".join(rows) + "\n").encode())
        raise AssertionError(f"unexpected command {argv}")


class ProductionReader:
    def execute(self, sql, args):
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


class Matrix:
    def __init__(self, failure=None, callback=None, reader=None):
        self.failure = failure
        self.callback = callback
        self.reader = reader
        self.calls = []

    def execute(self, plan, proof, secrets):
        self.calls.append((plan, proof, secrets))
        if self.callback:
            self.callback()
        if self.failure:
            raise self.failure
        fingerprint, count = _fingerprint(self.reader)
        readback = IsolatedMatrixReadback(
            plan.branch.branch_name, plan.branch.branch_id,
            EXPECTED_MIGRATION_SHA256, plan.statement_count,
            EXPECTED_SCHEMA_OBJECTS, plan.apply_event_id, 1,
            {key: True for key in BEHAVIOR_ASSERTION_IDS},
            plan.rollback_event_id, plan.apply_event_id, 1,
            0, 0, 0, 0, fingerprint, fingerprint, count, count,
        )
        return build_redacted_evidence(plan, readback, intent=intent(), proof=proof)


def run(tmp_path, cli=None, matrix=None, git=None, current_intent=None, **lifecycle_kwargs):
    reader = ProductionReader()
    matrix = matrix or Matrix()
    matrix.reader = reader
    ticks = [0]

    def utc_clock():
        ticks[0] += 1
        return NOW + timedelta(seconds=ticks[0])

    return run_disposable_matrix_lifecycle(
        intent=current_intent or intent(),
        cli=cli or Cli(),
        matrix_executor=matrix,
        git_reader=git or Git(),
        production_reader=reader,
        evidence_directory=tmp_path / "evidence",
        secret_directory=tmp_path / "secrets",
        now=NOW,
        reconciliation_sleeper=lifecycle_kwargs.pop(
            "reconciliation_sleeper", lambda seconds: None
        ),
        reconciliation_utc_clock=lifecycle_kwargs.pop(
            "reconciliation_utc_clock", utc_clock
        ),
        **lifecycle_kwargs,
    )


def _payload(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_success_is_single_attempt_redacted_durable_and_cleanup_verified(tmp_path):
    cli = Cli()
    matrix = Matrix()
    result = run(tmp_path, cli, matrix)
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 1, 1)
    assert not cli.exists
    assert result.cleanup_verified is True
    assert result.branch_id == "01a-disposable-lifecycle"
    assert list((tmp_path / "secrets").iterdir()) == []
    execution = _payload(result.execution_evidence_path)
    terminal = _payload(result.terminal_evidence_path)
    assert execution["source_commit"] == EXPECTED_SOURCE_COMMIT
    assert execution["evidence_contract"] == "oracle-research-isolated-matrix-execution-v1"
    assert terminal["executor_git_commit"] == EXPECTED_EXECUTOR_GIT_COMMIT
    assert terminal["cleanup"]["cleanup_verified"] is True
    combined = result.execution_evidence_path.read_bytes() + result.terminal_evidence_path.read_bytes()
    assert TOKEN.strip() not in combined
    assert stat.S_IMODE(os.lstat(result.execution_evidence_path).st_mode) == 0o600
    assert stat.S_IMODE(os.lstat(result.terminal_evidence_path).st_mode) == 0o600


def test_ambiguous_create_is_reconciled_without_retry(tmp_path):
    cli = Cli(create="ambiguous_created")
    result = run(tmp_path, cli)
    assert cli.create_count == 1
    assert cli.destroy_count == 1
    assert _payload(result.terminal_evidence_path)["create"]["ambiguous"] is True


def test_definite_failed_create_proves_absence_without_token_or_destroy(tmp_path):
    cli = Cli(create="failed_before")
    with pytest.raises(LifecycleError, match="exact absence"):
        run(tmp_path, cli)
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 0, 0)
    terminal = next((tmp_path / "evidence").glob("*-terminal.json"))
    assert _payload(terminal)["primary_failure_type"] == "LifecycleError"


def test_ambiguous_create_without_exact_identity_records_cleanup_incident(tmp_path):
    cli = Cli(create="ambiguous_created")
    cli.malformed_show = True
    with pytest.raises(Exception):
        run(tmp_path, cli)
    assert cli.create_count == 1
    assert cli.destroy_count == 0
    incident = next((tmp_path / "evidence").glob("*-cleanup-incident.json"))
    payload = _payload(incident)
    assert payload["cleanup_failure_type"] == "CleanupError"
    assert payload["branch_id"] is None


class Fatal(BaseException):
    pass


@pytest.mark.parametrize("failure", [RuntimeError("matrix failed"), Fatal()])
def test_primary_exception_and_base_exception_always_clean_and_re_raise(tmp_path, failure):
    cli = Cli()
    with pytest.raises(type(failure)):
        run(tmp_path, cli, Matrix(failure=failure))
    assert cli.destroy_count == 1
    assert not cli.exists
    assert list((tmp_path / "secrets").iterdir()) == []
    terminal = next((tmp_path / "evidence").glob("*-terminal.json"))
    assert _payload(terminal)["primary_failure_type"] == type(failure).__name__
    assert _payload(terminal)["cleanup"]["cleanup_verified"] is True


def test_primary_failure_is_preserved_with_durable_cleanup_incident(tmp_path):
    cli = Cli(destroy="failed_present")
    primary = RuntimeError("primary matrix failure")
    with pytest.raises(RuntimeError, match="primary matrix failure"):
        run(tmp_path, cli, Matrix(failure=primary))
    assert cli.destroy_count == 1
    incident = next((tmp_path / "evidence").glob("*-cleanup-incident.json"))
    payload = _payload(incident)
    assert payload["primary_failure_type"] == "RuntimeError"
    assert payload["cleanup_failure_type"] == "CleanupError"
    assert "primary matrix failure" not in incident.read_text(encoding="utf-8")
    assert TOKEN.strip() not in incident.read_bytes()


def test_ambiguous_destroy_is_success_only_after_dual_absence_readback(tmp_path):
    cli = Cli(destroy="ambiguous_destroyed")
    result = run(tmp_path, cli)
    cleanup = _payload(result.terminal_evidence_path)["cleanup"]
    assert cli.destroy_count == 1
    assert cleanup["destroy_result"] == "AMBIGUOUS_TIMEOUT_PROVEN_BY_READBACK"
    assert cleanup["branch_show_readback"] == "EXACT_OBSERVED_NOT_FOUND"
    assert cleanup["parent_branch_list_readback"] == "EXACT_NAME_ABSENCE"


def test_destroy_response_success_is_insufficient_when_branch_remains(tmp_path):
    cli = Cli(destroy="failed_present")
    with pytest.raises(CleanupError):
        run(tmp_path, cli)
    assert cli.destroy_count == 1
    assert cli.exists
    assert list((tmp_path / "evidence").glob("*-cleanup-incident.json"))


def test_parent_list_presence_blocks_cleanup_even_when_show_is_not_found(tmp_path):
    cli = Cli()
    cli.force_list_present = True
    with pytest.raises(CleanupError):
        run(tmp_path, cli)
    assert cli.destroy_count == 1


def test_fresh_identity_change_blocks_exact_target_destruction(tmp_path):
    cli = Cli()

    def reuse_name():
        cli.branch_id = "01a-conflicting-reused-name"

    with pytest.raises(CleanupError):
        run(tmp_path, cli, Matrix(callback=reuse_name))
    assert cli.destroy_count == 0
    assert cli.exists


def test_executor_git_commit_is_distinct_and_mismatch_stops_before_create(tmp_path):
    cli = Cli()
    with pytest.raises(LifecycleError, match="differs from preregistration"):
        run(tmp_path, cli, git=Git("0" * 40))
    assert cli.create_count == 0


def test_command_vector_count_order_and_scope_are_exact_before_create(tmp_path):
    cli = Cli()
    changed = replace(intent(), commands=tuple(reversed(intent().commands)))
    with pytest.raises(LifecycleError, match="count, order, or scope"):
        run(tmp_path, cli, current_intent=changed)
    assert cli.create_count == 0


def test_wrong_create_result_argv_stops_before_token_and_still_cleans(tmp_path):
    cli = Cli(wrong_create_argv=True)
    with pytest.raises(LifecycleError, match="Create result command identity"):
        run(tmp_path, cli)
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 0, 1)
    assert cli.exists is False
    terminal = next((tmp_path / "evidence").glob("*-terminal.json"))
    payload = _payload(terminal)
    assert payload["primary_failure_type"] == "LifecycleError"
    assert payload["cleanup"]["cleanup_verified"] is True


def test_identity_propagates_on_third_read_without_duplicate_create(tmp_path):
    cli = Cli(identity_absent_shows=2)
    sleeps = []
    result = run(tmp_path, cli, reconciliation_sleeper=sleeps.append)
    assert result.cleanup_verified is True
    assert sleeps == [5.0, 5.0]
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 1, 1)


def test_partial_success_identity_materializes_then_proceeds_without_duplicate_create(tmp_path):
    cli = Cli(partial_identity_shows=2)
    sleeps = []
    result = run(tmp_path, cli, reconciliation_sleeper=sleeps.append)
    assert result.cleanup_verified is True
    assert sleeps == [5.0, 5.0]
    assert cli.branch_show_count >= 3
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 1, 1)


def test_primary_exhaustion_cleanup_phase_later_binds_and_destroys_once(tmp_path):
    cli = Cli(identity_absent_shows=4)
    sleeps = []
    with pytest.raises(IdentityPropagationPending):
        run(tmp_path, cli, reconciliation_sleeper=sleeps.append)
    assert cli.create_count == 1
    assert cli.token_count == 0
    assert cli.destroy_count == 1
    assert cli.exists is False
    terminal = next((tmp_path / "evidence").glob("*-terminal.json"))
    payload = _payload(terminal)
    assert payload["primary_failure_type"] == "IdentityPropagationPending"
    assert payload["cleanup"]["cleanup_verified"] is True
    assert sum(sleeps) <= 45.0


def test_contradictory_identity_never_issues_token_or_destroy(tmp_path):
    cli = Cli()
    cli.malformed_show = True
    sleeps = []
    with pytest.raises(LifecycleError, match="unresolved"):
        run(tmp_path, cli, reconciliation_sleeper=sleeps.append)
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 0, 0)
    assert cli.branch_show_count == 4
    assert sleeps == [5.0, 5.0, 5.0]
    assert sum(sleeps) <= 45.0
    assert cli.exists is True
    assert next((tmp_path / "evidence").glob("*-cleanup-incident.json"))


def test_identity_absence_across_both_phases_stays_within_single_wait_budget(tmp_path):
    cli = Cli(identity_absent_shows=99)
    sleeps = []
    with pytest.raises(IdentityPropagationPending):
        run(tmp_path, cli, reconciliation_sleeper=sleeps.append)
    assert sum(sleeps) <= 45.0
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 0, 0)
    assert next((tmp_path / "evidence").glob("*-cleanup-incident.json"))


def test_terminal_binds_raw_matrix_file_sha_to_shared_cleanup(tmp_path):
    result = run(tmp_path)
    terminal = _payload(result.terminal_evidence_path)
    observed = __import__("hashlib").sha256(
        result.execution_evidence_path.read_bytes()
    ).hexdigest()
    assert terminal["matrix_evidence_file_sha256"] == observed
    assert terminal["cleanup"]["persisted_evidence_file_sha256"] == observed


def test_sequential_duplicate_intent_is_rejected_without_any_second_cli_mutation(tmp_path):
    cli = Cli()
    run(tmp_path, cli)
    counts = (cli.create_count, cli.token_count, cli.destroy_count)
    with pytest.raises(LifecycleError, match="durable claim|outcome evidence"):
        run(tmp_path, cli)
    assert (cli.create_count, cli.token_count, cli.destroy_count) == counts == (1, 1, 1)
    claim = next((tmp_path / "evidence").glob("*-claim.json"))
    assert stat.S_IMODE(os.lstat(claim).st_mode) == 0o600


def test_concurrent_duplicate_claim_allows_exactly_one_lifecycle(tmp_path):
    cli = Cli()

    def invoke():
        try:
            return run(tmp_path, cli)
        except BaseException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: invoke(), range(2)))
    assert sum(isinstance(value, LifecycleArtifacts) for value in outcomes) == 1
    assert sum(isinstance(value, LifecycleError) for value in outcomes) == 1
    assert (cli.create_count, cli.token_count, cli.destroy_count) == (1, 1, 1)


def test_atomic_evidence_replaces_completely_with_exact_mode_and_readback(tmp_path):
    path = tmp_path / "evidence.json"
    atomic_write_redacted_json(path, {"generation": 1})
    first_inode = os.lstat(path).st_ino
    atomic_write_redacted_json(path, {"generation": 2})
    assert _payload(path) == {"generation": 2}
    assert stat.S_IMODE(os.lstat(path).st_mode) == 0o600
    assert not list(tmp_path.glob(".*.tmp"))
    assert os.lstat(path).st_ino != first_inode


def test_repository_git_identity_uses_exact_scoped_safe_directory_argv(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, EXPECTED_EXECUTOR_GIT_COMMIT + "\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    identity = RepositoryGitIdentity(tmp_path)
    assert identity.head() == EXPECTED_EXECUTOR_GIT_COMMIT
    resolved = tmp_path.resolve()
    assert captured["argv"] == (
        "git", "-c", f"safe.directory={resolved}", "rev-parse", "HEAD"
    )
    assert captured["cwd"] == resolved
    assert captured["shell"] is False
    assert captured["check"] is False
    assert captured["capture_output"] is True


def test_repository_git_identity_rejects_stderr_and_invalid_root(monkeypatch, tmp_path):
    def failed(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, EXPECTED_EXECUTOR_GIT_COMMIT + "\n", "warning\n")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(LifecycleError, match="could not be read exactly"):
        RepositoryGitIdentity(tmp_path).head()
    with pytest.raises(LifecycleError, match="could not be resolved"):
        RepositoryGitIdentity(tmp_path / "missing")
