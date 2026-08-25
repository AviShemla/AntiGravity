"""Evidence table comparing legacy AG and proposed stock-decision gates.

This module is pure policy evaluation: it performs no I/O, model fitting,
database writes, order creation, or service activation. Raw Bayesian output is
always retained even when every action lane resolves to HOLD or NO_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from model_lineage import LineageError, Recommendation
from statistical_units import basis_points_to_percentage_points


@dataclass(frozen=True)
class LegacyPersona:
    probability_threshold: float
    kelly_multiplier: float
    maximum_allocation: float
    flat_fallback: float


LEGACY_PERSONAS = {
    "Conservative": LegacyPersona(0.65, 0.25, 0.10, 0.00),
    "Neutral": LegacyPersona(0.60, 0.50, 0.10, 0.10),
    "BallsForBrains": LegacyPersona(0.55, 0.90, 0.15, 0.15),
}


@dataclass(frozen=True)
class PredictionEvidence:
    probability_up_mean: float
    probability_up_q05: float
    probability_up_q95: float
    expected_return_pp: float
    expected_risk_pp: float


@dataclass(frozen=True)
class DecisionContext:
    snapshot_validated: bool
    universe_approved: bool
    source_date_aligned: bool
    model_run_completed: bool
    sampler_qa_passed: bool
    research_promotion_approved: bool
    quarantined: bool = False
    legacy_blacklisted: bool = False
    available_capital: float = 0.0
    vix_close: float = 15.0
    price_available: bool = True
    round_trip_cost_bps: float = 0.0


@dataclass(frozen=True)
class ComparisonRow:
    criterion: str
    ag_rule: str
    ag_result: str
    codex_rule: str
    codex_result: str
    balanced_rule: str
    balanced_result: str


@dataclass(frozen=True)
class EligibilityComparison:
    raw_model_signal: Recommendation
    ag_action: Recommendation
    codex_action: Recommendation
    balanced_action: Recommendation
    legacy_allocation_fraction: float
    shadow_allocation_fraction: float
    legacy_vix_multiplier: float
    shadow_vix_multiplier: float
    hard_gate_failures: tuple[str, ...]
    rows: tuple[ComparisonRow, ...]


def _validate(evidence: PredictionEvidence, context: DecisionContext) -> None:
    values = (
        evidence.probability_up_mean,
        evidence.probability_up_q05,
        evidence.probability_up_q95,
        evidence.expected_return_pp,
        evidence.expected_risk_pp,
        context.available_capital,
        context.vix_close,
        context.round_trip_cost_bps,
    )
    if not all(isfinite(value) for value in values):
        raise LineageError("Prediction eligibility evidence must be finite.")
    if not (
        0.0 <= evidence.probability_up_q05
        <= evidence.probability_up_mean
        <= evidence.probability_up_q95
        <= 1.0
    ):
        raise LineageError("Posterior probability interval is invalid.")
    if evidence.expected_risk_pp < 0.0 or context.available_capital < 0.0:
        raise LineageError("Risk and available capital cannot be negative.")
    if context.round_trip_cost_bps < 0.0:
        raise LineageError("Transaction-cost basis points cannot be negative.")


def legacy_raw_signal(probability_up: float) -> Recommendation:
    """Legacy stock scorecard thresholds from export_bayesian_scorecard_TNX.py."""
    if probability_up > 0.65:
        return Recommendation.BUY
    if probability_up < 0.35:
        return Recommendation.SELL
    return Recommendation.HOLD


def _legacy_vix_multiplier(persona: str, vix_close: float) -> float:
    if persona == "Conservative":
        return 0.0 if vix_close > 25.0 else (0.3 if vix_close > 20.0 else 1.0)
    if persona == "BallsForBrains":
        return 0.0 if vix_close > 45.0 else (0.8 if vix_close > 35.0 else 1.0)
    return 0.0 if vix_close > 30.0 else (0.8 if vix_close > 20.0 else 1.0)


SHADOW_VIX_BANDS = {
    # These are comparison hypotheses, not approved production thresholds.
    # They reuse AG's existing transition/cutoff bounds while replacing the
    # discontinuous zero allocation with a visible 25% sizing floor.
    "Conservative": (20.0, 25.0, 0.25),
    "Neutral": (20.0, 30.0, 0.25),
    "BallsForBrains": (35.0, 45.0, 0.25),
}


def shadow_vix_multiplier(persona: str, vix_close: float) -> float:
    """Return a continuous shadow-only sizing multiplier in ``[floor, 1]``."""
    if persona not in SHADOW_VIX_BANDS:
        raise LineageError("Unknown persona has no shadow VIX policy.")
    start, end, floor = SHADOW_VIX_BANDS[persona]
    if vix_close <= start:
        return 1.0
    if vix_close >= end:
        return floor
    progress = (vix_close - start) / (end - start)
    return 1.0 - progress * (1.0 - floor)


def _legacy_buy_allocation(
    evidence: PredictionEvidence,
    context: DecisionContext,
    persona: LegacyPersona,
    vix_multiplier: float,
) -> float:
    if evidence.probability_up_mean <= persona.probability_threshold:
        return 0.0
    if evidence.expected_return_pp <= 0.0 or evidence.expected_risk_pp <= 0.0:
        raw_kelly = 0.0
    else:
        payoff = evidence.expected_return_pp / evidence.expected_risk_pp
        raw_kelly = max(
            0.0,
            evidence.probability_up_mean - (1.0 - evidence.probability_up_mean) / payoff,
        )
    applied = raw_kelly * persona.kelly_multiplier * vix_multiplier
    if applied == 0.0 and persona.flat_fallback > 0.0:
        applied = persona.flat_fallback * vix_multiplier
    return min(applied, persona.maximum_allocation)


def _hard_evidence_passes(context: DecisionContext) -> bool:
    return not hard_gate_failures(context)


def hard_gate_failures(context: DecisionContext) -> tuple[str, ...]:
    """Return explicit evidence failures; sizing conditions never appear here."""
    checks = (
        (context.snapshot_validated, "SNAPSHOT_NOT_VALIDATED"),
        (context.universe_approved, "UNIVERSE_NOT_APPROVED"),
        (context.source_date_aligned, "SOURCE_DATE_MISMATCH"),
        (context.model_run_completed, "MODEL_RUN_NOT_COMPLETED"),
        (context.sampler_qa_passed, "SAMPLER_QA_FAILED"),
        (context.research_promotion_approved, "RESEARCH_PROMOTION_NOT_APPROVED"),
        (not context.quarantined, "ACTIVE_EVIDENCE_QUARANTINE"),
    )
    return tuple(reason for passed, reason in checks if not passed)


def _shadow_buy_allocation(
    evidence: PredictionEvidence,
    context: DecisionContext,
    persona: LegacyPersona,
    vix_multiplier: float,
) -> float:
    """Compute shadow sizing without AG's fixed-allocation fallback."""
    net_return = evidence.expected_return_pp - basis_points_to_percentage_points(context.round_trip_cost_bps)
    if net_return <= 0.0 or evidence.expected_risk_pp <= 0.0:
        return 0.0
    payoff = net_return / evidence.expected_risk_pp
    raw_kelly = max(
        0.0,
        evidence.probability_up_mean
        - (1.0 - evidence.probability_up_mean) / payoff,
    )
    return min(
        raw_kelly * persona.kelly_multiplier * vix_multiplier,
        persona.maximum_allocation,
    )


