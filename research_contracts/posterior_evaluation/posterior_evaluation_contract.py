"""Deterministic, fixture-only posterior evaluation and evidence contract.

This module is intentionally pure.  It accepts already-produced in-memory
research fixtures, validates their lineage and temporal contract, evaluates
them, and returns immutable review artifacts.  It does not read or write files,
contact a database or network service, fit a model, choose a security, stage an
order, or authorize any operational action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from enum import StrEnum
import hashlib
import json
from math import isfinite, log, sqrt
import re
from typing import Any


IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_SAFETY_GATE_REASONS = {
    "SNAPSHOT_VALIDATED": "SNAPSHOT_NOT_VALIDATED",
    "UNIVERSE_APPROVED": "UNIVERSE_NOT_APPROVED",
    "SOURCE_DATE_ALIGNED": "SOURCE_DATE_MISMATCH",
    "MODEL_RUN_COMPLETED": "MODEL_RUN_NOT_COMPLETED",
    "SAMPLER_QA_PASSED": "SAMPLER_QA_FAILED",
    "RESEARCH_PROMOTION_APPROVED": "RESEARCH_PROMOTION_NOT_APPROVED",
    "NOT_QUARANTINED": "ACTIVE_EVIDENCE_QUARANTINE",
}
REQUIRED_SAFETY_GATES = tuple(REQUIRED_SAFETY_GATE_REASONS)
OLD_AG_DECISIONS = frozenset({"BUY", "SELL", "HOLD"})
CODEX_DECISIONS = frozenset({"BUY", "SELL", "HOLD", "NO_TRADE"})


class ContractError(ValueError):
    """Fixture evidence violates the frozen research contract."""


class ArtifactStatus(StrEnum):
    ABSENT_POSTERIOR_BLOCKED = "ABSENT_POSTERIOR_BLOCKED"
    DIAGNOSTIC_BLOCKED = "DIAGNOSTIC_BLOCKED"
    PROMOTION_BLOCKED = "PROMOTION_BLOCKED"


class RecordedDecision(StrEnum):
    """A recorded comparison label, never an operational instruction."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class ArtifactLineage:
    contract_version: str
    model_run_id: str
    research_dataset_id: str
    source_snapshot_id: str
    source_snapshot_sha256: str
    universe_id: str
    universe_sha256: str
    code_version: str
    configuration_sha256: str
    preregistration_id: str
    preregistration_sha256: str
    preregistration_observed_at_utc: datetime
    baseline_audit_id: str
    baseline_audit_sha256: str
    baseline_audit_observed_at_utc: datetime
    session_calendar_id: str
    session_calendar_sha256: str
    hierarchy_registry_id: str
    hierarchy_registry_sha256: str
    sampler_name: str
    seed_policy: str
    observed_at_utc: datetime


@dataclass(frozen=True)
class SessionCalendar:
    calendar_id: str
    sessions: tuple[date, ...]
    session_available_at_utc: tuple[datetime, ...]


@dataclass(frozen=True)
class HierarchyEntry:
    ticker: str
    persona: str
    hierarchy_path: tuple[str, ...]


@dataclass(frozen=True)
class HierarchyRegistry:
    registry_id: str
    observed_at_utc: datetime
    entries: tuple[HierarchyEntry, ...]


@dataclass(frozen=True)
class VerifiedSafetyEvidence:
    snapshot_validation_id: str
    validated_snapshot_sha256: str
    snapshot_validated_at_utc: datetime
    universe_approval_id: str
    approved_universe_sha256: str
    universe_approved_at_utc: datetime
    model_completion_id: str
    completed_model_run_id: str
    model_completed_at_utc: datetime
    quarantine_registry_id: str
    quarantine_registry_sha256: str
    quarantine_registry_observed_at_utc: datetime
    quarantined_prediction_ids: tuple[str, ...]


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: str
    train_start_index: int
    train_end_index: int
    test_start_index: int
    test_end_index: int
    training_sessions: int
    purge_sessions: int
    test_sessions: int
    observed_temporal_overlap_sessions: int


@dataclass(frozen=True)
class ParameterDiagnostic:
    parameter: str
    sampled_chains: int
    draws_per_chain: int
    r_hat: float
    ess_bulk: float
    ess_tail: float


@dataclass(frozen=True)
class ChainDiagnostic:
    chain_id: int
    posterior_draws: int
    tuning_draws: int
    divergences: int
    bfmi: float


@dataclass(frozen=True)
class ConvergencePolicy:
    maximum_r_hat: float = 1.01
    minimum_ess_bulk: float = 400.0
    minimum_ess_tail: float = 400.0
    maximum_divergences: int = 0
    minimum_bfmi: float = 0.30
    minimum_chains: int = 4


@dataclass(frozen=True)
class SamplerPolicy:
    sampler_name: str
    expected_chains: int
    posterior_draws_per_chain: int
    tuning_draws_per_chain: int
    required_parameters: tuple[str, ...]
    convergence: ConvergencePolicy = ConvergencePolicy()


@dataclass(frozen=True)
class EvaluationPolicy:
    calibration_bins: int
    probability_clip: float
    round_trip_cost_bps: float
    one_way_slippage_bps: float
    charge_terminal_close: bool
    expected_predictions: int
    expected_folds: int
    prediction_cutoff_hour_utc: int
    prediction_cutoff_minute_utc: int
    sampler: SamplerPolicy


@dataclass(frozen=True)
class PosteriorOutcome:
    prediction_id: str
    fold_id: str
    ticker: str
    persona: str
    hierarchy_path: tuple[str, ...]
    prediction_date: date
    source_session_date: date
    posterior_available_at_utc: datetime
    prediction_cutoff_at_utc: datetime
    probability_up_mean: float
    probability_up_std: float
    probability_up_q05: float
    probability_up_q95: float
    expected_return_pp: float
    expected_return_std_pp: float
    expected_risk_pp: float
    realized_return_pp: float
    research_signed_allocation: float


@dataclass(frozen=True)
class HardSafetyGate:
    gate_id: str
    passed: bool
    reason_code: str


@dataclass(frozen=True)
class SizingAdjustment:
    adjustment_id: str
    multiplier: float
    reason: str


@dataclass(frozen=True)
class RecordedDecisionEvidence:
    prediction_id: str
    old_ag_decision: RecordedDecision
    old_ag_reasons: tuple[str, ...]
    proposed_codex_decision: RecordedDecision
    proposed_codex_reasons: tuple[str, ...]
    sizing_adjustments: tuple[SizingAdjustment, ...]


@dataclass(frozen=True)
class RawBayesianOutput:
    probability_up_mean: float
    probability_up_std: float
    probability_up_q05: float
    probability_up_q95: float
    expected_return_pp: float
    expected_return_std_pp: float
    expected_risk_pp: float


@dataclass(frozen=True)
class PredictionEvidenceRow:
    prediction_id: str
    model_run_id: str
    fold_id: str
    ticker: str
    persona: str
    prediction_date: date
    source_session_date: date
    posterior_available_at_utc: datetime
    prediction_cutoff_at_utc: datetime
    raw_bayesian_output: RawBayesianOutput
    old_ag_decision: RecordedDecision
    old_ag_reasons: tuple[str, ...]
    proposed_codex_decision: RecordedDecision
    proposed_codex_reasons: tuple[str, ...]
    hard_safety_gates: tuple[HardSafetyGate, ...]
    sizing_adjustments: tuple[SizingAdjustment, ...]
    review_only: bool
    operationally_eligible: bool


@dataclass(frozen=True)
class CalibrationMetrics:
    observations: int
    accuracy: float
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    expected_return_mae_pp: float
    expected_return_rmse_pp: float


