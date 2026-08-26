import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from datetime import datetime
from dataclasses import replace
import time

import pytest

from scripts.oracle_research_dataset_isolated_matrix import (
    EXPECTED_SOURCE_COMMIT,
    MIGRATION_PATH,
    TemporaryBranchApproval,
    _pre_branch_payload,
    build_pre_branch_intent,
)
from scripts.run_oracle_research_dataset_isolated_matrix_lifecycle import (
    MAX_CHECKPOINT_INTERVAL_SECONDS,
    WorkerConfig,
    WorkerError,
    main,
    run_worker,
)


COMMIT = "9" * 40
TOKEN = "production-secret-test-token-value"


def write_inputs(tmp_path):
    from datetime import datetime, timezone

    intent = build_pre_branch_intent(
        migration_bytes=MIGRATION_PATH.read_bytes(),
        branch_name="theoracle-codex-oracle-rd-20260826t1900z-a1b2c3",
        approval=TemporaryBranchApproval(
            "avi-six-action-matrix-20260826", True, True, True, True, True, True
        ),
        source_commit=EXPECTED_SOURCE_COMMIT,
        created_at=datetime(2026, 8, 26, 19, 0, tzinfo=timezone.utc),
    )
    intent_path = tmp_path / "intent.json"
    intent_path.write_text(json.dumps(_pre_branch_payload(intent)), encoding="utf-8")
    env_path = tmp_path / "production.env"
    env_path.write_text(
        "TURSO_DATABASE_URL=libsql://theoracle-avishe.aws-eu-west-1.turso.io\n"
        f"TURSO_AUTH_TOKEN={TOKEN}\n",
        encoding="utf-8",
    )
    os.chmod(env_path, 0o600)
    return WorkerConfig(
        intent_path,
        env_path,
        tmp_path / "evidence",
        tmp_path / "secrets",
        tmp_path / "checkpoint.json",
        COMMIT,
        tmp_path,
    )


class Reader:
    pass


class Matrix:
    pass


def test_worker_passes_explicit_commit_and_writes_only_redacted_checkpoints(tmp_path):
    config = write_inputs(tmp_path)
    captured = {}
    sentinel = object()

    def reader_factory(endpoint, token):
        assert endpoint == "https://theoracle-avishe.aws-eu-west-1.turso.io/v2/pipeline"
        assert token == TOKEN
        return Reader()

    def matrix_factory(url, token, reader, intent):
        assert token == TOKEN and reader.__class__ is Reader
        assert intent.intent_id
        return Matrix()

    def lifecycle(**kwargs):
        captured.update(kwargs)
        return sentinel

    result = run_worker(
        config,
        lifecycle=lifecycle,
        cli=object(),
        git_reader=object(),
        production_reader_factory=reader_factory,
        matrix_executor_factory=matrix_factory,
    )
    assert result is sentinel
    assert captured["expected_executor_git_commit"] == COMMIT
    assert captured["production_reader"].__class__ is Reader
    checkpoint = json.loads(config.checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["state"] == "COMPLETE"
    assert checkpoint["executor_git_commit"] == COMMIT
    assert checkpoint["pid"] == os.getpid()
    assert checkpoint["max_checkpoint_interval_seconds"] == MAX_CHECKPOINT_INTERVAL_SECONDS
    assert datetime.fromisoformat(checkpoint["checkpoint_at_utc"].replace("Z", "+00:00")).tzinfo
    assert TOKEN not in config.checkpoint_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.lstat(config.checkpoint_path).st_mode) == 0o600


def test_worker_failure_checkpoint_preserves_only_exception_type(tmp_path):
    config = write_inputs(tmp_path)

    def fail(**kwargs):
        raise RuntimeError("contains-sensitive-detail")

    with pytest.raises(RuntimeError, match="contains-sensitive-detail"):
        run_worker(
            config,
            lifecycle=fail,
            production_reader_factory=lambda endpoint, token: Reader(),
            matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
        )
    raw = config.checkpoint_path.read_text(encoding="utf-8")
    assert "contains-sensitive-detail" not in raw
    assert TOKEN not in raw
    assert json.loads(raw)["failure_type"] == "RuntimeError"


