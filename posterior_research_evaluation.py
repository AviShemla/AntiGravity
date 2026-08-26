"""Pure research evaluation for dated hierarchical posterior outcomes.

This module has no file, database, network, model-fitting, recommendation, or
order side effects.  It evaluates already-realized posterior forecasts using
explicit units and a complete portfolio panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite, log, sqrt
from typing import Iterable

from model_lineage import LineageError


@dataclass(frozen=True)
class PosteriorOutcome:
    leaf_id: str
    hierarchy_path: tuple[str, ...]
    prediction_date: date
    source_session_date: date
    probability_up: float
    probability_q05: float
    probability_q95: float
    expected_return_pp: float
    expected_return_std_pp: float
    realized_return_pp: float
    signed_allocation: float


@dataclass(frozen=True)
class EvaluationConfig:
    run_id: str
    portfolio_id: str
    round_trip_cost_bps: float
    calibration_bins: int = 10
    probability_clip: float = 1e-12


@dataclass(frozen=True)
class CalibrationMetrics:
    observations: int
    accuracy: float
    brier_score: float
    log_loss: float
    calibration_error: float
    expected_return_mae_pp: float
    expected_return_rmse_pp: float


@dataclass(frozen=True)
class PerformanceMetrics:
    sessions: int
    gross_turnover: float
    transaction_cost_pp_sum: float
    gross_total_return: float
    net_total_return: float
    max_drawdown: float


@dataclass(frozen=True)
class HierarchicalEvaluation:
    hierarchy_path: tuple[str, ...]
    calibration: CalibrationMetrics
    performance: PerformanceMetrics


@dataclass(frozen=True)
class PosteriorEvaluationReport:
    run_id: str
    portfolio_id: str
    probability_unit: str
    return_unit: str
    transaction_cost_unit: str
    nodes: tuple[HierarchicalEvaluation, ...]


def _validate_config(config: EvaluationConfig) -> None:
    if not config.run_id.strip() or not config.portfolio_id.strip():
        raise LineageError("Posterior evaluation requires run and portfolio identifiers.")
    if not isfinite(config.round_trip_cost_bps) or config.round_trip_cost_bps < 0.0:
        raise LineageError("Round-trip transaction cost must be finite and non-negative.")
    if config.calibration_bins < 2:
        raise LineageError("Posterior evaluation requires at least two calibration bins.")
    if not 0.0 < config.probability_clip < 0.5:
        raise LineageError("Probability clipping must lie strictly between zero and one half.")


def _validate_outcomes(rows: tuple[PosteriorOutcome, ...]) -> tuple[date, ...]:
    if not rows:
        raise LineageError("Posterior evaluation requires at least one outcome.")
    seen: set[tuple[str, date]] = set()
    leaves: set[str] = set()
    dates: set[date] = set()
    leaf_dates: dict[str, set[date]] = {}
    leaf_paths: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if not row.leaf_id.strip() or not row.hierarchy_path or any(
            not item.strip() for item in row.hierarchy_path
        ):
            raise LineageError("Every posterior outcome requires stable leaf and hierarchy identifiers.")
        key = (row.leaf_id, row.prediction_date)
        if key in seen:
            raise LineageError("Posterior evaluation contains a duplicate leaf/date outcome.")
        seen.add(key)
        if row.source_session_date >= row.prediction_date:
            raise LineageError("Posterior source session must precede its prediction date.")
        numeric = (
            row.probability_up,
            row.probability_q05,
            row.probability_q95,
            row.expected_return_pp,
            row.expected_return_std_pp,
            row.realized_return_pp,
            row.signed_allocation,
        )
        if not all(isfinite(value) for value in numeric):
            raise LineageError("Posterior evaluation evidence must be finite.")
        if not 0.0 <= row.probability_q05 <= row.probability_up <= row.probability_q95 <= 1.0:
            raise LineageError("Posterior probability interval is invalid.")
        if row.expected_return_std_pp < 0.0:
            raise LineageError("Expected-return posterior uncertainty cannot be negative.")
        if not -1.0 <= row.signed_allocation <= 1.0:
            raise LineageError("Signed allocation must be within [-1, 1].")
        if row.realized_return_pp <= -100.0:
            raise LineageError("Realized asset return must be greater than -100 percentage points.")
        existing_path = leaf_paths.setdefault(row.leaf_id, row.hierarchy_path)
        if existing_path != row.hierarchy_path:
            raise LineageError("A leaf cannot change hierarchy inside one evaluation report.")
        leaves.add(row.leaf_id)
        dates.add(row.prediction_date)
        leaf_dates.setdefault(row.leaf_id, set()).add(row.prediction_date)
    ordered_dates = tuple(sorted(dates))
    expected_dates = set(ordered_dates)
    if any(leaf_dates[leaf] != expected_dates for leaf in leaves):
        raise LineageError(
            "Transaction-cost evaluation requires an explicit complete leaf/date panel; "
            "include zero-allocation rows for inactive leaves."
        )
    for current_date in ordered_dates:
        gross_exposure = sum(
            abs(row.signed_allocation) for row in rows if row.prediction_date == current_date
        )
        if gross_exposure > 1.0 + 1e-12:
            raise LineageError("Portfolio gross allocation exceeds one.")
    return ordered_dates


def _calibration(rows: tuple[PosteriorOutcome, ...], config: EvaluationConfig) -> CalibrationMetrics:
    count = len(rows)
    probabilities = [row.probability_up for row in rows]
    outcomes = [1.0 if row.realized_return_pp > 0.0 else 0.0 for row in rows]
    accuracy = sum((probability >= 0.5) == bool(outcome) for probability, outcome in zip(probabilities, outcomes)) / count
    brier = sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes)) / count
    clipped = [min(1.0 - config.probability_clip, max(config.probability_clip, value)) for value in probabilities]
    log_loss = -sum(
        outcome * log(probability) + (1.0 - outcome) * log(1.0 - probability)
        for probability, outcome in zip(clipped, outcomes)
    ) / count
    calibration_error = 0.0
    for bin_index in range(config.calibration_bins):
        low = bin_index / config.calibration_bins
        high = (bin_index + 1) / config.calibration_bins
        indices = [
            index for index, probability in enumerate(probabilities)
            if low <= probability < high or (bin_index == config.calibration_bins - 1 and probability == 1.0)
        ]
        if indices:
            mean_probability = sum(probabilities[index] for index in indices) / len(indices)
            mean_outcome = sum(outcomes[index] for index in indices) / len(indices)
            calibration_error += len(indices) / count * abs(mean_probability - mean_outcome)
    errors = [row.expected_return_pp - row.realized_return_pp for row in rows]
    return CalibrationMetrics(
        observations=count,
        accuracy=float(accuracy),
        brier_score=float(brier),
        log_loss=float(log_loss),
        calibration_error=float(calibration_error),
        expected_return_mae_pp=float(sum(abs(error) for error in errors) / count),
        expected_return_rmse_pp=float(sqrt(sum(error * error for error in errors) / count)),
    )


def _performance(
    rows: tuple[PosteriorOutcome, ...],
    dates: tuple[date, ...],
    config: EvaluationConfig,
) -> PerformanceMetrics:
    prior_allocations: dict[str, float] = {}
    gross_equity = 1.0
    net_equity = 1.0
    net_peak = 1.0
    max_drawdown = 0.0
    turnover_total = 0.0
    cost_pp_total = 0.0
    for current_date in dates:
        dated = [row for row in rows if row.prediction_date == current_date]
        gross_return_pp = sum(
            row.signed_allocation * row.realized_return_pp for row in dated
        )
        turnover = sum(
            abs(row.signed_allocation - prior_allocations.get(row.leaf_id, 0.0))
            for row in dated
        )
        # Half the declared round-trip cost is charged on each unit change.
        cost_pp = turnover * config.round_trip_cost_bps / 200.0
        net_return_pp = gross_return_pp - cost_pp
        if gross_return_pp <= -100.0 or net_return_pp <= -100.0:
            raise LineageError("Portfolio return would make the research equity path non-positive.")
        gross_equity *= 1.0 + gross_return_pp / 100.0
        net_equity *= 1.0 + net_return_pp / 100.0
        net_peak = max(net_peak, net_equity)
        max_drawdown = max(max_drawdown, 1.0 - net_equity / net_peak)
        turnover_total += turnover
        cost_pp_total += cost_pp
        prior_allocations.update({row.leaf_id: row.signed_allocation for row in dated})
    return PerformanceMetrics(
        sessions=len(dates),
        gross_turnover=float(turnover_total),
        transaction_cost_pp_sum=float(cost_pp_total),
        gross_total_return=float(gross_equity - 1.0),
        net_total_return=float(net_equity - 1.0),
        max_drawdown=float(max_drawdown),
    )


def evaluate_hierarchical_posteriors(
    outcomes: Iterable[PosteriorOutcome],
    config: EvaluationConfig,
) -> PosteriorEvaluationReport:
    """Evaluate immutable posterior outcomes at every hierarchy prefix.

    The input must be a complete leaf/date panel.  A final close transaction is
    charged only when the caller supplies a dated zero-allocation outcome.
    """
    _validate_config(config)
    rows = tuple(outcomes)
    all_dates = _validate_outcomes(rows)
    paths: set[tuple[str, ...]] = {()}
    for row in rows:
        paths.update(row.hierarchy_path[:depth] for depth in range(1, len(row.hierarchy_path) + 1))
    nodes: list[HierarchicalEvaluation] = []
    for path in sorted(paths, key=lambda value: (len(value), value)):
        selected = tuple(row for row in rows if row.hierarchy_path[:len(path)] == path)
        selected_dates = tuple(current_date for current_date in all_dates if any(
            row.prediction_date == current_date for row in selected
        ))
        nodes.append(HierarchicalEvaluation(
            hierarchy_path=path,
            calibration=_calibration(selected, config),
            performance=_performance(selected, selected_dates, config),
        ))
    return PosteriorEvaluationReport(
        run_id=config.run_id,
        portfolio_id=config.portfolio_id,
        probability_unit="fraction",
        return_unit="fraction_compounded_from_percentage_points",
        transaction_cost_unit="basis_points_round_trip_converted_to_percentage_points",
        nodes=tuple(nodes),
    )
