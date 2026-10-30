#!/usr/bin/env python3
"""Secure write-once I/O wrapper for the pure stock preregistration binder.

This wrapper reads only caller-named local artifacts, validates a separately
produced perpetual SELECT-only readback, invokes the immutable-v4 binder, and
atomically persists one fixture-only preregistration manifest.  It does not
import a database or network client and cannot fit a model.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Mapping

try:  # Canonical package layout.
    from . import stock_model_preregistration_binding as binding
    from .stock_model_preregistration import PreregistrationError
except ImportError:  # Direct execution from an immutable closure.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import stock_model_preregistration_binding as binding
    from stock_model_preregistration import PreregistrationError


MAX_JSON_BYTES = 16 * 1024 * 1024


class RuntimeBoundaryError(RuntimeError):
    """Raised before persistence when a filesystem or JSON gate fails."""


def _reject_constant(value: str) -> object:
    raise RuntimeBoundaryError(f"JSON contains prohibited non-finite constant {value}")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeBoundaryError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def decode_strict_json(raw: bytes, label: str) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_JSON_BYTES:
        raise RuntimeBoundaryError(f"{label} size is outside the contract")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeBoundaryError(f"{label} is not strict UTF-8 JSON") from exc
    if type(value) is not dict:
        raise RuntimeBoundaryError(f"{label} root must be an object")
    return value


def _require_root_owned(metadata: os.stat_result, label: str) -> None:
    if not hasattr(metadata, "st_uid") or metadata.st_uid != 0:
        raise RuntimeBoundaryError(f"{label} must be root-owned")


def read_root_owned_json(path: Path, label: str) -> tuple[dict[str, object], str]:
    """Open one absolute root-owned regular file without following symlinks."""
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise RuntimeBoundaryError(f"{label} must be an absolute non-symlink path")
    before = os.lstat(path)
    _require_root_owned(before, label)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
            stat.S_IMODE(before.st_mode) & 0o022):
        raise RuntimeBoundaryError(
            f"{label} must be a single-link regular file with no group/world writes"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        _require_root_owned(opened, label)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
            raise RuntimeBoundaryError(f"{label} changed during secure open")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_JSON_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_JSON_BYTES:
                raise RuntimeBoundaryError(f"{label} exceeds the size limit")
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    return decode_strict_json(raw, label), hashlib.sha256(raw).hexdigest()


def read_root_owned_0600_json(path: Path, label: str) -> tuple[dict[str, object], str]:
    """Apply the stricter runtime-input mode before the race-safe reader."""
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise RuntimeBoundaryError(f"{label} must be an absolute non-symlink path")
    metadata = os.lstat(path)
    _require_root_owned(metadata, label)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
            stat.S_IMODE(metadata.st_mode) != 0o600):
        raise RuntimeBoundaryError(f"{label} must be root-owned mode-0600 single-link")
    return read_root_owned_json(path, label)


def _secure_output_parent(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.exists() or path.is_symlink():
        raise RuntimeBoundaryError("output must be a new absolute non-symlink path")
    parent = path.parent
    if parent.is_symlink():
        raise RuntimeBoundaryError("output directory must not be a symlink")
    resolved = parent.resolve(strict=True)
    metadata = os.lstat(parent)
    _require_root_owned(metadata, "output directory")
    if resolved != parent or not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RuntimeBoundaryError("output directory must be root-owned mode-0700")
    return resolved


def write_json_once(path: Path, payload: Mapping[str, object]) -> str:
    """Persist JSON atomically without an overwrite-capable operation."""
    parent = _secure_output_parent(path)
    try:
        raw = (json.dumps(
            payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False,
        ) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeBoundaryError("output payload is not canonical JSON data") from exc
    temporary = parent / f".{path.name}.{os.getpid()}.{os.urandom(12).hex()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    linked = False
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise RuntimeBoundaryError("atomic output write made no progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        linked = True
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        os.unlink(temporary)
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as exc:
        raise RuntimeBoundaryError("output already exists; overwrite is prohibited") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            os.unlink(temporary)
        if linked and path.exists():
            metadata = os.lstat(path)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise RuntimeBoundaryError("persisted output metadata differs")
    return hashlib.sha256(raw).hexdigest()


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeBoundaryError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeBoundaryError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def bind_perpetual_readback(
    *, final_manifest, immutable_audit, lineage_mapping, current_readback,
    final_manifest_file_sha256, immutable_audit_file_sha256,
    current_model_git_commit, observed_at_utc, run_id,
):
    """Build NEW_RUN using immutable v4 evidence plus canonical perpetual proof."""
    try:
        from .audit_stock_preregistration_manifest import proof_from_verified_readback
    except ImportError:
        from audit_stock_preregistration_manifest import proof_from_verified_readback
    proof = proof_from_verified_readback(current_readback)
    return binding.bind_verified_v4_baseline_with_current_readback(
        final_manifest=final_manifest, immutable_audit=immutable_audit,
        lineage_mapping=lineage_mapping,
        final_manifest_file_sha256=final_manifest_file_sha256,
        immutable_audit_file_sha256=immutable_audit_file_sha256,
        current_readback=proof, current_model_git_commit=current_model_git_commit,
        observed_at_utc=observed_at_utc, run_id=run_id)


def _verify_current_readback(**kwargs):
    """Late import keeps the independent verifier out of the pure binder path."""
    try:
        from .verify_current_baseline_readback import verify
    except ImportError:
        from verify_current_baseline_readback import verify
    return verify(**kwargs)


def bind_from_files(
    *, final_manifest_path: Path, immutable_audit_path: Path,
    source_readback_path: Path, current_readback_path: Path,
    output_path: Path, current_model_git_commit: str,
    observed_at_utc: datetime, run_id: str,
) -> tuple[dict[str, object], str]:
    """Securely read, bind, and write one immutable preregistration manifest."""
    final_manifest, final_sha = read_root_owned_0600_json(final_manifest_path, "final manifest")
    immutable_audit, immutable_sha = read_root_owned_0600_json(immutable_audit_path, "immutable audit")
    source, source_sha = read_root_owned_0600_json(source_readback_path, "readback source evidence")
    readback, readback_sha = read_root_owned_0600_json(current_readback_path, "current readback")
    _verify_current_readback(
        source=source, source_raw_sha256=source_sha,
        artifact=readback, artifact_raw_sha256=readback_sha,
        final_manifest=final_manifest, final_raw_sha256=final_sha,
        immutable_audit=immutable_audit, immutable_audit_raw_sha256=immutable_sha,
        proposed_model_git_commit=current_model_git_commit,
    )
    lineage = source.get("lineage_mapping")
    if type(lineage) is not dict:
        raise RuntimeBoundaryError("verified source lineage mapping is absent")
    manifest = bind_perpetual_readback(
        final_manifest=final_manifest, immutable_audit=immutable_audit,
        current_readback=readback, lineage_mapping=lineage,
        final_manifest_file_sha256=final_sha,
        immutable_audit_file_sha256=immutable_sha,
        current_model_git_commit=current_model_git_commit,
        observed_at_utc=observed_at_utc, run_id=run_id,
    )
    if (manifest.get("preflight", {}).get("status") != "PASS" or
            manifest.get("preflight", {}).get("fixture_only") is not True or
            manifest.get("preflight", {}).get("model_fit_authorized") is not False or
            manifest.get("execution", {}).get("model_fit_started") is not False):
        raise RuntimeBoundaryError("pure binder returned an unauthorized state")
    output_sha = write_json_once(output_path, manifest)
    return manifest, output_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument("--immutable-audit", type=Path, required=True)
    parser.add_argument("--current-readback-source", type=Path, required=True)
    parser.add_argument("--current-readback", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-git-commit", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        _manifest, output_sha = bind_from_files(
            final_manifest_path=args.final_manifest,
            immutable_audit_path=args.immutable_audit,
            source_readback_path=args.current_readback_source,
            current_readback_path=args.current_readback,
            output_path=args.output,
            current_model_git_commit=args.model_git_commit,
            observed_at_utc=_utc(args.observed_at_utc, "observation"), run_id=args.run_id,
        )
    except (RuntimeBoundaryError, PreregistrationError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": "PERSISTED_FIXTURE_ONLY", "output_sha256": output_sha,
        "model_fit_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
