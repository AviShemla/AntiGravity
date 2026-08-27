"""Pure v2 resource envelope for the measured four-chain S08 rehearsal.

This contract represents planning evidence only.  It has no launcher, process,
filesystem, network, database, model, recommendation, order, or trading path.
The scientific identity and diagnostic thresholds are exact constants. Runtime
and memory limits are derived from injected measured evidence; capacity must
also preserve explicit system and guarded-ingestion reservations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
import hashlib
import json
import re


CONTRACT_ID = "codex-oracle-s08-resource-bounded-execution-v2"
MEASUREMENT_CONTRACT_ID = "codex-oracle-s08-four-chain-measurement-v1"
CAPACITY_VERIFIED_STATUS = "CAPACITY_VERIFIED_NOT_EXECUTION_AUTHORIZATION"
RESOURCE_BLOCKED_STATUS = "RESOURCE_BLOCKED"
MEASURED_ELAPSED_SECONDS = 7_425
MEASURED_CPU_QUOTA_PERCENT = 200
MEASURED_PEAK_MEMORY_BYTES = 1_404_485_632
MEASURED_CPU_USAGE_NSEC = 14_782_971_921_000
MEASURED_INVOCATION_ID = "e8a9f0c2b3834aaf88c3ffbd333a77a6"
MEASURED_EXIT_STATUS = 1
MEASURED_STARTED_AT_UTC = datetime(2026, 8, 27, 12, 52, 22, tzinfo=timezone.utc)
MEASURED_FINISHED_AT_UTC = datetime(2026, 8, 27, 14, 58, 32, tzinfo=timezone.utc)
RUNTIME_HEADROOM_NUMERATOR = 5
RUNTIME_HEADROOM_DENOMINATOR = 4
RUNTIME_ROUND_SECONDS = 60
INGESTION_TIME_BUFFER_SECONDS = 3_600
MEMORY_HEADROOM_NUMERATOR = 5
MEMORY_HEADROOM_DENOMINATOR = 4
MEMORY_ROUND_BYTES = 64 * 1024 * 1024
MIN_INGESTION_CPU_RESERVATION_PERCENT = 100
MIN_SYSTEM_CPU_RESERVATION_PERCENT = 100
MIN_INGESTION_MEMORY_RESERVATION_BYTES = 2 * 1024 * 1024 * 1024
MIN_SYSTEM_MEMORY_RESERVATION_BYTES = 1 * 1024 * 1024 * 1024
MIN_DISK_AFTER_RUN_BYTES = 5 * 1024 * 1024 * 1024
OBSERVATION_FRESHNESS_SECONDS = 120
_SHA = re.compile(r"[0-9a-f]{64}")
_ZERO = {"predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0}


class ResourceContractV2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class ExactScienceIdentity:
    dependency_lock_sha256: str
    fixture_sha256: str
    model_config_sha256: str
    sampler_sha256: str
    chains: int
    draws: int
    tune: int
    max_rhat: float
    min_bulk_ess: int
    min_tail_ess: int
    min_bfmi: float
    max_divergences: int
    max_treedepth_fraction: float
    return_unit: str = "PERCENT"
    topology: str = "INDEPENDENT_TICKER_LAG_EDGES_PARTIAL_POOLING"
    claim_scope: str = "OBSERVATIONAL_PREDICTIVE_ASSOCIATION_NOT_CAUSAL"


@dataclass(frozen=True)
class MeasuredFourChainEvidence:
    contract_id: str
    evidence_raw_sha256: str
    run_id: str
    started_at_utc: datetime
    finished_at_utc: datetime
    elapsed_seconds: int
    invocation_id: str
    cpu_usage_nsec: int
    exit_status: int
    science: ExactScienceIdentity
    cpu_quota_percent: int
    peak_memory_bytes: int
    maximum_checkpoint_gap_seconds: int | None
    measurement_complete: bool
    fixture_only: bool
    database_writes: int
    downstream_counts: dict[str, int]


@dataclass(frozen=True)
class IngestionSafeCapacity:
    observed_at_utc: datetime
    available_cpu_count: int
    ingestion_cpu_reservation_percent: int
    system_cpu_reservation_percent: int
    available_memory_bytes: int
    available_disk_bytes: int
    ingestion_memory_reservation_bytes: int
    system_memory_reservation_bytes: int
    expected_output_bytes: int
    guarded_ingestion_active: bool
    next_guarded_ingestion_at_utc: datetime
    ingestion_priority_reserved: bool
    no_duplicate_worker_observed: bool


@dataclass(frozen=True)
class ResourceBoundedExecutionPlanV2:
    contract_id: str
    status: str
    run_id: str
    measurement_raw_sha256: str
    science_sha256: str
    cpu_quota_percent: int
    available_cpu_capacity_percent: int
    required_cpu_capacity_percent: int
    ingestion_cpu_reservation_percent: int
    system_cpu_reservation_percent: int
    memory_max_bytes: int
    runtime_limit_seconds: int
    runtime_headroom_seconds: int
    ingestion_time_buffer_seconds: int
    ingestion_memory_reservation_bytes: int
    system_memory_reservation_bytes: int
    disk_reservation_bytes: int
    checkpoint_max_age_seconds: int | None
    nice: int
    io_weight: int
    fixture_only: bool
    database_write_scope: str
    downstream_authorized: bool
    execution_authorized: bool
    capacity_observed_at_utc: datetime
    blockers: tuple[str, ...]
    plan_sha256: str


def _primitive(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def canonical_sha256(value: object) -> str:
    raw = json.dumps(
        _primitive(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ResourceContractV2Error(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ResourceContractV2Error(f"{label} must be lowercase SHA-256")


def _round_up(value: int, quantum: int) -> int:
    return ((value + quantum - 1) // quantum) * quantum


def derived_runtime_limit_seconds(elapsed_seconds: int) -> int:
    if type(elapsed_seconds) is not int or elapsed_seconds != MEASURED_ELAPSED_SECONDS:
        raise ResourceContractV2Error("runtime evidence is not the exact measured 7425 seconds")
    with_headroom = ceil(
        elapsed_seconds * RUNTIME_HEADROOM_NUMERATOR / RUNTIME_HEADROOM_DENOMINATOR
    )
    return _round_up(with_headroom, RUNTIME_ROUND_SECONDS)


def derived_memory_limit_bytes(peak_memory_bytes: int) -> int:
    if type(peak_memory_bytes) is not int or peak_memory_bytes <= 0:
        raise ResourceContractV2Error("measured peak memory must be positive")
    with_headroom = ceil(
        peak_memory_bytes * MEMORY_HEADROOM_NUMERATOR / MEMORY_HEADROOM_DENOMINATOR
    )
    return _round_up(with_headroom, MEMORY_ROUND_BYTES)


def _validate_science(science: ExactScienceIdentity) -> str:
    if type(science) is not ExactScienceIdentity:
        raise ResourceContractV2Error("science identity type differs")
    for value, label in (
        (science.dependency_lock_sha256, "dependency lock"),
        (science.fixture_sha256, "fixture"),
        (science.model_config_sha256, "model configuration"),
        (science.sampler_sha256, "sampler"),
    ):
        _sha(value, label)
    if (science.chains, science.draws, science.tune) != (4, 1_000, 1_000):
        raise ResourceContractV2Error("four-chain sampler counts differ")
    numeric = (science.max_rhat, science.min_bfmi, science.max_treedepth_fraction)
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not isfinite(item) for item in numeric):
        raise ResourceContractV2Error("diagnostic threshold is non-finite")
    if (
        science.max_rhat != 1.01
        or science.min_bulk_ess != 400
        or science.min_tail_ess != 400
        or science.min_bfmi != 0.3
        or science.max_divergences != 0
        or science.max_treedepth_fraction != 0.01
    ):
        raise ResourceContractV2Error("scientific or convergence threshold was weakened")
    if (
        science.return_unit != "PERCENT"
        or science.topology != "INDEPENDENT_TICKER_LAG_EDGES_PARTIAL_POOLING"
        or science.claim_scope != "OBSERVATIONAL_PREDICTIVE_ASSOCIATION_NOT_CAUSAL"
    ):
        raise ResourceContractV2Error("science topology, unit, or claim boundary differs")
    return canonical_sha256(science)


def _validate_measurement(evidence: MeasuredFourChainEvidence) -> tuple[str, int, int]:
    if type(evidence) is not MeasuredFourChainEvidence:
        raise ResourceContractV2Error("measurement evidence type differs")
    if evidence.contract_id != MEASUREMENT_CONTRACT_ID:
        raise ResourceContractV2Error("measurement contract identity differs")
    _sha(evidence.evidence_raw_sha256, "measurement raw evidence")
    started = _utc(evidence.started_at_utc, "measurement start")
    finished = _utc(evidence.finished_at_utc, "measurement finish")
    if started != MEASURED_STARTED_AT_UTC or finished != MEASURED_FINISHED_AT_UTC:
        raise ResourceContractV2Error("measurement systemd start or exit timestamp differs")
    if evidence.elapsed_seconds != MEASURED_ELAPSED_SECONDS:
        raise ResourceContractV2Error("measurement is not the exact 7425-second run")
    science_sha = _validate_science(evidence.science)
    if evidence.cpu_quota_percent != MEASURED_CPU_QUOTA_PERCENT:
        raise ResourceContractV2Error("measurement is not the exact 200% CPUQuota readback")
    if evidence.peak_memory_bytes != MEASURED_PEAK_MEMORY_BYTES:
        raise ResourceContractV2Error("measurement is not the exact MemoryPeak readback")
    if evidence.invocation_id != MEASURED_INVOCATION_ID:
        raise ResourceContractV2Error("measurement InvocationID differs")
    if evidence.cpu_usage_nsec != MEASURED_CPU_USAGE_NSEC:
        raise ResourceContractV2Error("measurement CPUUsageNSec differs")
    if evidence.exit_status != MEASURED_EXIT_STATUS:
        raise ResourceContractV2Error("measurement exit status differs")
    memory = derived_memory_limit_bytes(evidence.peak_memory_bytes)
    runtime = derived_runtime_limit_seconds(evidence.elapsed_seconds)
    if evidence.maximum_checkpoint_gap_seconds is not None:
        raise ResourceContractV2Error(
            "checkpoint gap must remain UNKNOWN because v6 emitted no durable progress"
        )
    if evidence.measurement_complete is not True or evidence.fixture_only is not True:
        raise ResourceContractV2Error("measurement completion or fixture boundary differs")
    if evidence.database_writes != 0 or dict(evidence.downstream_counts) != _ZERO:
        raise ResourceContractV2Error("measurement contains prohibited side effects")
    return science_sha, runtime, memory


def build_resource_bounded_execution_plan_v2(
    *, evidence: MeasuredFourChainEvidence, capacity: IngestionSafeCapacity,
    now_utc: datetime, nice: int = 10, io_weight: int = 50,
) -> ResourceBoundedExecutionPlanV2:
    """Build a non-executable, measured resource plan or fail closed."""
    science_sha, runtime, memory = _validate_measurement(evidence)
    if type(capacity) is not IngestionSafeCapacity:
        raise ResourceContractV2Error("capacity observation type differs")
    now = _utc(now_utc, "current time")
    observed = _utc(capacity.observed_at_utc, "capacity observation")
    ingestion = _utc(capacity.next_guarded_ingestion_at_utc, "next guarded ingestion")
    if observed > now or (now - observed).total_seconds() > OBSERVATION_FRESHNESS_SECONDS:
        raise ResourceContractV2Error("capacity observation is stale or future-dated")
    integer_fields = (
        capacity.available_cpu_count, capacity.available_memory_bytes,
        capacity.available_disk_bytes, capacity.ingestion_memory_reservation_bytes,
        capacity.system_memory_reservation_bytes, capacity.expected_output_bytes,
        capacity.ingestion_cpu_reservation_percent,
        capacity.system_cpu_reservation_percent,
    )
    if any(type(item) is not int or item <= 0 for item in integer_fields):
        raise ResourceContractV2Error("capacity contains nonpositive or noninteger evidence")
    if capacity.ingestion_cpu_reservation_percent < MIN_INGESTION_CPU_RESERVATION_PERCENT:
        raise ResourceContractV2Error("ingestion CPU reservation is below the fixed floor")
    if capacity.system_cpu_reservation_percent < MIN_SYSTEM_CPU_RESERVATION_PERCENT:
        raise ResourceContractV2Error("system CPU reservation is below the fixed floor")
    if capacity.ingestion_memory_reservation_bytes < MIN_INGESTION_MEMORY_RESERVATION_BYTES:
        raise ResourceContractV2Error("ingestion memory reservation is below the fixed floor")
    if capacity.system_memory_reservation_bytes < MIN_SYSTEM_MEMORY_RESERVATION_BYTES:
        raise ResourceContractV2Error("system memory reservation is below the fixed floor")
    disk_reservation = capacity.expected_output_bytes + MIN_DISK_AFTER_RUN_BYTES
    available_cpu = capacity.available_cpu_count * 100
    required_cpu = (
        evidence.cpu_quota_percent
        + capacity.ingestion_cpu_reservation_percent
        + capacity.system_cpu_reservation_percent
    )
    blockers: list[str] = ["DURABLE_PROGRESS_UNOBSERVED"]
    if required_cpu > available_cpu:
        blockers.append(
            f"CPU_CAPACITY_REQUIRED_{required_cpu}_AVAILABLE_{available_cpu}"
        )
    if memory + capacity.ingestion_memory_reservation_bytes + capacity.system_memory_reservation_bytes > capacity.available_memory_bytes:
        blockers.append("MEMORY_CAPACITY")
    if disk_reservation > capacity.available_disk_bytes:
        blockers.append("DISK_CAPACITY")
    if capacity.guarded_ingestion_active is not False:
        blockers.append("GUARDED_INGESTION_ACTIVE")
    if capacity.ingestion_priority_reserved is not True:
        blockers.append("INGESTION_PRIORITY_NOT_RESERVED")
    if capacity.no_duplicate_worker_observed is not True:
        blockers.append("DUPLICATE_WORKER_NOT_CLEARED")
    if now + timedelta(seconds=runtime + INGESTION_TIME_BUFFER_SECONDS) > ingestion:
        blockers.append("INGESTION_TIME_BUFFER")
    if type(nice) is not int or nice < 5 or type(io_weight) is not int or not 1 <= io_weight <= 100:
        raise ResourceContractV2Error("low-priority scheduling boundary differs")
    payload = {
        "contract_id": CONTRACT_ID,
        "status": RESOURCE_BLOCKED_STATUS if blockers else CAPACITY_VERIFIED_STATUS,
        "run_id": evidence.run_id,
        "measurement_raw_sha256": evidence.evidence_raw_sha256,
        "science_sha256": science_sha,
        "cpu_quota_percent": evidence.cpu_quota_percent,
        "available_cpu_capacity_percent": available_cpu,
        "required_cpu_capacity_percent": required_cpu,
        "ingestion_cpu_reservation_percent": capacity.ingestion_cpu_reservation_percent,
        "system_cpu_reservation_percent": capacity.system_cpu_reservation_percent,
        "memory_max_bytes": memory,
        "runtime_limit_seconds": runtime,
        "runtime_headroom_seconds": runtime - evidence.elapsed_seconds,
        "ingestion_time_buffer_seconds": INGESTION_TIME_BUFFER_SECONDS,
        "ingestion_memory_reservation_bytes": capacity.ingestion_memory_reservation_bytes,
        "system_memory_reservation_bytes": capacity.system_memory_reservation_bytes,
        "disk_reservation_bytes": disk_reservation,
        "checkpoint_max_age_seconds": evidence.maximum_checkpoint_gap_seconds,
        "nice": nice,
        "io_weight": io_weight,
        "fixture_only": True,
        "database_write_scope": "NONE",
        "downstream_authorized": False,
        "execution_authorized": False,
        "capacity_observed_at_utc": observed,
        "blockers": tuple(blockers),
    }
    return ResourceBoundedExecutionPlanV2(
        **payload, plan_sha256=canonical_sha256(payload),
    )


def audit_resource_bounded_execution_plan_v2(
    plan: ResourceBoundedExecutionPlanV2, *, evidence: MeasuredFourChainEvidence,
    capacity: IngestionSafeCapacity, now_utc: datetime,
) -> None:
    rebuilt = build_resource_bounded_execution_plan_v2(
        evidence=evidence, capacity=capacity, now_utc=now_utc,
        nice=plan.nice, io_weight=plan.io_weight,
    )
    if type(plan) is not ResourceBoundedExecutionPlanV2 or plan != rebuilt:
        raise ResourceContractV2Error("resource plan identity or evidence binding differs")
