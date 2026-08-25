"""Deterministic synthetic smoke test for the isolated PyMC stock core."""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stock_model_dataset import StockModelDataset
from stock_pymc_core import fit_stock_posterior


def main() -> int:
    rng = np.random.default_rng(20260822)
    observations = 80
    features = 3
    x = rng.normal(size=(observations, features))
    logits = -0.1 + x @ np.asarray([0.7, -0.4, 0.2])
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    y_direction = rng.binomial(1, probabilities)
    y_return = 0.05 + x @ np.asarray([0.3, -0.2, 0.1]) + rng.standard_t(8, observations) * 0.5
    start = date(2026, 4, 1)
    dataset = StockModelDataset(
        ticker="SYNTHETIC",
        source_session_date=start + timedelta(days=observations - 1),
        prediction_date=start + timedelta(days=observations),
        feature_names=("f1", "f2", "f3"),
        training_dates=tuple(start + timedelta(days=i) for i in range(observations)),
        x_train=x,
        y_direction=y_direction,
        y_return_pp=y_return,
        x_predict=np.asarray([[0.5, -0.25, 0.1]]),
        train_mean=np.zeros(features),
        train_scale=np.ones(features),
    )
    evidence = fit_stock_posterior(dataset)
    print(json.dumps({
        "ticker": evidence.ticker,
        "probability_up_mean": evidence.probability_up_mean,
        "probability_up_std": evidence.probability_up_std,
        "expected_return_pp_mean": evidence.expected_return_pp_mean,
        "expected_return_pp_std": evidence.expected_return_pp_std,
        "predictive_risk_pp": evidence.predictive_risk_pp,
        "diagnostics": evidence.diagnostics.__dict__,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
