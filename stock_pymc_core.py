"""PyMC stock posterior engine with no file, network, broker, or DB writes."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

import numpy as np

from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics, validate_sampler_trace
from stock_model_dataset import StockModelDataset


@dataclass(frozen=True)
class StockPosteriorEvidence:
    ticker: str
    probability_up_mean: float
    probability_up_std: float
    probability_up_q05: float
    probability_up_q95: float
    expected_return_pct_mean: float
    expected_return_pct_std: float
    predictive_risk_pct: float
    diagnostics: SamplerDiagnostics


def _sigmoid(values: np.ndarray) -> np.ndarray:
    positive = values >= 0
    result = np.empty_like(values, dtype=float)
    result[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_values = np.exp(values[~positive])
    result[~positive] = exp_values / (1.0 + exp_values)
    return result


def summarize_stock_posterior(
    *,
    ticker: str,
    x_predict: np.ndarray,
    alpha_direction: np.ndarray,
    beta_direction: np.ndarray,
    alpha_return: np.ndarray,
    beta_return: np.ndarray,
    return_scale: np.ndarray,
    return_nu: np.ndarray,
    diagnostics: SamplerDiagnostics,
) -> StockPosteriorEvidence:
    """Summarize parameter draws into uncertainty-preserving forecast evidence."""
    x = np.asarray(x_predict, dtype=float)
    if x.shape[0] != 1:
        raise LineageError("Stock posterior summary requires exactly one prediction row.")
    x = x.reshape(-1)
    a_dir = np.asarray(alpha_direction, dtype=float).reshape(-1)
    b_dir = np.asarray(beta_direction, dtype=float).reshape(-1, len(x))
    a_ret = np.asarray(alpha_return, dtype=float).reshape(-1)
    b_ret = np.asarray(beta_return, dtype=float).reshape(-1, len(x))
    scale = np.asarray(return_scale, dtype=float).reshape(-1)
    nu = np.asarray(return_nu, dtype=float).reshape(-1)
    sample_count = len(a_dir)
    arrays = (a_dir, a_ret, scale, nu)
    if any(len(array) != sample_count for array in arrays) or len(b_dir) != sample_count or len(b_ret) != sample_count:
        raise LineageError("Posterior draw counts do not match.")
    if sample_count < 2 or not all(np.isfinite(array).all() for array in (*arrays, b_dir, b_ret, x)):
        raise LineageError("Posterior evidence is missing or non-finite.")
    if np.any(scale <= 0) or np.any(nu <= 2):
        raise LineageError("Return posterior requires positive scale and Student-t nu > 2.")

    probabilities = _sigmoid(a_dir + b_dir @ x)
    return_means = a_ret + b_ret @ x
    aleatoric_variance = np.square(scale) * nu / (nu - 2.0)
    total_return_variance = float(np.var(return_means, ddof=1) + np.mean(aleatoric_variance))
    result = StockPosteriorEvidence(
        ticker=ticker,
        probability_up_mean=float(np.mean(probabilities)),
        probability_up_std=float(np.std(probabilities, ddof=1)),
        probability_up_q05=float(np.quantile(probabilities, 0.05)),
        probability_up_q95=float(np.quantile(probabilities, 0.95)),
        expected_return_pct_mean=float(np.mean(return_means)),
        expected_return_pct_std=float(np.std(return_means, ddof=1)),
        predictive_risk_pct=float(np.sqrt(total_return_variance)),
        diagnostics=diagnostics,
    )
    numeric = (
        result.probability_up_mean, result.probability_up_std,
        result.probability_up_q05, result.probability_up_q95,
        result.expected_return_pct_mean, result.expected_return_pct_std,
        result.predictive_risk_pct,
    )
    if not all(isfinite(value) for value in numeric) or result.probability_up_std <= 0:
        raise LineageError("Posterior forecast uncertainty is invalid.")
    return result


def fit_stock_posterior(
    dataset: StockModelDataset,
    *,
    sampler_config: Mapping[str, object] | None = None,
) -> StockPosteriorEvidence:
    """Fit direction and robust-return heads; fail if sampler QA is not green."""
    if dataset.x_train.ndim != 2 or dataset.x_predict.shape != (1, dataset.x_train.shape[1]):
        raise LineageError("Stock model matrices have incompatible shapes.")
    if len(dataset.y_direction) != len(dataset.x_train) or len(dataset.y_return_pct) != len(dataset.x_train):
        raise LineageError("Stock model outcomes do not align with training features.")
    if len(np.unique(dataset.y_direction)) < 2:
        raise LineageError("Direction training outcome contains only one class.")
    values = (dataset.x_train, dataset.x_predict, dataset.y_direction, dataset.y_return_pct)
    if not all(np.isfinite(value).all() for value in values):
        raise LineageError("Stock model matrices contain non-finite values.")

    from engine_config import configure_bayesian_engine
    config = dict(configure_bayesian_engine() if sampler_config is None else sampler_config)
    import pymc as pm

    feature_count = dataset.x_train.shape[1]
    return_location = float(np.mean(dataset.y_return_pct))
    return_spread = max(float(np.std(dataset.y_return_pct, ddof=1)), 0.10)
    with pm.Model(coords={"feature": dataset.feature_names}) as model:
        x_train = pm.Data("x_train", dataset.x_train, dims=("observation", "feature"))
        alpha_direction = pm.Normal("alpha_direction", mu=0.0, sigma=1.0)
        beta_direction = pm.Normal("beta_direction", mu=0.0, sigma=0.5, dims="feature")
        direction_probability = pm.math.sigmoid(alpha_direction + pm.math.dot(x_train, beta_direction))
        pm.Bernoulli("direction_observed", p=direction_probability, observed=dataset.y_direction)

        alpha_return = pm.Normal("alpha_return", mu=return_location, sigma=return_spread)
        beta_return = pm.Normal("beta_return", mu=0.0, sigma=0.5, dims="feature")
        return_scale = pm.HalfNormal("return_scale", sigma=return_spread)
        return_nu = pm.Deterministic("return_nu", pm.Exponential("return_nu_minus_two", 0.1) + 2.0)
        return_mu = alpha_return + pm.math.dot(x_train, beta_return)
        pm.StudentT(
            "return_observed", nu=return_nu, mu=return_mu,
            sigma=return_scale, observed=dataset.y_return_pct,
        )
        trace = pm.sample(**config)

    diagnostics = validate_sampler_trace(trace)
    posterior = trace.posterior
    return summarize_stock_posterior(
        ticker=dataset.ticker,
        x_predict=dataset.x_predict,
        alpha_direction=posterior["alpha_direction"].values,
        beta_direction=posterior["beta_direction"].values,
        alpha_return=posterior["alpha_return"].values,
        beta_return=posterior["beta_return"].values,
        return_scale=posterior["return_scale"].values,
        return_nu=posterior["return_nu"].values,
        diagnostics=diagnostics,
    )
