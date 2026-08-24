"""ETF PyMC engine with explicit lineage-backed stock hyper-priors."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

import numpy as np

from etf_model_dataset import ETFModelDataset
from etf_prior_builder import PreparedETFStockPrior
from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics, validate_sampler_trace


@dataclass(frozen=True)
class ETFPosteriorEvidence:
    ticker: str
    probability_up_mean: float
    probability_up_std: float
    probability_up_q05: float
    probability_up_q95: float
    expected_return_pct_mean: float
    expected_return_pct_std: float
    predictive_risk_pct: float
    stock_direction_prior_mean_log_odds: float
    stock_direction_prior_sigma_log_odds: float
    stock_return_prior_mean_pct: float
    stock_return_prior_sigma_pct: float
    stock_weight_coverage: float
    stock_contributor_count: int
    diagnostics: SamplerDiagnostics


def validate_etf_inputs(
    dataset: ETFModelDataset,
    stock_prior: PreparedETFStockPrior,
) -> None:
    if dataset.prediction_date != stock_prior.stock_batch.prediction_date:
        raise LineageError("ETF dataset and stock prior prediction dates do not match.")
    if dataset.source_session_date != stock_prior.stock_batch.source_session_date:
        raise LineageError("ETF dataset and stock prior source sessions do not match.")
    if dataset.x_train.ndim != 2 or dataset.x_predict.shape != (1, dataset.x_train.shape[1]):
        raise LineageError("ETF model matrices have incompatible shapes.")
    if len(dataset.y_direction) != len(dataset.x_train) or len(dataset.y_return_pct) != len(dataset.x_train):
        raise LineageError("ETF model outcomes do not align with training features.")
    if len(np.unique(dataset.y_direction)) < 2:
        raise LineageError("ETF direction training outcome contains only one class.")
    values = (dataset.x_train, dataset.x_predict, dataset.y_direction, dataset.y_return_pct)
    if not all(np.isfinite(value).all() for value in values):
        raise LineageError("ETF model matrices contain non-finite values.")
    aggregate = stock_prior.aggregate
    prior_values = (
        aggregate.mean_log_odds,
        aggregate.sigma_log_odds,
        aggregate.weighted_expected_return,
        aggregate.expected_return_sigma,
        aggregate.weight_coverage,
    )
    if not all(isfinite(value) for value in prior_values):
        raise LineageError("Stock-derived ETF prior contains non-finite values.")
    if aggregate.sigma_log_odds <= 0.0 or aggregate.expected_return_sigma <= 0.0:
        raise LineageError("Stock-derived ETF prior uncertainty must be positive.")


def _sigmoid(values: np.ndarray) -> np.ndarray:
    positive = values >= 0
    result = np.empty_like(values, dtype=float)
    result[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exponent = np.exp(values[~positive])
    result[~positive] = exponent / (1.0 + exponent)
    return result


def summarize_etf_posterior(
    *,
    dataset: ETFModelDataset,
    stock_prior: PreparedETFStockPrior,
    alpha_direction: np.ndarray,
    beta_direction: np.ndarray,
    alpha_return: np.ndarray,
    beta_return: np.ndarray,
    return_scale: np.ndarray,
    return_nu: np.ndarray,
    diagnostics: SamplerDiagnostics,
) -> ETFPosteriorEvidence:
    validate_etf_inputs(dataset, stock_prior)
    x = dataset.x_predict.reshape(-1)
    a_direction = np.asarray(alpha_direction, dtype=float).reshape(-1)
    b_direction = np.asarray(beta_direction, dtype=float).reshape(-1, len(x))
    a_return = np.asarray(alpha_return, dtype=float).reshape(-1)
    b_return = np.asarray(beta_return, dtype=float).reshape(-1, len(x))
    scale = np.asarray(return_scale, dtype=float).reshape(-1)
    nu = np.asarray(return_nu, dtype=float).reshape(-1)
    count = len(a_direction)
    if count < 2 or any(len(value) != count for value in (b_direction, a_return, b_return, scale, nu)):
        raise LineageError("ETF posterior draw counts do not match.")
    if not all(np.isfinite(value).all() for value in (a_direction, b_direction, a_return, b_return, scale, nu)):
        raise LineageError("ETF posterior evidence is missing or non-finite.")
    if np.any(scale <= 0.0) or np.any(nu <= 2.0):
        raise LineageError("ETF return posterior requires positive scale and Student-t nu > 2.")

    probabilities = _sigmoid(a_direction + b_direction @ x)
    return_means = a_return + b_return @ x
    predictive_variance = float(
        np.var(return_means, ddof=1) + np.mean(np.square(scale) * nu / (nu - 2.0))
    )
    aggregate = stock_prior.aggregate
    result = ETFPosteriorEvidence(
        ticker=dataset.ticker,
        probability_up_mean=float(np.mean(probabilities)),
        probability_up_std=float(np.std(probabilities, ddof=1)),
        probability_up_q05=float(np.quantile(probabilities, 0.05)),
        probability_up_q95=float(np.quantile(probabilities, 0.95)),
        expected_return_pct_mean=float(np.mean(return_means)),
        expected_return_pct_std=float(np.std(return_means, ddof=1)),
        predictive_risk_pct=float(np.sqrt(predictive_variance)),
        stock_direction_prior_mean_log_odds=aggregate.mean_log_odds,
        stock_direction_prior_sigma_log_odds=aggregate.sigma_log_odds,
        stock_return_prior_mean_pct=aggregate.weighted_expected_return,
        stock_return_prior_sigma_pct=aggregate.expected_return_sigma,
        stock_weight_coverage=aggregate.weight_coverage,
        stock_contributor_count=aggregate.contributor_count,
        diagnostics=diagnostics,
    )
    numeric = tuple(
        value for key, value in result.__dict__.items()
        if key not in {"ticker", "stock_contributor_count", "diagnostics"}
    )
    if not all(isfinite(value) for value in numeric) or result.probability_up_std <= 0.0:
        raise LineageError("ETF posterior forecast uncertainty is invalid.")
    return result


def fit_etf_posterior(
    dataset: ETFModelDataset,
    stock_prior: PreparedETFStockPrior,
    *,
    sampler_config: Mapping[str, object] | None = None,
) -> ETFPosteriorEvidence:
    """Fit ETF direction/return heads using auditable stock hyper-priors."""
    validate_etf_inputs(dataset, stock_prior)
    from engine_config import configure_bayesian_engine
    config = dict(configure_bayesian_engine() if sampler_config is None else sampler_config)
    import pymc as pm

    aggregate = stock_prior.aggregate
    feature_count = dataset.x_train.shape[1]
    observed_return_spread = max(float(np.std(dataset.y_return_pct, ddof=1)), 0.10)
    with pm.Model(coords={"feature": dataset.feature_names}) as model:
        x_train = pm.Data("x_train", dataset.x_train, dims=("observation", "feature"))
        alpha_direction = pm.Normal(
            "alpha_direction",
            mu=aggregate.mean_log_odds,
            sigma=aggregate.sigma_log_odds,
        )
        beta_direction = pm.Normal("beta_direction", mu=0.0, sigma=0.5, dims="feature")
        probability = pm.math.sigmoid(alpha_direction + pm.math.dot(x_train, beta_direction))
        pm.Bernoulli("direction_observed", p=probability, observed=dataset.y_direction)

        alpha_return = pm.Normal(
            "alpha_return",
            mu=aggregate.weighted_expected_return,
            sigma=aggregate.expected_return_sigma,
        )
        beta_return = pm.Normal("beta_return", mu=0.0, sigma=0.5, dims="feature")
        return_scale = pm.HalfNormal("return_scale", sigma=observed_return_spread)
        return_nu = pm.Deterministic(
            "return_nu", pm.Exponential("return_nu_minus_two", 0.1) + 2.0
        )
        return_mu = alpha_return + pm.math.dot(x_train, beta_return)
        pm.StudentT(
            "return_observed", nu=return_nu, mu=return_mu,
            sigma=return_scale, observed=dataset.y_return_pct,
        )
        trace = pm.sample(**config)

    diagnostics = validate_sampler_trace(trace)
    posterior = trace.posterior
    return summarize_etf_posterior(
        dataset=dataset,
        stock_prior=stock_prior,
        alpha_direction=posterior["alpha_direction"].values,
        beta_direction=posterior["beta_direction"].values,
        alpha_return=posterior["alpha_return"].values,
        beta_return=posterior["beta_return"].values,
        return_scale=posterior["return_scale"].values,
        return_nu=posterior["return_nu"].values,
        diagnostics=diagnostics,
    )
