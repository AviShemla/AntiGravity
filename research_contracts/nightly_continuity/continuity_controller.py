"""Fail-closed recurring controller for guarded Codex Oracle ingestion.

The controller never writes to Turso.  Its preflight dependency is an immutable,
SELECT-only executable which emits a local evidence document.  Pure functions
in this module decide whether to dispatch ingestion, resume at postflight, or
perform an idempotent no-op.
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
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator, Mapping, Sequence


SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UNIT_RE = re.compile(r"^codex-market-(?:ingestion|ingestion-postflight|ingestion-handoff)@\d{4}-\d{2}-\d{2}\.service$")
FORBIDDEN_UNITS = (
    "ag-sniper.service",
    "antigravity-nightly.timer",
    "antigravity-qa-watchdog.timer",
)


class ContractError(RuntimeError):
    """Evidence or configuration violated the continuity contract."""


class Action(str, Enum):
    START_INGESTION = "START_INGESTION"
    START_POSTFLIGHT = "START_POSTFLIGHT"
    NOOP_ACTIVE = "NOOP_ACTIVE"
    NOOP_VERIFIED = "NOOP_VERIFIED"


@dataclass(frozen=True)
class Session:
    session_date: str
    close_utc: datetime


@dataclass(frozen=True)
class SnapshotState:
    source_session: str
    snapshot_count: int
    snapshot_id: str | None
    status: str | None
    approval_count: int
    screening_count: int
    database_writes: int
    query_mode: str


@dataclass(frozen=True)
class UnitState:
    load: str
    active: str
    sub: str
    result: str
    main_pid: int
    invocation_id: str

    @property
    def is_active(self) -> bool:
        return self.active in {"active", "activating", "reloading"}

    @property
    def has_failed(self) -> bool:
        return self.active == "failed" or self.result == "failed"


@dataclass(frozen=True)
class Decision:
    action: Action
    unit: str | None
    reason: str


@dataclass(frozen=True)
class Liveness:
    status: str
    reason: str
    active_unit: str | None
    main_pid: int
    checkpoint_age_seconds: float | None


@dataclass(frozen=True)
class Capacity:
    safe: bool
    load_per_cpu: float
    available_memory_mb: int
    free_disk_mb: int
    reason: str


@dataclass(frozen=True)
class ProgressMarker:
    source_session: str
    stage: str
    status: str
    main_pid: int
    invocation_id: str
    code_version: str
    completed_units: int
    total_units: int
    observed_at: datetime
    age_seconds: float


@dataclass(frozen=True)
class PriorityState:
    cpu_weight: int
    io_weight: int
    nice: int
    io_scheduling_class: int
    io_scheduling_priority: int


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ContractError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def load_calendar(
    path: Path, expected_sha256: str, *, now: datetime | None = None,
    minimum_future_horizon: timedelta = timedelta(0),
) -> tuple[Session, ...]:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise ContractError("calendar SHA-256 is invalid")
    if sha256_file(path) != expected_sha256:
        raise ContractError("calendar artifact hash mismatch")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("contract_id") != "codex-nyse-session-calendar-v1":
        raise ContractError("calendar contract identity mismatch")
    valid_through = parse_utc(str(raw.get("valid_through_utc", "")))
    if minimum_future_horizon < timedelta(0):
        raise ContractError("calendar future horizon cannot be negative")
    if now is not None:
        if now.tzinfo is None:
            raise ContractError("calendar check time must be timezone-aware")
        if valid_through < now.astimezone(timezone.utc) + minimum_future_horizon:
            raise ContractError("NYSE calendar coverage is exhausted or too near its horizon")
    rows = raw.get("sessions")
    if not isinstance(rows, list) or not rows:
        raise ContractError("calendar has no sessions")
    sessions: list[Session] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ContractError("calendar session is not an object")
        date = str(row.get("session_date", ""))
        if not SESSION_RE.fullmatch(date) or date in seen:
            raise ContractError("calendar session date is invalid or duplicated")
        seen.add(date)
        sessions.append(Session(date, parse_utc(str(row.get("close_utc", "")))))
    if sessions != sorted(sessions, key=lambda item: item.close_utc):
        raise ContractError("calendar sessions are not ordered by close time")
    if any(left.close_utc >= right.close_utc for left, right in zip(sessions, sessions[1:])):
        raise ContractError("calendar close times are not strictly increasing")
    return tuple(sessions)


def latest_fully_completed_session(
    sessions: Sequence[Session], now: datetime, *, settlement_delay: timedelta
) -> Session:
    if now.tzinfo is None:
        raise ContractError("current time must be timezone-aware")
    if settlement_delay < timedelta(0):
        raise ContractError("settlement delay cannot be negative")
    now_utc = now.astimezone(timezone.utc)
    completed = [session for session in sessions if session.close_utc + settlement_delay <= now_utc]
    if not completed:
        raise ContractError("calendar has no fully completed NYSE session")
    return completed[-1]


def validate_snapshot_evidence(raw: Mapping[str, object], *, source_session: str) -> SnapshotState:
    if raw.get("contract_id") != "codex-market-ingestion-idempotency-preflight-v1":
        raise ContractError("preflight contract identity mismatch")
    if raw.get("source_session") != source_session:
        raise ContractError("preflight source-session mismatch")
    if raw.get("query_mode") != "SELECT_ONLY" or int(raw.get("database_writes", -1)) != 0:
        raise ContractError("preflight is not proven SELECT-only")
    statements = raw.get("statements")
    if not isinstance(statements, list) or not statements:
        raise ContractError("preflight statement evidence is missing")
    if any(not isinstance(item, str) or not item.lstrip().upper().startswith("SELECT ") for item in statements):
        raise ContractError("preflight includes a non-SELECT statement")
    count = int(raw.get("snapshot_count", -1))
    if count not in {0, 1}:
        raise ContractError("snapshot cardinality is ambiguous")
    snapshot_id = raw.get("snapshot_id")
    status = raw.get("status")
    if count == 0 and (snapshot_id is not None or status is not None):
        raise ContractError("absent snapshot has contradictory identity")
    if count == 1 and (not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(status, str)):
        raise ContractError("existing snapshot identity/status is incomplete")
    return SnapshotState(
        source_session=source_session,
        snapshot_count=count,
        snapshot_id=snapshot_id if isinstance(snapshot_id, str) else None,
        status=status if isinstance(status, str) else None,
        approval_count=int(raw.get("approval_count", -1)),
        screening_count=int(raw.get("screening_count", -1)),
        database_writes=0,
        query_mode="SELECT_ONLY",
    )


def verify_handoff(
    path: Path, *, source_session: str, now: datetime,
    max_age_seconds: int,
) -> bool:
    if not path.is_file():
        return False
    if max_age_seconds <= 0:
        raise ContractError("handoff maximum age must be positive")
    _secure_regular(path)
    encoded = path.read_bytes()
    raw = json.loads(encoded.decode("utf-8"))
    if encoded != canonical_bytes(raw):
        raise ContractError("handoff JSON is not canonical")
    if raw.get("contract_id") != "codex-market-ingestion-postflight-handoff-v1":
        raise ContractError("handoff contract identity mismatch")
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict):
        raise ContractError("handoff evidence is missing")
    if raw.get("evidence_sha256") != hashlib.sha256(canonical_bytes(evidence)).hexdigest():
        raise ContractError("handoff evidence hash mismatch")
    if evidence.get("source_session") != source_session or evidence.get("status") != "STAGING":
        raise ContractError("handoff session/lifecycle mismatch")
    if evidence.get("last_date") != source_session:
        raise ContractError("handoff latest data date does not match its source session")
    if int(evidence.get("approval_events", -1)) != 0 or int(evidence.get("screening_runs", -1)) != 0:
        raise ContractError("handoff proves unauthorized downstream output")
    if raw.get("snapshot_lifecycle_unchanged") is not True or raw.get("successor_authorized") is not True:
        raise ContractError("handoff does not preserve STAGING lifecycle")
    if not isinstance(evidence.get("snapshot_id"), str) or not evidence["snapshot_id"]:
        raise ContractError("handoff snapshot identity is missing")
    if not SHA256_RE.fullmatch(str(evidence.get("checksum", ""))) or not SHA256_RE.fullmatch(str(evidence.get("code_version", ""))):
        raise ContractError("handoff immutable data/code identity is invalid")
    rows = evidence.get("rows")
    tickers = evidence.get("feature_tickers")
    lineage = evidence.get("provider_lineage_rows")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (rows, tickers, lineage)):
        raise ContractError("handoff reconciliation counts are invalid")
    if rows <= 0 or tickers <= 0 or lineage != tickers + 2:
        raise ContractError("handoff reconciliation counts contradict the contract")
    observed = parse_utc(str(raw.get("observed_at", "")))
    age = (now.astimezone(timezone.utc) - observed).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ContractError("handoff evidence is future-dated or stale")
    return True


def verify_progress_marker(
    path: Path, *, source_session: str, stage: str, unit: UnitState,
    now: datetime, max_age_seconds: int,
) -> ProgressMarker:
    if max_age_seconds <= 0 or unit.main_pid <= 0 or not unit.invocation_id:
        raise ContractError("progress-marker liveness inputs are invalid")
    _secure_regular(path)
    encoded = path.read_bytes()
    raw = json.loads(encoded.decode("utf-8"))
    if encoded != canonical_bytes(raw):
        raise ContractError("progress marker is not canonical JSON")
    if raw.get("contract_id") != "codex-market-ingestion-progress-v1":
        raise ContractError("progress-marker contract identity mismatch")
    if raw.get("source_session") != source_session or raw.get("stage") != stage:
        raise ContractError("progress-marker source/stage mismatch")
    if raw.get("status") != "ACTIVE":
        raise ContractError("progress marker does not describe active work")
    if int(raw.get("main_pid", 0)) != unit.main_pid or raw.get("invocation_id") != unit.invocation_id:
        raise ContractError("progress marker does not bind the live systemd process")
    code_version = str(raw.get("code_version", ""))
    if not SHA256_RE.fullmatch(code_version):
        raise ContractError("progress-marker code identity is invalid")
    completed = int(raw.get("completed_units", -1))
    total = int(raw.get("total_units", -1))
    if total <= 0 or completed < 0 or completed > total:
        raise ContractError("progress-marker counters are invalid")
    observed = parse_utc(str(raw.get("observed_at", "")))
    age = (now.astimezone(timezone.utc) - observed).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ContractError("progress marker is future-dated or stale")
    return ProgressMarker(
        source_session, stage, "ACTIVE", unit.main_pid, unit.invocation_id,
        code_version, completed, total, observed, age,
    )


def validate_priority(state: PriorityState) -> None:
    if (
        state.cpu_weight < 900 or state.io_weight < 900 or state.nice > -5
        or state.io_scheduling_class != 2 or state.io_scheduling_priority != 0
    ):
        raise ContractError("installed ingestion unit violates guarded-priority policy")


def decide(
    *, source_session: str, snapshot: SnapshotState, ingestion: UnitState,
    postflight: UnitState, handoff: UnitState, handoff_verified: bool,
    forbidden_safe: bool,
) -> Decision:
    if not forbidden_safe:
        raise ContractError("a legacy safety unit is active or enabled")
    units = (ingestion, postflight, handoff)
    if any(unit.has_failed for unit in units):
        raise ContractError("a pipeline unit has a preserved failed state; automatic retry is forbidden")
    active = [index for index, unit in enumerate(units) if unit.is_active]
    if len(active) > 1:
        raise ContractError("multiple pipeline stages are active")
    if handoff_verified:
        if snapshot.snapshot_count != 1 or snapshot.status != "STAGING":
            raise ContractError("verified handoff contradicts snapshot evidence")
        return Decision(Action.NOOP_VERIFIED, None, "verified STAGING handoff already exists")
    if active:
        return Decision(Action.NOOP_ACTIVE, None, "the exact source-session pipeline is already active")
    if snapshot.snapshot_count == 1:
        if snapshot.status != "STAGING":
            raise ContractError("existing snapshot is not STAGING")
        if snapshot.approval_count != 0 or snapshot.screening_count != 0:
            raise ContractError("existing snapshot has unauthorized downstream outputs")
        unit = f"codex-market-ingestion-postflight@{source_session}.service"
        return Decision(Action.START_POSTFLIGHT, unit, "resume safely from the existing unique STAGING snapshot")
    if snapshot.approval_count not in {0, -1} or snapshot.screening_count not in {0, -1}:
        raise ContractError("absent snapshot has contradictory downstream counts")
    unit = f"codex-market-ingestion@{source_session}.service"
    return Decision(Action.START_INGESTION, unit, "no snapshot exists for the fully completed session")


def assess_liveness(
    *, units: Mapping[str, UnitState], handoff_verified: bool,
    checkpoint_exists: bool, checkpoint_age_seconds: float | None,
    max_checkpoint_age_seconds: float,
) -> Liveness:
    if max_checkpoint_age_seconds <= 0:
        raise ContractError("maximum checkpoint age must be positive")
    if any(unit.has_failed for unit in units.values()):
        return Liveness("FAILED", "a pipeline unit has failed", None, 0, checkpoint_age_seconds)
    active = [(name, unit) for name, unit in units.items() if unit.is_active]
    if len(active) > 1:
        return Liveness("CONTRADICTORY", "multiple pipeline stages are active", None, 0, checkpoint_age_seconds)
    if handoff_verified:
        return Liveness("VERIFIED", "terminal STAGING handoff independently reads back", None, 0, checkpoint_age_seconds)
    if not active:
        return Liveness("STALLED", "no live pipeline unit and no verified handoff", None, 0, checkpoint_age_seconds)
    name, unit = active[0]
    if unit.main_pid <= 0:
        return Liveness("STALLED", "active unit has no live MainPID", name, unit.main_pid, checkpoint_age_seconds)
    if not checkpoint_exists or checkpoint_age_seconds is None:
        return Liveness("STALLED", "active unit has no durable progress marker", name, unit.main_pid, None)
    if checkpoint_age_seconds > max_checkpoint_age_seconds:
        return Liveness("STALLED", "durable progress marker exceeded its maximum interval", name, unit.main_pid, checkpoint_age_seconds)
    return Liveness("ACTIVE", "live PID and fresh durable progress marker are present", name, unit.main_pid, checkpoint_age_seconds)


def assess_capacity(
    *, load_1m: float, cpu_count: int, available_memory_mb: int,
    free_disk_mb: int, max_load_per_cpu: float, min_memory_mb: int,
    min_disk_mb: int,
) -> Capacity:
    if cpu_count < 1 or min_memory_mb < 0 or min_disk_mb < 0 or max_load_per_cpu <= 0:
        raise ContractError("capacity policy is invalid")
    normalized = load_1m / cpu_count
    failures = []
    if normalized > max_load_per_cpu:
        failures.append("CPU load exceeds policy")
    if available_memory_mb < min_memory_mb:
        failures.append("available memory is below policy")
    if free_disk_mb < min_disk_mb:
        failures.append("free disk is below policy")
    return Capacity(
        safe=not failures, load_per_cpu=normalized,
        available_memory_mb=available_memory_mb, free_disk_mb=free_disk_mb,
        reason="; ".join(failures) if failures else "capacity gates pass",
    )


def foreign_pipeline_units(active_units: Sequence[str], *, source_session: str) -> tuple[str, ...]:
    if not SESSION_RE.fullmatch(source_session):
        raise ContractError("source session is invalid")
    expected_suffix = f"@{source_session}.service"
    foreign = []
    for unit in active_units:
        if not UNIT_RE.fullmatch(unit):
            raise ContractError("active pipeline unit escaped the allowlist")
        if not unit.endswith(expected_suffix):
            foreign.append(unit)
    return tuple(sorted(foreign))


def _secure_regular(
    path: Path,
    expected_sha256: str | None = None,
    *,
    expected_mode: int = 0o600,
) -> None:
    if expected_mode not in {0o600, 0o700}:
        raise ContractError("secure regular-file mode policy is invalid")
    if path.is_symlink():
        raise ContractError(f"{path} must not be a symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ContractError(f"{path} must be a single-link regular file")
    if os.name != "nt" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != expected_mode):
        raise ContractError(f"{path} must be root-owned mode {expected_mode:04o}")
    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise ContractError(f"{path} hash mismatch")


def load_config(path: Path) -> dict[str, object]:
    _secure_regular(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "calendar_path", "calendar_sha256", "preflight_executable",
        "preflight_sha256", "state_root", "handoff_root", "systemctl_path",
        "settlement_delay_seconds", "max_preflight_age_seconds",
        "max_checkpoint_age_seconds", "progress_marker_template",
        "calendar_min_future_horizon_seconds", "max_handoff_age_seconds",
        "max_load_per_cpu", "min_available_memory_mb", "min_free_disk_mb",
    }
    if not required.issubset(raw):
        raise ContractError("runtime configuration is incomplete")
    for key in ("calendar_sha256", "preflight_sha256"):
        if not SHA256_RE.fullmatch(str(raw[key])):
            raise ContractError(f"{key} is invalid")
    for key in ("calendar_path", "preflight_executable", "state_root", "handoff_root", "systemctl_path"):
        if not Path(str(raw[key])).is_absolute():
            raise ContractError(f"{key} must be absolute")
    if "/current/" in str(raw["preflight_executable"]):
        raise ContractError("mutable current symlinks are forbidden")
    marker = str(raw["progress_marker_template"])
    if not marker.startswith("/") or marker.count("{source_session}") != 1:
        raise ContractError("progress marker template must be absolute and contain one source-session placeholder")
    return raw


def _unit_state(systemctl: str, unit: str) -> UnitState:
    if not UNIT_RE.fullmatch(unit):
        raise ContractError("unit name is outside the continuity allowlist")
    command = [systemctl, "show", unit, "--no-page", "--property=LoadState,ActiveState,SubState,Result,MainPID,InvocationID"]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise ContractError(f"systemd inspection failed for {unit}")
    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    if values.get("LoadState") not in {"loaded", "not-found"}:
        raise ContractError(f"ambiguous load state for {unit}")
    return UnitState(
        load=values.get("LoadState", ""), active=values.get("ActiveState", ""),
        sub=values.get("SubState", ""), result=values.get("Result", ""),
        main_pid=int(values.get("MainPID", "0") or 0),
        invocation_id=values.get("InvocationID", ""),
    )


def _verify_installed_ingestion_priority(systemctl: str, unit: str) -> None:
    if not UNIT_RE.fullmatch(unit) or not unit.startswith("codex-market-ingestion@"):
        raise ContractError("priority audit target is outside the ingestion allowlist")
    result = subprocess.run(
        [systemctl, "show", unit, "--no-page", "--property=CPUWeight,IOWeight,Nice,IOSchedulingClass,IOSchedulingPriority"],
        check=False, capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        raise ContractError("installed ingestion priority inspection failed")
    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    try:
        state = PriorityState(
            cpu_weight=int(values["CPUWeight"]), io_weight=int(values["IOWeight"]),
            nice=int(values["Nice"]), io_scheduling_class=int(values["IOSchedulingClass"]),
            io_scheduling_priority=int(values["IOSchedulingPriority"]),
        )
    except (KeyError, ValueError) as exc:
        raise ContractError("installed ingestion priority evidence is incomplete") from exc
    validate_priority(state)


def _forbidden_units_safe(systemctl: str) -> bool:
    for unit in FORBIDDEN_UNITS:
        active = subprocess.run([systemctl, "is-active", unit], capture_output=True, text=True, timeout=20)
        enabled = subprocess.run([systemctl, "is-enabled", unit], capture_output=True, text=True, timeout=20)
        if active.stdout.strip() not in {"inactive", "failed", "unknown"}:
            return False
        if enabled.stdout.strip() not in {"disabled", "masked", "static", "not-found"}:
            return False
    return True


def _active_pipeline_units(systemctl: str) -> tuple[str, ...]:
    found: set[str] = set()
    for pattern in (
        "codex-market-ingestion@*.service",
        "codex-market-ingestion-postflight@*.service",
        "codex-market-ingestion-handoff@*.service",
    ):
        result = subprocess.run(
            [systemctl, "list-units", pattern, "--state=active,activating,reloading", "--no-legend", "--plain"],
            check=False, capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            raise ContractError("whole-pipeline active-unit inspection failed")
        for line in result.stdout.splitlines():
            if line.strip():
                unit = line.split()[0]
                if not UNIT_RE.fullmatch(unit):
                    raise ContractError("systemd returned a pipeline unit outside the allowlist")
                found.add(unit)
    return tuple(sorted(found))


def _read_capacity(config: Mapping[str, object], state_root: Path) -> Capacity:
    cpu_count = os.cpu_count() or 1
    try:
        load_1m = os.getloadavg()[0]
    except (AttributeError, OSError):
        load_1m = 0.0
    available_mb = -1
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                available_mb = int(line.split()[1]) // 1024
                break
    if available_mb < 0:
        raise ContractError("available-memory evidence is unavailable")
    free_mb = shutil.disk_usage(state_root).free // (1024 * 1024)
    return assess_capacity(
        load_1m=load_1m, cpu_count=cpu_count,
        available_memory_mb=available_mb, free_disk_mb=free_mb,
        max_load_per_cpu=float(config["max_load_per_cpu"]),
        min_memory_mb=int(config["min_available_memory_mb"]),
        min_disk_mb=int(config["min_free_disk_mb"]),
    )


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ContractError("continuity controller is already running") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ContractError("continuity controller is already running") from exc
        yield
    finally:
        handle.close()


def append_event(state_root: Path, event: Mapping[str, object]) -> None:
    state_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = state_root / "events.jsonl"
    if path.exists() or path.is_symlink():
        _secure_regular(path)
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ContractError("event journal mode must be 0600")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "ab") as handle:
        handle.write(canonical_bytes(event))
        handle.flush()
        os.fsync(handle.fileno())


def _run_preflight(config: Mapping[str, object], session: str, now: datetime) -> SnapshotState:
    executable = Path(str(config["preflight_executable"]))
    _secure_regular(
        executable,
        str(config["preflight_sha256"]),
        expected_mode=0o700,
    )
    state_root = Path(str(config["state_root"]))
    evidence_dir = state_root / "preflight" / session
    evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    output = evidence_dir / (now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + ".json")
    command = [str(executable), "--source-session", session, "--output", str(output)]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ContractError("SELECT-only idempotency preflight failed")
    _secure_regular(output)
    raw = json.loads(output.read_text(encoding="utf-8"))
    observed = parse_utc(str(raw.get("observed_at", "")))
    max_age = timedelta(seconds=int(config["max_preflight_age_seconds"]))
    if observed > now.astimezone(timezone.utc) + timedelta(seconds=5) or now.astimezone(timezone.utc) - observed > max_age:
        raise ContractError("preflight evidence is stale or future-dated")
    return validate_snapshot_evidence(raw, source_session=session)


def run(config_path: Path, *, now: datetime) -> Decision:
    config = load_config(config_path)
    state_root = Path(str(config["state_root"]))
    with exclusive_lock(state_root / "controller.lock"):
        calendar_path = Path(str(config["calendar_path"]))
        _secure_regular(calendar_path, str(config["calendar_sha256"]))
        sessions = load_calendar(
            calendar_path, str(config["calendar_sha256"]), now=now,
            minimum_future_horizon=timedelta(seconds=int(config["calendar_min_future_horizon_seconds"])),
        )
        selected = latest_fully_completed_session(
            sessions, now,
            settlement_delay=timedelta(seconds=int(config["settlement_delay_seconds"])),
        )
        source = selected.session_date
        systemctl = str(config["systemctl_path"])
        states = {
            name: _unit_state(systemctl, f"codex-market-{name}@{source}.service")
            for name in ("ingestion", "ingestion-postflight", "ingestion-handoff")
        }
        handoff_path = Path(str(config["handoff_root"])) / source / "postflight-handoff.json"
        handoff_ok = verify_handoff(
            handoff_path, source_session=source, now=now,
            max_age_seconds=int(config["max_handoff_age_seconds"]),
        )
        snapshot = _run_preflight(config, source, now)
        active_pipeline = _active_pipeline_units(systemctl)
        foreign_active = foreign_pipeline_units(active_pipeline, source_session=source)
        if foreign_active:
            raise ContractError("another source-session ingestion pipeline is active")
        decision = decide(
            source_session=source, snapshot=snapshot,
            ingestion=states["ingestion"], postflight=states["ingestion-postflight"],
            handoff=states["ingestion-handoff"], handoff_verified=handoff_ok,
            forbidden_safe=_forbidden_units_safe(systemctl),
        )
        event = {
            "contract_id": "codex-nightly-continuity-event-v1",
            "recorded_at": now.astimezone(timezone.utc).isoformat(),
            "source_session": source, "action": decision.action.value,
            "unit": decision.unit, "reason": decision.reason,
            "snapshot_count": snapshot.snapshot_count,
            "snapshot_id": snapshot.snapshot_id, "snapshot_status": snapshot.status,
            "handoff_verified": handoff_ok,
        }
        capacity = None
        if decision.unit is not None:
            capacity = _read_capacity(config, state_root)
            if not capacity.safe:
                raise ContractError(f"guarded ingestion capacity gate failed: {capacity.reason}")
            if decision.action is Action.START_INGESTION:
                _verify_installed_ingestion_priority(systemctl, decision.unit)
            event["capacity"] = {
                "load_per_cpu": capacity.load_per_cpu,
                "available_memory_mb": capacity.available_memory_mb,
                "free_disk_mb": capacity.free_disk_mb,
                "status": "PASS",
            }
        append_event(state_root, event)
        if decision.unit is not None:
            if not UNIT_RE.fullmatch(decision.unit):
                raise ContractError("dispatch unit escaped the allowlist")
            started = subprocess.run(
                [systemctl, "start", "--no-block", decision.unit],
                check=False, capture_output=True, text=True, timeout=20,
            )
            if started.returncode != 0:
                raise ContractError("systemd dispatch failed")
        return decision


def _last_event(state_root: Path) -> dict[str, object]:
    path = state_root / "events.jsonl"
    if not path.is_file():
        raise ContractError("no continuity dispatch event exists")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ContractError("continuity event journal is empty")
    raw = json.loads(lines[-1])
    if raw.get("contract_id") != "codex-nightly-continuity-event-v1":
        raise ContractError("latest continuity event has an invalid contract")
    return raw


def monitor(config_path: Path, *, now: datetime) -> Liveness:
    config = load_config(config_path)
    state_root = Path(str(config["state_root"]))
    with exclusive_lock(state_root / "controller.lock"):
        if not (state_root / "events.jsonl").is_file():
            return Liveness("QUIESCENT", "no continuity dispatch has occurred yet", None, 0, None)
        event = _last_event(state_root)
        source = str(event.get("source_session", ""))
        if not SESSION_RE.fullmatch(source):
            raise ContractError("latest continuity event has an invalid source session")
        systemctl = str(config["systemctl_path"])
        units = {
            name: _unit_state(systemctl, f"codex-market-{name}@{source}.service")
            for name in ("ingestion", "ingestion-postflight", "ingestion-handoff")
        }
        if not _forbidden_units_safe(systemctl):
            raise ContractError("a legacy safety unit is active or enabled")
        handoff_path = Path(str(config["handoff_root"])) / source / "postflight-handoff.json"
        handoff_ok = verify_handoff(
            handoff_path, source_session=source, now=now,
            max_age_seconds=int(config["max_handoff_age_seconds"]),
        )
        marker = Path(str(config["progress_marker_template"]).format(source_session=source))
        active = [(name, unit) for name, unit in units.items() if unit.is_active]
        marker_exists = marker.is_file()
        marker_age = None
        if len(active) == 1:
            name, active_unit = active[0]
            if not marker_exists:
                marker_age = None
            else:
                stage = {
                    "ingestion": "INGESTION",
                    "ingestion-postflight": "POSTFLIGHT",
                    "ingestion-handoff": "HANDOFF",
                }[name]
                marker_age = verify_progress_marker(
                    marker, source_session=source, stage=stage, unit=active_unit,
                    now=now, max_age_seconds=int(config["max_checkpoint_age_seconds"]),
                ).age_seconds
        result = assess_liveness(
            units=units, handoff_verified=handoff_ok,
            checkpoint_exists=marker_exists, checkpoint_age_seconds=marker_age,
            max_checkpoint_age_seconds=float(config["max_checkpoint_age_seconds"]),
        )
        append_event(state_root, {
            "contract_id": "codex-nightly-continuity-event-v1",
            "recorded_at": now.astimezone(timezone.utc).isoformat(),
            "source_session": source, "action": "LIVENESS_CHECK",
            "liveness_status": result.status, "reason": result.reason,
            "active_unit": result.active_unit, "main_pid": result.main_pid,
            "checkpoint_age_seconds": result.checkpoint_age_seconds,
            "handoff_verified": handoff_ok,
        })
        return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--now", help="test-only timezone-aware ISO timestamp")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        now = parse_utc(args.now) if args.now else datetime.now(timezone.utc)
        if args.monitor:
            result = monitor(args.config, now=now)
            print(f"CONTINUITY_LIVENESS status={result.status} unit={result.active_unit or '-'} pid={result.main_pid} checkpoint_age={result.checkpoint_age_seconds}")
            return 0 if result.status in {"ACTIVE", "VERIFIED", "QUIESCENT"} else 2
        decision = run(args.config, now=now)
        print(f"CONTINUITY_{decision.action.value} unit={decision.unit or '-'} reason={decision.reason}")
        return 0
    except (ContractError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"CONTINUITY_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
