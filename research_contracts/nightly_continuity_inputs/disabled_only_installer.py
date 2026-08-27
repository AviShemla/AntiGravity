"""Root-owned, disabled-only installer/auditor for S02 recurring continuity.

This module installs immutable files only. It never calls ``systemctl start``,
``enable``, ``restart``, or ``daemon-reload``. Unit activation is a separate,
explicitly approved deployment phase outside this contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol, Sequence


CONTRACT_ID = "codex-nightly-continuity-disabled-deployment-v1"
ROLLBACK_CONTRACT_ID = "codex-nightly-continuity-disabled-rollback-v1"
AUDIT_CONTRACT_ID = "codex-nightly-continuity-disabled-audit-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEPLOYMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{7,127}$")

RECURRING_UNITS = frozenset(
    {
        "codex-market-ingestion@.service",
        "codex-market-ingestion-postflight@.service",
        "codex-market-ingestion-handoff@.service",
        "codex-market-nightly-continuity.service",
        "codex-market-nightly-continuity.timer",
        "codex-market-nightly-continuity-watchdog.service",
        "codex-market-nightly-continuity-watchdog.timer",
    }
)
LEGACY_SAFETY_UNITS = frozenset(
    {
        "ag-sniper.service",
        "antigravity-nightly.timer",
        "antigravity-qa-watchdog.timer",
    }
)
ALL_GUARDED_UNITS = RECURRING_UNITS | LEGACY_SAFETY_UNITS

REQUIRED_ROLES = frozenset(
    {
        "CALENDAR",
        "CONTROLLER_CONFIG",
        "PREFLIGHT_ENTRYPOINT",
        "CONTROLLER_ENTRYPOINT",
        *(f"SYSTEMD_UNIT:{name}" for name in RECURRING_UNITS),
    }
)
EXACT_ROLE_TARGETS = {
    "CALENDAR": "/etc/codex-oracle/nyse-calendar-2026.json",
    "CONTROLLER_CONFIG": "/etc/codex-oracle/nightly-continuity.json",
    **{
        f"SYSTEMD_UNIT:{name}": f"/etc/systemd/system/{name}"
        for name in RECURRING_UNITS
    },
}
ALLOWED_MODES = {
    "CALENDAR": 0o600,
    "CONTROLLER_CONFIG": 0o600,
    "PREFLIGHT_ENTRYPOINT": 0o555,
    "CONTROLLER_ENTRYPOINT": 0o555,
    **{f"SYSTEMD_UNIT:{name}": 0o644 for name in RECURRING_UNITS},
}


class InstallerContractError(RuntimeError):
    """The disabled-only installation or its evidence failed closed."""


@dataclass(frozen=True)
class UnitState:
    active_state: str
    unit_file_state: str


class UnitInspector(Protocol):
    def inspect(self, unit: str) -> UnitState: ...


class SystemctlShowInspector:
    """Read-only systemd inspector; the only subprocess command is ``show``."""

    def __init__(self, systemctl: str = "/usr/bin/systemctl") -> None:
        if systemctl != "/usr/bin/systemctl":
            raise InstallerContractError("systemctl path must be /usr/bin/systemctl")
        self._systemctl = systemctl

    def inspect(self, unit: str) -> UnitState:
        if unit not in ALL_GUARDED_UNITS:
            raise InstallerContractError("unit escaped the guarded allowlist")
        result = subprocess.run(
            [
                self._systemctl,
                "show",
                unit,
                "--property=ActiveState",
                "--property=UnitFileState",
                "--value",
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise InstallerContractError("read-only systemd inspection failed")
        rows = result.stdout.splitlines()
        if len(rows) != 2:
            raise InstallerContractError("systemd inspection result shape is invalid")
        return UnitState(rows[0].strip(), rows[1].strip())


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_mode(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0[0-7]{3}", value):
        raise InstallerContractError("artifact mode must be a four-digit octal string")
    return int(value, 8)


def _mode_matches(actual: int, expected: int, *, fixture_mode: bool) -> bool:
    if not (fixture_mode and os.name == "nt"):
        return actual == expected
    # Windows fixtures can preserve only the write/no-write distinction. The
    # production path remains Linux-only and requires the exact POSIX mode.
    return bool(actual & stat.S_IWUSR) == bool(expected & stat.S_IWUSR)


def _relative_source(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise InstallerContractError("artifact source must be a non-empty path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise InstallerContractError("artifact source must be normalized and relative")
    return path


def _absolute_target(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise InstallerContractError("artifact target must be a non-empty path")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise InstallerContractError("artifact target must be normalized and absolute")
    if str(path) in {"/", "/etc", "/opt", "/var"}:
        raise InstallerContractError("artifact target is dangerously broad")
    return path


def _validate_entrypoint_target(role: str, target: str, sha256: str) -> None:
    if role == "PREFLIGHT_ENTRYPOINT":
        pattern = rf"^/opt/codex-oracle/releases/market-ingestion-preflight-{sha256}/run-select-only-preflight$"
    else:
        pattern = rf"^/opt/codex-oracle/releases/nightly-continuity-{sha256}/run-nightly-continuity$"
    if not re.fullmatch(pattern, target):
        raise InstallerContractError(f"{role} target does not bind its release hash")


def validate_deployment_manifest(raw: Mapping[str, object]) -> None:
    if raw.get("contract_id") != CONTRACT_ID:
        raise InstallerContractError("deployment contract identity mismatch")
    deployment_id = raw.get("deployment_id")
    if not isinstance(deployment_id, str) or not DEPLOYMENT_ID_RE.fullmatch(deployment_id):
        raise InstallerContractError("deployment_id is invalid")
    if raw.get("apply_mode") != "INSTALL_DISABLED_ONLY":
        raise InstallerContractError("deployment mode is not disabled-only")
    for key in (
        "no_enable",
        "no_start",
        "no_restart",
        "no_daemon_reload",
        "no_turso_writes",
        "no_snapshot_lifecycle_changes",
    ):
        if raw.get(key) is not True:
            raise InstallerContractError(f"{key} must be true")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise InstallerContractError("artifacts must be a non-empty array")
    seen_roles: set[str] = set()
    seen_targets: set[str] = set()
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise InstallerContractError("artifact entry must be an object")
        role = item.get("role")
        if role not in REQUIRED_ROLES or role in seen_roles:
            raise InstallerContractError("artifact role is missing, unknown, or duplicated")
        seen_roles.add(str(role))
        _relative_source(item.get("source"))
        target = str(_absolute_target(item.get("target")))
        if target in seen_targets:
            raise InstallerContractError("artifact target is duplicated")
        seen_targets.add(target)
        expected_hash = item.get("sha256")
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            raise InstallerContractError("artifact SHA-256 is invalid")
        if _parse_mode(item.get("mode")) != ALLOWED_MODES[str(role)]:
            raise InstallerContractError("artifact mode does not match its role")
        if role in EXACT_ROLE_TARGETS and target != EXACT_ROLE_TARGETS[str(role)]:
            raise InstallerContractError("artifact target does not match its role")
        if role in {"PREFLIGHT_ENTRYPOINT", "CONTROLLER_ENTRYPOINT"}:
            _validate_entrypoint_target(str(role), target, expected_hash)
    if seen_roles != REQUIRED_ROLES:
        raise InstallerContractError("deployment manifest does not cover every required role")
    unit_states = raw.get("required_unit_states")
    if not isinstance(unit_states, Mapping) or set(unit_states) != ALL_GUARDED_UNITS:
        raise InstallerContractError("required unit-state set is incomplete or excessive")
    for unit, state_value in unit_states.items():
        if state_value != {"active_state": "inactive", "unit_file_state": "disabled"}:
            raise InstallerContractError(f"{unit} is not pinned inactive/disabled")


def load_manifest(path: Path, expected_sha256: str) -> Mapping[str, object]:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise InstallerContractError("deployment manifest SHA-256 is invalid")
    encoded = path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise InstallerContractError("deployment manifest SHA-256 mismatch")
    raw = json.loads(encoded.decode("utf-8"))
    if encoded != canonical_bytes(raw):
        raise InstallerContractError("deployment manifest is not canonical JSON")
    if not isinstance(raw, Mapping):
        raise InstallerContractError("deployment manifest must be an object")
    validate_deployment_manifest(raw)
    return raw


def _require_disabled_units(inspector: UnitInspector) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for unit in sorted(ALL_GUARDED_UNITS):
        state = inspector.inspect(unit)
        if state.active_state != "inactive" or state.unit_file_state != "disabled":
            raise InstallerContractError(f"{unit} is not inactive and disabled")
        evidence[unit] = {
            "active_state": state.active_state,
            "unit_file_state": state.unit_file_state,
        }
    return evidence


def _fixture_target(root: Path, posix_target: str) -> Path:
    relative = PurePosixPath(posix_target).relative_to("/")
    return root.joinpath(*relative.parts)


def _secure_source(path: Path, expected_sha256: str) -> None:
    if path.is_symlink():
        raise InstallerContractError("source artifact must not be a symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise InstallerContractError("source artifact must be a single-link regular file")
    if sha256_file(path) != expected_sha256:
        raise InstallerContractError("source artifact hash mismatch")


def _atomic_copy(source: Path, target: Path, mode: int, *, fixture_mode: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise InstallerContractError("target must not be a symlink")
    candidate = target.parent / f".{target.name}.candidate-{os.getpid()}"
    if candidate.exists() or candidate.is_symlink():
        raise InstallerContractError("candidate path already exists")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(candidate, flags, mode)
        with source.open("rb") as read_handle, os.fdopen(fd, "wb") as write_handle:
            shutil.copyfileobj(read_handle, write_handle)
            write_handle.flush()
            os.fsync(write_handle.fileno())
        os.chmod(candidate, mode)
        if not fixture_mode:
            os.chown(candidate, 0, 0)
        os.replace(candidate, target)
    finally:
        if candidate.exists():
            candidate.unlink()


def _write_once_canonical(
    path: Path, value: Mapping[str, object], *, mode: int, fixture_mode: bool
) -> None:
    """Create immutable evidence without following links or overwriting evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, mode)
        if not fixture_mode:
            os.chown(path, 0, 0)
    except Exception:
        if path.exists() and not path.is_symlink():
            path.unlink()
        raise


