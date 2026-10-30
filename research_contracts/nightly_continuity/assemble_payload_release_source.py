"""Assemble reviewed runtime files into an immutable-release source tree.

This is an offline packaging operation.  It never contacts Turso, modifies
systemd, or changes a snapshot lifecycle.  The later ``build_release.py`` step
hashes every copied byte into the release identity.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence


class AssemblyError(RuntimeError):
    pass


COMMON = {
    "nightly_continuity_impl/stage_runner.py": "stage_runner.py",
    "nightly_continuity_impl/release_layout.py": "release_layout.py",
    "nightly_continuity_impl/payload_adapter_contract.py": "payload_adapter_contract.py",
}
INGESTION_FILES: Mapping[str, str] = {
    **COMMON,
    "nightly_continuity_impl/runner_sources/run-market-ingestion": "run-market-ingestion",
    "nightly_continuity_impl/payload_adapter_sources/run-market-ingestion-impl": "payload/run-market-ingestion-impl",
    "antigravity/scripts/rebuild_market_features_to_turso.py": "implementation/scripts/rebuild_market_features_to_turso.py",
    "antigravity/scripts/stage_market_features_to_turso.py": "implementation/scripts/stage_market_features_to_turso.py",
    "antigravity/market_data_provider.py": "implementation/market_data_provider.py",
    "antigravity/market_data_guard.py": "implementation/market_data_guard.py",
    "antigravity/turso_read_pipeline.py": "implementation/turso_read_pipeline.py",
    "antigravity/model_lineage.py": "implementation/model_lineage.py",
}
HANDOFF_FILES: Mapping[str, str] = {
    **COMMON,
    "nightly_continuity_impl/runner_sources/run-market-ingestion-postflight": "run-market-ingestion-postflight",
    "nightly_continuity_impl/runner_sources/run-market-ingestion-handoff": "run-market-ingestion-handoff",
    "nightly_continuity_impl/payload_adapter_sources/run-market-ingestion-postflight-impl": "payload/run-market-ingestion-postflight-impl",
    "nightly_continuity_impl/payload_adapter_sources/run-market-ingestion-handoff-impl": "payload/run-market-ingestion-handoff-impl",
    "ingestion_handoff_impl/market_ingestion_postflight_cli.py": "implementation/market_ingestion_postflight_cli.py",
    "ingestion_handoff_impl/market_ingestion_postflight.py": "implementation/market_ingestion_postflight.py",
    "ingestion_handoff_impl/verify_postflight_handoff.py": "implementation/verify_postflight_handoff.py",
    "antigravity/turso_read_pipeline.py": "implementation/turso_read_pipeline.py",
    "antigravity/model_lineage.py": "implementation/model_lineage.py",
}
FILE_MAPS = {
    "market-ingestion": INGESTION_FILES,
    "market-ingestion-handoff": HANDOFF_FILES,
}
EXECUTABLE_NAMES = {
    "run-market-ingestion",
    "run-market-ingestion-postflight",
    "run-market-ingestion-handoff",
    "payload/run-market-ingestion-impl",
    "payload/run-market-ingestion-postflight-impl",
    "payload/run-market-ingestion-handoff-impl",
}

SOURCE_PREFIX_ALIASES = {
    "nightly_continuity_impl": "research_contracts/nightly_continuity",
    "ingestion_handoff_impl": "research_contracts/market_ingestion_handoff",
    "antigravity": "",
}


def resolve_reviewed_source(workspace_root: Path, source_relative: str) -> Path:
    """Resolve an allowlisted source in isolated or canonical layouts.

    The isolated review tree uses short top-level package names while the
    canonical repository nests those same reviewed packages under
    ``research_contracts``.  Resolution is deterministic: prefer the exact
    reviewed path, otherwise try the single declared prefix alias.  Every
    candidate must remain inside the workspace after symlink resolution.
    """

    relative = PurePosixPath(source_relative)
    if relative.is_absolute() or not relative.parts or any(
        part in ("", ".", "..") for part in relative.parts
    ):
        raise AssemblyError(f"reviewed source path is unsafe: {source_relative}")

    candidates = [Path(*relative.parts)]
    alias = SOURCE_PREFIX_ALIASES.get(relative.parts[0])
    if alias is not None:
        candidates.append(Path(*PurePosixPath(alias).parts, *relative.parts[1:]))

    try:
        root = workspace_root.resolve(strict=True)
    except OSError as exc:
        raise AssemblyError("workspace root cannot be resolved") from exc

    for candidate_relative in candidates:
        candidate = workspace_root / candidate_relative
        if not candidate.exists():
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise AssemblyError(
                f"reviewed source escapes the workspace: {source_relative}"
            ) from exc
        return candidate
    raise AssemblyError(f"reviewed source is missing: {source_relative}")


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise AssemblyError(f"reviewed source is missing or unsafe: {path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AssemblyError(f"reviewed source is not a single-link regular file: {path}")
    return path.read_bytes()


def assemble_source(
    workspace_root: Path, output: Path, release_kind: str
) -> tuple[Path, ...]:
    if release_kind not in FILE_MAPS:
        raise AssemblyError("release kind is outside the payload allowlist")
    if workspace_root.is_symlink() or not workspace_root.is_dir():
        raise AssemblyError("workspace root is missing or unsafe")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.assemble.{os.getpid()}.{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    created: list[Path] = []
    try:
        for source_relative, target_relative in FILE_MAPS[release_kind].items():
            encoded = _read_regular(
                resolve_reviewed_source(workspace_root, source_relative)
            )
            target = staging / target_relative
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            mode = 0o700 if target_relative in EXECUTABLE_NAMES else 0o600
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(target, flags, mode)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(target, mode)
            created.append(target)
        os.replace(staging, output)
        return tuple(output / path.relative_to(staging) for path in created)
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=tuple(FILE_MAPS), required=True)
    args = parser.parse_args(argv)
    paths = assemble_source(args.workspace_root, args.output, args.kind)
    print(f"PAYLOAD_SOURCE_ASSEMBLED kind={args.kind} files={len(paths)} path={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