@dataclass(frozen=True)
class CostDrawdownMetrics:
    sessions: int
    gross_turnover: float
    terminal_close_turnover: float
    transaction_cost_pp_sum: float
    gross_total_return_fraction: float
    net_total_return_fraction: float
    max_drawdown_fraction: float


@dataclass(frozen=True)
class ConvergenceSummary:
    chains: int
    parameters: int
    posterior_draws: int
    tuning_draws: int
    divergences: int
    maximum_r_hat: float
    minimum_ess_bulk: float
    minimum_ess_tail: float
    minimum_bfmi: float
    passed: bool
    failure_codes: tuple[str, ...]


@dataclass(frozen=True)
class OperationalBoundary:
    fixture_only: bool = True
    database_accessed: bool = False
    network_accessed: bool = False
    model_fit_performed: bool = False
    recommendation_created: bool = False
    order_created: bool = False
    etf_output_created: bool = False
    promotion_authorized: bool = False


@dataclass(frozen=True)
class PosteriorEvaluationRequest:
    lineage: ArtifactLineage
    policy: EvaluationPolicy
    session_calendar: SessionCalendar
    hierarchy_registry: HierarchyRegistry
    safety_evidence: VerifiedSafetyEvidence
    folds: tuple[WalkForwardFold, ...]
    parameter_diagnostics: tuple[ParameterDiagnostic, ...]
    chain_diagnostics: tuple[ChainDiagnostic, ...]
    outcomes: tuple[PosteriorOutcome, ...]
    recorded_decisions: tuple[RecordedDecisionEvidence, ...]


@dataclass(frozen=True)
class PosteriorEvaluationArtifact:
    artifact_id: str
    request_sha256: str
    artifact_type: str
    status: ArtifactStatus
    blocker_codes: tuple[str, ...]
    lineage: ArtifactLineage
    policy: EvaluationPolicy
    session_calendar: SessionCalendar
    hierarchy_registry: HierarchyRegistry
    safety_evidence: VerifiedSafetyEvidence
    folds: tuple[WalkForwardFold, ...]
    fold_count: int
    prediction_count: int
    convergence: ConvergenceSummary | None
    calibration: CalibrationMetrics | None
    cost_and_drawdown: CostDrawdownMetrics | None
    prediction_evidence_rows: tuple[PredictionEvidenceRow, ...]
    boundary: OperationalBoundary


@dataclass(frozen=True)
class SemanticAuditResult:
    passed: bool
    request_sha256: str
    artifact_sha256: str
    checked_predictions: int
    checked_folds: int


def _identifier(value: str, label: str) -> str:
    if type(value) is not str:
        raise ContractError(f"{label} must be an actual string identifier.")
    normalized = value.strip()
    if normalized != value or not IDENTIFIER.fullmatch(normalized):
        raise ContractError(f"{label} is invalid.")
    return normalized


def _finite(value: float, label: str) -> float:
    if type(value) is not float:
        raise ContractError(f"{label} must be an exact finite float; coercion is forbidden.")
    if not isfinite(value):
        raise ContractError(f"{label} must be an exact finite float.")
    return value