def install_disabled_only(
    manifest: Mapping[str, object],
    *,
    manifest_sha256: str,
    source_root: Path,
    target_root: Path,
    rollback_root: Path,
    inspector: UnitInspector,
    observed_at: datetime,
    fixture_mode: bool = False,
) -> dict[str, object]:
    """Install files while proving all guarded units remain disabled/inactive."""

    validate_deployment_manifest(manifest)
    if not SHA256_RE.fullmatch(manifest_sha256):
        raise InstallerContractError("manifest SHA-256 is invalid")
    if hashlib.sha256(canonical_bytes(manifest)).hexdigest() != manifest_sha256:
        raise InstallerContractError("in-memory manifest SHA-256 mismatch")
    if observed_at.tzinfo is None:
        raise InstallerContractError("observed_at must be timezone-aware")
    if not fixture_mode:
        if os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise InstallerContractError("production installation must run as root")
        if target_root != Path("/"):
            raise InstallerContractError("production target root must be /")
    before_units = _require_disabled_units(inspector)
    rollback_dir = rollback_root / str(manifest["deployment_id"])
    if rollback_dir.exists() or rollback_dir.is_symlink():
        raise InstallerContractError("rollback directory already exists")
    rollback_dir.mkdir(parents=True)
    records: list[dict[str, object]] = []
    try:
        # Phase 1 is read-only with respect to deployment targets: verify every
        # source and capture every previous target before any replacement.
        for item in manifest["artifacts"]:  # type: ignore[index]
            role = str(item["role"])
            source = source_root.joinpath(*_relative_source(item["source"]).parts)
            expected_hash = str(item["sha256"])
            _secure_source(source, expected_hash)
            target = _fixture_target(target_root, str(item["target"]))
            previous: dict[str, object]
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file():
                    raise InstallerContractError("existing target is not a regular file")
                prior_hash = sha256_file(target)
                prior_mode = stat.S_IMODE(target.stat().st_mode)
                backup = rollback_dir / "previous" / f"{len(records):03d}-{target.name}"
                backup.parent.mkdir(parents=True, exist_ok=True)
                _atomic_copy(target, backup, prior_mode, fixture_mode=fixture_mode)
                previous = {
                    "state": "PRESENT",
                    "sha256": prior_hash,
                    "mode": f"0{prior_mode:o}",
                    "backup": str(backup.relative_to(rollback_dir)).replace("\\", "/"),
                }
            else:
                previous = {"state": "ABSENT"}
            mode = _parse_mode(item["mode"])
            records.append(
                {
                    "role": role,
                    "target": str(item["target"]),
                    "installed_sha256": expected_hash,
                    "installed_mode": f"0{mode:o}",
                    "previous": previous,
                }
            )
        rollback = {
            "contract_id": ROLLBACK_CONTRACT_ID,
            "deployment_contract_id": CONTRACT_ID,
            "deployment_id": manifest["deployment_id"],
            "deployment_manifest_sha256": manifest_sha256,
            "prepared_at_utc": observed_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "fixture_mode": fixture_mode,
            "no_enable": True,
            "no_start": True,
            "no_restart": True,
            "no_daemon_reload": True,
            "unit_states_before": before_units,
            "artifacts": records,
            "status": "PREPARED_BEFORE_TARGET_MUTATION",
        }
        rollback_path = rollback_dir / "rollback-manifest.json"
        _write_once_canonical(
            rollback_path, rollback, mode=0o600, fixture_mode=fixture_mode
        )

        # Re-check safety immediately before the first target mutation.
        _require_disabled_units(inspector)
        for item in manifest["artifacts"]:  # type: ignore[index]
            source = source_root.joinpath(*_relative_source(item["source"]).parts)
            target = _fixture_target(target_root, str(item["target"]))
            _atomic_copy(
                source,
                target,
                _parse_mode(item["mode"]),
                fixture_mode=fixture_mode,
            )
            if sha256_file(target) != item["sha256"]:
                raise InstallerContractError("installed artifact hash mismatch")

        after_units = _require_disabled_units(inspector)
        completion = {
            "contract_id": CONTRACT_ID,
            "deployment_id": manifest["deployment_id"],
            "deployment_manifest_sha256": manifest_sha256,
            "rollback_manifest_sha256": sha256_file(rollback_path),
            "installed_at_utc": observed_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "unit_states_after": after_units,
            "artifact_count": len(records),
            "status": "INSTALLED_DISABLED_ONLY",
        }
        _write_once_canonical(
            rollback_dir / "installation-completion.json",
            completion,
            mode=0o600,
            fixture_mode=fixture_mode,
        )
        return rollback
    except Exception:
        # Partial install evidence stays quarantined for explicit rollback.
        raise


