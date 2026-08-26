"""Pure research-only integration for hierarchical stock posterior cohorts.

The integration accepts already-built stock datasets and explicit decision
contexts, assembles the hierarchical model input, delegates posterior
generation to a required injectable fitter, and emits review-only comparison
and audit evidence.  It performs no persistence or external I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Callable, Mapping, Sequence

from model_lineage import LineageError, Recommendation
from stock_hierarchical_pymc_core import (
    HierarchicalStockDataset,
    build_hierarchical_stock_dataset,
)
from stock_model_dataset import StockModelDataset
from stock_posterior_bridge import (
    compare_research_only_posterior,
    posterior_to_prediction_evidence,
)
from stock_prediction_audit import (
    StockPredictionAuditRecords,
    build_stock_prediction_audit_records,
)
from stock_prediction_eligibility import (
    DecisionContext,
    EligibilityComparison,
    LEGACY_PERSONAS,
)
from stock_pymc_core import StockPosteriorEvidence


@dataclass(frozen=True)
class CohortDecisionLane:
    persona_name: str
    resolved_base_persona: str
    context: DecisionContext


@dataclass(frozen=True)
class FrozenCohortTarget:
    dataset: StockModelDataset
    decision_lanes: tuple[CohortDecisionLane, ...]


@dataclass(frozen=True)
class HierarchicalCohortConfig:
    model_run_id: str
    source_session_date: date
    prediction_date: date
    audit_created_at_utc: datetime


@dataclass(frozen=True)
class CohortDecisionEvidence:
    persona_name: str
    resolved_base_persona: str
    comparison: EligibilityComparison
    audit_records: StockPredictionAuditRecords


@dataclass(frozen=True)
class CohortTargetEvidence:
    ticker: str
    posterior: StockPosteriorEvidence
    decisions: tuple[CohortDecisionEvidence, ...]


@dataclass(frozen=True)
class HierarchicalCohortResult:
    model_run_id: str
    source_session_date: date
    prediction_date: date
    hierarchical_dataset: HierarchicalStockDataset
    targets: tuple[CohortTargetEvidence, ...]
    action_policy: str = "RESEARCH_ONLY_PROMOTION_FORCED_CLOSED"


HierarchicalPosteriorFitter = Callable[
    [HierarchicalStockDataset], Mapping[str, StockPosteriorEvidence]
]


def _validate_inputs(
    config: HierarchicalCohortConfig,
    targets: tuple[FrozenCohortTarget, ...],
) -> None:
    if not config.model_run_id.strip():
        raise LineageError("Hierarchical cohort requires an explicit model run ID.")
    if config.source_session_date >= config.prediction_date:
        raise LineageError("Hierarchical cohort source session must precede prediction date.")
    if config.audit_created_at_utc.tzinfo is None:
        raise LineageError("Hierarchical cohort audit timestamp must be timezone-aware.")
    if len(targets) < 2:
        raise LineageError("Hierarchical cohort requires at least two target datasets.")
    tickers = tuple(target.dataset.ticker for target in targets)
    if len(set(tickers)) != len(tickers):
        raise LineageError("Hierarchical cohort target tickers must be unique.")
    for target in targets:
        dataset = target.dataset
        if (
            dataset.source_session_date != config.source_session_date
            or dataset.prediction_date != config.prediction_date
        ):
            raise LineageError("Hierarchical cohort dataset lineage does not match its run.")
        if not target.decision_lanes:
            raise LineageError(f"{dataset.ticker} has no decision-audit lanes.")
        lane_names = tuple(lane.persona_name for lane in target.decision_lanes)
        if len(set(lane_names)) != len(lane_names):
            raise LineageError(f"{dataset.ticker} decision-audit personas must be unique.")
        for lane in target.decision_lanes:
            if not lane.persona_name.strip():
                raise LineageError("Hierarchical cohort persona identifier is required.")
            if lane.resolved_base_persona not in LEGACY_PERSONAS:
                raise LineageError("Hierarchical cohort base persona is not governed.")


def run_hierarchical_cohort_research(
    targets: Sequence[FrozenCohortTarget],
    config: HierarchicalCohortConfig,
    *,
    posterior_fitter: HierarchicalPosteriorFitter,
) -> HierarchicalCohortResult:
    """Build and evaluate one frozen hierarchical cohort without side effects.

    A fitter is deliberately mandatory: importing this module cannot select or
    execute a model.  Every action-capable comparison lane is forced to
    ``NO_TRADE`` even if its caller supplied an approved promotion flag.
    """
    frozen_targets = tuple(targets)
    _validate_inputs(config, frozen_targets)
    hierarchical = build_hierarchical_stock_dataset(
        tuple(target.dataset for target in frozen_targets)
    )
    posterior_map = posterior_fitter(hierarchical)
    if not isinstance(posterior_map, Mapping) or not posterior_map:
        raise LineageError("Hierarchical fitter produced no posterior outputs.")
    expected_tickers = set(hierarchical.tickers)
    actual_tickers = set(posterior_map)
    if actual_tickers != expected_tickers:
        missing = sorted(expected_tickers - actual_tickers)
        extra = sorted(actual_tickers - expected_tickers)
        raise LineageError(
            f"Hierarchical posterior ticker coverage mismatch; missing={missing}, extra={extra}."
        )

    by_ticker = {target.dataset.ticker: target for target in frozen_targets}
    output: list[CohortTargetEvidence] = []
    audit_timestamp = config.audit_created_at_utc.astimezone(timezone.utc)
    for ticker in hierarchical.tickers:
        posterior = posterior_map[ticker]
        if not isinstance(posterior, StockPosteriorEvidence):
            raise LineageError("Hierarchical fitter returned an invalid posterior payload.")
        if posterior.ticker != ticker:
            raise LineageError("Hierarchical posterior payload ticker does not match its key.")
        prediction_evidence = posterior_to_prediction_evidence(posterior)
        decisions: list[CohortDecisionEvidence] = []
        for lane in by_ticker[ticker].decision_lanes:
            frozen_context = replace(
                lane.context,
                research_promotion_approved=False,
            )
            comparison = compare_research_only_posterior(
                posterior,
                frozen_context,
                persona_name=lane.resolved_base_persona,
            )
            if (
                comparison.codex_action is not Recommendation.NO_TRADE
                or comparison.balanced_action is not Recommendation.NO_TRADE
                or "RESEARCH_PROMOTION_NOT_APPROVED" not in comparison.hard_gate_failures
            ):
                raise LineageError("Hierarchical research promotion gate did not fail closed.")
            audit = build_stock_prediction_audit_records(
                model_run_id=config.model_run_id,
                ticker=ticker,
                persona=lane.persona_name,
                resolved_base_persona=lane.resolved_base_persona,
                evidence=prediction_evidence,
                context=frozen_context,
                created_at_utc=audit_timestamp,
            )
            decisions.append(CohortDecisionEvidence(
                persona_name=lane.persona_name,
                resolved_base_persona=lane.resolved_base_persona,
                comparison=comparison,
                audit_records=audit,
            ))
        output.append(CohortTargetEvidence(
            ticker=ticker,
            posterior=posterior,
            decisions=tuple(decisions),
        ))
    return HierarchicalCohortResult(
        model_run_id=config.model_run_id,
        source_session_date=config.source_session_date,
        prediction_date=config.prediction_date,
        hierarchical_dataset=hierarchical,
        targets=tuple(output),
    )
