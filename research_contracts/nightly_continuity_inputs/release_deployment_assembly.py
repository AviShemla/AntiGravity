"""Assemble one deterministic, fixture-verifiable recurring deployment contract.

The assembler is read-only except for an optional write-once evidence output.
It verifies prebuilt immutable releases and rendered units; it never builds,
deploys, activates, or reloads a unit and never contacts Turso.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Mapping

try:
    from s02_recurring_deployment_impl import disabled_only_installer as installer
    from s02_recurring_deployment_impl import nyse_calendar_artifact as calendar_contract
except ModuleNotFoundError:  # Canonical repository package path.
    from research_contracts.nightly_continuity_inputs import (
        disabled_only_installer as installer,
    )
    from research_contracts.nightly_continuity_inputs import (
        nyse_calendar_artifact as calendar_contract,
    )


ASSEMBLY_CONTRACT_ID = "codex-recurring-release-deployment-assembly-v1"
RELEASE_CONTRACT_ID = "codex-oracle-immutable-release-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

RELEASE_REQUIRED = {
    "nightly-continuity": {
        "run-nightly-continuity": "0700",
        "run-nightly-continuity-watchdog": "0700",
        "continuity_controller.py": "0600",
        "release_layout.py": "0600",
    },
    "market-ingestion": {
        "run-market-ingestion": "0700",
        "stage_runner.py": "0600",
        "release_layout.py": "0600",
        "payload/run-market-ingestion-impl": "0700",
    },
    "market-ingestion-handoff": {
        "run-market-ingestion-postflight": "0700",
        "run-market-ingestion-handoff": "0700",
        "stage_runner.py": "0600",
        "release_layout.py": "0600",
        "payload/run-market-ingestion-postflight-impl": "0700",
        "payload/run-market-ingestion-handoff-impl": "0700",
    },
}

RUNNERS = {
    "CONTROLLER": ("nightly-continuity", "run-nightly-continuity"),
    "WATCHDOG": ("nightly-continuity", "run-nightly-continuity-watchdog"),
    "INGESTION": ("market-ingestion", "run-market-ingestion"),
    "POSTFLIGHT": ("market-ingestion-handoff", "run-market-ingestion-postflight"),
    "HANDOFF": ("market-ingestion-handoff", "run-market-ingestion-handoff"),
}

UNIT_RUNNER_BINDINGS = {
    "codex-market-nightly-continuity.service": "CONTROLLER",
    "codex-market-nightly-continuity-watchdog.service": "WATCHDOG",
    "codex-market-ingestion@.service": "INGESTION",
    "codex-market-ingestion-postflight@.service": "POSTFLIGHT",
    "codex-market-ingestion-handoff@.service": "HANDOFF",
}

CONFIG_EXACT = {
    "state_root": "/var/lib/codex-oracle/nightly-continuity",
    "handoff_root": "/var/lib/codex-oracle/market-ingestion",
    "systemctl_path": "/usr/bin/systemctl",
    "progress_marker_template": (
        "/var/lib/codex-oracle/market-ingestion/{source_session}/progress.json"
    ),
}
CONFIG_POSITIVE_NUMBERS = frozenset(
    {
        "settlement_delay_seconds",
        "calendar_min_future_horizon_seconds",
        "max_preflight_age_seconds",
        "max_handoff_age_seconds",
        "max_checkpoint_age_seconds",
        "max_load_per_cpu",
        "min_available_memory_mb",
        "min_free_disk_mb",
    }
)


class AssemblyContractError(RuntimeError):
    pass


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


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise AssemblyContractError("assembly input path must be normalized and relative")
    return path


def _secure_regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise AssemblyContractError(f"input is absent or a symlink: {path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AssemblyContractError(f"input is not a single-link regular file: {path}")


def _read_canonical(path: Path) -> Mapping[str, object]:
    _secure_regular(path)
    encoded = path.read_bytes()
    raw = json.loads(encoded.decode("utf-8"))
    if not isinstance(raw, Mapping) or encoded != canonical_bytes(raw):
        raise AssemblyContractError(f"JSON input is not canonical: {path}")
    return raw


def _verify_release(
    release_root: Path, kind: str, release_id: str
) -> tuple[Path, Mapping[str, Mapping[str, str]]]:
    if kind not in RELEASE_REQUIRED or not SHA256_RE.fullmatch(release_id):
        raise AssemblyContractError("release kind or identity is invalid")
    directory = release_root / f"{kind}-{release_id}"
    if directory.is_symlink() or not directory.is_dir():
        raise AssemblyContractError("immutable release directory is missing")
    manifest_path = directory / "release-manifest.json"
    raw = _read_canonical(manifest_path)
    encoded = manifest_path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != release_id:
        raise AssemblyContractError("release ID does not bind canonical manifest")
    if raw.get("contract_id") != RELEASE_CONTRACT_ID or raw.get("release_kind") != kind:
        raise AssemblyContractError("release manifest contract/kind mismatch")
    rows = raw.get("files")
    if not isinstance(rows, list) or not rows:
        raise AssemblyContractError("release file inventory is empty")
    inventory: dict[str, Mapping[str, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise AssemblyContractError("release file row is not an object")
        relative = str(row.get("path", ""))
        _relative(relative)
        if relative in inventory:
            raise AssemblyContractError("release file path is duplicated")
        digest, mode = str(row.get("sha256", "")), str(row.get("mode", ""))
        if not SHA256_RE.fullmatch(digest) or mode not in {"0600", "0700"}:
            raise AssemblyContractError("release file hash/mode is invalid")
        artifact = directory.joinpath(*PurePosixPath(relative).parts)
        _secure_regular(artifact)
        if sha256_file(artifact) != digest:
            raise AssemblyContractError("release file hash mismatch")
        inventory[relative] = {"sha256": digest, "mode": mode}
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != set(inventory) | {"release-manifest.json"}:
        raise AssemblyContractError("release has unmanifested or missing files")
    required = RELEASE_REQUIRED[kind]
    if not set(required).issubset(inventory):
        raise AssemblyContractError("release lacks a required runtime artifact")
    for relative, expected_mode in required.items():
        if inventory[relative]["mode"] != expected_mode:
            raise AssemblyContractError("required release artifact mode mismatch")
    return directory, inventory


def _verify_units(
    units_dir: Path, runner_rows: Mapping[str, Mapping[str, str]]
) -> list[dict[str, str]]:
    expected = set(installer.RECURRING_UNITS)
    actual = {path.name for path in units_dir.iterdir() if path.is_file() or path.is_symlink()}
    if actual != expected:
        raise AssemblyContractError("rendered unit set is not exactly seven files")
    rows = []
    for unit in sorted(expected):
        path = units_dir / unit
        _secure_regular(path)
        body = path.read_text(encoding="utf-8")
        if "/current/" in body or re.search(r"@[A-Z][A-Z0-9_]+@", body):
            raise AssemblyContractError("unit contains mutable or unresolved binding")
        if re.search(r"ExecStart\s*=.*systemctl.*(?:enable|start|restart|daemon-reload)", body):
            raise AssemblyContractError("unit contains a forbidden activation command")
        role = UNIT_RUNNER_BINDINGS.get(unit)
        if role and runner_rows[role]["target"] not in body:
            raise AssemblyContractError(f"{unit} is not bound to its verified runner")
        rows.append(
            {
                "unit": unit,
                "source_sha256": sha256_file(path),
                "source_mode": "0600",
                "deployment_mode": "0644",
                "target": f"/etc/systemd/system/{unit}",
            }
        )
    return rows


def assemble(
    *,
    source_root: Path,
    calendar_source: str,
    ruleset_source: str,
    ruleset_sha256: str,
    preflight_source: str,
    preflight_sha256: str,
    controller_config_source: str,
    release_root_source: str,
    controller_release_id: str,
    ingestion_release_id: str,
    handoff_release_id: str,
    units_source: str,
    deployment_id: str,
) -> dict[str, object]:
    """Verify all inputs and assemble nested disabled-only deployment evidence."""

    if not installer.DEPLOYMENT_ID_RE.fullmatch(deployment_id):
        raise AssemblyContractError("deployment_id is invalid")
    paths = {
        "calendar": calendar_source,
        "ruleset": ruleset_source,
        "preflight": preflight_source,
        "config": controller_config_source,
        "releases": release_root_source,
        "units": units_source,
    }
    resolved = {
        key: source_root.joinpath(*_relative(value).parts) for key, value in paths.items()
    }
    ruleset = calendar_contract.load_ruleset(resolved["ruleset"], ruleset_sha256)
    calendar = _read_canonical(resolved["calendar"])
    calendar_contract.validate_calendar_artifact(
        calendar, ruleset=ruleset, ruleset_sha256=ruleset_sha256
    )
    calendar_sha256 = sha256_file(resolved["calendar"])
    _secure_regular(resolved["preflight"])
    if not SHA256_RE.fullmatch(preflight_sha256) or sha256_file(resolved["preflight"]) != preflight_sha256:
        raise AssemblyContractError("preflight identity mismatch")

    release_ids = {
        "nightly-continuity": controller_release_id,
        "market-ingestion": ingestion_release_id,
        "market-ingestion-handoff": handoff_release_id,
    }
    releases = {}
    inventories = {}
    for kind, release_id in release_ids.items():
        directory, inventory = _verify_release(resolved["releases"], kind, release_id)
        releases[kind] = directory
        inventories[kind] = inventory

    runner_rows = {}
    for role, (kind, relative) in RUNNERS.items():
        release_id = release_ids[kind]
        item = inventories[kind][relative]
        runner_rows[role] = {
            "release_kind": kind,
            "release_id": release_id,
            "path": relative,
            "sha256": item["sha256"],
            "mode": item["mode"],
            "target": f"/opt/codex-oracle/releases/{kind}-{release_id}/{relative}",
        }

    config = _read_canonical(resolved["config"])
    expected_config_bindings = {
        "calendar_path": installer.EXACT_ROLE_TARGETS["CALENDAR"],
        "calendar_sha256": calendar_sha256,
        "preflight_executable": (
            "/opt/codex-oracle/releases/market-ingestion-preflight-"
            f"{preflight_sha256}/run-select-only-preflight"
        ),
        "preflight_sha256": preflight_sha256,
    }
    for key, value in expected_config_bindings.items():
        if config.get(key) != value:
            raise AssemblyContractError(f"controller config {key} binding mismatch")
    for key, value in CONFIG_EXACT.items():
        if config.get(key) != value:
            raise AssemblyContractError(f"controller config {key} invariant mismatch")
    for key in CONFIG_POSITIVE_NUMBERS:
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise AssemblyContractError(f"controller config {key} must be positive")
    units = _verify_units(resolved["units"], runner_rows)

    deployment_artifacts = [
        {
            "role": "CALENDAR",
            "source": calendar_source,
            "target": installer.EXACT_ROLE_TARGETS["CALENDAR"],
            "sha256": calendar_sha256,
            "mode": "0600",
        },
        {
            "role": "CONTROLLER_CONFIG",
            "source": controller_config_source,
            "target": installer.EXACT_ROLE_TARGETS["CONTROLLER_CONFIG"],
            "sha256": sha256_file(resolved["config"]),
            "mode": "0600",
        },
        {
            "role": "PREFLIGHT_ENTRYPOINT",
            "source": preflight_source,
            "target": expected_config_bindings["preflight_executable"],
            "sha256": preflight_sha256,
            "mode": "0700",
        },
        {
            "role": "CONTROLLER_ENTRYPOINT",
            "source": (
                f"{release_root_source}/nightly-continuity-{controller_release_id}/"
                "run-nightly-continuity"
            ),
            "target": runner_rows["CONTROLLER"]["target"],
            "sha256": runner_rows["CONTROLLER"]["sha256"],
            "release_sha256": controller_release_id,
            "mode": "0700",
        },
    ]
    for unit in units:
        deployment_artifacts.append(
            {
                "role": f"SYSTEMD_UNIT:{unit['unit']}",
                "source": f"{units_source}/{unit['unit']}",
                "target": unit["target"],
                "sha256": unit["source_sha256"],
                "mode": unit["deployment_mode"],
            }
        )
    deployment = {
        "contract_id": installer.CONTRACT_ID,
        "deployment_id": deployment_id,
        "apply_mode": "INSTALL_DISABLED_ONLY",
        "no_enable": True,
        "no_start": True,
        "no_restart": True,
        "no_daemon_reload": True,
        "no_turso_writes": True,
        "no_snapshot_lifecycle_changes": True,
        "artifacts": deployment_artifacts,
        "required_unit_states": {
            unit: {"active_state": "inactive", "unit_file_state": "disabled"}
            for unit in sorted(installer.ALL_GUARDED_UNITS)
        },
    }
    installer.validate_deployment_manifest(deployment)
    deployment_sha256 = hashlib.sha256(canonical_bytes(deployment)).hexdigest()
    assembly = {
        "contract_id": ASSEMBLY_CONTRACT_ID,
        "deployment_id": deployment_id,
        "calendar": {
            "contract_id": calendar_contract.CONTRACT_ID,
            "sha256": calendar_sha256,
            "ruleset_sha256": ruleset_sha256,
        },
        "preflight": {
            "contract_id": "codex-market-ingestion-idempotency-preflight-v1",
            "sha256": preflight_sha256,
            "target": expected_config_bindings["preflight_executable"],
        },
        "controller": {
            "source_sha256": inventories["nightly-continuity"]["continuity_controller.py"]["sha256"],
            "release_id": controller_release_id,
            "config_sha256": sha256_file(resolved["config"]),
        },
        "releases": [
            {
                "kind": kind,
                "release_id": release_ids[kind],
                "manifest_sha256": release_ids[kind],
            }
            for kind in sorted(release_ids)
        ],
        "runners": [runner_rows[role] | {"role": role} for role in sorted(runner_rows)],
        "units": units,
        "disabled_installation": {
            "contract_id": installer.CONTRACT_ID,
            "manifest_sha256": deployment_sha256,
            "manifest": deployment,
        },
        "rollback": {
            "contract_id": installer.ROLLBACK_CONTRACT_ID,
            "deployment_id": deployment_id,
            "deployment_manifest_sha256": deployment_sha256,
        },
        "audit": {"contract_id": installer.AUDIT_CONTRACT_ID},
        "activation": "EXPLICITLY_OUT_OF_SCOPE",
    }
    validate_assembly(assembly)
    return assembly


def validate_assembly(raw: Mapping[str, object]) -> None:
    if raw.get("contract_id") != ASSEMBLY_CONTRACT_ID:
        raise AssemblyContractError("assembly identity mismatch")
    disabled = raw.get("disabled_installation")
    if not isinstance(disabled, Mapping) or disabled.get("contract_id") != installer.CONTRACT_ID:
        raise AssemblyContractError("disabled installer identity mismatch")
    deployment = disabled.get("manifest")
    if not isinstance(deployment, Mapping):
        raise AssemblyContractError("nested deployment manifest is missing")
    installer.validate_deployment_manifest(deployment)
    if raw.get("deployment_id") != deployment.get("deployment_id"):
        raise AssemblyContractError("assembly/deployment ID mismatch")
    deployment_hash = hashlib.sha256(canonical_bytes(deployment)).hexdigest()
    if disabled.get("manifest_sha256") != deployment_hash:
        raise AssemblyContractError("nested deployment identity mismatch")
    rollback = raw.get("rollback")
    if not isinstance(rollback, Mapping) or rollback != {
        "contract_id": installer.ROLLBACK_CONTRACT_ID,
        "deployment_id": deployment["deployment_id"],
        "deployment_manifest_sha256": deployment_hash,
    }:
        raise AssemblyContractError("rollback identity is not exact")
    audit = raw.get("audit")
    if audit != {"contract_id": installer.AUDIT_CONTRACT_ID}:
        raise AssemblyContractError("audit identity is not exact")
    release_rows = raw.get("releases")
    if not isinstance(release_rows, list) or len(release_rows) != len(RELEASE_REQUIRED):
        raise AssemblyContractError("release coverage is not exactly three")
    release_ids = {}
    for row in release_rows:
        if not isinstance(row, Mapping):
            raise AssemblyContractError("release identity row is invalid")
        kind, release_id = row.get("kind"), row.get("release_id")
        if kind not in RELEASE_REQUIRED or kind in release_ids:
            raise AssemblyContractError("release kind is unknown or duplicated")
        if not isinstance(release_id, str) or not SHA256_RE.fullmatch(release_id):
            raise AssemblyContractError("release identity is invalid")
        if row.get("manifest_sha256") != release_id:
            raise AssemblyContractError("release manifest identity mismatch")
        release_ids[str(kind)] = release_id
    if set(release_ids) != set(RELEASE_REQUIRED):
        raise AssemblyContractError("release coverage is incomplete")

    runners = raw.get("runners")
    if (
        not isinstance(runners, list)
        or len(runners) != len(RUNNERS)
        or {row.get("role") for row in runners if isinstance(row, Mapping)} != set(RUNNERS)
    ):
        raise AssemblyContractError("runner coverage is not exactly five")
    runner_by_role = {}
    for row in runners:
        if not isinstance(row, Mapping):
            raise AssemblyContractError("runner row is invalid")
        role = str(row["role"])
        kind, relative = RUNNERS[role]
        expected_release_id = release_ids[kind]
        expected_target = (
            f"/opt/codex-oracle/releases/{kind}-{expected_release_id}/{relative}"
        )
        if row.get("release_kind") != kind or row.get("path") != relative:
            raise AssemblyContractError("runner kind/path identity mismatch")
        if row.get("release_id") != expected_release_id or row.get("target") != expected_target:
            raise AssemblyContractError("runner release/target identity mismatch")
        if row.get("mode") != "0700" or not SHA256_RE.fullmatch(str(row.get("sha256", ""))):
            raise AssemblyContractError("runner hash/mode identity mismatch")
        runner_by_role[role] = row
    units = raw.get("units")
    if (
        not isinstance(units, list)
        or len(units) != len(installer.RECURRING_UNITS)
        or {row.get("unit") for row in units if isinstance(row, Mapping)}
        != set(installer.RECURRING_UNITS)
    ):
        raise AssemblyContractError("unit coverage is not exactly seven")
    unit_by_name = {}
    for row in units:
        if not isinstance(row, Mapping):
            raise AssemblyContractError("unit row is invalid")
        unit = str(row["unit"])
        if row.get("target") != f"/etc/systemd/system/{unit}":
            raise AssemblyContractError("unit target identity mismatch")
        if row.get("source_mode") != "0600" or row.get("deployment_mode") != "0644":
            raise AssemblyContractError("unit mode identity mismatch")
        if not SHA256_RE.fullmatch(str(row.get("source_sha256", ""))):
            raise AssemblyContractError("unit source hash identity mismatch")
        unit_by_name[unit] = row

    artifact_by_role = {str(row["role"]): row for row in deployment["artifacts"]}
    for unit, row in unit_by_name.items():
        artifact = artifact_by_role[f"SYSTEMD_UNIT:{unit}"]
        if (
            artifact["sha256"] != row["source_sha256"]
            or artifact["target"] != row["target"]
            or artifact["mode"] != row["deployment_mode"]
        ):
            raise AssemblyContractError("unit/deployment artifact identity mismatch")
    controller_artifact = artifact_by_role["CONTROLLER_ENTRYPOINT"]
    controller_runner = runner_by_role["CONTROLLER"]
    if (
        controller_artifact["sha256"] != controller_runner["sha256"]
        or controller_artifact["target"] != controller_runner["target"]
        or controller_artifact.get("release_sha256") != controller_runner["release_id"]
        or controller_artifact["mode"] != controller_runner["mode"]
    ):
        raise AssemblyContractError("controller runner/deployment identity mismatch")
    calendar = raw.get("calendar")
    preflight = raw.get("preflight")
    controller = raw.get("controller")
    if not isinstance(calendar, Mapping) or calendar.get("contract_id") != calendar_contract.CONTRACT_ID:
        raise AssemblyContractError("calendar identity is invalid")
    if not all(SHA256_RE.fullmatch(str(calendar.get(key, ""))) for key in ("sha256", "ruleset_sha256")):
        raise AssemblyContractError("calendar hash identity is invalid")
    if artifact_by_role["CALENDAR"]["sha256"] != calendar["sha256"]:
        raise AssemblyContractError("calendar/deployment identity mismatch")
    if not isinstance(preflight, Mapping) or preflight.get("contract_id") != "codex-market-ingestion-idempotency-preflight-v1":
        raise AssemblyContractError("preflight identity is invalid")
    if (
        not SHA256_RE.fullmatch(str(preflight.get("sha256", "")))
        or artifact_by_role["PREFLIGHT_ENTRYPOINT"]["sha256"] != preflight["sha256"]
        or artifact_by_role["PREFLIGHT_ENTRYPOINT"]["target"] != preflight.get("target")
    ):
        raise AssemblyContractError("preflight/deployment identity mismatch")
    if not isinstance(controller, Mapping):
        raise AssemblyContractError("controller identity is invalid")
    if controller.get("release_id") != release_ids["nightly-continuity"]:
        raise AssemblyContractError("controller release identity mismatch")
    if not all(SHA256_RE.fullmatch(str(controller.get(key, ""))) for key in ("source_sha256", "config_sha256")):
        raise AssemblyContractError("controller hash identity is invalid")
    if artifact_by_role["CONTROLLER_CONFIG"]["sha256"] != controller["config_sha256"]:
        raise AssemblyContractError("controller config/deployment identity mismatch")
    if raw.get("activation") != "EXPLICITLY_OUT_OF_SCOPE":
        raise AssemblyContractError("assembly attempted to authorize activation")


def write_assembly_once(path: Path, assembly: Mapping[str, object]) -> str:
    validate_assembly(assembly)
    encoded = canonical_bytes(assembly)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    return hashlib.sha256(encoded).hexdigest()
