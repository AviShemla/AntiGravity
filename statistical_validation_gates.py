"""Frozen statistical validation gates for stock and ETF research evidence.

The package evaluates already-computed evidence. It does not fit models, read or
write databases, promote data, create recommendations or orders, or control
services. Bayesian posterior outputs remain stochastic and are always retained;
validation determines only whether shadow sizing may be considered and whether
a comparative sizing reduction is warranted.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics
from stock_prediction_eligibility import ComparisonRow, EligibilityComparison, PredictionEvidence


@dataclass(frozen=True)
class WalkForwardEvidence:
    fold_count: int
    oos_observation_count: int
    embargo_sessions: int
    train_test_overlap_count: int


@dataclass(frozen=True)
class CalibrationEvidence:
    model_brier: float
    naive_brier: float
    model_log_loss: float
    naive_log_loss: float
    expected_calibration_error: float


@dataclass(frozen=True)
class ComparativeEvidence:
    model_net_return_pp: float
    simple_baseline_net_return_pp: float
    arena_median_net_return_pp: float
    model_max_drawdown_pp: float
    arena_median_max_drawdown_pp: float


@dataclass(frozen=True)
class CostDrawdownEvidence:
    gross_return_pp: float
    total_transaction_cost_pp: float
    net_return_pp: float
    stress_net_return_pp: float
    turnover_fraction: float
    max_drawdown_pp: float


@dataclass(frozen=True)
class LineageEvidence:
    exact_market_snapshot_id: str
    exact_universe_snapshot_id: str
    exact_model_run_id: str
    source_session_aligned: bool
    input_checksums_match: bool
    point_in_time_features_only: bool
    provider_lineage_complete: bool
    stock_prior_lineage_complete: bool | None = None


@dataclass(frozen=True)
class FrozenValidationPolicy:
    max_rhat: float = 1.05
    min_ess_bulk: float = 200.0
    min_ess_tail: float = 100.0
    min_ebfmi: float = 0.20
    max_divergences: int = 0
    max_tree_depth_saturation_fraction: float = 0.01
    min_chains: int = 2
    min_walk_forward_folds: int = 3
    min_oos_observations: int = 30
    min_embargo_sessions: int = 1
    max_expected_calibration_error: float = 0.10
    max_drawdown_pp: float = 20.0
    minimum_stress_net_return_pp: float = 0.0
    comparative_failure_multiplier: float = 0.50
    minimum_comparative_multiplier: float = 0.25


@dataclass(frozen=True)
class ValidationGate:
    name: str
    severity: str
    passed: bool
    measured: str
    threshold: str
    failure_reason: str | None = None


@dataclass(frozen=True)
class StatisticalValidationReview:
    raw_prediction: PredictionEvidence
    research_visible: bool
    hard_gate_passed: bool
    shadow_sizing_eligible: bool
    comparative_sizing_multiplier: float
    gates: tuple[ValidationGate, ...]
    hard_failures: tuple[str, ...]
    sizing_warnings: tuple[str, ...]


@dataclass(frozen=True)
class PredictionEligibilityReviewTable:
    raw_prediction: PredictionEvidence
    validation_review: StatisticalValidationReview
    existing_comparison: EligibilityComparison
    rows: tuple[ComparisonRow, ...]


def _finite(values: tuple[float, ...], label: str) -> None:
    if not all(isfinite(float(value)) for value in values):
        raise LineageError(f"{label} contains non-finite evidence.")


def _gate(
    name: str,
    severity: str,
    passed: bool,
    measured: str,
    threshold: str,
    failure_reason: str,
) -> ValidationGate:
    if severity not in {"HARD", "SIZING"}:
        raise LineageError("Validation gate severity must be HARD or SIZING.")
    return ValidationGate(
        name=name,
        severity=severity,
        passed=passed,
        measured=measured,
        threshold=threshold,
        failure_reason=None if passed else failure_reason,
    )


def evaluate_statistical_validation(
    *,
    raw_prediction: PredictionEvidence,
    diagnostics: SamplerDiagnostics,
    walk_forward: WalkForwardEvidence,
    calibration: CalibrationEvidence,
    comparative: ComparativeEvidence,
    costs: CostDrawdownEvidence,
    lineage: LineageEvidence,
    asset_class: str,
    policy: FrozenValidationPolicy = FrozenValidationPolicy(),
) -> StatisticalValidationReview:
    """Evaluate fixed research gates without changing the Bayesian posterior."""
    normalized_asset = asset_class.strip().upper()
    if normalized_asset not in {"STOCK", "ETF"}:
        raise LineageError("Statistical validation supports STOCK or ETF evidence.")
    _finite(
        (
            raw_prediction.probability_up_mean,
            raw_prediction.probability_up_q05,
            raw_prediction.probability_up_q95,
            raw_prediction.expected_return_pp,
            raw_prediction.expected_risk_pp,
        ),
        "Raw prediction",
    )
    if not (
        0.0 <= raw_prediction.probability_up_q05
        <= raw_prediction.probability_up_mean
        <= raw_prediction.probability_up_q95
        <= 1.0
    ):
        raise LineageError("Raw Bayesian probability interval is invalid.")
    _finite(
        (
            diagnostics.max_rhat,
            diagnostics.min_ess_bulk,
            diagnostics.min_ess_tail,
            diagnostics.min_bfmi,
            diagnostics.tree_depth_saturation_fraction,
            calibration.model_brier,
            calibration.naive_brier,
            calibration.model_log_loss,
            calibration.naive_log_loss,
            calibration.expected_calibration_error,
            comparative.model_net_return_pp,
            comparative.simple_baseline_net_return_pp,
            comparative.arena_median_net_return_pp,
            comparative.model_max_drawdown_pp,
            comparative.arena_median_max_drawdown_pp,
            costs.gross_return_pp,
            costs.total_transaction_cost_pp,
            costs.net_return_pp,
            costs.stress_net_return_pp,
            costs.turnover_fraction,
            costs.max_drawdown_pp,
        ),
        "Statistical validation",
    )
    if any(
        value < 0.0
        for value in (
            calibration.model_brier,
            calibration.naive_brier,
            calibration.model_log_loss,
            calibration.naive_log_loss,
            calibration.expected_calibration_error,
            comparative.model_max_drawdown_pp,
            comparative.arena_median_max_drawdown_pp,
            costs.total_transaction_cost_pp,
            costs.turnover_fraction,
            costs.max_drawdown_pp,
        )
    ):
        raise LineageError("Loss, cost, turnover, and drawdown magnitudes cannot be negative.")

    sampler_pass = all(
        (
            diagnostics.chains >= policy.min_chains,
            diagnostics.max_rhat <= policy.max_rhat,
            diagnostics.min_ess_bulk >= policy.min_ess_bulk,
            diagnostics.min_ess_tail >= policy.min_ess_tail,
            diagnostics.min_bfmi >= policy.min_ebfmi,
            diagnostics.divergences <= policy.max_divergences,
            diagnostics.tree_depth_saturation_fraction
            <= policy.max_tree_depth_saturation_fraction,
        )
    )
    walk_forward_pass = all(
        (
            walk_forward.fold_count >= policy.min_walk_forward_folds,
            walk_forward.oos_observation_count >= policy.min_oos_observations,
            walk_forward.embargo_sessions >= policy.min_embargo_sessions,
            walk_forward.train_test_overlap_count == 0,
        )
    )
    calibration_pass = all(
        (
            calibration.model_brier < calibration.naive_brier,
            calibration.model_log_loss < calibration.naive_log_loss,
            calibration.expected_calibration_error
            <= policy.max_expected_calibration_error,
        )
    )
    lineage_required = all(
        (
            bool(lineage.exact_market_snapshot_id),
            bool(lineage.exact_universe_snapshot_id),
            bool(lineage.exact_model_run_id),
            lineage.source_session_aligned,
            lineage.input_checksums_match,
            lineage.point_in_time_features_only,
            lineage.provider_lineage_complete,
        )
    )
    if normalized_asset == "ETF":
        lineage_required = lineage_required and lineage.stock_prior_lineage_complete is True
    cost_risk_pass = all(
        (
            abs((costs.gross_return_pp - costs.total_transaction_cost_pp) - costs.net_return_pp)
            <= 1e-9,
            costs.stress_net_return_pp > policy.minimum_stress_net_return_pp,
            costs.max_drawdown_pp <= policy.max_drawdown_pp,
        )
    )
    baseline_pass = comparative.model_net_return_pp > comparative.simple_baseline_net_return_pp
    arena_pass = all(
        (
            comparative.model_net_return_pp >= comparative.arena_median_net_return_pp,
            comparative.model_max_drawdown_pp
            <= comparative.arena_median_max_drawdown_pp,
        )
    )

    gates = (
        _gate(
            "Bayesian convergence",
            "HARD",
            sampler_pass,
            (
                f"chains={diagnostics.chains},rhat={diagnostics.max_rhat:.4f},"
                f"ess_bulk={diagnostics.min_ess_bulk:.1f},"
                f"ess_tail={diagnostics.min_ess_tail:.1f},"
                f"ebfmi={diagnostics.min_bfmi:.4f},"
                f"divergences={diagnostics.divergences},"
                f"tree_depth_fraction={diagnostics.tree_depth_saturation_fraction:.4f}"
            ),
            (
                f"chains>={policy.min_chains},rhat<={policy.max_rhat},"
                f"ess_bulk>={policy.min_ess_bulk},ess_tail>={policy.min_ess_tail},"
                f"ebfmi>={policy.min_ebfmi},divergences<={policy.max_divergences},"
                f"tree_depth_fraction<={policy.max_tree_depth_saturation_fraction}"
            ),
            "BAYESIAN_CONVERGENCE_FAILED",
        ),
        _gate(
            "Walk-forward/OOS design",
            "HARD",
            walk_forward_pass,
            (
                f"folds={walk_forward.fold_count},"
                f"oos={walk_forward.oos_observation_count},"
                f"embargo={walk_forward.embargo_sessions},"
                f"overlap={walk_forward.train_test_overlap_count}"
            ),
            (
                f"folds>={policy.min_walk_forward_folds},"
                f"oos>={policy.min_oos_observations},"
                f"embargo>={policy.min_embargo_sessions},overlap=0"
            ),
            "WALK_FORWARD_OOS_FAILED",
        ),
        _gate(
            "Probability calibration",
            "HARD",
            calibration_pass,
            (
                f"brier={calibration.model_brier:.6f} vs {calibration.naive_brier:.6f},"
                f"log_loss={calibration.model_log_loss:.6f} vs "
                f"{calibration.naive_log_loss:.6f},"
                f"ece={calibration.expected_calibration_error:.6f}"
            ),
            (
                "model brier/log-loss strictly better than naive; "
                f"ece<={policy.max_expected_calibration_error}"
            ),
            "PROBABILITY_CALIBRATION_FAILED",
        ),
        _gate(
            "Immutable lineage",
            "HARD",
            lineage_required,
            (
                f"market={bool(lineage.exact_market_snapshot_id)},"
                f"universe={bool(lineage.exact_universe_snapshot_id)},"
                f"run={bool(lineage.exact_model_run_id)},"
                f"session={lineage.source_session_aligned},"
                f"checksums={lineage.input_checksums_match},"
                f"point_in_time={lineage.point_in_time_features_only},"
                f"provider={lineage.provider_lineage_complete},"
                f"stock_prior={lineage.stock_prior_lineage_complete}"
            ),
            "all exact lineage fields true; ETF stock_prior_lineage_complete=true",
            "IMMUTABLE_LINEAGE_FAILED",
        ),
        _gate(
            "Costs and drawdown",
            "HARD",
            cost_risk_pass,
            (
                f"gross={costs.gross_return_pp:.6f}pp,"
                f"cost={costs.total_transaction_cost_pp:.6f}pp,"
                f"net={costs.net_return_pp:.6f}pp,"
                f"stress_net={costs.stress_net_return_pp:.6f}pp,"
                f"drawdown={costs.max_drawdown_pp:.6f}pp"
            ),
            (
                "gross-cost=net; "
                f"stress_net>{policy.minimum_stress_net_return_pp}pp;"
                f"drawdown<={policy.max_drawdown_pp}pp"
            ),
            "COST_DRAWDOWN_FAILED",
        ),
        _gate(
            "Simple baseline comparison",
            "SIZING",
            baseline_pass,
            (
                f"model_net={comparative.model_net_return_pp:.6f}pp,"
                f"baseline_net={comparative.simple_baseline_net_return_pp:.6f}pp"
            ),
            "model net return > simple baseline net return",
            "SIMPLE_BASELINE_NOT_BEATEN",
        ),
        _gate(
            "Arena median comparison",
            "SIZING",
            arena_pass,
            (
                f"model_net={comparative.model_net_return_pp:.6f}pp,"
                f"arena_net={comparative.arena_median_net_return_pp:.6f}pp,"
                f"model_dd={comparative.model_max_drawdown_pp:.6f}pp,"
                f"arena_dd={comparative.arena_median_max_drawdown_pp:.6f}pp"
            ),
            "model net >= Arena median and model drawdown <= Arena median",
            "ARENA_MEDIAN_NOT_MET",
        ),
    )
    hard_failures = tuple(
        gate.failure_reason
        for gate in gates
        if gate.severity == "HARD" and not gate.passed and gate.failure_reason
    )
    sizing_warnings = tuple(
        gate.failure_reason
        for gate in gates
        if gate.severity == "SIZING" and not gate.passed and gate.failure_reason
    )
    hard_pass = not hard_failures
    multiplier = 0.0
    if hard_pass:
        multiplier = max(
            policy.minimum_comparative_multiplier,
            policy.comparative_failure_multiplier ** len(sizing_warnings),
        )
    return StatisticalValidationReview(
        raw_prediction=raw_prediction,
        research_visible=True,
        hard_gate_passed=hard_pass,
        shadow_sizing_eligible=hard_pass,
        comparative_sizing_multiplier=multiplier,
        gates=gates,
        hard_failures=hard_failures,
        sizing_warnings=sizing_warnings,
    )


def build_ag_codex_comparison_table(
    *,
    raw_prediction: PredictionEvidence,
    validation_review: StatisticalValidationReview,
    existing_comparison: EligibilityComparison,
) -> PredictionEligibilityReviewTable:
    """Append statistical-review rows to the existing AG/Codex comparison."""
    if validation_review.raw_prediction != raw_prediction:
        raise LineageError("Validation and eligibility tables reference different predictions.")
    hard_result = (
        "PASS"
        if validation_review.hard_gate_passed
        else ",".join(validation_review.hard_failures)
    )
    warning_result = (
        "PASS"
        if not validation_review.sizing_warnings
        else ",".join(validation_review.sizing_warnings)
    )
    extra = (
        ComparisonRow(
            criterion="Statistical validation",
            ag_rule="AG production criteria were not proven to include this complete gate package.",
            ag_result="UNPROVEN",
            codex_rule=(
                "Require convergence, embargoed walk-forward/OOS, calibration, immutable "
                "lineage, and cost/drawdown reconciliation."
            ),
            codex_result=hard_result,
            balanced_rule="Same hard research-integrity gates; raw posterior remains visible.",
            balanced_result=hard_result,
        ),
        ComparisonRow(
            criterion="Baseline and Arena sizing",
            ag_rule="AG did not prove a systematic baseline/Arena sizing adjustment here.",
            ag_result="UNPROVEN",
            codex_rule="Comparative misses reduce shadow sizing; they do not erase the posterior.",
            codex_result=(
                f"multiplier={validation_review.comparative_sizing_multiplier:.6f};"
                f"{warning_result}"
            ),
            balanced_rule="Use the same measured research-only sizing multiplier.",
            balanced_result=(
                f"multiplier={validation_review.comparative_sizing_multiplier:.6f}"
            ),
        ),
    )
    return PredictionEligibilityReviewTable(
        raw_prediction=raw_prediction,
        validation_review=validation_review,
        existing_comparison=existing_comparison,
        rows=existing_comparison.rows + extra,
    )
