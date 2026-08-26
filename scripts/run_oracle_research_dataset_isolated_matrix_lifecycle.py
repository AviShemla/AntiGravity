"""Persistent-worker entrypoint for one approved disposable Turso matrix lifecycle.

The executable Git identity is always supplied explicitly by the operator or
unit definition.  This module has no defaults that depend on its own future
commit and never prints credentials, CLI response bodies, or database rows.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from scripts.oracle_research_dataset_isolated_matrix import execute_with_adapter
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    IsolatedMatrixExecutionAdapter,
    MatrixCredentials,
    TursoMatrixBranch,
    _endpoint,
    build_redacted_evidence,
    load_pre_branch_intent,
    validate_credentials,
)
from scripts.oracle_research_dataset_isolated_matrix_lifecycle import (
    RepositoryGitIdentity,
    SubprocessLifecycleCli,
    atomic_write_redacted_json,
    run_disposable_matrix_lifecycle,
)
from turso_read_pipeline import TursoReadPipeline


MAX_PRODUCTION_ENV_BYTES = 64 * 1024
MAX_TURSO_SETTINGS_BYTES = 64 * 1024
MAX_CHECKPOINT_INTERVAL_SECONDS = 300


class WorkerError(RuntimeError):
    """Redacted worker configuration or lifecycle failure."""


@dataclass(frozen=True)
class WorkerConfig:
    intent_path: Path
    production_env_path: Path
    turso_settings_path: Path
    turso_settings_owner_uid: int
    evidence_directory: Path
    secret_directory: Path
    checkpoint_path: Path
    executor_git_commit: str
    repository_root: Path = ROOT
    max_checkpoint_interval_seconds: int = MAX_CHECKPOINT_INTERVAL_SECONDS
    heartbeat_interval_seconds: float = 60.0


class ConcreteMatrixExecutor:
    """Build the real isolated branch adapter only after lifecycle binding."""

    def __init__(self, production_url: str, production_token: str, production_reader, intent):
        self._production_url = production_url
        self._production_token = production_token
        self._production_reader = production_reader
        self._intent = intent

    def execute(self, plan, proof, secrets):
        credentials = MatrixCredentials(
            secrets.branch_url,
            secrets.branch_token,
            self._production_url,
            self._production_token,
        )
        branch_endpoint, _ = validate_credentials(plan, proof, credentials)
        import requests

        adapter = IsolatedMatrixExecutionAdapter(
            TursoMatrixBranch(
                branch_endpoint,
                secrets.branch_token,
                session=requests.Session(),
            ),
            self._production_reader,
        )
        readback = execute_with_adapter(plan, adapter)
        return build_redacted_evidence(plan, readback, intent=self._intent, proof=proof)


def _read_turso_settings(
    path: Path, *, expected_owner_uid: int
) -> tuple[bytes, tuple[int, int, int, int, int]]:
    path = Path(path)
    if expected_owner_uid < 0:
        raise WorkerError("Expected Turso settings owner is invalid.")
    try:
        absolute = path.absolute()
        resolved = path.resolve(strict=True)
        before = os.lstat(path)
    except OSError as exc:
        raise WorkerError("Turso settings file is unavailable.") from exc
    if resolved != absolute:
        raise WorkerError("Turso settings path contains a symbolic link.")
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != expected_owner_uid
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size <= 0
        or before.st_size > MAX_TURSO_SETTINGS_BYTES
    ):
        raise WorkerError("Turso settings file metadata is not exact.")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise WorkerError("Turso settings file could not be opened safely.") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != expected_owner_uid
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_size != before.st_size
        ):
            raise WorkerError("Turso settings file identity changed while opening.")
        chunks: list[bytes] = []
        remaining = MAX_TURSO_SETTINGS_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    try:
        after_path = os.lstat(path)
    except OSError as exc:
        raise WorkerError("Turso settings file disappeared during read.") from exc
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    if (
        len(raw) != before.st_size
        or (
            after_fd.st_dev,
            after_fd.st_ino,
            after_fd.st_size,
            after_fd.st_mtime_ns,
            after_fd.st_ctime_ns,
        ) != identity
        or (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_size,
            after_path.st_mtime_ns,
            after_path.st_ctime_ns,
        ) != identity
        or after_path.st_uid != expected_owner_uid
        or stat.S_IMODE(after_path.st_mode) != 0o600
        or after_path.st_nlink != 1
    ):
        raise WorkerError("Turso settings file changed during read.")
    return raw, identity


def _write_private_settings(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise WorkerError("Ephemeral Turso settings copy did not make progress.")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or path.read_bytes() != raw
    ):
        raise WorkerError("Ephemeral Turso settings copy metadata or content is not exact.")


def _remove_ephemeral_turso_home(home: Path) -> None:
    metadata = os.lstat(home)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise WorkerError("Ephemeral Turso HOME cleanup target is not exact.")

    def remove_tree(directory: Path) -> None:
        with os.scandir(directory) as entries:
            children = list(entries)
        for entry in children:
            child = Path(entry.path)
            child_metadata = os.lstat(child)
            if stat.S_ISDIR(child_metadata.st_mode) and not stat.S_ISLNK(
                child_metadata.st_mode
            ):
                remove_tree(child)
            else:
                os.unlink(child)
        os.rmdir(directory)

    remove_tree(home)


@contextmanager
def ephemeral_turso_home(
    settings_path: Path,
    *,
    expected_owner_uid: int,
    temp_root: Path = Path("/tmp"),
):
    """Provide Turso a private writable HOME while preserving its source settings."""

    raw, source_identity = _read_turso_settings(
        settings_path, expected_owner_uid=expected_owner_uid
    )
    home = Path(tempfile.mkdtemp(prefix="oracle-turso-home-", dir=Path(temp_root)))
    previous_home = os.environ.get("HOME")
    had_home = "HOME" in os.environ
    home_overridden = False
    try:
        os.chmod(home, 0o700)
        config_directory = home / ".config"
        turso_directory = config_directory / "turso"
        config_directory.mkdir(mode=0o700)
        turso_directory.mkdir(mode=0o700)
        _write_private_settings(turso_directory / "settings.json", raw)
        os.environ["HOME"] = str(home)
        home_overridden = True
        try:
            yield home
        finally:
            if had_home:
                os.environ["HOME"] = previous_home or ""
            else:
                os.environ.pop("HOME", None)
            home_overridden = False
    finally:
        if home_overridden:
            if had_home:
                os.environ["HOME"] = previous_home or ""
            else:
                os.environ.pop("HOME", None)
        try:
            after_raw, after_identity = _read_turso_settings(
                settings_path, expected_owner_uid=expected_owner_uid
            )
            if after_identity != source_identity or after_raw != raw:
                raise WorkerError("Original Turso settings changed during lifecycle.")
        finally:
            _remove_ephemeral_turso_home(home)


def _read_production_env(path: Path) -> dict[str, str]:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise WorkerError("Production credential file is unavailable.") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size <= 0
        or before.st_size > MAX_PRODUCTION_ENV_BYTES
    ):
        raise WorkerError("Production credential file metadata is not exact.")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise WorkerError("Production credential file could not be opened safely.") from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_size != before.st_size
        ):
            raise WorkerError("Production credential file identity changed while opening.")
        chunks: list[bytes] = []
        remaining = MAX_PRODUCTION_ENV_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    try:
        after_path = os.lstat(path)
    except OSError as exc:
        raise WorkerError("Production credential file disappeared during read.") from exc
    if (
        len(raw) != before.st_size
        or (after_fd.st_dev, after_fd.st_ino, after_fd.st_size)
        != (before.st_dev, before.st_ino, before.st_size)
        or (after_path.st_dev, after_path.st_ino, after_path.st_size)
        != (before.st_dev, before.st_ino, before.st_size)
    ):
        raise WorkerError("Production credential file changed during read.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkerError("Production credential file is not UTF-8.") from exc
    lines = text.splitlines()
    expected = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN")
    if len(lines) != 2:
        raise WorkerError("Production credential file key count is not exact.")
    values: dict[str, str] = {}
    for line, expected_key in zip(lines, expected, strict=True):
        if "=" not in line:
            raise WorkerError("Production credential file line is malformed.")
        key, value = line.split("=", 1)
        if key != expected_key or not value or value != value.strip():
            raise WorkerError("Production credential file key order or value is invalid.")
        if key in values:
            raise WorkerError("Production credential file contains a duplicate key.")
        values[key] = value
    return values


def _production_credentials(path: Path) -> tuple[str, str, str]:
    values = _read_production_env(path)
    url = values.get("TURSO_DATABASE_URL", "")
    token = values.get("TURSO_AUTH_TOKEN", "")
    try:
        endpoint = _endpoint(url, expected_name="theoracle")
    except Exception as exc:
        raise WorkerError("Production database URL is invalid.") from exc
    if not token:
        raise WorkerError("Production read credential is missing.")
    return url, token, endpoint


def _checkpoint(
    config: WorkerConfig,
    state: str,
    *,
    sequence: int,
    failure_type: str | None = None,
) -> None:
    if config.max_checkpoint_interval_seconds <= 0:
        raise WorkerError("Maximum checkpoint interval must be positive.")
    atomic_write_redacted_json(
        config.checkpoint_path,
        {
            "evidence_contract": "oracle-isolated-matrix-worker-checkpoint-v1",
            "state": state,
            "sequence": sequence,
            "checkpoint_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "pid": os.getpid(),
            "max_checkpoint_interval_seconds": config.max_checkpoint_interval_seconds,
            "intent_file_sha256": hashlib.sha256(config.intent_path.read_bytes()).hexdigest(),
            "executor_git_commit": config.executor_git_commit,
            "evidence_directory": config.evidence_directory.name,
            "failure_type": failure_type,
        },
    )


def run_worker(
    config: WorkerConfig,
    *,
    lifecycle: Callable = run_disposable_matrix_lifecycle,
    cli=None,
    git_reader=None,
    production_reader_factory: Callable[[str, str], object] | None = None,
    matrix_executor_factory: Callable[[str, str, object, object], object] | None = None,
    now: datetime | None = None,
):
    intent = load_pre_branch_intent(config.intent_path)
    sequence = [0]
    _checkpoint(config, "STARTING", sequence=sequence[0])
    stop_heartbeat = threading.Event()
    heartbeat_errors: list[BaseException] = []

    def heartbeat() -> None:
        while not stop_heartbeat.wait(config.heartbeat_interval_seconds):
            try:
                sequence[0] += 1
                _checkpoint(config, "RUNNING", sequence=sequence[0])
            except BaseException as exc:
                heartbeat_errors.append(exc)
                return

    heartbeat_thread: threading.Thread | None = None
    result = None
    primary: BaseException | None = None
    primary_tb = None
    try:
        if (
            config.heartbeat_interval_seconds <= 0
            or config.heartbeat_interval_seconds > 60
            or config.heartbeat_interval_seconds >= config.max_checkpoint_interval_seconds
        ):
            raise WorkerError("Heartbeat interval is outside the declared checkpoint SLA.")
        heartbeat_thread = threading.Thread(
            target=heartbeat,
            name="oracle-isolated-matrix-checkpoint",
            daemon=True,
        )
        heartbeat_thread.start()
        production_url, production_token, endpoint = _production_credentials(
            config.production_env_path
        )
        production_reader_factory = production_reader_factory or (
            lambda value, secret: TursoReadPipeline(value, secret, timeout_seconds=45.0)
        )
        production_reader = production_reader_factory(endpoint, production_token)
        matrix_executor_factory = matrix_executor_factory or ConcreteMatrixExecutor
        matrix_executor = matrix_executor_factory(
            production_url, production_token, production_reader, intent
        )
        with ephemeral_turso_home(
            config.turso_settings_path,
            expected_owner_uid=config.turso_settings_owner_uid,
        ):
            result = lifecycle(
                intent=intent,
                cli=cli or SubprocessLifecycleCli(),
                matrix_executor=matrix_executor,
                git_reader=git_reader or RepositoryGitIdentity(config.repository_root),
                production_reader=production_reader,
                evidence_directory=config.evidence_directory,
                secret_directory=config.secret_directory,
                now=now,
                expected_executor_git_commit=config.executor_git_commit,
            )
    except BaseException as exc:
        primary = exc
        primary_tb = sys.exc_info()[2]
    finally:
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join()
    if heartbeat_errors and primary is None:
        primary = WorkerError("Worker heartbeat persistence failed.")
        primary_tb = primary.__traceback__
    sequence[0] += 1
    if primary is not None:
        _checkpoint(
            config,
            "FAILED",
            sequence=sequence[0],
            failure_type=type(primary).__name__,
        )
        raise primary.with_traceback(primary_tb)
    _checkpoint(config, "COMPLETE", sequence=sequence[0])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent-json", type=Path, required=True)
    parser.add_argument("--production-env-file", type=Path, required=True)
    parser.add_argument("--turso-settings-file", type=Path, required=True)
    parser.add_argument("--turso-settings-owner-uid", type=int, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--secret-directory", type=Path, required=True)
    parser.add_argument("--checkpoint-json", type=Path, required=True)
    parser.add_argument("--executor-git-commit", required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument(
        "--max-checkpoint-interval-seconds",
        type=int,
        default=MAX_CHECKPOINT_INTERVAL_SECONDS,
    )
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    config = WorkerConfig(
        args.intent_json,
        args.production_env_file,
        args.turso_settings_file,
        args.turso_settings_owner_uid,
        args.evidence_directory,
        args.secret_directory,
        args.checkpoint_json,
        args.executor_git_commit,
        args.repository_root,
        args.max_checkpoint_interval_seconds,
        args.heartbeat_interval_seconds,
    )
    try:
        run_worker(config)
    except Exception:
        print("Oracle isolated matrix worker failed; inspect redacted checkpoint.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
