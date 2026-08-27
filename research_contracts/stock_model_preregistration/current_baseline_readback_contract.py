"""Pure evidence contract for perpetual SELECT-only baseline readbacks.

This module performs no I/O.  A separate authorized reader may supply a fresh
in-memory fixture describing its SELECT results.  This evaluator validates and
hashes that evidence for later preregistration-v3 integration.  It cannot
connect to a database, write data, fit a model, or authorize READY state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Any


CONTRACT_ID = "codex-oracle-current-baseline-readback-v1"
# The baseline deployment is v4, while its immutable semantic contract ID is
# the exact producer-auditor contract embedded in the evidence artifact.
SOURCE_AUDIT_CONTRACT_ID = "full-universe-common-simple-baselines-audit-v1"
MAX_PROOF_AGE = timedelta(minutes=5)
FULL_CALENDAR_LENGTH = 1_246
MODEL_CALENDAR_LENGTH = 416
MODEL_SLICE_START_INDEX = 830
EXPECTED_COVERAGE = (
    ("folds", 1_896),
    ("oos_observations", 56_880),
    ("tickers", 474),
)
EXPECTED_SIDE_EFFECTS = (
    ("bayesian_fits", 0),
    ("database_writes", 0),
    ("etf_outputs", 0),
    ("orders", 0),
    ("predictions", 0),
    ("recommendations", 0),
)
EXPECTED_DOWNSTREAM = (
    ("etf_prior_lineage", 0),
    ("execution_events", 0),
    ("execution_plan_approvals", 0),
    ("execution_plans", 0),
    ("model_runs", 0),
    ("model_scorecards", 0),
    ("stock_prediction_criterion_audits", 0),
    ("stock_prediction_decision_audits", 0),
)
REQUIRED_SELECT_QUERIES = (
    "SELECT_DOWNSTREAM_COUNTS",
    "SELECT_DOWNSTREAM_SCHEMA",
    "SELECT_SCREENING_RUNS",
    "SELECT_SESSION_CALENDAR",
    "SELECT_TICKER_UNIVERSE",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,160}")


class ReadbackContractError(ValueError):
    """Readback evidence is incomplete, stale, contradictory, or unsafe."""


class ReadbackStatus(StrEnum):
    VERIFIED_SELECT_ONLY = "VERIFIED_SELECT_ONLY"


@dataclass(frozen=True)
class NamedCount:
    name: str
    count: int


@dataclass(frozen=True)
class ImmutableV4AuditLineage:
    source_contract_id: str
    snapshot_id: str
    snapshot_sha256: str
    universe_id: str
    universe_sha256: str
    full_session_calendar_sha256: str
    model_session_dates_sha256: str
    baseline_manifest_sha256: str
    source_audit_artifact_sha256: str
    embedded_audit_evidence_sha256: str
    audit_envelope_sha256: str
    source_code_git_sha: str
    audit_completed_at_utc: datetime
    audit_observed_at_utc: datetime


@dataclass(frozen=True)
class CurrentReadbackEvidence:
    status: ReadbackStatus
    snapshot_id: str
    snapshot_sha256: str
    universe_id: str
    universe_sha256: str
    full_session_calendar_sha256: str
    model_session_dates_sha256: str
    baseline_manifest_sha256: str
    source_audit_artifact_sha256: str
    embedded_audit_evidence_sha256: str
    audit_envelope_sha256: str
    source_readback_artifact_sha256: str
    source_readback_embedded_evidence_sha256: str
    query_started_at_utc: datetime
    query_completed_at_utc: datetime
    source_readback_observed_at_utc: datetime
    select_query_ids: tuple[str, ...]
    coverage: tuple[NamedCount, ...]
    side_effects: tuple[NamedCount, ...]
    downstream_counts: tuple[NamedCount, ...]


@dataclass(frozen=True)
class ReadbackRequest:
    lineage: ImmutableV4AuditLineage
    full_session_calendar_dates: tuple[str, ...]
    model_session_dates: tuple[str, ...]
    evidence: CurrentReadbackEvidence


@dataclass(frozen=True)
class OperationalBoundary:
    fixture_only: bool = True
    evaluator_performed_io: bool = False
    database_writes: int = 0
    model_fit_performed: bool = False
    ready_state_available: bool = False
    model_fit_authorized: bool = False


@dataclass(frozen=True)
class VerifiedReadbackArtifact:
    artifact_id: str
    contract_id: str
    status: ReadbackStatus
    observed_at_utc: datetime
    request_sha256: str
    lineage: ImmutableV4AuditLineage
    full_session_calendar_dates: tuple[str, ...]
    model_session_dates: tuple[str, ...]
    evidence: CurrentReadbackEvidence
    boundary: OperationalBoundary


def canonical_sha(value: object) -> str:
    try:
        payload = json.dumps(
            _primitive(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReadbackContractError("canonical evidence contains an unsupported value") from exc
    return hashlib.sha256(payload).hexdigest()


def _primitive(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if type(value) is datetime:
        return _utc(value, "serialized timestamp").isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    return value


def _utc(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ReadbackContractError(f"{label} must be an exact timezone-aware datetime")
    if value.utcoffset() != timedelta(0):
        raise ReadbackContractError(f"{label} must be normalized to UTC")
    return value.astimezone(timezone.utc)


def _sha(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ReadbackContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise ReadbackContractError(f"{label} must be a stable identifier")
    return value


def _count_tuple(
    values: tuple[NamedCount, ...], expected: tuple[tuple[str, int], ...], label: str,
) -> tuple[NamedCount, ...]:
    if type(values) is not tuple:
        raise ReadbackContractError(f"{label} must be an immutable tuple")
    normalized: list[tuple[str, int]] = []
    for row in values:
        if type(row) is not NamedCount:
            raise ReadbackContractError(f"{label} rows must use the exact NamedCount type")
        name = _identifier(row.name, f"{label} name")
        if type(row.count) is not int:
            raise ReadbackContractError(f"{label}.{name} must be an integer")
        normalized.append((name, row.count))
    if tuple(sorted(normalized)) != expected:
        raise ReadbackContractError(f"{label} schema or zero-count evidence differs")
    return tuple(NamedCount(name, count) for name, count in expected)


def _calendar_dates(values: tuple[str, ...], expected_length: int, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) != expected_length:
        raise ReadbackContractError(f"{label} must contain exactly {expected_length} dates")
    parsed: list[date] = []
    for value in values:
        if type(value) is not str:
            raise ReadbackContractError(f"{label} entries must be ISO date strings")
        try:
            item = date.fromisoformat(value)
        except ValueError as exc:
            raise ReadbackContractError(f"{label} contains an invalid date") from exc
        if item.isoformat() != value:
            raise ReadbackContractError(f"{label} dates must use canonical ISO format")
        parsed.append(item)
    if tuple(sorted(set(parsed))) != tuple(parsed):
        raise ReadbackContractError(f"{label} dates must be increasing and unique")
    return values


def _freeze(request: ReadbackRequest) -> ReadbackRequest:
    if type(request) is not ReadbackRequest:
        raise ReadbackContractError("request must use the exact ReadbackRequest type")
    try:
        evidence = replace(
            request.evidence,
            select_query_ids=tuple(request.evidence.select_query_ids),
            coverage=tuple(request.evidence.coverage),
            side_effects=tuple(request.evidence.side_effects),
            downstream_counts=tuple(request.evidence.downstream_counts),
        )
        return replace(
            request,
            full_session_calendar_dates=tuple(request.full_session_calendar_dates),
            model_session_dates=tuple(request.model_session_dates),
            evidence=evidence,
        )
    except (AttributeError, TypeError) as exc:
        raise ReadbackContractError("request contains an invalid nested collection") from exc


def build_verified_readback(
    request: ReadbackRequest, *, observed_at_utc: datetime,
) -> VerifiedReadbackArtifact:
    """Validate one fresh in-memory readback and return immutable evidence."""
    request = _freeze(request)
    observed_at = _utc(observed_at_utc, "contract observation")
    lineage = request.lineage
    evidence = request.evidence
    if lineage.source_contract_id != SOURCE_AUDIT_CONTRACT_ID:
        raise ReadbackContractError("immutable source audit contract is not v4")
    for value, label in (
        (lineage.snapshot_id, "snapshot identifier"),
        (lineage.universe_id, "universe identifier"),
    ):
        _identifier(value, label)
    for value, label in (
        (lineage.snapshot_sha256, "snapshot digest"),
        (lineage.universe_sha256, "universe digest"),
        (lineage.full_session_calendar_sha256, "full calendar digest"),
        (lineage.model_session_dates_sha256, "model calendar digest"),
        (lineage.baseline_manifest_sha256, "baseline manifest digest"),
        (lineage.source_audit_artifact_sha256, "source audit file digest"),
        (lineage.embedded_audit_evidence_sha256, "source embedded evidence digest"),
        (lineage.audit_envelope_sha256, "audit envelope digest"),
    ):
        _sha(value, label)
    if type(lineage.source_code_git_sha) is not str or not _GIT_SHA.fullmatch(lineage.source_code_git_sha):
        raise ReadbackContractError("source code identity must be an exact Git SHA")
    audit_completed = _utc(lineage.audit_completed_at_utc, "audit completion")
    audit_observed = _utc(lineage.audit_observed_at_utc, "audit observation")
    if audit_observed < audit_completed:
        raise ReadbackContractError("immutable v4 audit chronology is contradictory")

    full_dates = _calendar_dates(request.full_session_calendar_dates, FULL_CALENDAR_LENGTH, "full calendar")
    model_dates = _calendar_dates(request.model_session_dates, MODEL_CALENDAR_LENGTH, "model calendar")
    if model_dates != full_dates[MODEL_SLICE_START_INDEX:]:
        raise ReadbackContractError("416-session model calendar is not the exact governed v4 slice")
    if canonical_sha(list(full_dates)) != lineage.full_session_calendar_sha256:
        raise ReadbackContractError("full calendar identity differs from immutable v4 lineage")
    if canonical_sha(list(model_dates)) != lineage.model_session_dates_sha256:
        raise ReadbackContractError("model calendar identity differs from immutable v4 lineage")

    if type(evidence.status) is not ReadbackStatus or evidence.status is not ReadbackStatus.VERIFIED_SELECT_ONLY:
        raise ReadbackContractError("readback status is not exact VERIFIED_SELECT_ONLY")
    identity_pairs = (
        (evidence.snapshot_id, lineage.snapshot_id),
        (evidence.snapshot_sha256, lineage.snapshot_sha256),
        (evidence.universe_id, lineage.universe_id),
        (evidence.universe_sha256, lineage.universe_sha256),
        (evidence.full_session_calendar_sha256, lineage.full_session_calendar_sha256),
        (evidence.model_session_dates_sha256, lineage.model_session_dates_sha256),
        (evidence.baseline_manifest_sha256, lineage.baseline_manifest_sha256),
        (evidence.source_audit_artifact_sha256, lineage.source_audit_artifact_sha256),
        (evidence.embedded_audit_evidence_sha256, lineage.embedded_audit_evidence_sha256),
        (evidence.audit_envelope_sha256, lineage.audit_envelope_sha256),
    )
    if any(actual != expected for actual, expected in identity_pairs):
        raise ReadbackContractError("fresh readback does not preserve immutable v4 source identities")
    _sha(evidence.source_readback_artifact_sha256, "readback file digest")
    _sha(evidence.source_readback_embedded_evidence_sha256, "readback embedded evidence digest")
    all_evidence_hashes = {
        lineage.source_audit_artifact_sha256,
        lineage.embedded_audit_evidence_sha256,
        lineage.audit_envelope_sha256,
        evidence.source_readback_artifact_sha256,
        evidence.source_readback_embedded_evidence_sha256,
    }
    if len(all_evidence_hashes) != 5:
        raise ReadbackContractError("raw and embedded audit/readback identities are conflated")
    query_started = _utc(evidence.query_started_at_utc, "query start")
    query_completed = _utc(evidence.query_completed_at_utc, "query completion")
    source_observed = _utc(evidence.source_readback_observed_at_utc, "source readback observation")
    if not audit_observed <= query_started <= query_completed == source_observed <= observed_at:
        raise ReadbackContractError("readback chronology is contradictory or retimestamped")
    if observed_at - source_observed > MAX_PROOF_AGE:
        raise ReadbackContractError("current readback evidence is stale")
    if tuple(sorted(evidence.select_query_ids)) != REQUIRED_SELECT_QUERIES:
        raise ReadbackContractError("readback did not execute the exact SELECT-only query set")
    if any(type(query_id) is not str or not query_id.startswith("SELECT_") for query_id in evidence.select_query_ids):
        raise ReadbackContractError("non-SELECT evidence is prohibited")
    coverage = _count_tuple(evidence.coverage, EXPECTED_COVERAGE, "coverage")
    side_effects = _count_tuple(evidence.side_effects, EXPECTED_SIDE_EFFECTS, "side effects")
    downstream = _count_tuple(evidence.downstream_counts, EXPECTED_DOWNSTREAM, "downstream counts")
    evidence = replace(
        evidence,
        select_query_ids=REQUIRED_SELECT_QUERIES,
        coverage=coverage,
        side_effects=side_effects,
        downstream_counts=downstream,
    )
    request = replace(request, evidence=evidence)
    request_sha = canonical_sha(request)
    payload = {
        "contract_id": CONTRACT_ID,
        "status": ReadbackStatus.VERIFIED_SELECT_ONLY,
        "observed_at_utc": observed_at,
        "request_sha256": request_sha,
        "lineage": lineage,
        "full_session_calendar_dates": full_dates,
        "model_session_dates": model_dates,
        "evidence": evidence,
        "boundary": OperationalBoundary(),
    }
    return VerifiedReadbackArtifact(
        artifact_id="current_baseline_readback_" + canonical_sha(payload),
        contract_id=CONTRACT_ID,
        status=ReadbackStatus.VERIFIED_SELECT_ONLY,
        observed_at_utc=observed_at,
        request_sha256=request_sha,
        lineage=lineage,
        full_session_calendar_dates=full_dates,
        model_session_dates=model_dates,
        evidence=evidence,
        boundary=OperationalBoundary(),
    )


def audit_verified_readback(
    request: ReadbackRequest,
    artifact: VerifiedReadbackArtifact,
    *,
    observed_at_utc: datetime,
) -> None:
    """Rebuild the artifact and reject forged boundaries or outer rehashes."""
    if type(artifact) is not VerifiedReadbackArtifact:
        raise ReadbackContractError("artifact must use the exact verified type")
    if artifact.boundary != OperationalBoundary():
        raise ReadbackContractError("operational boundary was weakened")
    expected = build_verified_readback(request, observed_at_utc=observed_at_utc)
    if canonical_sha(artifact) != canonical_sha(expected):
        raise ReadbackContractError("artifact semantics differ from an independent rebuild")
