"""Pure evidence model for a validated screen with no qualifying candidates.

This module intentionally performs no I/O.  It converts already-read screening
evidence into a deterministic terminal research outcome without creating model
outputs, recommendations, or ETF priors.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from model_lineage import LineageError


NO_QUALIFYING_OUTPUT = "NO_QUALIFYING_OUTPUT"


@dataclass(frozen=True)
class CandidateScreeningEvidence:
    ticker: str
    eligible: bool
    rejection_reasons: tuple[str, ...]
    oos_sessions: int
    oos_accuracy: float | None = None
    accuracy_ci_low: float | None = None
    accuracy_ci_high: float | None = None
    brier_score: float | None = None
    log_loss: float | None = None
    calibration_error: float | None = None
    majority_accuracy: float | None = None
    own_lag_accuracy: float | None = None
    own_lag_brier: float | None = None
    selected_depth: int | None = None
    feature_spec_json: str | None = None


@dataclass(frozen=True)
class ScreeningArmEvidence:
    screening_run_id: str
    market_snapshot_id: str
    snapshot_checksum_sha256: str
    snapshot_status: str
    source_session_date: str
    cutoff_utc: str
    code_version: str
    config_json: str
    run_status: str
    validation_notes: str
    expected_ticker_count: int
    candidates: tuple[CandidateScreeningEvidence, ...]


@dataclass(frozen=True)
class DownstreamOutputCounts:
    model_runs: int
    model_scorecards: int
    etf_priors: int
    recommendations: int = 0
    orders: int = 0


@dataclass(frozen=True)
class ReasonCount:
    reason: str
    count: int


@dataclass(frozen=True)
class MetricSummary:
    evaluated_candidates: int
    data_rejected_candidates: int
    mean_oos_accuracy: float | None
    mean_accuracy_ci_low: float | None
    mean_accuracy_ci_high: float | None
    mean_brier_score: float | None
    mean_log_loss: float | None
    mean_calibration_error: float | None
    mean_majority_accuracy: float | None
    mean_own_lag_accuracy: float | None
    mean_own_lag_brier: float | None


@dataclass(frozen=True)
class TerminalArmEvidence:
    arm: ScreeningArmEvidence
    config_sha256: str
    metrics: MetricSummary
    rejection_reason_counts: tuple[ReasonCount, ...]


@dataclass(frozen=True)
class NoQualifyingOutputEvidence:
    outcome_id: str
    state: str
    terminal: bool
    terminal_reason: str
    arms: tuple[TerminalArmEvidence, ...]
    downstream: DownstreamOutputCounts
    production_promotion_allowed: bool
    permitted_successors: tuple[str, ...]


_METRIC_FIELDS = (
    "oos_accuracy",
    "accuracy_ci_low",
    "accuracy_ci_high",
    "brier_score",
    "log_loss",
    "calibration_error",
    "majority_accuracy",
    "own_lag_accuracy",
    "own_lag_brier",
)
_PROBABILITY_FIELDS = set(_METRIC_FIELDS) - {"log_loss"}


def _required_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LineageError(f"{label} is required.")
    return value


def _validate_metric(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LineageError(f"{name} must be a finite number.")
    if value < 0 or (name in _PROBABILITY_FIELDS and value > 1):
        raise LineageError(f"{name} is outside its governed bounds.")


def _validated_config_json(config_json: str, expected_tickers: int) -> str:
    _required_text(config_json, "config_json")
    try:
        config = json.loads(config_json)
    except (TypeError, ValueError) as exc:
        raise LineageError("config_json is not valid JSON.") from exc
    if not isinstance(config, dict) or not config:
        raise LineageError("config_json must contain a non-empty JSON object.")
    hypotheses = config.get("eligibility_hypotheses")
    if isinstance(hypotheses, bool) or not isinstance(hypotheses, int):
        raise LineageError("config_json is missing integer eligibility_hypotheses.")
    if hypotheses != expected_tickers:
        raise LineageError("Familywise eligibility hypotheses do not cover the frozen universe.")
    return hashlib.sha256(config_json.encode("utf-8")).hexdigest()


def _validate_lineage_dates(source_session_date: str, cutoff_utc: str) -> None:
    try:
        parsed_date = date.fromisoformat(source_session_date)
    except ValueError as exc:
        raise LineageError("source_session_date must be an ISO calendar date.") from exc
    if parsed_date.isoformat() != source_session_date:
        raise LineageError("source_session_date must use canonical YYYY-MM-DD form.")
    try:
        parsed_cutoff = datetime.fromisoformat(cutoff_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LineageError("cutoff_utc must be an ISO timestamp.") from exc
    if parsed_cutoff.tzinfo is None or parsed_cutoff.utcoffset() is None:
        raise LineageError("cutoff_utc must be timezone-aware.")


def _validate_candidate(candidate: CandidateScreeningEvidence) -> None:
    _required_text(candidate.ticker, "candidate ticker")
    if candidate.ticker != candidate.ticker.strip().upper():
        raise LineageError("Candidate ticker must be normalized uppercase evidence.")
    if candidate.eligible:
        raise LineageError("NO_QUALIFYING_OUTPUT cannot contain an eligible candidate.")
    if candidate.oos_sessions < 0:
        raise LineageError("Candidate oos_sessions cannot be negative.")
    if not candidate.rejection_reasons or any(
        not isinstance(reason, str) or not reason.strip() for reason in candidate.rejection_reasons
    ):
        raise LineageError("Every non-qualifying candidate requires an exact rejection reason.")
    values = {name: getattr(candidate, name) for name in _METRIC_FIELDS}
    if candidate.oos_sessions == 0:
        if any(value is not None for value in values.values()):
            raise LineageError("A data-rejected candidate cannot contain fabricated metrics.")
        if candidate.selected_depth is not None or candidate.feature_spec_json is not None:
            raise LineageError("A data-rejected candidate cannot contain a selected model specification.")
        return
    if any(value is None for value in values.values()):
        raise LineageError("An evaluated candidate must preserve all baseline and statistical metrics.")
    for name, value in values.items():
        _validate_metric(name, value)  # type: ignore[arg-type]
    if not (
        candidate.accuracy_ci_low <= candidate.oos_accuracy <= candidate.accuracy_ci_high
    ):
        raise LineageError("Accuracy must lie inside its preserved confidence interval.")
    if (
        isinstance(candidate.selected_depth, bool)
        or not isinstance(candidate.selected_depth, int)
        or not 1 <= candidate.selected_depth <= 5
    ):
        raise LineageError("An evaluated candidate requires governed selected depth 1..5.")
    _required_text(candidate.feature_spec_json or "", "feature_spec_json")
    try:
        feature_spec = json.loads(candidate.feature_spec_json or "")
    except ValueError as exc:
        raise LineageError("feature_spec_json is not valid JSON.") from exc
    if not isinstance(feature_spec, dict) or int(feature_spec.get("depth", -1)) != candidate.selected_depth:
        raise LineageError("Selected depth does not match feature_spec_json.")


def _mean(candidates: tuple[CandidateScreeningEvidence, ...], field: str) -> float | None:
    values = [getattr(candidate, field) for candidate in candidates if candidate.oos_sessions > 0]
    if not values:
        return None
    return sum(values) / len(values)  # type: ignore[arg-type]


def _summarize(candidates: tuple[CandidateScreeningEvidence, ...]) -> MetricSummary:
    evaluated = sum(candidate.oos_sessions > 0 for candidate in candidates)
    return MetricSummary(
        evaluated_candidates=evaluated,
        data_rejected_candidates=len(candidates) - evaluated,
        mean_oos_accuracy=_mean(candidates, "oos_accuracy"),
        mean_accuracy_ci_low=_mean(candidates, "accuracy_ci_low"),
        mean_accuracy_ci_high=_mean(candidates, "accuracy_ci_high"),
        mean_brier_score=_mean(candidates, "brier_score"),
        mean_log_loss=_mean(candidates, "log_loss"),
        mean_calibration_error=_mean(candidates, "calibration_error"),
        mean_majority_accuracy=_mean(candidates, "majority_accuracy"),
        mean_own_lag_accuracy=_mean(candidates, "own_lag_accuracy"),
        mean_own_lag_brier=_mean(candidates, "own_lag_brier"),
    )


def _reason_counts(candidates: tuple[CandidateScreeningEvidence, ...]) -> tuple[ReasonCount, ...]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        for reason in candidate.rejection_reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return tuple(ReasonCount(reason, counts[reason]) for reason in sorted(counts))


def _validate_arm(arm: ScreeningArmEvidence) -> TerminalArmEvidence:
    for label in (
        "screening_run_id",
        "market_snapshot_id",
        "source_session_date",
        "cutoff_utc",
        "code_version",
        "validation_notes",
    ):
        _required_text(getattr(arm, label), label)
    _validate_lineage_dates(arm.source_session_date, arm.cutoff_utc)
    if arm.run_status != "VALIDATED" or arm.snapshot_status != "VALIDATED":
        raise LineageError("Terminal evidence requires validated screening and snapshot lineage.")
    checksum = arm.snapshot_checksum_sha256
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        raise LineageError("Snapshot checksum must be a lowercase SHA-256 digest.")
    if arm.expected_ticker_count <= 0:
        raise LineageError("Expected ticker count must be positive.")
    if len(arm.candidates) != arm.expected_ticker_count:
        raise LineageError("Screening candidate coverage is incomplete.")
    tickers = [candidate.ticker for candidate in arm.candidates]
    if len(set(tickers)) != len(tickers):
        raise LineageError("Screening candidate coverage contains duplicate tickers.")
    for candidate in arm.candidates:
        _validate_candidate(candidate)
    config_sha256 = _validated_config_json(arm.config_json, arm.expected_ticker_count)
    return TerminalArmEvidence(
        arm=arm,
        config_sha256=config_sha256,
        metrics=_summarize(arm.candidates),
        rejection_reason_counts=_reason_counts(arm.candidates),
    )


def build_no_qualifying_output_evidence(
    arms: Iterable[ScreeningArmEvidence],
    *,
    downstream: DownstreamOutputCounts,
) -> NoQualifyingOutputEvidence:
    """Return a deterministic fail-closed terminal result for zero-candidate screens."""
    arm_tuple = tuple(arms)
    if not arm_tuple:
        raise LineageError("NO_QUALIFYING_OUTPUT requires at least one screening arm.")
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 0
        for count in (
            downstream.model_runs,
            downstream.model_scorecards,
            downstream.etf_priors,
            downstream.recommendations,
            downstream.orders,
        )
    ):
        raise LineageError("Downstream output counts must be non-negative integers.")
    if any(
        count != 0
        for count in (
            downstream.model_runs,
            downstream.model_scorecards,
            downstream.etf_priors,
            downstream.recommendations,
            downstream.orders,
        )
    ):
        raise LineageError("NO_QUALIFYING_OUTPUT requires zero downstream outputs.")
    terminal_arms = tuple(_validate_arm(arm) for arm in arm_tuple)
    if len({item.arm.screening_run_id for item in terminal_arms}) != len(terminal_arms):
        raise LineageError("Screening arm identifiers must be unique.")
    lineage = {
        (
            item.arm.market_snapshot_id,
            item.arm.snapshot_checksum_sha256,
            item.arm.source_session_date,
            item.arm.cutoff_utc,
            item.arm.code_version,
        )
        for item in terminal_arms
    }
    if len(lineage) != 1:
        raise LineageError("Screening arms do not share exact snapshot, cutoff, and code lineage.")
    outcome_material = "\n".join(
        f"{item.arm.screening_run_id}:{item.config_sha256}"
        for item in sorted(terminal_arms, key=lambda item: item.arm.screening_run_id)
    )
    snapshot_material = next(iter(lineage))
    outcome_id = "no_qualifying_" + hashlib.sha256(
        ("|".join(snapshot_material) + "\n" + outcome_material).encode("utf-8")
    ).hexdigest()[:24]
    return NoQualifyingOutputEvidence(
        outcome_id=outcome_id,
        state=NO_QUALIFYING_OUTPUT,
        terminal=True,
        terminal_reason="Validated full-universe screening produced zero eligible candidates.",
        arms=terminal_arms,
        downstream=downstream,
        production_promotion_allowed=False,
        permitted_successors=(
            "REVIEW_PRESERVED_SCREENING_EVIDENCE",
            "PREREGISTER_SEPARATE_RESEARCH_EXPERIMENT",
        ),
    )
