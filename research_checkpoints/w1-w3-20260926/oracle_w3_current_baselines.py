"""Lifecycle-aware simple baselines for the frozen W2 Oracle input."""

from __future__ import annotations

import math
from typing import Iterable


TRAIN, PURGE, FOLDS, TEST = 289, 7, 4, 30
MIN_ROWS = TRAIN + PURGE + FOLDS * TEST


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, value))))


def _fit_lag1_logistic(train: list[float]) -> tuple[float, float]:
    intercept = 0.0
    coefficient = 0.0
    pairs = [(train[index - 1], 1.0 if train[index] > 0.0 else 0.0) for index in range(1, len(train))]
    for _ in range(200):
        gradient_i = gradient_b = 0.0
        for lag, target in pairs:
            error = _sigmoid(intercept + coefficient * lag) - target
            gradient_i += error
            gradient_b += error * lag
        scale = 0.05 / len(pairs)
        intercept -= scale * gradient_i
        coefficient -= scale * gradient_b
    return intercept, coefficient


def _lag1_logistic(train: list[float], previous: float) -> float:
    intercept, coefficient = _fit_lag1_logistic(train)
    return _sigmoid(intercept + coefficient * previous)


def evaluate(ticker: str, rows: Iterable[dict[str, object]]) -> dict[str, object]:
    records = list(rows)
    dates = [str(row["date"]) for row in records]
    values = [float(row["daily_return_pct"]) for row in records]
    if dates != sorted(set(dates)) or any(not math.isfinite(value) for value in values):
        raise ValueError("Returns require unique ordered dates and finite values")
    if len(values) < MIN_ROWS:
        return {"ticker": ticker, "status": "REJECTED_INSUFFICIENT_HISTORY", "observations": len(values)}
    scores = {"majority_direction": 0.0, "constant_training_rate": 0.0, "lag1_logistic": 0.0}
    observations = 0
    predictions = []
    for fold in range(FOLDS):
        start = fold * TEST
        train = values[start:start + TRAIN]
        test = values[start + TRAIN + PURGE:start + TRAIN + PURGE + TEST]
        majority = 1.0 if sum(value > 0.0 for value in train) / len(train) >= 0.5 else 0.0
        rate = sum(value > 0.0 for value in train) / len(train)
        intercept, coefficient = _fit_lag1_logistic(train)
        for offset, actual in enumerate(test):
            target_index = start + TRAIN + PURGE + offset
            previous_index = target_index - 1
            probability = _sigmoid(intercept + coefficient * values[previous_index])
            target = 1.0 if actual > 0.0 else 0.0
            scores["majority_direction"] += (majority - target) ** 2
            scores["constant_training_rate"] += (rate - target) ** 2
            scores["lag1_logistic"] += (probability - target) ** 2
            predictions.append({
                "fold": fold, "target_date": dates[target_index],
                "information_date": dates[previous_index],
                "training_end_date": dates[start + TRAIN - 1],
                "lag1_return": values[previous_index], "outcome": target,
                "probabilities": {"majority_direction": majority,
                                  "constant_training_rate": rate,
                                  "lag1_logistic": probability},
            })
            observations += 1
    return {"ticker": ticker, "status": "EVALUATED", "observations": observations,
            "brier_score": {name: value / observations for name, value in scores.items()},
            "predictions": predictions}
