"""Research-only hierarchical stock model with no I/O or trading actions."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence
import numpy as np

from model_lineage import LineageError
from sampler_qa import SamplerDiagnostics, validate_sampler_trace
from stock_model_dataset import StockModelDataset
from stock_pymc_core import StockPosteriorEvidence, summarize_stock_posterior

EDGE = re.compile(r"^(.+)_return_x_volume_ratio_lag([1-9][0-9]*)$")


@dataclass(frozen=True)
class HierarchicalStockDataset:
    tickers: tuple[str, ...]
    training_dates: tuple[object, ...]
    edge_names: tuple[tuple[str | None, ...], ...]
    edge_lags: tuple[tuple[int | None, ...], ...]
    x_train: np.ndarray
    y_direction: np.ndarray
    y_return_pp: np.ndarray
    x_predict: np.ndarray


def _edges(item: StockModelDataset) -> list[tuple[int, str, int]]:
    found = []
    for index, name in enumerate(item.feature_names):
        match = EDGE.fullmatch(name)
        if match:
            lag = int(match.group(2))
            if lag > 7:
                raise LineageError(f"Screened edge {name} exceeds governed lag 1-7.")
            found.append((index, name, lag))
    if not 1 <= len(found) <= 5:
        raise LineageError(f"{item.ticker} must have governed model depth 1-5.")
    return found


def build_hierarchical_stock_dataset(items: Sequence[StockModelDataset]) -> HierarchicalStockDataset:
    """Align independently selected edges into five structural slots."""
    items = tuple(items)
    tickers = tuple(item.ticker for item in items)
    if len(items) < 2 or len(set(tickers)) != len(tickers):
        raise LineageError("Hierarchical pooling requires at least two unique targets.")
    if len({item.source_session_date for item in items}) != 1:
        raise LineageError("Hierarchical datasets must share one source session.")
    common = set(items[0].training_dates)
    for item in items[1:]:
        common &= set(item.training_dates)
    dates = tuple(sorted(common))
    if len(dates) < 2:
        raise LineageError("Hierarchical datasets need two common training sessions.")
    x = np.zeros((len(items), len(dates), 5))
    xp = np.zeros((len(items), 5))
    yd = np.zeros((len(items), len(dates)), dtype=int)
    yr = np.zeros((len(items), len(dates)))
    names, lags = [], []
    for target, item in enumerate(items):
        positions = {date: index for index, date in enumerate(item.training_dates)}
        rows = np.asarray([positions[date] for date in dates])
        if item.x_train.shape != (len(item.training_dates), len(item.feature_names)):
            raise LineageError(f"{item.ticker} training shape is inconsistent.")
        if item.x_predict.shape != (1, len(item.feature_names)):
            raise LineageError(f"{item.ticker} prediction shape is inconsistent.")
        if len(np.unique(item.y_direction)) < 2:
            raise LineageError(f"{item.ticker} direction outcome has one class.")
        target_names: list[str | None] = [None] * 5
        target_lags: list[int | None] = [None] * 5
        for slot, (column, name, lag) in enumerate(_edges(item)):
            x[target, :, slot] = item.x_train[rows, column]
            xp[target, slot] = item.x_predict[0, column]
            target_names[slot], target_lags[slot] = name, lag
        yd[target], yr[target] = item.y_direction[rows], item.y_return_pp[rows]
        names.append(tuple(target_names))
        lags.append(tuple(target_lags))
    if not all(np.isfinite(value).all() for value in (x, xp, yd, yr)):
        raise LineageError("Hierarchical arrays contain non-finite values.")
    return HierarchicalStockDataset(tickers, dates, tuple(names), tuple(lags), x, yd, yr, xp)


def summarize_hierarchical_stock_posteriors(
    data: HierarchicalStockDataset, *, alpha_direction: np.ndarray,
    beta_direction: np.ndarray, alpha_return: np.ndarray, beta_return: np.ndarray,
    return_scale: np.ndarray, return_nu: np.ndarray, diagnostics: SamplerDiagnostics,
) -> Mapping[str, StockPosteriorEvidence]:
    count = len(data.tickers)
    ad = np.asarray(alpha_direction).reshape(-1, count)
    bd = np.asarray(beta_direction).reshape(-1, count, 5)
    ar = np.asarray(alpha_return).reshape(-1, count)
    br = np.asarray(beta_return).reshape(-1, count, 5)
    scale = np.asarray(return_scale).reshape(-1, count)
    nu = np.asarray(return_nu).reshape(-1)
    return {
        ticker: summarize_stock_posterior(
            ticker=ticker, x_predict=data.x_predict[index:index + 1],
            alpha_direction=ad[:, index], beta_direction=bd[:, index],
            alpha_return=ar[:, index], beta_return=br[:, index],
            return_scale=scale[:, index], return_nu=nu, diagnostics=diagnostics,
        )
        for index, ticker in enumerate(data.tickers)
    }


def fit_hierarchical_stock_posteriors(
    data: HierarchicalStockDataset, *, sampler_config: Mapping[str, object] | None = None,
) -> Mapping[str, StockPosteriorEvidence]:
    """Fit non-centred target effects and independent edge coefficients."""
    from engine_config import configure_bayesian_engine
    import pymc as pm

    config = dict(configure_bayesian_engine() if sampler_config is None else sampler_config)
    spread = max(float(np.std(data.y_return_pp, ddof=1)), 0.1)
    coords = {"target": data.tickers, "feature": tuple(f"edge_{i}" for i in range(1, 6))}
    with pm.Model(coords=coords):
        x = pm.Data("x_train", data.x_train, dims=("target", "observation", "feature"))
        ad = pm.Deterministic("alpha_direction", pm.Normal("ad_global", 0, 1) + pm.Normal("ad_raw", 0, 1, dims="target") * pm.HalfNormal("ad_scale", .5), dims="target")
        bd = pm.Deterministic("beta_direction", pm.Normal("bd_global", 0, .5, dims="feature") + pm.Normal("bd_raw", 0, 1, dims=("target", "feature")) * pm.HalfNormal("bd_scale", .25, dims="feature"), dims=("target", "feature"))
        pm.Bernoulli("direction_observed", logit_p=ad[:, None] + pm.math.sum(x * bd[:, None, :], axis=2), observed=data.y_direction)
        ar = pm.Deterministic("alpha_return", pm.Normal("ar_global", float(np.mean(data.y_return_pp)), spread) + pm.Normal("ar_raw", 0, 1, dims="target") * pm.HalfNormal("ar_scale", spread), dims="target")
        br = pm.Deterministic("beta_return", pm.Normal("br_global", 0, .5, dims="feature") + pm.Normal("br_raw", 0, 1, dims=("target", "feature")) * pm.HalfNormal("br_scale", .25, dims="feature"), dims=("target", "feature"))
        scale = pm.HalfNormal("return_scale", spread, dims="target")
        nu = pm.Deterministic("return_nu", pm.Exponential("nu_minus_two", .1) + 2)
        mu = ar[:, None] + pm.math.sum(x * br[:, None, :], axis=2)
        pm.StudentT("return_observed", nu=nu, mu=mu, sigma=scale[:, None], observed=data.y_return_pp)
        trace = pm.sample(**config)
    diagnostics = validate_sampler_trace(trace)
    p = trace.posterior
    return summarize_hierarchical_stock_posteriors(
        data, alpha_direction=p["alpha_direction"].values,
        beta_direction=p["beta_direction"].values,
        alpha_return=p["alpha_return"].values, beta_return=p["beta_return"].values,
        return_scale=p["return_scale"].values, return_nu=p["return_nu"].values,
        diagnostics=diagnostics,
    )
