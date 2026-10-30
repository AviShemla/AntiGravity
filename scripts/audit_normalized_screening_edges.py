"""SELECT-only CLI for exact normalized screening-edge evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from normalized_edge_extraction import VALIDATED_20260825_ARMS, read_normalized_edge_audit
from turso_read_pipeline import TursoReadPipeline


def _write_durable_evidence(path_text: str, payload: bytes) -> None:
    """Atomically create one non-overwritable mode-0600 evidence file."""
    target = Path(path_text)
    if not target.is_absolute():
        raise ValueError("Durable evidence path must be absolute.")
    parent = target.parent.resolve(strict=True)
    parent_stat = parent.stat()
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise ValueError("Durable evidence parent is not a directory.")
    if target.parent != parent:
        raise ValueError("Durable evidence parent must be canonical and symlink-free.")
    temp = parent / f".{target.name}.tmp.{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = None
    try:
        fd = os.open(temp, flags, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, target, follow_symlinks=False)
        os.unlink(temp)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        target_stat = target.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(target_stat.st_mode)
            or stat.S_IMODE(target_stat.st_mode) != 0o600
            or target_stat.st_nlink != 1
        ):
            raise ValueError("Durable evidence metadata is not exact.")
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def _endpoint(raw: str) -> str:
    normalized = raw.replace("libsql://", "https://", 1).rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.hostname.split(".")[0] != "theoracle-avishe"
    ):
        raise ValueError("Turso URL does not identify the exact credential-free audit target.")
    return normalized + "/v2/pipeline"


def main(argv: list[str] | None = None, *, pipeline_factory=TursoReadPipeline) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--expected-snapshot-id", required=True)
    parser.add_argument("--expected-source-session-date", required=True)
    parser.add_argument("--expected-cutoff-utc", required=True)
    parser.add_argument("--expected-code-version", required=True)
    parser.add_argument("--output-path")
    args = parser.parse_args(argv)
    expected_ids = {arm.run_id for arm in VALIDATED_20260825_ARMS}
    if len(args.run_id) != len(expected_ids) or set(args.run_id) != expected_ids:
        print("Normalized-edge audit failed; inspect redacted durable logs.", file=sys.stderr)
        return 1
    try:
        raw_url = os.environ.get("TURSO_DATABASE_URL", "")
        token = os.environ.get("TURSO_AUTH_TOKEN", "")
        if not raw_url or not token:
            raise ValueError("Audit credentials are unavailable.")
        db = pipeline_factory(_endpoint(raw_url), token, timeout_seconds=30.0)
        evidence = read_normalized_edge_audit(
            db,
            expected_arms=VALIDATED_20260825_ARMS,
            expected_snapshot_id=args.expected_snapshot_id,
            expected_source_session_date=args.expected_source_session_date,
            expected_cutoff_utc=args.expected_cutoff_utc,
            expected_code_version=args.expected_code_version,
        )
    except Exception:
        print("Normalized-edge audit failed; inspect redacted durable logs.", file=sys.stderr)
        return 1
    encoded = (
        json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    try:
        if args.output_path:
            _write_durable_evidence(args.output_path, encoded)
        else:
            sys.stdout.buffer.write(encoded)
    except Exception:
        print("Normalized-edge audit failed; inspect redacted durable logs.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
