"""Release-local fail-closed supervisor with atomic progress heartbeats."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from release_layout import verify_release


SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STAGES = {"INGESTION", "POSTFLIGHT", "HANDOFF"}


class StageRunnerError(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _secure_directory(path: Path) -> None:
    if path.is_symlink():
        raise StageRunnerError(f"progress directory is a symlink: {path}")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise StageRunnerError(f"progress parent is not a directory: {path}")
    if os.name != "nt" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700):
        raise StageRunnerError(f"progress directory must be root-owned mode 0700: {path}")


def atomic_progress_write(path: Path, evidence: Mapping[str, object]) -> None:
    parent = path.parent
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _secure_directory(parent)
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise StageRunnerError("progress marker must not be a symlink")
        current = path.stat()
        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
            raise StageRunnerError("existing progress marker is not a single-link regular file")
        if os.name != "nt" and (current.st_uid != 0 or stat.S_IMODE(current.st_mode) != 0o600):
            raise StageRunnerError("existing progress marker must be root-owned mode 0600")
    encoded = canonical_bytes(evidence)
    temporary = parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary.exists():
            temporary.unlink()


def progress_evidence(
    *, source_session: str, stage: str, status: str, main_pid: int,
    invocation_id: str, code_version: str, completed_units: int,
    total_units: int, now: datetime | None = None,
) -> dict[str, object]:
    if not SESSION_RE.fullmatch(source_session) or stage not in STAGES:
        raise StageRunnerError("source session or stage is invalid")
    if status not in {"ACTIVE", "SUCCEEDED", "FAILED"}:
        raise StageRunnerError("progress status is invalid")
    if main_pid <= 0 or not invocation_id or not SHA256_RE.fullmatch(code_version):
        raise StageRunnerError("progress identity is incomplete")
    if total_units <= 0 or completed_units < 0 or completed_units > total_units:
        raise StageRunnerError("progress counters are invalid")
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise StageRunnerError("progress timestamp must be timezone-aware")
    return {
        "contract_id": "codex-market-ingestion-progress-v1",
        "source_session": source_session,
        "stage": stage,
        "status": status,
        "main_pid": main_pid,
        "invocation_id": invocation_id,
        "code_version": code_version,
        "completed_units": completed_units,
        "total_units": total_units,
        "observed_at": observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _secure_payload(release_root: Path, relative_payload: str) -> Path:
    candidate = Path(relative_payload)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise StageRunnerError("payload path escaped its immutable release")
    path = release_root / candidate
    if path.is_symlink():
        raise StageRunnerError("payload must not be a symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise StageRunnerError("payload is not a single-link regular file")
    if os.name != "nt" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700):
        raise StageRunnerError("payload must be root-owned mode 0700")
    return path


def supervise(
    *, stage: str, relative_payload: str, source_session: str,
    progress_marker: Path, code_version: str, payload_args: Sequence[str],
    heartbeat_seconds: float, total_units: int, invocation_id: str,
    release_root: Path,
) -> int:
    if heartbeat_seconds <= 0 or heartbeat_seconds > 300:
        raise StageRunnerError("heartbeat interval must be in (0, 300] seconds")
    payload = _secure_payload(release_root, relative_payload)
    main_pid = os.getpid()

    def write(status: str, completed: int) -> None:
        atomic_progress_write(progress_marker, progress_evidence(
            source_session=source_session, stage=stage, status=status,
            main_pid=main_pid, invocation_id=invocation_id,
            code_version=code_version, completed_units=completed,
            total_units=total_units,
        ))

    write("ACTIVE", 0)
    process = subprocess.Popen([str(payload), *payload_args], shell=False)
    terminated = False

    def terminate(signum: int, _frame: object) -> None:
        nonlocal terminated
        terminated = True
        if process.poll() is None:
            process.send_signal(signum)

    previous = {
        signum: signal.signal(signum, terminate)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        while True:
            try:
                result = process.wait(timeout=heartbeat_seconds)
                break
            except subprocess.TimeoutExpired:
                write("ACTIVE", 0)
        if result == 0 and not terminated:
            write("SUCCEEDED", total_units)
            return 0
        write("FAILED", 0)
        if result < 0:
            return 128 + (-result)
        return result if result != 0 else 128 + signal.SIGTERM
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_stage_main(
    stage: str, relative_payload: str, argv: Sequence[str] | None = None,
    *, release_root: Path | None = None,
) -> int:
    raw_argv = list(argv or ())
    if raw_argv.count("--source-session") != 1:
        raise StageRunnerError("exactly one source session argument is required")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--progress-marker", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0)
    parser.add_argument("--total-units", type=int, default=1)
    args, payload_args = parser.parse_known_args(raw_argv)
    # The supervisor owns the session identity for marker integrity, but the
    # reviewed payload also needs that same identity.  Re-inject the parsed
    # value so it cannot be omitted or independently overridden downstream.
    payload_args = ["--source-session", args.source_session, *payload_args]
    root = release_root or Path(__file__).resolve().parent
    release_kind = "market-ingestion" if stage == "INGESTION" else "market-ingestion-handoff"
    verify_release(
        root.parent, release_kind, args.code_version,
        require_root=(os.name != "nt"),
    )
    invocation_id = os.environ.get("INVOCATION_ID", "")
    return supervise(
        stage=stage, relative_payload=relative_payload,
        source_session=args.source_session, progress_marker=args.progress_marker,
        code_version=args.code_version, payload_args=payload_args,
        heartbeat_seconds=args.heartbeat_seconds, total_units=args.total_units,
        invocation_id=invocation_id, release_root=root,
    )