def test_production_env_requires_owner_only_regular_file(tmp_path):
    config = write_inputs(tmp_path)
    os.chmod(config.production_env_path, 0o644)
    with pytest.raises(WorkerError, match="metadata is not exact"):
        run_worker(
            config,
            lifecycle=lambda **kwargs: None,
            production_reader_factory=lambda endpoint, token: Reader(),
            matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
        )
    checkpoint = json.loads(config.checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["state"] == "FAILED"
    assert checkpoint["failure_type"] == "WorkerError"


def test_production_env_rejects_symlink_and_hardlink(tmp_path):
    config = write_inputs(tmp_path)
    original = config.production_env_path
    symlink = tmp_path / "symlink.env"
    symlink.symlink_to(original)
    for candidate in (symlink,):
        changed = WorkerConfig(
            config.intent_path, candidate, config.evidence_directory,
            config.secret_directory, config.checkpoint_path,
            config.executor_git_commit, config.repository_root,
        )
        with pytest.raises(WorkerError, match="metadata is not exact"):
            run_worker(
                changed,
                lifecycle=lambda **kwargs: None,
                production_reader_factory=lambda endpoint, token: Reader(),
                matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
            )
    hardlink = tmp_path / "hardlink.env"
    os.link(original, hardlink)
    with pytest.raises(WorkerError, match="metadata is not exact"):
        run_worker(
            config,
            lifecycle=lambda **kwargs: None,
            production_reader_factory=lambda endpoint, token: Reader(),
            matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
        )


@pytest.mark.parametrize(
    "content",
    [
        "TURSO_DATABASE_URL=libsql://theoracle-avishe.turso.io\n",
        "TURSO_DATABASE_URL=libsql://theoracle-avishe.turso.io\nTURSO_DATABASE_URL=x\n",
        "TURSO_AUTH_TOKEN=x\nTURSO_DATABASE_URL=libsql://theoracle-avishe.turso.io\n",
        "TURSO_DATABASE_URL=libsql://theoracle-avishe.turso.io\nTURSO_AUTH_TOKEN=x\nEXTRA=y\n",
    ],
)
def test_production_env_rejects_missing_duplicate_wrong_order_and_extra_keys(tmp_path, content):
    config = write_inputs(tmp_path)
    config.production_env_path.write_text(content, encoding="utf-8")
    os.chmod(config.production_env_path, 0o600)
    with pytest.raises(WorkerError, match="key count|key order"):
        run_worker(
            config,
            lifecycle=lambda **kwargs: None,
            production_reader_factory=lambda endpoint, token: Reader(),
            matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
        )


def test_cli_requires_explicit_executor_git_commit_before_any_execution(tmp_path):
    with pytest.raises(SystemExit) as error:
        main([
            "--intent-json", str(tmp_path / "intent.json"),
            "--production-env-file", str(tmp_path / "production.env"),
            "--evidence-directory", str(tmp_path / "evidence"),
            "--secret-directory", str(tmp_path / "secrets"),
            "--checkpoint-json", str(tmp_path / "checkpoint.json"),
        ])
    assert error.value.code == 2


def test_checkpoint_contains_no_url_token_or_database_rows(tmp_path):
    config = write_inputs(tmp_path)
    run_worker(
        config,
        lifecycle=lambda **kwargs: object(),
        production_reader_factory=lambda endpoint, token: Reader(),
        matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
    )
    raw = config.checkpoint_path.read_text(encoding="utf-8")
    assert "libsql://" not in raw
    assert "https://" not in raw
    assert TOKEN not in raw


def test_credential_preflight_failure_has_durable_failed_checkpoint(tmp_path):
    config = write_inputs(tmp_path)
    config.production_env_path.write_text(
        "TURSO_DATABASE_URL=libsql://theoracle-avishe.turso.io\n",
        encoding="utf-8",
    )
    os.chmod(config.production_env_path, 0o600)
    with pytest.raises(WorkerError):
        run_worker(config)
    payload = json.loads(config.checkpoint_path.read_text(encoding="utf-8"))
    assert payload["state"] == "FAILED"
    assert payload["failure_type"] == "WorkerError"
    assert payload["sequence"] == 1


def test_heartbeat_refreshes_checkpoint_during_long_lifecycle(tmp_path):
    config = replace(
        write_inputs(tmp_path),
        max_checkpoint_interval_seconds=1,
        heartbeat_interval_seconds=0.01,
    )
    observed = {}

    def lifecycle(**kwargs):
        time.sleep(0.04)
        observed.update(json.loads(config.checkpoint_path.read_text(encoding="utf-8")))
        return object()

    run_worker(
        config,
        lifecycle=lifecycle,
        production_reader_factory=lambda endpoint, token: Reader(),
        matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
    )
    assert observed["state"] == "RUNNING"
    assert observed["sequence"] >= 1
    terminal = json.loads(config.checkpoint_path.read_text(encoding="utf-8"))
    assert terminal["state"] == "COMPLETE"
    assert terminal["sequence"] > observed["sequence"]


def test_heartbeat_persistence_failure_surfaces_after_lifecycle_cleanup(monkeypatch, tmp_path):
    import scripts.run_oracle_research_dataset_isolated_matrix_lifecycle as module

    config = replace(
        write_inputs(tmp_path),
        max_checkpoint_interval_seconds=1,
        heartbeat_interval_seconds=0.01,
    )
    actual = module._checkpoint
    lifecycle_finished = []

    def failing_checkpoint(config, state, **kwargs):
        if state == "RUNNING":
            raise OSError("sensitive-heartbeat-detail")
        return actual(config, state, **kwargs)

    monkeypatch.setattr(module, "_checkpoint", failing_checkpoint)

    def lifecycle(**kwargs):
        time.sleep(0.04)
        lifecycle_finished.append(True)
        return object()

    with pytest.raises(WorkerError, match="heartbeat persistence failed"):
        run_worker(
            config,
            lifecycle=lifecycle,
            production_reader_factory=lambda endpoint, token: Reader(),
            matrix_executor_factory=lambda url, token, reader, intent: Matrix(),
        )
    assert lifecycle_finished == [True]
    payload = json.loads(config.checkpoint_path.read_text(encoding="utf-8"))
    assert payload["state"] == "FAILED"
    assert "sensitive-heartbeat-detail" not in config.checkpoint_path.read_text(encoding="utf-8")


def test_cli_boundary_redacts_arbitrary_exception_text(monkeypatch, capsys, tmp_path):
    import scripts.run_oracle_research_dataset_isolated_matrix_lifecycle as module

    secret = "token-secret-value libsql://theoracle-secret.turso.io"
    monkeypatch.setattr(module, "run_worker", lambda config: (_ for _ in ()).throw(RuntimeError(secret)))
    exit_code = main([
        "--intent-json", str(tmp_path / "intent.json"),
        "--production-env-file", str(tmp_path / "production.env"),
        "--evidence-directory", str(tmp_path / "evidence"),
        "--secret-directory", str(tmp_path / "secrets"),
        "--checkpoint-json", str(tmp_path / "checkpoint.json"),
        "--executor-git-commit", COMMIT,
    ])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert secret not in captured.out + captured.err
    assert "token-secret-value" not in captured.out + captured.err
    assert "libsql://" not in captured.out + captured.err


def test_absolute_script_invocation_from_unrelated_cwd_bootstraps_repository(tmp_path):
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_oracle_research_dataset_isolated_matrix_lifecycle.py"
    )
    completed = subprocess.run(
        (sys.executable, str(script), "--help"),
        cwd=tmp_path,
        shell=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0
    assert "--executor-git-commit" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stdout + completed.stderr