def _aware_utc(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{label} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _integer(value: int, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractError(f"{label} must be an integer greater than or equal to {minimum}.")
    return value


def _validate_lineage(lineage: ArtifactLineage) -> None:
    for value, label in (
        (lineage.contract_version, "Contract version"),
        (lineage.model_run_id, "Model run identifier"),
        (lineage.research_dataset_id, "Research dataset identifier"),
        (lineage.source_snapshot_id, "Source snapshot identifier"),
        (lineage.universe_id, "Universe identifier"),
        (lineage.preregistration_id, "Preregistration identifier"),
        (lineage.baseline_audit_id, "Baseline audit identifier"),
        (lineage.session_calendar_id, "Session calendar identifier"),
        (lineage.hierarchy_registry_id, "Hierarchy registry identifier"),
        (lineage.sampler_name, "Sampler name"),
        (lineage.seed_policy, "Seed policy"),
    ):
        _identifier(value, label)
    for value, label in (
        (lineage.source_snapshot_sha256, "Source snapshot digest"),
        (lineage.universe_sha256, "Universe digest"),
        (lineage.configuration_sha256, "Configuration digest"),
        (lineage.preregistration_sha256, "Preregistration digest"),
        (lineage.baseline_audit_sha256, "Baseline audit digest"),
        (lineage.session_calendar_sha256, "Session calendar digest"),
        (lineage.hierarchy_registry_sha256, "Hierarchy registry digest"),
    ):
        if type(value) is not str or not SHA256.fullmatch(value):
            raise ContractError(f"{label} must be a lowercase SHA-256 digest.")
    if type(lineage.code_version) is not str or not GIT_SHA.fullmatch(lineage.code_version):
        raise ContractError("Code version must be an exact lowercase 40-character Git SHA.")
    _aware_utc(lineage.preregistration_observed_at_utc, "Preregistration observation timestamp")
    _aware_utc(lineage.baseline_audit_observed_at_utc, "Baseline audit observation timestamp")
    _aware_utc(lineage.observed_at_utc, "Lineage observation timestamp")


def _validate_policy(policy: EvaluationPolicy) -> None:
    if _integer(policy.calibration_bins, "Calibration-bin count", minimum=2) < 2:
        raise ContractError("Calibration requires at least two bins.")
    if not 0.0 < _finite(policy.probability_clip, "Probability clip") < 0.5:
        raise ContractError("Probability clip must lie strictly between zero and one half.")
    if _finite(policy.round_trip_cost_bps, "Round-trip cost") < 0.0:
        raise ContractError("Round-trip cost cannot be negative.")
    if _finite(policy.one_way_slippage_bps, "One-way slippage") < 0.0:
        raise ContractError("One-way slippage cannot be negative.")
    if policy.charge_terminal_close is not True:
        raise ContractError("Complete cost evidence requires an explicit terminal close charge.")
    _integer(policy.expected_predictions, "Expected prediction denominator", minimum=1)
    _integer(policy.expected_folds, "Expected fold denominator", minimum=1)
    cutoff_hour = _integer(policy.prediction_cutoff_hour_utc, "Prediction cutoff hour", minimum=0)
    cutoff_minute = _integer(policy.prediction_cutoff_minute_utc, "Prediction cutoff minute", minimum=0)
    if cutoff_hour > 23 or cutoff_minute > 59:
        raise ContractError("Governed UTC prediction cutoff time is invalid.")
    sampler = policy.sampler
    _identifier(sampler.sampler_name, "Sampler policy name")
    _integer(sampler.expected_chains, "Expected sampler chains", minimum=2)
    _integer(sampler.posterior_draws_per_chain, "Expected posterior draws", minimum=1)
    _integer(sampler.tuning_draws_per_chain, "Expected tuning draws", minimum=0)
    if not sampler.required_parameters:
        raise ContractError("Sampler policy requires an exact parameter set.")
    parameters = tuple(_identifier(value, "Required sampler parameter") for value in sampler.required_parameters)
    if len(parameters) != len(set(parameters)):
        raise ContractError("Required sampler parameters must be unique.")
    convergence = sampler.convergence
    if not 1.0 <= _finite(convergence.maximum_r_hat, "Maximum R-hat") <= 1.20:
        raise ContractError("Maximum R-hat threshold is outside the governed range.")
    if _finite(convergence.minimum_ess_bulk, "Minimum bulk ESS") <= 0 or _finite(convergence.minimum_ess_tail, "Minimum tail ESS") <= 0:
        raise ContractError("ESS thresholds must be positive.")
    _integer(convergence.maximum_divergences, "Maximum divergence count", minimum=0)
    _integer(convergence.minimum_chains, "Minimum convergence chains", minimum=2)
    if convergence.minimum_chains != sampler.expected_chains:
        raise ContractError("Convergence chain threshold must equal the exact sampler chain count.")
    if not 0.0 < _finite(convergence.minimum_bfmi, "Minimum BFMI") <= 1.0:
        raise ContractError("Minimum BFMI must lie in (0, 1].")


def session_calendar_sha256(calendar: SessionCalendar) -> str:
    """Return the digest of the exact ordered session sequence and identity."""
    return hashlib.sha256(canonical_json({
        "calendar_id": calendar.calendar_id,
        "sessions": calendar.sessions,
        "session_available_at_utc": calendar.session_available_at_utc,
    }).encode("utf-8")).hexdigest()


def _validate_session_calendar(calendar: SessionCalendar, lineage: ArtifactLineage) -> dict[date, int]:
    calendar_id = _identifier(calendar.calendar_id, "Session calendar identifier")
    if calendar_id != lineage.session_calendar_id:
        raise ContractError("Session calendar identity does not match lineage.")
    if not calendar.sessions:
        raise ContractError("Session calendar cannot be empty.")
    if len(calendar.session_available_at_utc) != len(calendar.sessions):
        raise ContractError("Session calendar dates and availability timestamps must have equal cardinality.")
    if any(type(value) is not date for value in calendar.sessions):
        raise ContractError("Session calendar entries must be exact dates.")
    if tuple(sorted(set(calendar.sessions))) != calendar.sessions:
        raise ContractError("Session calendar must be strictly increasing and unique.")
    normalized_times = tuple(
        _aware_utc(value, "Session availability timestamp")
        for value in calendar.session_available_at_utc
    )
    if normalized_times != calendar.session_available_at_utc:
        raise ContractError("Session availability timestamps must be normalized to UTC.")
    if any(timestamp.date() != session for session, timestamp in zip(calendar.sessions, normalized_times)):
        raise ContractError("Each session availability timestamp must bind to its session date.")
    if tuple(sorted(normalized_times)) != normalized_times:
        raise ContractError("Session availability timestamps must be strictly increasing.")
    if session_calendar_sha256(calendar) != lineage.session_calendar_sha256:
        raise ContractError("Session calendar digest does not match lineage.")
    return {session: index for index, session in enumerate(calendar.sessions)}


def hierarchy_registry_sha256(registry: HierarchyRegistry) -> str:
    """Return the digest of the normalized ticker/persona hierarchy registry."""
    return hashlib.sha256(canonical_json({
        "registry_id": registry.registry_id,
        "observed_at_utc": registry.observed_at_utc,
        "entries": sorted(registry.entries, key=lambda row: (row.ticker, row.persona)),
    }).encode("utf-8")).hexdigest()


def _validate_hierarchy_registry(
    registry: HierarchyRegistry,
    lineage: ArtifactLineage,
) -> dict[tuple[str, str], tuple[str, ...]]:
    registry_id = _identifier(registry.registry_id, "Hierarchy registry identifier")
    if registry_id != lineage.hierarchy_registry_id:
        raise ContractError("Hierarchy registry identity does not match lineage.")
    _aware_utc(registry.observed_at_utc, "Hierarchy registry observation timestamp")
    if not registry.entries:
        raise ContractError("Hierarchy registry cannot be empty.")
    entries: dict[tuple[str, str], tuple[str, ...]] = {}
    for entry in registry.entries:
        if type(entry.ticker) is not str or not TICKER.fullmatch(entry.ticker):
            raise ContractError("Hierarchy registry ticker must be a normalized string.")
        persona = _identifier(entry.persona, "Hierarchy registry persona")
        if not entry.hierarchy_path or any(
            type(item) is not str or not IDENTIFIER.fullmatch(item)
            for item in entry.hierarchy_path
        ):
            raise ContractError("Hierarchy registry path is invalid.")
        key = (entry.ticker, persona)
        if key in entries:
            raise ContractError("Hierarchy registry ticker/persona keys must be unique.")
        entries[key] = entry.hierarchy_path
    if hierarchy_registry_sha256(registry) != lineage.hierarchy_registry_sha256:
        raise ContractError("Hierarchy registry digest does not match lineage.")
    return entries


def quarantine_registry_sha256(evidence: VerifiedSafetyEvidence) -> str:
    """Return the digest of the immutable quarantined-prediction registry."""
    return hashlib.sha256(canonical_json({
        "quarantine_registry_id": evidence.quarantine_registry_id,
        "quarantine_registry_observed_at_utc": evidence.quarantine_registry_observed_at_utc,
        "quarantined_prediction_ids": sorted(evidence.quarantined_prediction_ids),
    }).encode("utf-8")).hexdigest()


def _validate_safety_evidence(evidence: VerifiedSafetyEvidence) -> None:
    for value, label in (
        (evidence.snapshot_validation_id, "Snapshot validation identifier"),
        (evidence.universe_approval_id, "Universe approval identifier"),
        (evidence.model_completion_id, "Model completion identifier"),
        (evidence.completed_model_run_id, "Completed model run identifier"),
        (evidence.quarantine_registry_id, "Quarantine registry identifier"),
    ):
        _identifier(value, label)
    for value, label in (
        (evidence.validated_snapshot_sha256, "Validated snapshot digest"),
        (evidence.approved_universe_sha256, "Approved universe digest"),
        (evidence.quarantine_registry_sha256, "Quarantine registry digest"),
    ):
        if type(value) is not str or not SHA256.fullmatch(value):
            raise ContractError(f"{label} must be a lowercase SHA-256 digest.")
    for prediction_id in evidence.quarantined_prediction_ids:
        _identifier(prediction_id, "Quarantined prediction identifier")
    _aware_utc(evidence.snapshot_validated_at_utc, "Snapshot validation timestamp")
    _aware_utc(evidence.universe_approved_at_utc, "Universe approval timestamp")
    _aware_utc(evidence.model_completed_at_utc, "Model completion timestamp")
    _aware_utc(evidence.quarantine_registry_observed_at_utc, "Quarantine registry observation timestamp")
    if len(evidence.quarantined_prediction_ids) != len(set(evidence.quarantined_prediction_ids)):
        raise ContractError("Quarantined prediction identifiers must be unique.")
    if quarantine_registry_sha256(evidence) != evidence.quarantine_registry_sha256:
        raise ContractError("Quarantine registry digest does not match its frozen members.")


def _validate_folds(
    folds: tuple[WalkForwardFold, ...],
    policy: EvaluationPolicy,
    calendar: SessionCalendar,
) -> dict[str, WalkForwardFold]:
    if len(folds) != policy.expected_folds:
        raise ContractError("Walk-forward fold count does not match its frozen denominator.")
    by_id: dict[str, WalkForwardFold] = {}
    validated_ids: list[str] = []
    for fold in folds:
        validated_ids.append(_identifier(fold.fold_id, "Fold identifier"))
        _integer(fold.test_start_index, "Test start index", minimum=0)
    if len(validated_ids) != len(set(validated_ids)):
        raise ContractError("Walk-forward fold identifiers must be unique.")
    ordered = sorted(folds, key=lambda fold: fold.test_start_index)
    prior_test_end_index: int | None = None
    calendar_last_index = len(calendar.sessions) - 1
    for fold in ordered:
        fold_id = fold.fold_id
        for value, label in (
            (fold.train_start_index, "Training start index"),
            (fold.train_end_index, "Training end index"),
            (fold.test_start_index, "Test start index"),
            (fold.test_end_index, "Test end index"),
            (fold.training_sessions, "Declared training sessions"),
            (fold.purge_sessions, "Declared purge sessions"),
            (fold.test_sessions, "Declared test sessions"),
            (fold.observed_temporal_overlap_sessions, "Declared overlap sessions"),
        ):
            _integer(value, label, minimum=0)
        if not 0 <= fold.train_start_index <= fold.train_end_index < fold.test_start_index <= fold.test_end_index <= calendar_last_index:
            raise ContractError("Walk-forward calendar-index chronology is invalid.")
        actual_training_sessions = fold.train_end_index - fold.train_start_index + 1
        actual_purge_sessions = fold.test_start_index - fold.train_end_index - 1
        actual_test_sessions = fold.test_end_index - fold.test_start_index + 1
        actual_overlap_sessions = len(
            set(range(fold.train_start_index, fold.train_end_index + 1))
            & set(range(fold.test_start_index, fold.test_end_index + 1))
        )
        if (
            fold.training_sessions != actual_training_sessions
            or fold.purge_sessions != actual_purge_sessions
            or fold.test_sessions != actual_test_sessions
            or fold.observed_temporal_overlap_sessions != actual_overlap_sessions
        ):
            raise ContractError("Declared walk-forward geometry does not match immutable calendar indices.")
        if actual_training_sessions < 126:
            raise ContractError("Walk-forward training evidence weakens the 126-session safeguard.")
        if actual_purge_sessions < 7:
            raise ContractError("Walk-forward purge evidence weakens the seven-session lag safeguard.")
        if actual_test_sessions < 1:
            raise ContractError("Walk-forward test-session count must be positive.")
        if actual_overlap_sessions != 0:
            raise ContractError("Walk-forward evidence contains temporal overlap.")
        if prior_test_end_index is not None and fold.test_start_index <= prior_test_end_index:
            raise ContractError("Walk-forward outer test folds overlap.")
        prior_test_end_index = fold.test_end_index
        by_id[fold_id] = fold
    return by_id


def _validate_diagnostics(
    parameters: tuple[ParameterDiagnostic, ...],
    chains: tuple[ChainDiagnostic, ...],
    sampler: SamplerPolicy,
) -> None:
    if not parameters or not chains:
        raise ContractError("Posterior evidence requires parameter and chain diagnostics.")
    parameter_ids: set[str] = set()
    for row in parameters:
        parameter = _identifier(row.parameter, "Diagnostic parameter")
        if parameter in parameter_ids:
            raise ContractError("Diagnostic parameters must be unique.")
        parameter_ids.add(parameter)
        if row.sampled_chains != sampler.expected_chains:
            raise ContractError("Parameter diagnostic chain dimension does not match sampler policy.")
        if row.draws_per_chain != sampler.posterior_draws_per_chain:
            raise ContractError("Parameter diagnostic draw dimension does not match sampler policy.")
        _integer(row.sampled_chains, "Parameter diagnostic chains", minimum=2)
        _integer(row.draws_per_chain, "Parameter diagnostic draws", minimum=1)
        if _finite(row.r_hat, "R-hat") < 1.0:
            raise ContractError("R-hat cannot be below one.")
        if _finite(row.ess_bulk, "Bulk ESS") <= 0 or _finite(row.ess_tail, "Tail ESS") <= 0:
            raise ContractError("Effective sample sizes must be positive.")
    chain_ids: set[int] = set()
    for row in chains:
        if type(row.chain_id) is not int or row.chain_id < 0 or row.chain_id in chain_ids:
            raise ContractError("Chain identifiers must be unique non-negative integers.")
        chain_ids.add(row.chain_id)
        _integer(row.posterior_draws, "Posterior draws", minimum=1)
        _integer(row.tuning_draws, "Tuning draws", minimum=0)
        _integer(row.divergences, "Divergence count", minimum=0)
        if row.posterior_draws != sampler.posterior_draws_per_chain:
            raise ContractError("Actual posterior draws do not match exact sampler policy.")
        if row.tuning_draws != sampler.tuning_draws_per_chain:
            raise ContractError("Actual tuning draws do not match exact sampler policy.")
        if not 0.0 < _finite(row.bfmi, "BFMI") <= 2.0:
            raise ContractError("BFMI must lie in (0, 2].")
    if parameter_ids != set(sampler.required_parameters):
        raise ContractError("Actual parameter diagnostics do not match the exact sampler parameter set.")
    if chain_ids != set(range(sampler.expected_chains)):
        raise ContractError("Actual chain identifiers do not match the exact sampler dimensions.")


def _validate_outcomes(
    outcomes: tuple[PosteriorOutcome, ...],
    folds: dict[str, WalkForwardFold],
    policy: EvaluationPolicy,
    session_indices: dict[date, int],
    calendar: SessionCalendar,
    hierarchy: dict[tuple[str, str], tuple[str, ...]],
) -> tuple[date, ...]:
    if len(outcomes) != policy.expected_predictions:
        raise ContractError("Posterior prediction count does not match its frozen denominator.")
    seen: set[str] = set()
    seen_cells: set[tuple[str, str, date]] = set()
    leaves: set[tuple[str, str]] = set()
    leaf_dates: dict[tuple[str, str], set[date]] = {}
    dates: set[date] = set()
    folds_with_outcomes: set[str] = set()
    for row in outcomes:
        prediction_id = _identifier(row.prediction_id, "Prediction identifier")
        if prediction_id in seen:
            raise ContractError("Posterior prediction identifiers must be unique.")
        seen.add(prediction_id)
        if row.fold_id not in folds:
            raise ContractError("Posterior outcome references an unknown walk-forward fold.")
        folds_with_outcomes.add(row.fold_id)
        if type(row.ticker) is not str:
            raise ContractError("Posterior ticker must be an actual string identifier.")
        ticker = row.ticker
        if not TICKER.fullmatch(ticker):
            raise ContractError("Posterior ticker must be normalized and valid.")
        persona = _identifier(row.persona, "Persona")
        if not row.hierarchy_path or any(
            type(item) is not str or not IDENTIFIER.fullmatch(item)
            for item in row.hierarchy_path
        ):
            raise ContractError("Posterior hierarchy path is invalid.")
        hierarchy_key = (ticker, persona)
        if hierarchy_key not in hierarchy or row.hierarchy_path != hierarchy[hierarchy_key]:
            raise ContractError("Posterior hierarchy path does not match the frozen ticker/persona registry.")
        fold = folds[row.fold_id]
        if type(row.prediction_date) is not date or type(row.source_session_date) is not date:
            raise ContractError("Prediction and source sessions must be exact dates.")
        if row.prediction_date not in session_indices or row.source_session_date not in session_indices:
            raise ContractError("Prediction and source sessions must exist in the immutable calendar.")
        prediction_index = session_indices[row.prediction_date]
        source_index = session_indices[row.source_session_date]
        if not fold.test_start_index <= prediction_index <= fold.test_end_index:
            raise ContractError("Prediction date lies outside its outer test fold.")
        if source_index >= prediction_index:
            raise ContractError("Posterior source session must precede prediction date.")
        available_at = _aware_utc(row.posterior_available_at_utc, "Posterior available-at timestamp")
        cutoff_at = _aware_utc(row.prediction_cutoff_at_utc, "Prediction cutoff timestamp")
        governed_cutoff = datetime(
            row.prediction_date.year,
            row.prediction_date.month,
            row.prediction_date.day,
            policy.prediction_cutoff_hour_utc,
            policy.prediction_cutoff_minute_utc,
            tzinfo=timezone.utc,
        )
        if cutoff_at != governed_cutoff:
            raise ContractError("Prediction cutoff does not match the governed UTC cutoff.")
        latest_required_at = max(
            calendar.session_available_at_utc[source_index],
            calendar.session_available_at_utc[fold.test_start_index - 1],
        )
        if available_at < latest_required_at:
            raise ContractError("Posterior predates the latest source/fold test session evidence.")
        if available_at > cutoff_at:
            raise ContractError("Posterior was not available by its prediction cutoff.")
        for value, label in (
            (row.probability_up_mean, "Posterior probability mean"),
            (row.probability_up_std, "Posterior probability standard deviation"),
            (row.probability_up_q05, "Posterior probability q05"),
            (row.probability_up_q95, "Posterior probability q95"),
            (row.expected_return_pp, "Expected return"),
            (row.expected_return_std_pp, "Expected-return standard deviation"),
            (row.expected_risk_pp, "Expected risk"),
            (row.realized_return_pp, "Realized return"),
            (row.research_signed_allocation, "Research signed allocation"),
        ):
            _finite(value, label)
        if not 0.0 <= row.probability_up_q05 <= row.probability_up_mean <= row.probability_up_q95 <= 1.0:
            raise ContractError("Posterior probability interval is invalid.")
        if row.probability_up_std <= 0 or row.expected_return_std_pp <= 0 or row.expected_risk_pp < 0:
            raise ContractError("Posterior uncertainty and risk evidence are invalid.")
        if row.realized_return_pp <= -100.0:
            raise ContractError("Realized return must be greater than -100 percentage points.")
        if not -1.0 <= row.research_signed_allocation <= 1.0:
            raise ContractError("Research allocation must be within [-1, 1].")
        leaf = (ticker, persona)
        cell = (ticker, persona, row.prediction_date)
        if cell in seen_cells:
            raise ContractError("Posterior contains a duplicate ticker/persona/date prediction cell.")
        seen_cells.add(cell)
        leaves.add(leaf)
        dates.add(row.prediction_date)
        leaf_dates.setdefault(leaf, set()).add(row.prediction_date)
    if folds_with_outcomes != set(folds):
        raise ContractError("Every frozen walk-forward fold must contain posterior outcomes.")
    expected_dates = set(dates)
    if any(leaf_dates[leaf] != expected_dates for leaf in leaves):
        raise ContractError("Cost evaluation requires a complete ticker/persona/date panel.")
    expected_cells = len(leaves) * len(expected_dates)
    if len(outcomes) != expected_cells or len(seen_cells) != expected_cells:
        raise ContractError("Cost allocation cardinality does not match the complete panel geometry.")
    for prediction_date in dates:
        gross = sum(abs(row.research_signed_allocation) for row in outcomes if row.prediction_date == prediction_date)
        if gross > 1.0 + 1e-12:
            raise ContractError("Research portfolio gross allocation exceeds one.")
    return tuple(sorted(dates))


def _validate_recorded_decisions(
    decisions: tuple[RecordedDecisionEvidence, ...],
    outcomes: tuple[PosteriorOutcome, ...],
) -> dict[str, RecordedDecisionEvidence]:
    by_id: dict[str, RecordedDecisionEvidence] = {}
    for row in decisions:
        prediction_id = _identifier(row.prediction_id, "Decision prediction identifier")
        if prediction_id in by_id:
            raise ContractError("Recorded decision evidence must be unique per prediction.")
        if type(row.old_ag_decision) is not RecordedDecision or row.old_ag_decision.value not in OLD_AG_DECISIONS:
            raise ContractError("Recorded AG decision is outside the exact allowed enum.")
        if type(row.proposed_codex_decision) is not RecordedDecision or row.proposed_codex_decision.value not in CODEX_DECISIONS:
            raise ContractError("Recorded Codex decision is outside the exact allowed enum.")
        if row.proposed_codex_decision is not RecordedDecision.NO_TRADE:
            raise ContractError("Fixture-only Codex decision evidence must remain NO_TRADE.")
        if not row.old_ag_reasons or not row.proposed_codex_reasons:
            raise ContractError("Both recorded decisions require explicit reasons.")
        for reason in (*row.old_ag_reasons, *row.proposed_codex_reasons):
            _identifier(reason, "Decision reason code")
        if not row.sizing_adjustments:
            raise ContractError("Sizing evidence requires an explicit adjustment or NO_ADJUSTMENT row.")
        adjustment_ids: set[str] = set()
        for adjustment in row.sizing_adjustments:
            adjustment_id = _identifier(adjustment.adjustment_id, "Sizing adjustment identifier")
            if adjustment_id in adjustment_ids:
                raise ContractError("Sizing adjustment identifiers must be unique.")
            adjustment_ids.add(adjustment_id)
            if not 0.0 <= _finite(adjustment.multiplier, "Sizing multiplier") <= 1.0:
                raise ContractError("Sizing multipliers must lie in [0, 1].")
            if not adjustment.reason.strip():
                raise ContractError("Sizing adjustments require an explanation.")
        by_id[prediction_id] = row
    outcome_ids = {row.prediction_id for row in outcomes}
    if set(by_id) != outcome_ids:
        raise ContractError("Every posterior prediction requires exactly one decision-evidence row.")
    return by_id


def _convergence_summary(
    parameters: tuple[ParameterDiagnostic, ...],
    chains: tuple[ChainDiagnostic, ...],
    policy: ConvergencePolicy,
) -> ConvergenceSummary:
    maximum_r_hat = max(row.r_hat for row in parameters)
    minimum_ess_bulk = min(row.ess_bulk for row in parameters)
    minimum_ess_tail = min(row.ess_tail for row in parameters)
    minimum_bfmi = min(row.bfmi for row in chains)
    divergences = sum(row.divergences for row in chains)
    failures: list[str] = []
    if len(chains) < policy.minimum_chains:
        failures.append("INSUFFICIENT_CHAINS")
    if maximum_r_hat > policy.maximum_r_hat:
        failures.append("R_HAT_EXCEEDED")
    if minimum_ess_bulk < policy.minimum_ess_bulk:
        failures.append("BULK_ESS_TOO_LOW")
    if minimum_ess_tail < policy.minimum_ess_tail:
        failures.append("TAIL_ESS_TOO_LOW")
    if divergences > policy.maximum_divergences:
        failures.append("DIVERGENCES_EXCEEDED")
    if minimum_bfmi < policy.minimum_bfmi:
        failures.append("BFMI_TOO_LOW")
    return ConvergenceSummary(
        chains=len(chains),
        parameters=len(parameters),
        posterior_draws=sum(row.posterior_draws for row in chains),
        tuning_draws=sum(row.tuning_draws for row in chains),
        divergences=divergences,
        maximum_r_hat=maximum_r_hat,
        minimum_ess_bulk=minimum_ess_bulk,
        minimum_ess_tail=minimum_ess_tail,
        minimum_bfmi=minimum_bfmi,
        passed=not failures,
        failure_codes=tuple(failures),
    )


def _calibration(outcomes: tuple[PosteriorOutcome, ...], policy: EvaluationPolicy) -> CalibrationMetrics:
    count = len(outcomes)
    probabilities = [row.probability_up_mean for row in outcomes]
    realized = [1.0 if row.realized_return_pp > 0.0 else 0.0 for row in outcomes]
    accuracy = sum((probability >= 0.5) == bool(actual) for probability, actual in zip(probabilities, realized)) / count
    brier = sum((probability - actual) ** 2 for probability, actual in zip(probabilities, realized)) / count
    clipped = [min(1.0 - policy.probability_clip, max(policy.probability_clip, value)) for value in probabilities]
    log_loss = -sum(actual * log(probability) + (1.0 - actual) * log(1.0 - probability) for probability, actual in zip(clipped, realized)) / count
    calibration_error = 0.0
    for bin_index in range(policy.calibration_bins):
        low = bin_index / policy.calibration_bins
        high = (bin_index + 1) / policy.calibration_bins
        indexes = [index for index, probability in enumerate(probabilities) if low <= probability < high or (bin_index == policy.calibration_bins - 1 and probability == 1.0)]
        if indexes:
            mean_probability = sum(probabilities[index] for index in indexes) / len(indexes)
            mean_actual = sum(realized[index] for index in indexes) / len(indexes)
            calibration_error += len(indexes) / count * abs(mean_probability - mean_actual)
    errors = [row.expected_return_pp - row.realized_return_pp for row in outcomes]
    return CalibrationMetrics(
        observations=count,
        accuracy=float(accuracy),
        brier_score=float(brier),
        log_loss=float(log_loss),
        expected_calibration_error=float(calibration_error),
        expected_return_mae_pp=float(sum(abs(error) for error in errors) / count),
        expected_return_rmse_pp=float(sqrt(sum(error * error for error in errors) / count)),
    )


def _cost_and_drawdown(
    outcomes: tuple[PosteriorOutcome, ...],
    dates: tuple[date, ...],
    policy: EvaluationPolicy,
) -> CostDrawdownMetrics:
    prior: dict[tuple[str, str], float] = {}
    gross_equity = 1.0
    net_equity = 1.0
    net_peak = 1.0
    max_drawdown = 0.0
    gross_turnover = 0.0
    cost_pp_total = 0.0
    one_way_cost_bps = policy.round_trip_cost_bps / 2.0 + policy.one_way_slippage_bps
    for prediction_date in dates:
        dated = tuple(row for row in outcomes if row.prediction_date == prediction_date)
        allocations = {(row.ticker, row.persona): row.research_signed_allocation for row in dated}
        if len(allocations) != len(dated):
            raise ContractError("Cost allocation cardinality contains a duplicate portfolio cell.")
        turnover = sum(abs(value - prior.get(key, 0.0)) for key, value in allocations.items())
        gross_return_pp = sum(row.research_signed_allocation * row.realized_return_pp for row in dated)
        cost_pp = turnover * one_way_cost_bps / 100.0
        net_return_pp = gross_return_pp - cost_pp
        if gross_return_pp <= -100.0 or net_return_pp <= -100.0:
            raise ContractError("Research equity path would become non-positive.")
        gross_equity *= 1.0 + gross_return_pp / 100.0
        net_equity *= 1.0 + net_return_pp / 100.0
        net_peak = max(net_peak, net_equity)
        max_drawdown = max(max_drawdown, 1.0 - net_equity / net_peak)
        gross_turnover += turnover
        cost_pp_total += cost_pp
        prior = allocations
    terminal_turnover = sum(abs(value) for value in prior.values())
    terminal_cost_pp = terminal_turnover * one_way_cost_bps / 100.0
    terminal_return_pp = -terminal_cost_pp
    if terminal_return_pp <= -100.0:
        raise ContractError("Terminal close cost would make research equity non-positive.")
    net_equity *= 1.0 + terminal_return_pp / 100.0
    max_drawdown = max(max_drawdown, 1.0 - net_equity / net_peak)
    gross_turnover += terminal_turnover
    cost_pp_total += terminal_cost_pp
    return CostDrawdownMetrics(
        sessions=len(dates),
        gross_turnover=float(gross_turnover),
        terminal_close_turnover=float(terminal_turnover),
        transaction_cost_pp_sum=float(cost_pp_total),
        gross_total_return_fraction=float(gross_equity - 1.0),
        net_total_return_fraction=float(net_equity - 1.0),
        max_drawdown_fraction=float(max_drawdown),
    )


def _validate_computed_metrics(
    convergence: ConvergenceSummary,
    calibration: CalibrationMetrics,
    performance: CostDrawdownMetrics,
) -> None:
    for value, label in (
        (convergence.chains, "Computed convergence chains"),
        (convergence.parameters, "Computed convergence parameters"),
        (convergence.posterior_draws, "Computed posterior draws"),
        (convergence.tuning_draws, "Computed tuning draws"),
        (convergence.divergences, "Computed divergences"),
        (calibration.observations, "Computed calibration observations"),
        (performance.sessions, "Computed performance sessions"),
    ):
        _integer(value, label, minimum=0)
    for value, label in (
        (convergence.maximum_r_hat, "Computed maximum R-hat"),
        (convergence.minimum_ess_bulk, "Computed minimum bulk ESS"),
        (convergence.minimum_ess_tail, "Computed minimum tail ESS"),
        (convergence.minimum_bfmi, "Computed minimum BFMI"),
        (calibration.accuracy, "Computed accuracy"),
        (calibration.brier_score, "Computed Brier score"),
        (calibration.log_loss, "Computed log loss"),
        (calibration.expected_calibration_error, "Computed calibration error"),
        (calibration.expected_return_mae_pp, "Computed return MAE"),
        (calibration.expected_return_rmse_pp, "Computed return RMSE"),
        (performance.gross_turnover, "Computed gross turnover"),
        (performance.terminal_close_turnover, "Computed terminal turnover"),
        (performance.transaction_cost_pp_sum, "Computed transaction cost"),
        (performance.gross_total_return_fraction, "Computed gross total return"),
        (performance.net_total_return_fraction, "Computed net total return"),
        (performance.max_drawdown_fraction, "Computed maximum drawdown"),
    ):
        _finite(value, label)


def _validate_observation_chronology(request: PosteriorEvaluationRequest) -> None:
    """Require the artifact observation to close over every bound timestamp."""
    observed = _aware_utc(request.lineage.observed_at_utc, "Lineage observation timestamp")
    preregistered = _aware_utc(
        request.lineage.preregistration_observed_at_utc,
        "Preregistration observation timestamp",
    )
    baseline_audited = _aware_utc(
        request.lineage.baseline_audit_observed_at_utc,
        "Baseline audit observation timestamp",
    )
    hierarchy_observed = _aware_utc(
        request.hierarchy_registry.observed_at_utc,
        "Hierarchy registry observation timestamp",
    )
    snapshot_validated = _aware_utc(
        request.safety_evidence.snapshot_validated_at_utc,
        "Snapshot validation timestamp",
    )
    universe_approved = _aware_utc(
        request.safety_evidence.universe_approved_at_utc,
        "Universe approval timestamp",
    )
    model_completed = _aware_utc(
        request.safety_evidence.model_completed_at_utc,
        "Model completion timestamp",
    )
    quarantine_observed = _aware_utc(
        request.safety_evidence.quarantine_registry_observed_at_utc,
        "Quarantine registry timestamp",
    )
    posterior_times = tuple(
        _aware_utc(row.posterior_available_at_utc, "Posterior available-at timestamp")
        for row in request.outcomes
    )
    cutoff_times = tuple(
        _aware_utc(row.prediction_cutoff_at_utc, "Prediction cutoff timestamp")
        for row in request.outcomes
    )
    bound_times = (
        preregistered,
        baseline_audited,
        hierarchy_observed,
        snapshot_validated,
        universe_approved,
        model_completed,
        quarantine_observed,
        *request.session_calendar.session_available_at_utc,
        *posterior_times,
        *cutoff_times,
    )
    if observed < max(bound_times):
        raise ContractError("Lineage observation timestamp does not close over every bound evidence timestamp.")
    if posterior_times:
        first_posterior = min(posterior_times)
        latest_prerequisite = max(
            hierarchy_observed,
            preregistered,
            baseline_audited,
            snapshot_validated,
            universe_approved,
        )
        if not hierarchy_observed <= preregistered <= baseline_audited <= first_posterior:
            raise ContractError(
                "Hierarchy, preregistration, baseline audit, and first-posterior chronology is incoherent."
            )
        if latest_prerequisite > first_posterior:
            raise ContractError("A posterior predates prerequisite evidence.")
        if model_completed < max(posterior_times):
            raise ContractError("Model completion predates a bound posterior output.")
    elif not hierarchy_observed <= preregistered <= baseline_audited <= model_completed:
        raise ContractError("Hierarchy, preregistration, baseline, and model chronology is incoherent.")
    if model_completed > observed:
        raise ContractError("Model completion occurs after artifact observation.")


def _evidence_rows(
    outcomes: tuple[PosteriorOutcome, ...],
    decisions: dict[str, RecordedDecisionEvidence],
    lineage: ArtifactLineage,
    safety: VerifiedSafetyEvidence,
    convergence: ConvergenceSummary,
    boundary: OperationalBoundary,
) -> tuple[PredictionEvidenceRow, ...]:
    rows: list[PredictionEvidenceRow] = []
    for outcome in sorted(outcomes, key=lambda row: row.prediction_id):
        decision = decisions[outcome.prediction_id]
        posterior_available = _aware_utc(outcome.posterior_available_at_utc, "Posterior timestamp")
        lineage_observed = _aware_utc(lineage.observed_at_utc, "Lineage observation timestamp")
        model_completed = _aware_utc(safety.model_completed_at_utc, "Model completion timestamp")
        quarantine_observed = _aware_utc(
            safety.quarantine_registry_observed_at_utc,
            "Quarantine registry timestamp",
        )
        quarantine_applicable = (
            quarantine_observed >= model_completed
            and quarantine_observed >= max(
                _aware_utc(row.posterior_available_at_utc, "Posterior timestamp")
                for row in outcomes
            )
            and quarantine_observed <= lineage_observed
        )
        computed_results = {
            "SNAPSHOT_VALIDATED": (
                safety.validated_snapshot_sha256 == lineage.source_snapshot_sha256
                and _aware_utc(safety.snapshot_validated_at_utc, "Snapshot validation timestamp")
                <= posterior_available
            ),
            "UNIVERSE_APPROVED": (
                safety.approved_universe_sha256 == lineage.universe_sha256
                and _aware_utc(safety.universe_approved_at_utc, "Universe approval timestamp")
                <= posterior_available
            ),
            "SOURCE_DATE_ALIGNED": True,
            "MODEL_RUN_COMPLETED": (
                safety.completed_model_run_id == lineage.model_run_id
                and posterior_available
                <= model_completed
                <= lineage_observed
            ),
            "SAMPLER_QA_PASSED": convergence.passed,
            "RESEARCH_PROMOTION_APPROVED": boundary.promotion_authorized,
            "NOT_QUARANTINED": (
                quarantine_applicable
                and outcome.prediction_id not in set(safety.quarantined_prediction_ids)
            ),
        }
        computed_reasons = dict(REQUIRED_SAFETY_GATE_REASONS)
        if not quarantine_applicable:
            computed_reasons["NOT_QUARANTINED"] = "QUARANTINE_EVIDENCE_NOT_APPLICABLE"
        gates = tuple(
            HardSafetyGate(
                gate_id=gate_id,
                passed=computed_results[gate_id],
                reason_code="PASS" if computed_results[gate_id] else computed_reasons[gate_id],
            )
            for gate_id in REQUIRED_SAFETY_GATES
        )
        failed_reasons = tuple(gate.reason_code for gate in gates if not gate.passed)
        proposed_reasons = tuple(dict.fromkeys((*decision.proposed_codex_reasons, *failed_reasons)))
        rows.append(PredictionEvidenceRow(
            prediction_id=outcome.prediction_id,
            model_run_id=lineage.model_run_id,
            fold_id=outcome.fold_id,
            ticker=outcome.ticker,
            persona=outcome.persona,
            prediction_date=outcome.prediction_date,
            source_session_date=outcome.source_session_date,
            posterior_available_at_utc=posterior_available,
            prediction_cutoff_at_utc=_aware_utc(outcome.prediction_cutoff_at_utc, "Prediction cutoff"),
            raw_bayesian_output=RawBayesianOutput(
                probability_up_mean=outcome.probability_up_mean,
                probability_up_std=outcome.probability_up_std,
                probability_up_q05=outcome.probability_up_q05,
                probability_up_q95=outcome.probability_up_q95,
                expected_return_pp=outcome.expected_return_pp,
                expected_return_std_pp=outcome.expected_return_std_pp,
                expected_risk_pp=outcome.expected_risk_pp,
            ),
            old_ag_decision=decision.old_ag_decision,
            old_ag_reasons=decision.old_ag_reasons,
            proposed_codex_decision=RecordedDecision.NO_TRADE,
            proposed_codex_reasons=proposed_reasons,
            hard_safety_gates=gates,
            sizing_adjustments=decision.sizing_adjustments,
            review_only=True,
            operationally_eligible=False,
        ))
    return tuple(rows)


def _deep_freeze_request(request: PosteriorEvaluationRequest) -> PosteriorEvaluationRequest:
    """Copy every nested collection into immutable tuples before validation/hash."""
    if type(request) is not PosteriorEvaluationRequest:
        raise ContractError("Posterior request must use the exact governed request type.")
    try:
        sampler = replace(
            request.policy.sampler,
            required_parameters=tuple(sorted(request.policy.sampler.required_parameters)),
        )
        policy = replace(request.policy, sampler=sampler)
        calendar = replace(
            request.session_calendar,
            sessions=tuple(request.session_calendar.sessions),
            session_available_at_utc=tuple(request.session_calendar.session_available_at_utc),
        )
        hierarchy_registry = replace(
            request.hierarchy_registry,
            entries=tuple(sorted((
                replace(entry, hierarchy_path=tuple(entry.hierarchy_path))
                for entry in request.hierarchy_registry.entries
            ), key=lambda entry: (entry.ticker, entry.persona))),
        )
        safety_evidence = replace(
            request.safety_evidence,
            quarantined_prediction_ids=tuple(sorted(request.safety_evidence.quarantined_prediction_ids)),
        )
        outcomes = tuple(
            replace(row, hierarchy_path=tuple(row.hierarchy_path))
            for row in request.outcomes
        )
        decisions = tuple(
            replace(
                row,
                old_ag_reasons=tuple(row.old_ag_reasons),
                proposed_codex_reasons=tuple(row.proposed_codex_reasons),
                sizing_adjustments=tuple(row.sizing_adjustments),
            )
            for row in request.recorded_decisions
        )
        return replace(
            request,
            policy=policy,
            session_calendar=calendar,
            hierarchy_registry=hierarchy_registry,
            safety_evidence=safety_evidence,
            folds=tuple(request.folds),
            parameter_diagnostics=tuple(request.parameter_diagnostics),
            chain_diagnostics=tuple(request.chain_diagnostics),
            outcomes=outcomes,
            recorded_decisions=decisions,
        )
    except (AttributeError, TypeError) as exc:
        raise ContractError("Posterior request contains an invalid nested collection.") from exc


def _primitive(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return _aware_utc(value, "Serialized timestamp").isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Return stable canonical JSON for an artifact or request."""
    try:
        return json.dumps(_primitive(value), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("Canonical evidence contains a non-finite or unsupported value.") from exc


def _artifact_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"posterior_research_evidence_{digest}"


def _request_sha256(request: PosteriorEvaluationRequest) -> str:
    """Bind all input evidence while ignoring semantically irrelevant tuple order."""
    normalized = {
        "lineage": request.lineage,
        "policy": request.policy,
        "session_calendar": request.session_calendar,
        "hierarchy_registry": request.hierarchy_registry,
        "safety_evidence": request.safety_evidence,
        "folds": sorted(request.folds, key=lambda row: row.fold_id),
        "parameter_diagnostics": sorted(request.parameter_diagnostics, key=lambda row: row.parameter),
        "chain_diagnostics": sorted(request.chain_diagnostics, key=lambda row: row.chain_id),
        "outcomes": sorted(request.outcomes, key=lambda row: row.prediction_id),
        "recorded_decisions": sorted(request.recorded_decisions, key=lambda row: row.prediction_id),
    }
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def build_fixture_posterior_artifact(request: PosteriorEvaluationRequest) -> PosteriorEvaluationArtifact:
    """Validate and evaluate one deterministic in-memory fixture request.

    No posterior rows produces a typed blocked artifact rather than fabricated
    metrics or placeholder prediction rows.  Diagnostic failures also preserve
    evaluation evidence but keep the artifact blocked from research review.
    """
    request = _deep_freeze_request(request)
    _validate_lineage(request.lineage)
    _validate_policy(request.policy)
    if request.policy.sampler.sampler_name != request.lineage.sampler_name:
        raise ContractError("Sampler policy identity does not match lineage.")
    session_indices = _validate_session_calendar(request.session_calendar, request.lineage)
    hierarchy = _validate_hierarchy_registry(request.hierarchy_registry, request.lineage)
    _validate_safety_evidence(request.safety_evidence)
    _validate_observation_chronology(request)
    folds = _validate_folds(request.folds, request.policy, request.session_calendar)
    boundary = OperationalBoundary()
    if not request.outcomes:
        if (
            request.recorded_decisions
            or request.parameter_diagnostics
            or request.chain_diagnostics
            or request.safety_evidence.quarantined_prediction_ids
        ):
            raise ContractError("Absent posterior output cannot carry orphan decisions or diagnostics.")
        request_sha256 = _request_sha256(request)
        payload = {
            "artifact_type": "CODEX_POSTERIOR_RESEARCH_EVIDENCE_V1",
            "status": ArtifactStatus.ABSENT_POSTERIOR_BLOCKED,
            "blocker_codes": ("ABSENT_POSTERIOR_OUTPUT",),
            "request_sha256": request_sha256,
            "lineage": request.lineage,
            "policy": request.policy,
            "session_calendar": request.session_calendar,
            "hierarchy_registry": request.hierarchy_registry,
            "safety_evidence": request.safety_evidence,
            "folds": tuple(sorted(request.folds, key=lambda row: row.fold_id)),
            "fold_count": len(request.folds),
            "prediction_count": 0,
            "boundary": boundary,
        }
        return PosteriorEvaluationArtifact(
            artifact_id=_artifact_id(payload),
            request_sha256=request_sha256,
            artifact_type=payload["artifact_type"],
            status=payload["status"],
            blocker_codes=payload["blocker_codes"],
            lineage=request.lineage,
            policy=request.policy,
            session_calendar=request.session_calendar,
            hierarchy_registry=request.hierarchy_registry,
            safety_evidence=request.safety_evidence,
            folds=tuple(sorted(request.folds, key=lambda row: row.fold_id)),
            fold_count=len(folds),
            prediction_count=0,
            convergence=None,
            calibration=None,
            cost_and_drawdown=None,
            prediction_evidence_rows=(),
            boundary=boundary,
        )
    _validate_diagnostics(request.parameter_diagnostics, request.chain_diagnostics, request.policy.sampler)
    dates = _validate_outcomes(
        request.outcomes,
        folds,
        request.policy,
        session_indices,
        request.session_calendar,
        hierarchy,
    )
    outcome_ids = {row.prediction_id for row in request.outcomes}
    if not set(request.safety_evidence.quarantined_prediction_ids) <= outcome_ids:
        raise ContractError("Quarantine registry contains predictions outside this exact artifact.")
    decisions = _validate_recorded_decisions(request.recorded_decisions, request.outcomes)
    request_sha256 = _request_sha256(request)
    convergence = _convergence_summary(request.parameter_diagnostics, request.chain_diagnostics, request.policy.sampler.convergence)
    calibration = _calibration(request.outcomes, request.policy)
    cost_and_drawdown = _cost_and_drawdown(request.outcomes, dates, request.policy)
    _validate_computed_metrics(convergence, calibration, cost_and_drawdown)
    evidence_rows = _evidence_rows(
        request.outcomes,
        decisions,
        request.lineage,
        request.safety_evidence,
        convergence,
        boundary,
    )
    gate_blockers = tuple(dict.fromkeys(
        gate.reason_code
        for row in evidence_rows
        for gate in row.hard_safety_gates
        if not gate.passed
    ))
    blockers = tuple(dict.fromkeys((*convergence.failure_codes, *gate_blockers)))
    status = ArtifactStatus.PROMOTION_BLOCKED if convergence.passed else ArtifactStatus.DIAGNOSTIC_BLOCKED
    payload = {
        "artifact_type": "CODEX_POSTERIOR_RESEARCH_EVIDENCE_V1",
        "status": status,
        "blocker_codes": blockers,
        "request_sha256": request_sha256,
        "lineage": request.lineage,
        "policy": request.policy,
        "session_calendar": request.session_calendar,
        "hierarchy_registry": request.hierarchy_registry,
        "safety_evidence": request.safety_evidence,
        "folds": tuple(sorted(request.folds, key=lambda row: row.fold_id)),
        "fold_count": len(folds),
        "prediction_count": len(request.outcomes),
        "convergence": convergence,
        "calibration": calibration,
        "cost_and_drawdown": cost_and_drawdown,
        "prediction_evidence_rows": evidence_rows,
        "boundary": boundary,
    }
    return PosteriorEvaluationArtifact(
        artifact_id=_artifact_id(payload),
        request_sha256=request_sha256,
        artifact_type=payload["artifact_type"],
        status=status,
        blocker_codes=blockers,
        lineage=request.lineage,
        policy=request.policy,
        session_calendar=request.session_calendar,
        hierarchy_registry=request.hierarchy_registry,
        safety_evidence=request.safety_evidence,
        folds=tuple(sorted(request.folds, key=lambda row: row.fold_id)),
        fold_count=len(folds),
        prediction_count=len(request.outcomes),
        convergence=convergence,
        calibration=calibration,
        cost_and_drawdown=cost_and_drawdown,
        prediction_evidence_rows=evidence_rows,
        boundary=boundary,
    )


def artifact_sha256(artifact: PosteriorEvaluationArtifact) -> str:
    """Return the digest of the complete immutable artifact."""
    return hashlib.sha256(canonical_json(artifact).encode("utf-8")).hexdigest()


def audit_fixture_posterior_artifact(
    request: PosteriorEvaluationRequest,
    artifact: PosteriorEvaluationArtifact,
) -> SemanticAuditResult:
    """Rebuild and semantically compare an artifact against its exact request.

    A caller-controlled digest cannot bless changed boundary flags, evidence
    rows, metrics, status, lineage, or counts.  The auditor reruns every request
    validator and requires byte-identical canonical semantics to a fresh build.
    """
    if type(artifact) is not PosteriorEvaluationArtifact:
        raise ContractError("Artifact must use the exact governed artifact type.")
    if artifact.boundary != OperationalBoundary():
        raise ContractError("Artifact operational boundary was forged or weakened.")
    if any(not row.review_only or row.operationally_eligible for row in artifact.prediction_evidence_rows):
        raise ContractError("Prediction evidence row violates the review-only boundary.")
    expected = build_fixture_posterior_artifact(request)
    if artifact.request_sha256 != expected.request_sha256:
        raise ContractError("Artifact request digest does not match validated input evidence.")
    if canonical_json(artifact) != canonical_json(expected):
        raise ContractError("Artifact semantics do not match an independently rebuilt artifact.")
    return SemanticAuditResult(
        passed=True,
        request_sha256=expected.request_sha256,
        artifact_sha256=artifact_sha256(expected),
        checked_predictions=expected.prediction_count,
        checked_folds=expected.fold_count,
    )
