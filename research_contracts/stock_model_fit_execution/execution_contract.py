"""Pure, immutable execution contract for one governed S08 stock-model fit.

This module performs no I/O, database access, process launch, model fit, or
downstream action.  It converts separately verified evidence into a content-
addressed launch authorization and validates append-only lifecycle evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from typing import Mapping, Sequence


CONTRACT_ID = "codex-oracle-s08-stock-fit-execution-v1"
PREREGISTRATION_CONTRACT_ID = "codex-oracle-hierarchical-stock-preregistration-v2"
AUTHORIZATION_SCOPE = "RESEARCH_ONLY_EXACT_PREREGISTERED_FIT"
OUTPUT_SCOPE = "FILESYSTEM_APPEND_ONLY_RESEARCH_EVIDENCE"
EXPECTED_LAGS = tuple(range(1, 8))
EXPECTED_DEPTHS = tuple(range(1, 6))
EXPECTED_TARGET_COUNT = 474
EXPECTED_FOLD_COUNT = 4
EXPECTED_MODEL_CALENDAR_SESSIONS = 416
MAX_EVIDENCE_AGE = timedelta(hours=1)
MAX_CHECKPOINT_AGE_SECONDS = 3600
MIN_INGESTION_BUFFER_SECONDS = 1800
DOWNSTREAM_COUNT_KEYS = frozenset({
    "predictions", "recommendations", "orders", "etf_outputs",
})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}")


class ExecutionContractError(RuntimeError):
    """Raised before launch or downstream use when a gate is not proven."""


class AuthorizationStatus(StrEnum):
    AUTHORIZED_NOT_STARTED = "AUTHORIZED_NOT_STARTED"


class CheckpointState(StrEnum):
    RUNNING = "RUNNING"
    TERMINAL_SUCCESS = "TERMINAL_SUCCESS"
    TERMINAL_SCIENTIFIC_FAILURE = "TERMINAL_SCIENTIFIC_FAILURE"
    QUARANTINED = "QUARANTINED"


def _primitive(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")
    if hasattr(value, "__dataclass_fields__"):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            _primitive(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExecutionContractError("contract contains unsupported or non-finite data") from exc


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExecutionContractError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ExecutionContractError(f"{label} must be a lowercase SHA-256")


def _git_sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise ExecutionContractError(f"{label} must be an immutable Git SHA")


def _safe_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ExecutionContractError(f"{label} is missing or unsafe")


def _exact_bool(value: object, expected: bool, label: str) -> None:
    if type(value) is not bool or value is not expected:
        raise ExecutionContractError(f"{label} must be {expected}")


def _zero_downstream_counts(value: object, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != DOWNSTREAM_COUNT_KEYS:
        raise ExecutionContractError(f"{label} schema differs")
    if any(type(item) is not int or item != 0 for item in value.values()):
        raise ExecutionContractError(f"{label} contains downstream outputs")


@dataclass(frozen=True)
class PreregistrationProof:
    contract_id: str
    run_id: str
    raw_sha256: str
    checkpoint_identity_sha256: str
    independent_audit_raw_sha256: str
    independent_audit_status: str
    independent_audit_observed_at_utc: datetime
    current_readback_raw_sha256: str
    current_readback_status: str
    current_readback_observed_at_utc: datetime
    snapshot_id: str
    snapshot_sha256: str
    universe_id: str
    universe_sha256: str
    full_session_calendar_sha256: str
    model_session_dates_sha256: str
    model_code_git_commit: str
    model_config_sha256: str
    sampler_sha256: str
    candidate_lags: tuple[int, ...]
    candidate_depths: tuple[int, ...]
    target_count: int
    fold_count: int
    model_calendar_sessions: int
    training_only_selection: bool
    multiple_testing_control: str
    zero_temporal_overlap: bool
    fixture_only: bool
    model_fit_authorized: bool
    model_fit_started: bool
    downstream_counts: Mapping[str, int]


@dataclass(frozen=True)
class ExplicitRunAuthorization:
    authorization_id: str
    authorization_record_sha256: str
    authorized_by: str
    authorized_at_utc: datetime
    launch_deadline_utc: datetime
    scope: str
    run_id: str
    preregistration_raw_sha256: str
    single_run_only: bool
    exact_model_only: bool
    research_only: bool
    database_write_scope: str
    prediction_persistence_authorized: bool
    recommendation_authorized: bool
    order_authorized: bool
    etf_output_authorized: bool
    trading_authorized: bool
    snapshot_validation_or_promotion_authorized: bool


@dataclass(frozen=True)
class CodeClosure:
    git_commit: str
    release_root: str
    release_manifest_sha256: str
    model_entrypoint: str
    model_entrypoint_sha256: str
    dependency_lock_sha256: str
    python_executable: str
    python_identity_sha256: str
    closure_file_count: int
    root_owned: bool
    immutable: bool
    secret_scan_passed: bool


@dataclass(frozen=True)
class ResourceEnvelope:
    observed_at_utc: datetime
    available_cpu_count: int
    cpu_quota_percent: int
    available_memory_bytes: int
    memory_max_bytes: int
    available_disk_bytes: int
    minimum_free_disk_bytes: int
    io_weight: int
    nice: int
    expected_max_runtime_seconds: int
    guarded_ingestion_active: bool
    next_guarded_ingestion_at_utc: datetime
    ingestion_priority_reserved: bool
    no_duplicate_writer_observed: bool


@dataclass(frozen=True)
class OutputBoundary:
    output_root: str
    checkpoint_path: str
    terminal_manifest_path: str
    quarantine_root: str
    append_only: bool = True
    overwrite_allowed: bool = False
    database_write_scope: str = "NONE"
    max_checkpoint_age_seconds: int = MAX_CHECKPOINT_AGE_SECONDS
    persist_predictions: bool = False
    create_recommendations: bool = False
    create_orders: bool = False
    create_etf_outputs: bool = False
    activate_trading: bool = False
    validate_or_promote_snapshot: bool = False


@dataclass(frozen=True)
class LaunchCommand:
    argv: tuple[str, ...]
    shell: bool
    working_directory: str
    environment_keys: tuple[str, ...]
    checkpoint_interval_seconds: int
    resume_supported: bool
    idempotency_key: str


@dataclass(frozen=True)
class ExecutionRequest:
    preregistration: PreregistrationProof
    authorization: ExplicitRunAuthorization
    code: CodeClosure
    resources: ResourceEnvelope
    output: OutputBoundary
    launch: LaunchCommand


@dataclass(frozen=True)
class ExecutionAuthorizationArtifact:
    contract_id: str
    status: AuthorizationStatus
    artifact_id: str
    request_sha256: str
    created_at_utc: datetime
    launch_deadline_utc: datetime
    run_id: str
    preregistration_raw_sha256: str
    checkpoint_identity_sha256: str
    authorization_record_sha256: str
    code_git_commit: str
    release_manifest_sha256: str
    output_root: str
    launch_argv: tuple[str, ...]
    checkpoint_interval_seconds: int
    max_checkpoint_age_seconds: int
    model_fit_started: bool
    database_writes_authorized: bool
    downstream_authorized: bool
    launch_performed: bool


@dataclass(frozen=True)
class CheckpointEvidence:
    contract_artifact_id: str
    run_id: str
    sequence: int
    state: CheckpointState
    observed_at_utc: datetime
    code_git_commit: str
    preregistration_raw_sha256: str
    payload_sha256: str
    completed_targets: int
    completed_folds: int
    divergences: int
    downstream_counts: Mapping[str, int]


@dataclass(frozen=True)
class TerminalReadback:
    contract_artifact_id: str
    run_id: str
    state: CheckpointState
    terminal_manifest_raw_sha256: str
    observed_at_utc: datetime
    target_count: int
    fold_count: int
    ticker_count: int
    candidate_lags: tuple[int, ...]
    candidate_depths: tuple[int, ...]
    snapshot_sha256: str
    universe_sha256: str
    model_code_git_commit: str
    model_config_sha256: str
    sampler_sha256: str
    zero_temporal_overlap: bool
    convergence_passed: bool
    partial_outputs_quarantined: bool
    downstream_counts: Mapping[str, int]


@dataclass(frozen=True)
class TerminalAuditResult:
    passed: bool
    scientific_outcome: str
    checked_targets: int
    checked_folds: int
    terminal_manifest_raw_sha256: str


def authorization_record_sha256(authorization: ExplicitRunAuthorization) -> str:
    """Hash the exact explicit authorization semantics, excluding its claim."""
    if type(authorization) is not ExplicitRunAuthorization:
        raise ExecutionContractError("authorization must use the exact governed type")
    payload = asdict(authorization)
    payload.pop("authorization_record_sha256")
    return canonical_sha256(payload)


def _validate_preregistration(proof: PreregistrationProof, now: datetime) -> None:
    if proof.contract_id != PREREGISTRATION_CONTRACT_ID:
        raise ExecutionContractError("preregistration contract identity differs")
    _safe_id(proof.run_id, "run_id")
    for label, value in (
        ("preregistration raw identity", proof.raw_sha256),
        ("checkpoint identity", proof.checkpoint_identity_sha256),
        ("independent audit raw identity", proof.independent_audit_raw_sha256),
        ("current readback raw identity", proof.current_readback_raw_sha256),
        ("snapshot identity", proof.snapshot_sha256),
        ("universe identity", proof.universe_sha256),
        ("full calendar identity", proof.full_session_calendar_sha256),
        ("model calendar identity", proof.model_session_dates_sha256),
        ("model configuration identity", proof.model_config_sha256),
        ("sampler identity", proof.sampler_sha256),
    ):
        _sha(value, label)
    _git_sha(proof.model_code_git_commit, "model code identity")
    if proof.independent_audit_status != "VERIFIED_FIXTURE_ONLY":
        raise ExecutionContractError("preregistration independent audit is not verified")
    if proof.current_readback_status != "VERIFIED_SELECT_ONLY":
        raise ExecutionContractError("current readback is not verified SELECT-only evidence")
    audit_time = _utc(proof.independent_audit_observed_at_utc, "audit time")
    readback_time = _utc(proof.current_readback_observed_at_utc, "readback time")
    if audit_time > now or readback_time > now:
        raise ExecutionContractError("preregistration evidence is future-dated")
    if now - audit_time > MAX_EVIDENCE_AGE or now - readback_time > MAX_EVIDENCE_AGE:
        raise ExecutionContractError("preregistration evidence is stale")
    if proof.candidate_lags != EXPECTED_LAGS or proof.candidate_depths != EXPECTED_DEPTHS:
        raise ExecutionContractError("lag/depth search geometry differs from preregistration")
    if (proof.target_count, proof.fold_count, proof.model_calendar_sessions) != (
        EXPECTED_TARGET_COUNT, EXPECTED_FOLD_COUNT, EXPECTED_MODEL_CALENDAR_SESSIONS,
    ):
        raise ExecutionContractError("target/fold/calendar geometry differs")
    _exact_bool(proof.training_only_selection, True, "training-only selection")
    if not isinstance(proof.multiple_testing_control, str) or not proof.multiple_testing_control.strip():
        raise ExecutionContractError("multiple-testing control is missing")
    _exact_bool(proof.zero_temporal_overlap, True, "zero temporal overlap")
    _exact_bool(proof.fixture_only, True, "preregistration fixture boundary")
    _exact_bool(proof.model_fit_authorized, False, "preregistration fit authorization")
    _exact_bool(proof.model_fit_started, False, "preregistration fit state")
    if (
        not isinstance(proof.snapshot_id, str) or not proof.snapshot_id.strip()
        or not isinstance(proof.universe_id, str) or not proof.universe_id.strip()
    ):
        raise ExecutionContractError("snapshot/universe identifiers are missing")
    _zero_downstream_counts(proof.downstream_counts, "preregistration downstream counts")


def _validate_explicit_authorization(
    authorization: ExplicitRunAuthorization, proof: PreregistrationProof, now: datetime,
) -> None:
    _safe_id(authorization.authorization_id, "authorization_id")
    _sha(authorization.authorization_record_sha256, "authorization record identity")
    if authorization.authorization_record_sha256 != authorization_record_sha256(authorization):
        raise ExecutionContractError("authorization record identity mismatch")
    if not isinstance(authorization.authorized_by, str) or not authorization.authorized_by.strip():
        raise ExecutionContractError("accountable authorizer is missing")
    authorized_at = _utc(authorization.authorized_at_utc, "authorization time")
    deadline = _utc(authorization.launch_deadline_utc, "launch deadline")
    if not authorized_at <= now <= deadline or deadline - authorized_at > timedelta(hours=24):
        raise ExecutionContractError("explicit launch authorization is not currently valid")
    if authorization.scope != AUTHORIZATION_SCOPE:
        raise ExecutionContractError("authorization scope differs")
    if authorization.run_id != proof.run_id or authorization.preregistration_raw_sha256 != proof.raw_sha256:
        raise ExecutionContractError("authorization is not bound to this exact preregistration")
    for label, value in (
        ("single-run boundary", authorization.single_run_only),
        ("exact-model boundary", authorization.exact_model_only),
        ("research-only boundary", authorization.research_only),
    ):
        _exact_bool(value, True, label)
    if authorization.database_write_scope != "NONE":
        raise ExecutionContractError("database writes are not authorized by this contract")
    for label, value in (
        ("prediction persistence", authorization.prediction_persistence_authorized),
        ("recommendations", authorization.recommendation_authorized),
        ("orders", authorization.order_authorized),
        ("ETF outputs", authorization.etf_output_authorized),
        ("trading", authorization.trading_authorized),
        ("snapshot lifecycle changes", authorization.snapshot_validation_or_promotion_authorized),
    ):
        _exact_bool(value, False, f"{label} authorization")


def _under(path: str, root: str, label: str) -> PurePosixPath:
    value = PurePosixPath(path)
    base = PurePosixPath(root)
    if not value.is_absolute() or value == base or base not in value.parents or ".." in value.parts:
        raise ExecutionContractError(f"{label} is outside its immutable boundary")
    return value


def _validate_code(code: CodeClosure, proof: PreregistrationProof) -> None:
    _git_sha(code.git_commit, "release Git identity")
    if code.git_commit != proof.model_code_git_commit:
        raise ExecutionContractError("release Git identity differs from preregistration")
    for label, value in (
        ("release manifest", code.release_manifest_sha256),
        ("model entrypoint", code.model_entrypoint_sha256),
        ("dependency lock", code.dependency_lock_sha256),
        ("Python identity", code.python_identity_sha256),
    ):
        _sha(value, label)
    release = PurePosixPath(code.release_root)
    expected_prefix = PurePosixPath("/opt/codex-oracle/releases")
    if not release.is_absolute() or expected_prefix not in release.parents:
        raise ExecutionContractError("release root is outside immutable release storage")
    _under(code.model_entrypoint, code.release_root, "model entrypoint")
    _under(code.python_executable, code.release_root, "Python executable")
    if type(code.closure_file_count) is not int or code.closure_file_count <= 0:
        raise ExecutionContractError("release closure is empty")
    for label, value in (
        ("root ownership", code.root_owned),
        ("immutable release", code.immutable),
        ("secret scan", code.secret_scan_passed),
    ):
        _exact_bool(value, True, label)


def _validate_resources(resources: ResourceEnvelope, now: datetime) -> None:
    observed = _utc(resources.observed_at_utc, "resource observation")
    ingestion = _utc(resources.next_guarded_ingestion_at_utc, "next ingestion")
    if observed > now or now - observed > timedelta(minutes=5):
        raise ExecutionContractError("resource observation is not fresh")
    for label, value in (
        ("available CPUs", resources.available_cpu_count),
        ("CPU quota", resources.cpu_quota_percent),
        ("available memory", resources.available_memory_bytes),
        ("memory maximum", resources.memory_max_bytes),
        ("available disk", resources.available_disk_bytes),
        ("minimum free disk", resources.minimum_free_disk_bytes),
        ("I/O weight", resources.io_weight),
        ("nice", resources.nice),
        ("maximum runtime", resources.expected_max_runtime_seconds),
    ):
        if type(value) is not int:
            raise ExecutionContractError(f"{label} must be an integer")
    if resources.available_cpu_count < 2 or not 1 <= resources.cpu_quota_percent <= 100:
        raise ExecutionContractError("CPU capacity or quota is unsafe")
    if resources.available_memory_bytes <= 0 or not 0 < resources.memory_max_bytes <= resources.available_memory_bytes * 4 // 5:
        raise ExecutionContractError("memory limit does not preserve headroom")
    if resources.minimum_free_disk_bytes <= 0 or resources.available_disk_bytes < resources.minimum_free_disk_bytes:
        raise ExecutionContractError("disk headroom is insufficient")
    if not 1 <= resources.io_weight <= 100 or resources.nice < 5:
        raise ExecutionContractError("research priority can contend with guarded ingestion")
    if resources.expected_max_runtime_seconds <= 0:
        raise ExecutionContractError("expected maximum runtime is invalid")
    _exact_bool(resources.guarded_ingestion_active, False, "guarded ingestion active state")
    _exact_bool(resources.ingestion_priority_reserved, True, "ingestion priority reservation")
    _exact_bool(resources.no_duplicate_writer_observed, True, "duplicate writer observation")
    completion_deadline = now + timedelta(seconds=resources.expected_max_runtime_seconds)
    if completion_deadline + timedelta(seconds=MIN_INGESTION_BUFFER_SECONDS) > ingestion:
        raise ExecutionContractError("fit cannot finish before the guarded-ingestion buffer")


def _validate_output(output: OutputBoundary, run_id: str) -> None:
    expected_root = f"/var/lib/codex-oracle/s08/{run_id}"
    if output.output_root != expected_root:
        raise ExecutionContractError("output root differs from exact run boundary")
    for path, label in (
        (output.checkpoint_path, "checkpoint path"),
        (output.terminal_manifest_path, "terminal manifest path"),
        (output.quarantine_root, "quarantine root"),
    ):
        _under(path, output.output_root, label)
    _exact_bool(output.append_only, True, "append-only output")
    _exact_bool(output.overwrite_allowed, False, "overwrite boundary")
    if output.database_write_scope != "NONE":
        raise ExecutionContractError("output boundary permits database writes")
    if not 1 <= output.max_checkpoint_age_seconds <= MAX_CHECKPOINT_AGE_SECONDS:
        raise ExecutionContractError("checkpoint freshness limit is unsafe")
    for label, value in (
        ("prediction persistence", output.persist_predictions),
        ("recommendations", output.create_recommendations),
        ("orders", output.create_orders),
        ("ETF outputs", output.create_etf_outputs),
        ("trading", output.activate_trading),
        ("snapshot lifecycle", output.validate_or_promote_snapshot),
    ):
        _exact_bool(value, False, f"output {label}")


def _validate_launch(
    launch: LaunchCommand,
    code: CodeClosure,
    proof: PreregistrationProof,
    output: OutputBoundary,
) -> None:
    if type(launch.argv) is not tuple or len(launch.argv) < 3 or any(type(item) is not str or not item for item in launch.argv):
        raise ExecutionContractError("launch argv must be an exact nonempty tuple")
    _exact_bool(launch.shell, False, "shell launch")
    expected_contract_path = f"/run/codex-oracle/s08/{proof.run_id}/execution-authorization.json"
    expected_argv = (
        code.python_executable,
        code.model_entrypoint,
        "--execution-contract", expected_contract_path,
        "--output-root", output.output_root,
        "--mode", "NEW_RUN",
    )
    if launch.argv != expected_argv:
        raise ExecutionContractError("launch command does not use the immutable closure")
    if launch.working_directory != code.release_root:
        raise ExecutionContractError("launch working directory differs from release root")
    if launch.environment_keys != ("PYTHONHASHSEED",):
        raise ExecutionContractError("launch environment differs from the exact credential-free allowlist")
    if not 1 <= launch.checkpoint_interval_seconds <= MAX_CHECKPOINT_AGE_SECONDS:
        raise ExecutionContractError("checkpoint interval is outside liveness bounds")
    _exact_bool(launch.resume_supported, True, "idempotent resume support")
    if launch.idempotency_key != canonical_sha256({
        "run_id": proof.run_id,
        "preregistration_raw_sha256": proof.raw_sha256,
        "code_git_commit": code.git_commit,
    }):
        raise ExecutionContractError("idempotency key differs from immutable run identity")


def build_execution_authorization(
    request: ExecutionRequest, *, created_at_utc: datetime,
) -> ExecutionAuthorizationArtifact:
    """Return a content-addressed authorization; never launch the fit itself."""
    if type(request) is not ExecutionRequest:
        raise ExecutionContractError("request must use the exact governed type")
    now = _utc(created_at_utc, "authorization creation")
    _validate_preregistration(request.preregistration, now)
    _validate_explicit_authorization(request.authorization, request.preregistration, now)
    _validate_code(request.code, request.preregistration)
    _validate_resources(request.resources, now)
    _validate_output(request.output, request.preregistration.run_id)
    _validate_launch(request.launch, request.code, request.preregistration, request.output)
    request_sha = canonical_sha256(request)
    artifact_payload = {
        "contract_id": CONTRACT_ID,
        "status": AuthorizationStatus.AUTHORIZED_NOT_STARTED,
        "request_sha256": request_sha,
        "created_at_utc": now,
        "launch_deadline_utc": request.authorization.launch_deadline_utc,
        "run_id": request.preregistration.run_id,
        "preregistration_raw_sha256": request.preregistration.raw_sha256,
        "checkpoint_identity_sha256": request.preregistration.checkpoint_identity_sha256,
        "authorization_record_sha256": request.authorization.authorization_record_sha256,
        "code_git_commit": request.code.git_commit,
        "release_manifest_sha256": request.code.release_manifest_sha256,
        "output_root": request.output.output_root,
        "launch_argv": request.launch.argv,
        "checkpoint_interval_seconds": request.launch.checkpoint_interval_seconds,
        "max_checkpoint_age_seconds": request.output.max_checkpoint_age_seconds,
        "model_fit_started": False,
        "database_writes_authorized": False,
        "downstream_authorized": False,
        "launch_performed": False,
    }
    artifact_id = f"s08-fit-auth-{canonical_sha256(artifact_payload)}"
    return ExecutionAuthorizationArtifact(artifact_id=artifact_id, **artifact_payload)


def audit_execution_authorization(
    request: ExecutionRequest,
    artifact: ExecutionAuthorizationArtifact,
    *, observed_at_utc: datetime,
) -> str:
    """Independently rebuild exact semantics and reject rehashed privilege drift."""
    if type(artifact) is not ExecutionAuthorizationArtifact:
        raise ExecutionContractError("artifact must use the exact governed type")
    observed = _utc(observed_at_utc, "audit observation")
    expected = build_execution_authorization(request, created_at_utc=artifact.created_at_utc)
    if observed < _utc(artifact.created_at_utc, "artifact creation") or observed > _utc(artifact.launch_deadline_utc, "launch deadline"):
        raise ExecutionContractError("authorization is not live at audit time")
    if canonical_json(artifact) != canonical_json(expected):
        raise ExecutionContractError("authorization semantics differ from an independent rebuild")
    return canonical_sha256(expected)


def audit_checkpoint_sequence(
    artifact: ExecutionAuthorizationArtifact,
    checkpoints: Sequence[CheckpointEvidence],
    *, observed_at_utc: datetime,
) -> CheckpointEvidence:
    """Validate an append-only sequence for the same exact run and contract."""
    if not checkpoints:
        raise ExecutionContractError("no checkpoint evidence exists")
    observed = _utc(observed_at_utc, "checkpoint audit observation")
    frozen = tuple(checkpoints)
    prior_time: datetime | None = None
    terminal_seen = False
    for index, checkpoint in enumerate(frozen, 1):
        if type(checkpoint) is not CheckpointEvidence or checkpoint.sequence != index:
            raise ExecutionContractError("checkpoint sequence is not contiguous")
        if type(checkpoint.state) is not CheckpointState:
            raise ExecutionContractError("checkpoint state is not governed")
        if checkpoint.contract_artifact_id != artifact.artifact_id or checkpoint.run_id != artifact.run_id:
            raise ExecutionContractError("checkpoint lineage differs from authorization")
        if checkpoint.code_git_commit != artifact.code_git_commit or checkpoint.preregistration_raw_sha256 != artifact.preregistration_raw_sha256:
            raise ExecutionContractError("checkpoint immutable identity differs")
        _sha(checkpoint.payload_sha256, "checkpoint payload")
        timestamp = _utc(checkpoint.observed_at_utc, "checkpoint timestamp")
        if timestamp < _utc(artifact.created_at_utc, "authorization creation") or timestamp > observed:
            raise ExecutionContractError("checkpoint chronology differs")
        if prior_time is not None and timestamp <= prior_time:
            raise ExecutionContractError("checkpoint timestamps are not strictly increasing")
        if terminal_seen:
            raise ExecutionContractError("checkpoint exists after terminal state")
        terminal_seen = checkpoint.state is not CheckpointState.RUNNING
        if (
            type(checkpoint.completed_targets) is not int
            or type(checkpoint.completed_folds) is not int
            or not 0 <= checkpoint.completed_targets <= EXPECTED_TARGET_COUNT
            or not 0 <= checkpoint.completed_folds <= EXPECTED_FOLD_COUNT
        ):
            raise ExecutionContractError("checkpoint progress exceeds frozen geometry")
        if type(checkpoint.divergences) is not int or checkpoint.divergences < 0:
            raise ExecutionContractError("checkpoint divergence count is invalid")
        _zero_downstream_counts(checkpoint.downstream_counts, "checkpoint downstream counts")
        prior_time = timestamp
    latest = frozen[-1]
    if latest.state is CheckpointState.RUNNING:
        age = (observed - _utc(latest.observed_at_utc, "latest checkpoint")).total_seconds()
        if age > artifact.max_checkpoint_age_seconds:
            raise ExecutionContractError("active checkpoint is stale; preserve evidence before repair")
    return latest


def audit_terminal_readback(
    artifact: ExecutionAuthorizationArtifact,
    preregistration: PreregistrationProof,
    terminal: TerminalReadback,
) -> TerminalAuditResult:
    """Accept success only on exact coverage; preserve scientific failure as typed."""
    if type(terminal) is not TerminalReadback:
        raise ExecutionContractError("terminal readback must use the exact governed type")
    if type(terminal.state) is not CheckpointState:
        raise ExecutionContractError("terminal state is not governed")
    if terminal.contract_artifact_id != artifact.artifact_id or terminal.run_id != artifact.run_id:
        raise ExecutionContractError("terminal readback lineage differs")
    _sha(terminal.terminal_manifest_raw_sha256, "terminal manifest")
    if _utc(terminal.observed_at_utc, "terminal observation") < _utc(
        artifact.created_at_utc, "authorization creation"
    ):
        raise ExecutionContractError("terminal readback predates authorization")
    if (
        terminal.snapshot_sha256 != preregistration.snapshot_sha256
        or terminal.universe_sha256 != preregistration.universe_sha256
        or terminal.model_code_git_commit != artifact.code_git_commit
        or terminal.model_config_sha256 != preregistration.model_config_sha256
        or terminal.sampler_sha256 != preregistration.sampler_sha256
    ):
        raise ExecutionContractError("terminal immutable lineage differs")
    if terminal.candidate_lags != EXPECTED_LAGS or terminal.candidate_depths != EXPECTED_DEPTHS:
        raise ExecutionContractError("terminal lag/depth coverage differs")
    if any(
        type(value) is not int or value < 0
        for value in (terminal.target_count, terminal.ticker_count, terminal.fold_count)
    ):
        raise ExecutionContractError("terminal coverage counts are invalid")
    _exact_bool(terminal.zero_temporal_overlap, True, "terminal temporal separation")
    _zero_downstream_counts(terminal.downstream_counts, "terminal downstream counts")
    if terminal.state is CheckpointState.TERMINAL_SUCCESS:
        if (terminal.target_count, terminal.ticker_count, terminal.fold_count) != (
            preregistration.target_count, preregistration.target_count, preregistration.fold_count,
        ):
            raise ExecutionContractError("successful terminal coverage is incomplete")
        _exact_bool(terminal.convergence_passed, True, "successful convergence")
        _exact_bool(terminal.partial_outputs_quarantined, False, "successful quarantine state")
        outcome = "ACCEPTED_RESEARCH_POSTERIOR"
    elif terminal.state is CheckpointState.TERMINAL_SCIENTIFIC_FAILURE:
        _exact_bool(terminal.convergence_passed, False, "scientific failure convergence")
        _exact_bool(terminal.partial_outputs_quarantined, True, "scientific failure quarantine")
        outcome = "PRESERVED_SCIENTIFIC_FAILURE_NO_DOWNSTREAM_USE"
    else:
        raise ExecutionContractError("terminal readback is not a terminal outcome")
    return TerminalAuditResult(
        passed=True,
        scientific_outcome=outcome,
        checked_targets=terminal.target_count,
        checked_folds=terminal.fold_count,
        terminal_manifest_raw_sha256=terminal.terminal_manifest_raw_sha256,
    )