def compare_stock_prediction(
    evidence: PredictionEvidence,
    context: DecisionContext,
    *,
    persona_name: str,
) -> EligibilityComparison:
    """Build a transparent three-lane decision comparison for one prediction.

    ``codex_action`` uses a deliberately strict posterior-interval rule.
    ``balanced_action`` preserves the legacy persona mean-probability threshold
    while requiring positive net expected return and the same evidence gates.
    Neither lane creates or authorizes an order.
    """
    _validate(evidence, context)
    if persona_name not in LEGACY_PERSONAS:
        raise LineageError(
            "Dynamic/unknown legacy personas require their resolved base persona as evidence."
        )
    persona = LEGACY_PERSONAS[persona_name]
    raw_signal = legacy_raw_signal(evidence.probability_up_mean)
    vix_multiplier = _legacy_vix_multiplier(persona_name, context.vix_close)
    proposed_vix_multiplier = shadow_vix_multiplier(persona_name, context.vix_close)
    legacy_allocation = _legacy_buy_allocation(evidence, context, persona, vix_multiplier)
    legacy_operational = all((
        not context.legacy_blacklisted,
        not context.quarantined,
        context.available_capital > 0.0,
        context.price_available,
        vix_multiplier > 0.0,
    ))
    ag_action = (
        Recommendation.BUY
        if legacy_operational and legacy_allocation > 0.0
        else (Recommendation.SELL if raw_signal is Recommendation.SELL else Recommendation.HOLD)
    )

    failures = hard_gate_failures(context)
    hard_pass = not failures
    net_return = evidence.expected_return_pp - basis_points_to_percentage_points(context.round_trip_cost_bps)
    codex_action = Recommendation.NO_TRADE
    balanced_action = Recommendation.NO_TRADE
    if hard_pass:
        if evidence.probability_up_q05 > 0.50 and net_return > 0.0:
            codex_action = Recommendation.BUY
        elif evidence.probability_up_q95 < 0.50 and net_return < 0.0:
            codex_action = Recommendation.SELL
        else:
            codex_action = Recommendation.HOLD

        balanced_sell_threshold = 1.0 - persona.probability_threshold
        if evidence.probability_up_mean > persona.probability_threshold and net_return > 0.0:
            balanced_action = Recommendation.BUY
        elif evidence.probability_up_mean < balanced_sell_threshold and net_return < 0.0:
            balanced_action = Recommendation.SELL
        else:
            balanced_action = Recommendation.HOLD

    shadow_allocation = (
        _shadow_buy_allocation(
            evidence, context, persona, proposed_vix_multiplier
        )
        if hard_pass and balanced_action is Recommendation.BUY
        else 0.0
    )

    rows = (
        ComparisonRow(
            "Raw Bayesian output",
            "Always shown; scorecard BUY >65%, SELL <35%, otherwise HOLD.",
            raw_signal.value,
            "Always shown with mean, 5%-95% interval, return, and risk.",
            "REPORTED",
            "Always shown even when downstream action is blocked.",
            "REPORTED",
        ),
        ComparisonRow(
            "Hard safety gates",
            "Legacy broker did not prove immutable snapshot/universe lineage here.",
            "UNPROVEN",
            "Validated snapshot, approved universe, aligned source date, completed run required.",
            "PASS" if hard_pass else ",".join(failures),
            "Same non-negotiable evidence gate.",
            "PASS" if hard_pass else ",".join(failures),
        ),
        ComparisonRow(
            "Direction strength",
            f"Persona opens BUY when mean P(UP) > {persona.probability_threshold:.2f}.",
            "PASS" if evidence.probability_up_mean > persona.probability_threshold else "FAIL",
            "BUY only when posterior q05 > 0.50; SELL only when q95 < 0.50.",
            codex_action.value,
            "Use persona mean threshold; interval remains a visible uncertainty warning.",
            balanced_action.value,
        ),
        ComparisonRow(
            "Kelly sizing",
            "Kelly uses expected return/risk; Neutral and BallsForBrains may fall back to flat allocation.",
            f"allocation={legacy_allocation:.6f}",
            "No fixed fallback; non-positive net return, risk, or Kelly remains zero.",
            f"shadow_allocation={shadow_allocation:.6f}",
            "Same shadow sizing; model output remains visible when allocation is zero.",
            f"shadow_allocation={shadow_allocation:.6f}",
        ),
        ComparisonRow(
            "VIX sizing versus gating",
            "Step multiplier can reduce allocation or hard-block it at the persona cutoff.",
            f"multiplier={vix_multiplier:.6f}",
            "Continuous shadow-only sizing; VIX alone cannot upgrade or reject model evidence.",
            f"multiplier={proposed_vix_multiplier:.6f}",
            "Backtest the continuous hypothesis before any paper-policy promotion.",
            "SHADOW_ONLY",
        ),
        ComparisonRow(
            "Operational safety",
            "Blacklist/quarantine, VIX cutoff, capital, and price availability can block allocation.",
            "PASS" if legacy_operational else "FAIL",
            "Execution controls are evaluated later and cannot upgrade a model decision.",
            "NOT_EVALUATED_FOR_ORDER",
            "Same: this report is a paper candidate, never an order authorization.",
            "NOT_EVALUATED_FOR_ORDER",
        ),
    )
    return EligibilityComparison(
        raw_model_signal=raw_signal,
        ag_action=ag_action,
        codex_action=codex_action,
        balanced_action=balanced_action,
        legacy_allocation_fraction=legacy_allocation,
        shadow_allocation_fraction=shadow_allocation,
        legacy_vix_multiplier=vix_multiplier,
        shadow_vix_multiplier=proposed_vix_multiplier,
        hard_gate_failures=failures,
        rows=rows,
    )
