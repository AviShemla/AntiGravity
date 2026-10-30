"""Immutable Linux closure and resource-safe synthetic S08 rehearsal contract.

This module is fixture-only.  It has no process launcher, network/database
client, or production path authority.  All runtime and liveness observations
are injected so an independent launcher can apply the same fail-closed rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from typing import Callable, Mapping

try:
    from hierarchical_model_impl.independent_edge_hierarchy import (
        SamplerDiagnosticsEvidence,
    )
except ModuleNotFoundError:
    from research_contracts.hierarchical_stock_model.independent_edge_hierarchy import (
        SamplerDiagnosticsEvidence,
    )

from .checkpoint_quarantine_contract import DurableFixtureStore, FixtureTerminal
from .pymc_hierarchical_backend import FrozenBackendConfig, PyMCBackendError, freeze_backend_config


CONTRACT_ID = "codex-oracle-s08-linux-synthetic-convergence-v1"
RUNNER_ID = "codex-oracle-s08-resource-bounded-fixture-runner-v1"
AUDITOR_ID = "codex-oracle-s08-fixture-terminal-auditor-v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")
_INGESTION_BUFFER = timedelta(hours=1)
_FRESHNESS = timedelta(minutes=2)
_ZERO = {"predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0}


def _canonical(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _canonical(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def canonical_sha256(value: object) -> str:
    raw = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise PyMCBackendError(f"{label} is not a lowercase SHA-256")


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PyMCBackendError(f"{label} is not timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class LinuxDependencyLock:
    contract_id: str
    platform_system: str
    platform_machine: str
    python_version: str
    python_implementation: str
    python_executable_sha256: str
    pymc_version: str
    pytensor_version: str
    arviz_version: str
    numpy_version: str
    blas_identity_sha256: str
    distribution_records_sha256: str
    lock_sha256: str


def build_dependency_lock(**identity: str) -> LinuxDependencyLock:
    payload = {
        "contract_id": CONTRACT_ID,
        **identity,
    }
    required = {
        "platform_system", "platform_machine", "python_version",
        "python_implementation", "python_executable_sha256", "pymc_version",
        "pytensor_version", "arviz_version", "numpy_version",
        "blas_identity_sha256", "distribution_records_sha256",
    }
    if set(identity) != required:
        raise PyMCBackendError("dependency identity fields differ")
    if identity["platform_system"] != "Linux" or not identity["platform_machine"]:
        raise PyMCBackendError("dependency lock is not an exact Linux identity")
    for key in ("python_executable_sha256", "blas_identity_sha256", "distribution_records_sha256"):
        _sha(identity[key], key)
    for key in ("python_version", "python_implementation", "pymc_version", "pytensor_version", "arviz_version", "numpy_version"):
        if not _SAFE.fullmatch(identity[key]):
            raise PyMCBackendError(f"{key} is missing or unsafe")
    digest = canonical_sha256(payload)
    return LinuxDependencyLock(**payload, lock_sha256=digest)


def verify_dependency_lock(lock: LinuxDependencyLock, observed: Mapping[str, str]) -> None:
    if type(lock) is not LinuxDependencyLock:
        raise PyMCBackendError("dependency lock type differs")
    expected = build_dependency_lock(**{
        key: getattr(lock, key) for key in lock.__dataclass_fields__
        if key not in {"contract_id", "lock_sha256"}
    })
    if lock != expected:
        raise PyMCBackendError("dependency lock content address differs")
    if dict(observed) != {
        key: getattr(lock, key) for key in lock.__dataclass_fields__
        if key not in {"contract_id", "lock_sha256"}
    }:
        raise PyMCBackendError("observed Linux dependency closure differs from lock")


@dataclass(frozen=True)
class SyntheticConvergenceEvidence:
    contract_id: str
    run_id: str
    fixture_sha256: str
    dependency_lock_sha256: str
    model_config_sha256: str
    sampler_sha256: str
    diagnostics: SamplerDiagnosticsEvidence
    fixture_only: bool
    synthetic_convergence_verified: bool
    scientific_evidence: bool
    posterior_persisted: bool
    database_write_scope: str
    downstream_counts: Mapping[str, int]
    evidence_sha256: str


def build_synthetic_convergence_evidence(
    *, run_id: str, fixture_sha256: str, lock: LinuxDependencyLock,
    config: FrozenBackendConfig, diagnostics: SamplerDiagnosticsEvidence,
) -> SyntheticConvergenceEvidence:
    if not _SAFE.fullmatch(run_id):
        raise PyMCBackendError("synthetic run ID is missing or unsafe")
    _sha(fixture_sha256, "fixture identity")
    verify_dependency_lock(lock, {
        key: getattr(lock, key) for key in lock.__dataclass_fields__
        if key not in {"contract_id", "lock_sha256"}
    })
    if config != freeze_backend_config(config.model, config.sampler):
        raise PyMCBackendError("backend configuration is not frozen")
    if type(diagnostics) is not SamplerDiagnosticsEvidence:
        raise PyMCBackendError("synthetic diagnostics type differs")
    if (diagnostics.chains, diagnostics.draws, diagnostics.tune) != (
        config.sampler.chains, config.sampler.draws, config.sampler.tune,
    ):
        raise PyMCBackendError("synthetic diagnostics do not use the frozen sampler counts")
    if diagnostics.chains != 4 or diagnostics.draws < 1000 or diagnostics.tune < 1000:
        raise PyMCBackendError("synthetic rehearsal weakens the four-chain minimum")
    values = (diagnostics.max_rhat, diagnostics.min_bulk_ess, diagnostics.min_tail_ess,
              diagnostics.bfmi_min, diagnostics.max_treedepth_fraction)
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) for value in values):
        raise PyMCBackendError("synthetic diagnostics are not numeric")
    if (diagnostics.max_rhat > 1.01 or diagnostics.min_bulk_ess < 400
            or diagnostics.min_tail_ess < 400 or diagnostics.bfmi_min < 0.3
            or diagnostics.divergences != 0
            or not 0 <= diagnostics.max_treedepth_fraction <= 0.01):
        raise PyMCBackendError("synthetic convergence gates failed")
    payload = {
        "contract_id": CONTRACT_ID, "run_id": run_id,
        "fixture_sha256": fixture_sha256,
        "dependency_lock_sha256": lock.lock_sha256,
        "model_config_sha256": config.model_config_sha256,
        "sampler_sha256": config.sampler_sha256,
        "diagnostics": diagnostics, "fixture_only": True,
        "synthetic_convergence_verified": True, "scientific_evidence": False,
        "posterior_persisted": False, "database_write_scope": "NONE",
        "downstream_counts": dict(_ZERO),
    }
    return SyntheticConvergenceEvidence(**payload, evidence_sha256=canonical_sha256(payload))


def verify_synthetic_convergence_evidence(
    evidence: SyntheticConvergenceEvidence, *, lock: LinuxDependencyLock,
    config: FrozenBackendConfig, fixture_sha256: str,
) -> None:
    rebuilt = build_synthetic_convergence_evidence(
        run_id=evidence.run_id, fixture_sha256=fixture_sha256, lock=lock,
        config=config, diagnostics=evidence.diagnostics,
    )
    if evidence != rebuilt:
        raise PyMCBackendError("synthetic convergence evidence identity or claim boundary differs")


@dataclass(frozen=True)
class ResourceObservation:
    observed_at_utc: datetime
    available_cpu_count: int
    available_memory_bytes: int
    available_disk_bytes: int
    guarded_ingestion_active: bool
    next_guarded_ingestion_at_utc: datetime
    no_duplicate_worker: bool


@dataclass(frozen=True)
class ResourceBoundedFixturePlan:
    contract_id: str
    runner_id: str
    run_id: str
    dependency_lock_sha256: str
    model_config_sha256: str
    sampler_sha256: str
    fixture_sha256: str
    cpu_quota_percent: int
    memory_max_bytes: int
    io_weight: int
    nice: int
    expected_max_runtime_seconds: int
    ingestion_buffer_seconds: int
    fixture_only: bool
    database_write_scope: str
    downstream_authorized: bool
    plan_sha256: str


def _validate_resources(value: ResourceObservation, *, now: datetime, plan: ResourceBoundedFixturePlan) -> None:
    observed = _aware(value.observed_at_utc, "resource observation")
    current = _aware(now, "current time")
    ingestion = _aware(value.next_guarded_ingestion_at_utc, "next ingestion")
    if observed > current or current - observed > _FRESHNESS:
        raise PyMCBackendError("resource observation is stale or future-dated")
    if value.guarded_ingestion_active:
        raise PyMCBackendError("guarded ingestion is active; fixture must yield")
    if value.no_duplicate_worker is not True:
        raise PyMCBackendError("duplicate fixture worker is present")
    if value.available_cpu_count < 2 or value.available_memory_bytes < plan.memory_max_bytes:
        raise PyMCBackendError("fixture resource capacity is insufficient")
    if value.available_disk_bytes < 1_000_000_000:
        raise PyMCBackendError("fixture free disk is insufficient")
    deadline = current + timedelta(seconds=plan.expected_max_runtime_seconds + plan.ingestion_buffer_seconds)
    if deadline > ingestion:
        raise PyMCBackendError("fixture cannot finish before guarded-ingestion buffer")


def build_resource_bounded_plan(
    *, run_id: str, lock: LinuxDependencyLock, config: FrozenBackendConfig,
    fixture_sha256: str, observation: ResourceObservation, now: datetime,
    cpu_quota_percent: int = 50, memory_max_bytes: int = 2_147_483_648,
    io_weight: int = 50, nice: int = 10, expected_max_runtime_seconds: int = 1800,
) -> ResourceBoundedFixturePlan:
    if not _SAFE.fullmatch(run_id):
        raise PyMCBackendError("runner run ID is missing or unsafe")
    _sha(fixture_sha256, "fixture identity")
    if not 1 <= cpu_quota_percent <= 50 or not 268_435_456 <= memory_max_bytes <= 4_294_967_296:
        raise PyMCBackendError("fixture CPU or memory bound differs")
    if not 1 <= io_weight <= 100 or nice < 5 or not 60 <= expected_max_runtime_seconds <= 3600:
        raise PyMCBackendError("fixture I/O, nice, or runtime bound differs")
    payload = {
        "contract_id": CONTRACT_ID, "runner_id": RUNNER_ID, "run_id": run_id,
        "dependency_lock_sha256": lock.lock_sha256,
        "model_config_sha256": config.model_config_sha256,
        "sampler_sha256": config.sampler_sha256,
        "fixture_sha256": fixture_sha256,
        "cpu_quota_percent": cpu_quota_percent, "memory_max_bytes": memory_max_bytes,
        "io_weight": io_weight, "nice": nice,
        "expected_max_runtime_seconds": expected_max_runtime_seconds,
        "ingestion_buffer_seconds": int(_INGESTION_BUFFER.total_seconds()),
        "fixture_only": True, "database_write_scope": "NONE",
        "downstream_authorized": False,
    }
    plan = ResourceBoundedFixturePlan(**payload, plan_sha256=canonical_sha256(payload))
    _validate_resources(observation, now=now, plan=plan)
    return plan


def run_resource_bounded_fixture(
    *, root: Path, plan: ResourceBoundedFixturePlan,
    observation_reader: Callable[[], ResourceObservation],
    now_reader: Callable[[], datetime],
    executor: Callable[[], SyntheticConvergenceEvidence],
) -> FixtureTerminal:
    if type(plan) is not ResourceBoundedFixturePlan:
        raise PyMCBackendError("resource-bounded plan type differs")
    payload = {key: getattr(plan, key) for key in plan.__dataclass_fields__ if key != "plan_sha256"}
    if plan.plan_sha256 != canonical_sha256(payload):
        raise PyMCBackendError("resource-bounded plan identity differs")
    started = now_reader()
    store = DurableFixtureStore.create(root, run_id=plan.run_id, plan_sha256=plan.plan_sha256, created_at_utc=started)
    store.append_checkpoint(observed_at_utc=started, completed_targets=0, total_targets=1,
                            completed_folds=0, total_folds=1, divergences=0)
    try:
        _validate_resources(observation_reader(), now=now_reader(), plan=plan)
        evidence = executor()
        if evidence.run_id != plan.run_id or evidence.fixture_sha256 != plan.fixture_sha256:
            raise PyMCBackendError("fixture executor evidence lineage differs")
        if evidence.dependency_lock_sha256 != plan.dependency_lock_sha256 or evidence.model_config_sha256 != plan.model_config_sha256 or evidence.sampler_sha256 != plan.sampler_sha256:
            raise PyMCBackendError("fixture executor immutable identity differs")
        _validate_resources(observation_reader(), now=now_reader(), plan=plan)
        finished = now_reader()
        store.append_checkpoint(observed_at_utc=finished, completed_targets=1, total_targets=1,
                                completed_folds=1, total_folds=1,
                                divergences=evidence.diagnostics.divergences)
        return store.finish(observed_at_utc=finished, success=True, completed_targets=1,
                            total_targets=1, completed_folds=1, total_folds=1)
    except BaseException as exc:
        store.finish(observed_at_utc=now_reader(), success=False, completed_targets=0,
                     total_targets=1, completed_folds=0, total_folds=1,
                     failure_class=type(exc).__name__)
        raise


@dataclass(frozen=True)
class FixtureTerminalAudit:
    auditor_id: str
    run_id: str
    plan_sha256: str
    terminal_sha256: str
    checkpoint_count: int
    exact_fixture_coverage: bool
    zero_downstream_outputs: bool
    audit_sha256: str


def audit_fixture_terminal(root: Path, plan: ResourceBoundedFixturePlan) -> FixtureTerminalAudit:
    store = DurableFixtureStore(root)
    manifest = store.manifest()
    checkpoints = store.read_checkpoints()
    terminal = store.read_terminal()
    if manifest.run_id != plan.run_id or manifest.plan_sha256 != plan.plan_sha256:
        raise PyMCBackendError("fixture terminal manifest lineage differs")
    if terminal.state != "TERMINAL_FIXTURE_SMOKE" or len(checkpoints) != 2:
        raise PyMCBackendError("fixture terminal is not an exact successful rehearsal")
    exact = terminal.completed_targets == terminal.total_targets == 1 and terminal.completed_folds == terminal.total_folds == 1
    zero = dict(terminal.downstream_counts) == _ZERO
    if not exact or not zero or terminal.scientific_evidence or terminal.convergence_claimed:
        raise PyMCBackendError("fixture terminal coverage or claim boundary differs")
    payload = {"auditor_id": AUDITOR_ID, "run_id": plan.run_id,
               "plan_sha256": plan.plan_sha256, "terminal_sha256": terminal.payload_sha256,
               "checkpoint_count": len(checkpoints), "exact_fixture_coverage": exact,
               "zero_downstream_outputs": zero}
    return FixtureTerminalAudit(**payload, audit_sha256=canonical_sha256(payload))