def audit_disabled_installation(
    manifest: Mapping[str, object],
    rollback: Mapping[str, object],
    *,
    manifest_sha256: str,
    target_root: Path,
    inspector: UnitInspector,
    observed_at: datetime,
    fixture_mode: bool = False,
) -> dict[str, object]:
    validate_deployment_manifest(manifest)
    if rollback.get("contract_id") != ROLLBACK_CONTRACT_ID:
        raise InstallerContractError("rollback manifest identity mismatch")
    if rollback.get("deployment_manifest_sha256") != manifest_sha256:
        raise InstallerContractError("rollback/deployment manifest hash mismatch")
    if rollback.get("status") != "PREPARED_BEFORE_TARGET_MUTATION":
        raise InstallerContractError("rollback manifest was not prepared before mutation")
    if any(
        rollback.get(key) is not True
        for key in ("no_enable", "no_start", "no_restart", "no_daemon_reload")
    ):
        raise InstallerContractError("rollback manifest weakened disabled-only policy")
    unit_states = _require_disabled_units(inspector)
    evidence: list[dict[str, object]] = []
    by_role = {str(item["role"]): item for item in manifest["artifacts"]}  # type: ignore[index]
    for role in sorted(REQUIRED_ROLES):
        item = by_role[role]
        target = _fixture_target(target_root, str(item["target"]))
        if target.is_symlink() or not target.is_file():
            raise InstallerContractError("installed target is absent or unsafe")
        info = target.stat()
        if info.st_nlink != 1 or not _mode_matches(
            stat.S_IMODE(info.st_mode),
            _parse_mode(item["mode"]),
            fixture_mode=fixture_mode,
        ):
            raise InstallerContractError("installed target mode/link count mismatch")
        if not fixture_mode and (info.st_uid != 0 or info.st_gid != 0):
            raise InstallerContractError("installed target is not root-owned")
        actual_hash = sha256_file(target)
        if actual_hash != item["sha256"]:
            raise InstallerContractError("installed target hash mismatch")
        evidence.append(
            {
                "role": role,
                "target": str(item["target"]),
                "sha256": actual_hash,
                "mode": item["mode"],
                "owner": "FIXTURE_CURRENT_USER" if fixture_mode else "root:root",
            }
        )
    return {
        "contract_id": AUDIT_CONTRACT_ID,
        "deployment_id": manifest["deployment_id"],
        "deployment_manifest_sha256": manifest_sha256,
        "observed_at_utc": observed_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "fixture_mode": fixture_mode,
        "no_enable_observed": True,
        "no_start_observed": True,
        "unit_states": unit_states,
        "artifacts": evidence,
        "status": "OBSERVED_DISABLED_ONLY",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--rollback-root", type=Path, required=True)
    parser.add_argument("--apply-disabled-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.apply_disabled_only:
            raise InstallerContractError("explicit --apply-disabled-only flag is required")
        manifest = load_manifest(args.manifest, args.manifest_sha256)
        rollback = install_disabled_only(
            manifest,
            manifest_sha256=args.manifest_sha256,
            source_root=args.source_root,
            target_root=Path("/"),
            rollback_root=args.rollback_root,
            inspector=SystemctlShowInspector(),
            observed_at=datetime.now(timezone.utc),
            fixture_mode=False,
        )
        print(
            "DISABLED_ONLY_INSTALLED "
            f"deployment_id={rollback['deployment_id']} artifacts={len(rollback['artifacts'])}"
        )
        return 0
    except (InstallerContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DISABLED_ONLY_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
