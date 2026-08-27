"""Immutable release-manifest and entrypoint binding contract."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_CONTRACT = "codex-oracle-immutable-release-v1"
REQUIRED_ENTRYPOINTS: Mapping[str, tuple[str, ...]] = {
    "nightly-continuity": (
        "run-nightly-continuity",
        "run-nightly-continuity-watchdog",
    ),
    "market-ingestion": ("run-market-ingestion",),
    "market-ingestion-handoff": (
        "run-market-ingestion-postflight",
        "run-market-ingestion-handoff",
    ),
}
REQUIRED_ARTIFACTS: Mapping[str, Mapping[str, int]] = {
    "nightly-continuity": {
        "run-nightly-continuity": 0o700,
        "run-nightly-continuity-watchdog": 0o700,
        "continuity_controller.py": 0o600,
        "release_layout.py": 0o600,
    },
    "market-ingestion": {
        "run-market-ingestion": 0o700,
        "stage_runner.py": 0o600,
        "release_layout.py": 0o600,
        "payload/run-market-ingestion-impl": 0o700,
    },
    "market-ingestion-handoff": {
        "run-market-ingestion-postflight": 0o700,
        "run-market-ingestion-handoff": 0o700,
        "stage_runner.py": 0o600,
        "release_layout.py": 0o600,
        "payload/run-market-ingestion-postflight-impl": 0o700,
        "payload/run-market-ingestion-handoff-impl": 0o700,
    },
}


class ReleaseLayoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseBindings:
    controller_id: str
    ingestion_id: str
    handoff_id: str
    controller: Path
    ingestion: Path
    handoff: Path


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _secure(path: Path, mode: int, *, require_root: bool) -> None:
    if path.is_symlink():
        raise ReleaseLayoutError(f"symlink forbidden in immutable release: {path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ReleaseLayoutError(f"release artifact is not a single-link regular file: {path}")
    if stat.S_IMODE(info.st_mode) != mode:
        raise ReleaseLayoutError(f"release artifact mode mismatch: {path}")
    if require_root and os.name != "nt" and info.st_uid != 0:
        raise ReleaseLayoutError(f"release artifact is not root-owned: {path}")


def verify_release(
    release_root: Path,
    release_kind: str,
    release_id: str,
    *,
    require_root: bool = True,
) -> Path:
    if release_kind not in REQUIRED_ENTRYPOINTS or not SHA256_RE.fullmatch(release_id):
        raise ReleaseLayoutError("release kind or identity is invalid")
    directory = release_root / f"{release_kind}-{release_id}"
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseLayoutError(f"immutable release directory is missing: {directory}")
    info = directory.stat()
    if require_root and os.name != "nt" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700):
        raise ReleaseLayoutError(f"release directory must be root-owned mode 0700: {directory}")
    manifest_path = directory / "release-manifest.json"
    _secure(manifest_path, 0o600, require_root=require_root)
    encoded = manifest_path.read_bytes()
    raw = json.loads(encoded.decode("utf-8"))
    if encoded != canonical_bytes(raw) or hashlib.sha256(encoded).hexdigest() != release_id:
        raise ReleaseLayoutError("release manifest is noncanonical or does not bind the directory identity")
    if raw.get("contract_id") != MANIFEST_CONTRACT or raw.get("release_kind") != release_kind:
        raise ReleaseLayoutError("release manifest contract/kind mismatch")
    rows = raw.get("files")
    if not isinstance(rows, list) or not rows:
        raise ReleaseLayoutError("release manifest has no files")
    listed: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ReleaseLayoutError("release file entry is not an object")
        relative = str(row.get("path", ""))
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or ".." in candidate.parts or relative in listed:
            raise ReleaseLayoutError("release file path is invalid or duplicated")
        listed.add(relative)
        mode_text = str(row.get("mode", ""))
        if mode_text not in {"0600", "0700"}:
            raise ReleaseLayoutError("release file mode is outside the allowlist")
        artifact = directory / candidate
        _secure(artifact, int(mode_text, 8), require_root=require_root)
        if not SHA256_RE.fullmatch(str(row.get("sha256", ""))) or sha256_file(artifact) != row["sha256"]:
            raise ReleaseLayoutError(f"release artifact hash mismatch: {relative}")
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != listed | {"release-manifest.json"}:
        raise ReleaseLayoutError("release contains unmanifested or missing files")
    if not set(REQUIRED_ARTIFACTS[release_kind]).issubset(listed):
        raise ReleaseLayoutError("release is missing a required runtime artifact")
    for relative, mode in REQUIRED_ARTIFACTS[release_kind].items():
        _secure(directory / relative, mode, require_root=require_root)
    return directory


def verify_release_set(
    release_root: Path,
    *,
    controller_id: str,
    ingestion_id: str,
    handoff_id: str,
    require_root: bool = True,
) -> ReleaseBindings:
    return ReleaseBindings(
        controller_id=controller_id,
        ingestion_id=ingestion_id,
        handoff_id=handoff_id,
        controller=verify_release(release_root, "nightly-continuity", controller_id, require_root=require_root),
        ingestion=verify_release(release_root, "market-ingestion", ingestion_id, require_root=require_root),
        handoff=verify_release(release_root, "market-ingestion-handoff", handoff_id, require_root=require_root),
    )
