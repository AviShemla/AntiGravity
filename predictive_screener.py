"""Leakage-resistant predictive lead/lag screening primitives.

This module intentionally describes observational relationships as predictive,
not causal. Feature discovery is performed only on training data. Outer test
folds are separated from training by an embargo equal to the maximum lag.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, log, sqrt
from statistics import NormalDist
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from model_lineage import LineageError


@dataclass(frozen=True)
class ScreeningConfig:
    min_train_sessions: int = 504
    training_window_sessions: int | None = None
    test_sessions: int = 63
    outer_folds: int = 4
    purge_sessions: int = 5
    min_oos_sessions: int = 200
    min_depth: int = 3
    max_depth: int = 5
    max_technical_features: int = 3
    familywise_alpha: float = 0.01
    max_calibration_error: float = 0.12
    min_brier_improvement: float = 0.005
    min_fit_observations: int = 100
    eligibility_hypotheses: int = 1

    def validate(self) -> None:
        if self.min_train_sessions < 126:
            raise LineageError("Screener requires at least 126 available training sessions.")
        if self.training_window_sessions is not None:
            if self.training_window_sessions < 126:
                raise LineageError("A rolling training window must contain at least 126 sessions.")
            if self.training_window_sessions > self.min_train_sessions:
                raise LineageError("Rolling training window exceeds the required available history.")
        if self.test_sessions < 20 or self.outer_folds < 2:
            raise LineageError("Screener requires at least two meaningful outer folds.")
        if self.purge_sessions < self.max_depth:
            raise LineageError("Purge/embargo must be at least the maximum lag depth.")
        if not 1 <= self.min_depth <= self.max_depth <= 5:
            raise LineageError("Predictive lag depth must be between 1 and 5.")
        if self.min_oos_sessions > self.test_sessions * self.outer_folds:
            raise LineageError("Minimum OOS sessions exceed the configured outer test capacity.")
        if not 0 < self.familywise_alpha < 0.1:
            raise LineageError("Familywise alpha is outside the supported safety range.")
        if self.min_fit_observations < 50:
            raise LineageError("Model fits require at least 50 completed observations.")
        if self.eligibility_hypotheses < 1:
            raise LineageError("Eligibility hypothesis count must be positive.")


@dataclass(frozen=True)
class FeatureSpec:
    depth: int
    lag_tickers: tuple[str, ...]
    technical_features: tuple[str, ...]


@dataclass(frozen=True)
class FoldWindow:
    fold_number: int
    train_positions: np.ndarray
    test_positions: np.ndarray


@dataclass(frozen=True)
class MetricSet:
    accuracy: float
    brier: float
    log_loss: float
    calibration_error: float


@dataclass(frozen=True)
class FoldEvaluation:
    fold_number: int
    train_start_date: str
    train_end_date: str
    test_start_date: str
    test_end_date: str
    purge_sessions: int
    spec: FeatureSpec
    model_metrics: MetricSet
    majority_accuracy: float
    own_lag_metrics: MetricSet
    y_true: tuple[int, ...]
    probabilities: tuple[float, ...]
    own_lag_probabilities: tuple[float, ...]


@dataclass(frozen=True)
class TickerEvaluation:
    ticker: str
    eligible: bool
    rejection_reasons: tuple[str, ...]
    model_metrics: MetricSet
    majority_accuracy: float
    own_lag_metrics: MetricSet
    accuracy_ci_low: float
    accuracy_ci_high: float
    final_spec: FeatureSpec | None
    folds: tuple[FoldEvaluation, ...]


def expanding_windows(index: pd.Index, config: ScreeningConfig) -> list[FoldWindow]:
    config.validate()
    total_required = (
        config.min_train_sessions
        + config.purge_sessions
        + config.test_sessions * config.outer_folds
    )
    if len(index) < total_required:
        raise LineageError(
            f"Only {len(index)} aligned sessions are available; {total_required} are required."
        )
    first_test_start = len(index) - config.test_sessions * config.outer_folds
    windows: list[FoldWindow] = []
    for fold in range(config.outer_folds):
        test_start = first_test_start + fold * config.test_sessions
        train_end = test_start - config.purge_sessions
        test_end = test_start + config.test_sessions
        if train_end < config.min_train_sessions:
            raise LineageError("A walk-forward fold has insufficient training history.")
        train_start = 0
        if config.training_window_sessions is not None:
            train_start = train_end - config.training_window_sessions
            if train_start < 0:
                raise LineageError("A walk-forward fold lacks the requested rolling history.")
        windows.append(
            FoldWindow(
                fold_number=fold + 1,
                train_positions=np.arange(train_start, train_end, dtype=int),
                test_positions=np.arange(test_start, test_end, dtype=int),
            )
        )
    return windows


def _normal_two_sided_pvalue_from_correlation(correlation: float, samples: int) -> float:
    """Conservative Fisher-z normal approximation used only for screening."""
    if samples <= 3 or not np.isfinite(correlation):
        return 1.0
    clipped = float(np.clip(correlation, -0.999999, 0.999999))
    fisher_z = 0.5 * log((1.0 + clipped) / (1.0 - clipped)) * sqrt(samples - 3)
    return max(0.0, min(1.0, 1.0 - erf(abs(fisher_z) / sqrt(2.0))))


def _select_one_bonferroni(target: pd.Series, candidates: pd.DataFrame, alpha: float) -> str | None:
    usable = candidates.loc[target.notna()].copy()
    target = target.loc[usable.index]
    correlations = usable.corrwith(target).dropna()
    if correlations.empty:
        return None
    threshold = alpha / len(correlations)
    ordered = correlations.abs().sort_values(ascending=False)
    for name in ordered.index:
        aligned = pd.concat([target, usable[name]], axis=1).dropna()
        if len(aligned) < 50:
            continue
        corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
        if _normal_two_sided_pvalue_from_correlation(corr, len(aligned)) <= threshold:
            return str(name)
    return None


def benjamini_hochberg_rejections(
    pvalues: dict[str, float], *, false_discovery_rate: float
) -> tuple[str, ...]:
    """Return the deterministically ordered hypotheses accepted by BH-FDR.

    This helper is research-only plumbing. Promotion policy remains separate,
    and the complete hypothesis family must be recorded by the caller.
    """
    if not 0.0 < false_discovery_rate < 1.0:
        raise LineageError("False-discovery rate must be between zero and one.")
    cleaned = {
        str(name): float(value)
        for name, value in pvalues.items()
        if np.isfinite(value) and 0.0 <= float(value) <= 1.0
    }
    if len(cleaned) != len(pvalues):
        raise LineageError("BH-FDR input contains an invalid p-value.")
    ordered = sorted(cleaned.items(), key=lambda item: (item[1], item[0]))
    accepted_count = 0
    hypotheses = len(ordered)
    for rank, (_name, pvalue) in enumerate(ordered, start=1):
        if pvalue <= false_discovery_rate * rank / hypotheses:
            accepted_count = rank
    return tuple(name for name, _value in ordered[:accepted_count])


def _select_one_bh_fdr(
    target: pd.Series, candidates: pd.DataFrame, false_discovery_rate: float
) -> str | None:
    usable = candidates.loc[target.notna()].copy()
    target = target.loc[usable.index]
    evidence: dict[str, tuple[float, float]] = {}
    for name in usable.columns:
        aligned = pd.concat([target, usable[name]], axis=1).dropna()
        if len(aligned) < 50:
            continue
        correlation = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
        pvalue = _normal_two_sided_pvalue_from_correlation(correlation, len(aligned))
        evidence[str(name)] = (pvalue, abs(correlation))
    if not evidence:
        return None
    accepted = benjamini_hochberg_rejections(
        {name: values[0] for name, values in evidence.items()},
        false_discovery_rate=false_discovery_rate,
    )
    if not accepted:
        return None
    return min(accepted, key=lambda name: (-evidence[name][1], evidence[name][0], name))


def discover_feature_spec(
    *,
    ticker: str,
    returns: pd.DataFrame,
    technical_features: pd.DataFrame,
    train_positions: Iterable[int],
    depth: int,
    familywise_alpha: float,
    max_technical_features: int,
    selection_method: str = "bonferroni",
) -> FeatureSpec | None:
    """Discover one feature specification using training rows only."""
    positions = np.asarray(list(train_positions), dtype=int)
    if depth < 1 or depth > 5 or len(positions) < 50:
        return None
    train_returns = returns.iloc[positions]
    target = train_returns[ticker]
    if selection_method == "bonferroni":
        selector = _select_one_bonferroni
    elif selection_method == "bh_fdr":
        selector = _select_one_bh_fdr
    else:
        raise LineageError(f"Unsupported feature-selection method: {selection_method!r}.")
    chain: list[str] = []
    current_target = target
    for _step in range(1, depth + 1):
        chosen = selector(
            current_target,
            train_returns.shift(1),
            familywise_alpha,
        )
        if chosen is None:
            return None
        chain.append(chosen)
        current_target = train_returns[chosen]

    tech_names: list[str] = []
    if not technical_features.empty and max_technical_features:
        train_technical = technical_features.iloc[positions]
        remaining = train_technical.copy()
        for _ in range(max_technical_features):
            chosen = selector(target, remaining, familywise_alpha)
            if chosen is None:
                break
            tech_names.append(chosen)
            remaining = remaining.drop(columns=[chosen])
    return FeatureSpec(depth=depth, lag_tickers=tuple(chain), technical_features=tuple(tech_names))


def build_design_matrix(
    *,
    ticker: str,
    returns: pd.DataFrame,
    technical_features: pd.DataFrame,
    spec: FeatureSpec,
) -> tuple[pd.DataFrame, pd.Series]:
    columns: dict[str, pd.Series] = {}
    for lag, lag_ticker in enumerate(spec.lag_tickers, start=1):
        columns[f"return__{lag_ticker}__lag{lag}"] = returns[lag_ticker].shift(lag)
    for name in spec.technical_features:
        columns[f"technical__{name}__lag1"] = technical_features[name].shift(1)
    design = pd.DataFrame(columns, index=returns.index)
    target = (returns[ticker] > 0).astype(float).where(returns[ticker].notna())
    return design, target


def fit_probabilities(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    *,
    min_fit_observations: int = 100,
) -> np.ndarray:
    joined = pd.concat([X_train, y_train.rename("target")], axis=1).dropna()
    if len(joined) < min_fit_observations or joined["target"].nunique() != 2:
        raise LineageError("Training fold lacks sufficient two-class observations.")
    test = X_test.dropna()
    if len(test) != len(X_test):
        raise LineageError("Test fold contains missing selected features.")
    train_x = joined[X_train.columns].to_numpy(dtype=float)
    train_y = joined["target"].to_numpy(dtype=int)
    test_x = test.to_numpy(dtype=float)
    means = train_x.mean(axis=0)
    scales = train_x.std(axis=0)
    scales[scales < 1e-12] = 1.0
    model = LogisticRegression(C=1.0, random_state=42, max_iter=1000)
    model.fit((train_x - means) / scales, train_y)
    return model.predict_proba((test_x - means) / scales)[:, 1]


def score_probabilities(y_true: Iterable[int], probabilities: Iterable[float]) -> MetricSet:
    y = np.asarray(list(y_true), dtype=int)
    p = np.asarray(list(probabilities), dtype=float)
    if len(y) == 0 or len(y) != len(p) or not np.isfinite(p).all():
        raise LineageError("Invalid probability evaluation input.")
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    predictions = (p >= 0.5).astype(int)
    bins = np.minimum((p * 10).astype(int), 9)
    calibration = 0.0
    for bin_number in range(10):
        mask = bins == bin_number
        if mask.any():
            calibration += mask.mean() * abs(float(y[mask].mean() - p[mask].mean()))
    return MetricSet(
        accuracy=float((predictions == y).mean()),
        brier=float(np.mean((p - y) ** 2)),
        log_loss=float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        calibration_error=float(calibration),
    )


def wilson_interval(successes: int, observations: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if observations <= 0 or successes < 0 or successes > observations:
        raise LineageError("Invalid Wilson interval counts.")
    rate = successes / observations
    denominator = 1.0 + z * z / observations
    centre = (rate + z * z / (2 * observations)) / denominator
    margin = z * sqrt((rate * (1 - rate) + z * z / (4 * observations)) / observations) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def eligibility_reasons(
    *,
    oos_sessions: int,
    successes: int,
    model: MetricSet,
    majority_accuracy: float,
    own_lag: MetricSet,
    config: ScreeningConfig,
) -> list[str]:
    reasons: list[str] = []
    if oos_sessions < config.min_oos_sessions:
        reasons.append("INSUFFICIENT_OOS_SESSIONS")
    adjusted_alpha = config.familywise_alpha / config.eligibility_hypotheses
    z = NormalDist().inv_cdf(1.0 - adjusted_alpha / 2.0)
    ci_low, _ = wilson_interval(successes, oos_sessions, z=z)
    if ci_low <= majority_accuracy:
        reasons.append("ACCURACY_CI_DOES_NOT_BEAT_MAJORITY")
    if own_lag.brier - model.brier < config.min_brier_improvement:
        reasons.append("BRIER_DOES_NOT_BEAT_OWN_LAG")
    if model.log_loss >= own_lag.log_loss:
        reasons.append("LOG_LOSS_DOES_NOT_BEAT_OWN_LAG")
    if model.calibration_error > config.max_calibration_error:
        reasons.append("CALIBRATION_ERROR_TOO_HIGH")
    return reasons


def _date_text(value: object) -> str:
    converted = pd.Timestamp(value)
    return converted.date().isoformat()


def _fit_and_score_spec(
    *,
    ticker: str,
    returns: pd.DataFrame,
    technical_features: pd.DataFrame,
    spec: FeatureSpec,
    train_positions: np.ndarray,
    test_positions: np.ndarray,
    min_fit_observations: int,
) -> tuple[MetricSet, np.ndarray, np.ndarray]:
    X, y = build_design_matrix(
        ticker=ticker,
        returns=returns,
        technical_features=technical_features,
        spec=spec,
    )
    y_test = y.iloc[test_positions]
    if y_test.isna().any():
        raise LineageError("Outer test target contains missing returns.")
    probabilities = fit_probabilities(
        X.iloc[train_positions],
        y.iloc[train_positions],
        X.iloc[test_positions],
        min_fit_observations=min_fit_observations,
    )
    truth = y_test.to_numpy(dtype=int)
    return score_probabilities(truth, probabilities), probabilities, truth


def _select_depth_inside_training(
    *,
    ticker: str,
    returns: pd.DataFrame,
    technical_features: pd.DataFrame,
    outer_train_positions: np.ndarray,
    config: ScreeningConfig,
) -> int | None:
    """Choose depth on a purged inner holdout wholly inside outer training."""
    inner_test_sessions = min(config.test_sessions, max(20, len(outer_train_positions) // 5))
    inner_test_start = len(outer_train_positions) - inner_test_sessions
    inner_train_end = inner_test_start - config.purge_sessions
    if inner_train_end < config.min_fit_observations + config.max_depth:
        return None
    inner_train = outer_train_positions[:inner_train_end]
    inner_test = outer_train_positions[inner_test_start:]
    candidates: list[tuple[float, float, int]] = []
    for depth in range(config.min_depth, config.max_depth + 1):
        spec = discover_feature_spec(
            ticker=ticker,
            returns=returns,
            technical_features=technical_features,
            train_positions=inner_train,
            depth=depth,
            familywise_alpha=config.familywise_alpha,
            max_technical_features=config.max_technical_features,
        )
        if spec is None:
            continue
        try:
            metrics, _probabilities, _truth = _fit_and_score_spec(
                ticker=ticker,
                returns=returns,
                technical_features=technical_features,
                spec=spec,
                train_positions=inner_train,
                test_positions=inner_test,
                min_fit_observations=config.min_fit_observations,
            )
        except LineageError:
            continue
        candidates.append((metrics.brier, metrics.log_loss, depth))
    if not candidates:
        return None
    return min(candidates)[2]


def evaluate_ticker(
    *,
    ticker: str,
    returns: pd.DataFrame,
    technical_features: pd.DataFrame,
    config: ScreeningConfig,
    fixed_spec: FeatureSpec | None = None,
) -> TickerEvaluation:
    """Nested, purged walk-forward evaluation for one ticker.

    By default, depth is selected on an inner holdout and feature discovery is
    repeated using only each outer training fold.  A pre-registered fixed_spec
    bypasses discovery so a simple, hypothesis-defined baseline can be tested
    without data-driven feature selection.  The outer fold is never used for
    either path.
    """
    config.validate()
    if ticker not in returns.columns:
        raise LineageError(f"Ticker {ticker!r} is missing from returns.")
    if not returns.index.equals(technical_features.index):
        raise LineageError("Return and technical-feature indexes are not aligned.")
    if fixed_spec is not None:
        missing_returns = sorted(set(fixed_spec.lag_tickers).difference(returns.columns))
        missing_technical = sorted(
            set(fixed_spec.technical_features).difference(technical_features.columns)
        )
        if missing_returns or missing_technical:
            raise LineageError(
                f"Fixed specification is missing returns={missing_returns}, "
                f"technical={missing_technical}."
            )
    windows = expanding_windows(returns.index, config)
    fold_results: list[FoldEvaluation] = []
    all_truth: list[int] = []
    all_probabilities: list[float] = []
    all_own_lag_probabilities: list[float] = []
    majority_correct = 0

    for window in windows:
        if fixed_spec is None:
            depth = _select_depth_inside_training(
                ticker=ticker,
                returns=returns,
                technical_features=technical_features,
                outer_train_positions=window.train_positions,
                config=config,
            )
            if depth is None:
                raise LineageError(f"No statistically admissible inner-fold specification for {ticker}.")
            spec = discover_feature_spec(
                ticker=ticker,
                returns=returns,
                technical_features=technical_features,
                train_positions=window.train_positions,
                depth=depth,
                familywise_alpha=config.familywise_alpha,
                max_technical_features=config.max_technical_features,
            )
            if spec is None:
                raise LineageError(f"No statistically admissible outer-fold specification for {ticker}.")
        else:
            spec = fixed_spec
        model_metrics, probabilities, truth = _fit_and_score_spec(
            ticker=ticker,
            returns=returns,
            technical_features=technical_features,
            spec=spec,
            train_positions=window.train_positions,
            test_positions=window.test_positions,
            min_fit_observations=config.min_fit_observations,
        )
        own_lag_spec = FeatureSpec(depth=1, lag_tickers=(ticker,), technical_features=())
        own_metrics, own_probabilities, own_truth = _fit_and_score_spec(
            ticker=ticker,
            returns=returns,
            technical_features=technical_features,
            spec=own_lag_spec,
            train_positions=window.train_positions,
            test_positions=window.test_positions,
            min_fit_observations=config.min_fit_observations,
        )
        if not np.array_equal(truth, own_truth):
            raise LineageError("Model and baseline outer targets are misaligned.")
        train_target = (returns[ticker].iloc[window.train_positions] > 0).astype(int)
        majority_class = int(train_target.mean() >= 0.5)
        fold_majority_accuracy = float((truth == majority_class).mean())
        majority_correct += int((truth == majority_class).sum())
        all_truth.extend(truth.tolist())
        all_probabilities.extend(probabilities.tolist())
        all_own_lag_probabilities.extend(own_probabilities.tolist())
        fold_results.append(
            FoldEvaluation(
                fold_number=window.fold_number,
                train_start_date=_date_text(returns.index[window.train_positions[0]]),
                train_end_date=_date_text(returns.index[window.train_positions[-1]]),
                test_start_date=_date_text(returns.index[window.test_positions[0]]),
                test_end_date=_date_text(returns.index[window.test_positions[-1]]),
                purge_sessions=config.purge_sessions,
                spec=spec,
                model_metrics=model_metrics,
                majority_accuracy=fold_majority_accuracy,
                own_lag_metrics=own_metrics,
                y_true=tuple(int(value) for value in truth),
                probabilities=tuple(float(value) for value in probabilities),
                own_lag_probabilities=tuple(float(value) for value in own_probabilities),
            )
        )

    aggregate = score_probabilities(all_truth, all_probabilities)
    aggregate_own = score_probabilities(all_truth, all_own_lag_probabilities)
    successes = int(((np.asarray(all_probabilities) >= 0.5) == np.asarray(all_truth)).sum())
    majority_accuracy = majority_correct / len(all_truth)
    reasons = eligibility_reasons(
        oos_sessions=len(all_truth),
        successes=successes,
        model=aggregate,
        majority_accuracy=majority_accuracy,
        own_lag=aggregate_own,
        config=config,
    )
    adjusted_alpha = config.familywise_alpha / config.eligibility_hypotheses
    eligibility_z = NormalDist().inv_cdf(1.0 - adjusted_alpha / 2.0)
    ci_low, ci_high = wilson_interval(successes, len(all_truth), z=eligibility_z)
    final_spec = fixed_spec
    if fixed_spec is None:
        final_depth = _select_depth_inside_training(
            ticker=ticker,
            returns=returns,
            technical_features=technical_features,
            outer_train_positions=np.arange(len(returns), dtype=int),
            config=config,
        )
        if final_depth is not None:
            final_spec = discover_feature_spec(
                ticker=ticker,
                returns=returns,
                technical_features=technical_features,
                train_positions=np.arange(len(returns), dtype=int),
                depth=final_depth,
                familywise_alpha=config.familywise_alpha,
                max_technical_features=config.max_technical_features,
            )
    if final_spec is None:
        reasons.append("NO_FINAL_ADMISSIBLE_SPECIFICATION")
    return TickerEvaluation(
        ticker=ticker,
        eligible=not reasons,
        rejection_reasons=tuple(reasons),
        model_metrics=aggregate,
        majority_accuracy=majority_accuracy,
        own_lag_metrics=aggregate_own,
        accuracy_ci_low=ci_low,
        accuracy_ci_high=ci_high,
        final_spec=final_spec,
        folds=tuple(fold_results),
    )
