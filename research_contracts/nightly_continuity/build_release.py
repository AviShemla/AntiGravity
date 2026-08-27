"""Atomically build and independently verify one immutable release directory."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Sequence

from release_layout import (
    MANIFEST_CONTRACT,
    REQUIRED_ARTIFACTS,
    REQUIRED_ENTRYPOINTS,
    ReleaseLayoutError,
    canonical_bytes,
    verify_release,
)


def _source_files(source: Path) -> tuple[Path, ...]:
    if source.is_symlink() or not source.is_dir():
        raise ReleaseLayoutError("release source is missing or is a symlink")
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ReleaseLayoutError(f"release source contains a symlink: {path}")
        if path.is_file():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ReleaseLayoutError(f"release source is not single-link: {path}")
            files.append(path)
    if not files:
        raise ReleaseLayoutError("release source has no files")
    return tuple(files)


def build_release(
    source: Path, release_root: Path, release_kind: str, *,
    require_root: bool = True,
) -> tuple[str, Path]:
    if release_kind not in REQUIRED_ENTRYPOINTS:
        raise ReleaseLayoutError("release kind is outside the allowlist")
    release_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if release_root.is_symlink():
        raise ReleaseLayoutError("release root must not be a symlink")
    if require_root and os.name != "nt":
        root_info = release_root.stat()
        if root_info.st_uid != 0 or stat.S_IMODE(root_info.st_mode) != 0o700:
            raise ReleaseLayoutError("release root must be root-owned mode 0700")
    files = _source_files(source)
    relative_files = {path.relative_to(source).as_posix(): path for path in files}
    if not set(REQUIRED_ARTIFACTS[release_kind]).issubset(relative_files):
        raise ReleaseLayoutError("release source lacks a required runtime artifact")
    staging = release_root / f".{release_kind}.build.{os.getpid()}.{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        rows = []
        for relative, original in sorted(relative_files.items()):
            target = staging / relative
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            mode = REQUIRED_ARTIFACTS[release_kind].get(relative, 0o600)
            encoded = original.read_bytes()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(target, flags, mode)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(target, mode)
            rows.append({
                "path": relative,
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "mode": f"{mode:04o}",
            })
        manifest = canonical_bytes({
            "contract_id": MANIFEST_CONTRACT,
            "release_kind": release_kind,
            "files": rows,
        })
        release_id = hashlib.sha256(manifest).hexdigest()
        manifest_path = staging / "release-manifest.json"
        descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(manifest)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(manifest_path, 0o600)
        directory_fd = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        destination = release_root / f"{release_kind}-{release_id}"
        if destination.exists() or destination.is_symlink():
            verify_release(
                release_root, release_kind, release_id,
                require_root=require_root,
            )
            shutil.rmtree(staging)
            return release_id, destination
        os.replace(staging, destination)
        parent_fd = os.open(release_root, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        verify_release(
            release_root, release_kind, release_id,
            require_root=require_root,
        )
        return release_id, destination
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--kind", choices=tuple(REQUIRED_ENTRYPOINTS), required=True)
    args = parser.parse_args(argv)
    release_id, destination = build_release(
        args.source, args.release_root, args.kind, require_root=True,
    )
    print(f"IMMUTABLE_RELEASE_BUILT kind={args.kind} id={release_id} path={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
