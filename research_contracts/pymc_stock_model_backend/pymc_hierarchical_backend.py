"""Concrete, research-only PyMC backend for the governed hierarchy boundary.

PyMC and ArviZ are imported only when :func:`make_pymc_backend` is called.
Importing this module has no filesystem, network, database, process, or model-
fit side effect.  The backend consumes only the already frozen in-memory
``HierarchicalFitRequest`` and returns the governed result type.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
from math import isfinite, sqrt
from typing import Any, Callable, Mapping

import numpy as np

try:
    from hierarchical_model_impl.independent_edge_hierarchy import (
        CanonicalPercentPosterior,
        HierarchicalBackendResult,
        HierarchicalContractError,
        HierarchicalFitRequest,
        SamplerDiagnosticsEvidence,
    )
except ImportError:  # canonical package layout after integration
    from research_contracts.hierarchical_stock_model.independent_edge_hierarchy import (
        CanonicalPercentPosterior,
        HierarchicalBackendResult,
        HierarchicalContractError,
        HierarchicalFitRequest,
        SamplerDiagnosticsEvidence,
    )


BACKEND_ID = "codex-oracle-pymc-independent-edge-hierarchy-v1"
_DIRECTION_VARS = ("direction_alpha", "direction_beta")
_RETURN_VARS = ("return_alpha", "return_beta", "return_sigma")


class PyMCBackendError(HierarchicalContractError):
    """Raised before accepting any posterior when the PyMC boundary differs."""


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class NumericModelConfig:
    direction_intercept_location: float = 0.0
    direction_intercept_scale: float = 1.0
    direction_edge_location: float = 0.0
    direction_edge_scale: float = 0.5
    return_intercept_location_pct: float = 0.0
    return_intercept_scale_pct: float = 1.0
    return_edge_location: float = 0.0
    return_edge_scale: float = 0.5
    return_sigma_scale_pct: float = 2.0
    student_t_nu_rate: float = 0.1
    student_t_nu_offset: float = 2.0
    hierarchy: str = "PARTIAL_POOLING_GLOBAL_EDGE_SCALE_AND_TARGET_INTERCEPTS"
    direction_likelihood: str = "BERNOULLI_LOGIT"
    return_likelihood: str = "STUDENT_T_PERCENT"
    edge_coefficients: str = "INDEPENDENT_EXCHANGEABLE_NO_POSITIONAL_CHAIN"
    standardization: str = "TRAINING_ONLY_PER_TARGET_EDGE"


@dataclass(frozen=True)
class SamplerConfig:
    chains: int = 4
    draws: int = 1000
    tune: int = 1000
    cores: int = 2
    random_seeds: tuple[int, ...] = (1729, 2718, 3141, 5772)
    target_accept: float = 0.95
    max_treedepth: int = 12
    init: str = "jitter+adapt_diag"
    progressbar: bool = False
    compute_convergence_checks: bool = True
    discard_tuned_samples: bool = True


@dataclass(frozen=True)
class FrozenBackendConfig:
    model: NumericModelConfig
    sampler: SamplerConfig
    model_config_sha256: str
    sampler_sha256: str
    backend_id: str = BACKEND_ID


@dataclass(frozen=True)
class PackedDesign:
    tickers: tuple[str, ...]
    target_index: np.ndarray
    x: np.ndarray
    edge_index: np.ndarray
    feature_mask: np.ndarray
    y_direction: np.ndarray
    y_return_pct: np.ndarray
    prediction_x: np.ndarray
    prediction_edge_index: np.ndarray
    prediction_feature_mask: np.ndarray
    edge_names: tuple[str, ...]


def model_payload(config: NumericModelConfig) -> Mapping[str, object]:
    return {"backend_id": BACKEND_ID, "numeric_model": asdict(config)}


def sampler_payload(config: SamplerConfig) -> Mapping[str, object]:
    return {"backend_id": BACKEND_ID, "sampler": asdict(config)}


def freeze_backend_config(
    model: NumericModelConfig = NumericModelConfig(),
    sampler: SamplerConfig = SamplerConfig(),
) -> FrozenBackendConfig:
    """Content-address every numeric prior and sampler decision."""
    _validate_numeric_config(model)
    _validate_sampler_config(sampler)
    return FrozenBackendConfig(
        model=model,
        sampler=sampler,
        model_config_sha256=_canonical_sha256(model_payload(model)),
        sampler_sha256=_canonical_sha256(sampler_payload(sampler)),
    )


def _finite_positive(value: object, label: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or value <= 0:
        raise PyMCBackendError(f"{label} must be finite and positive")


def _finite_number(value: object, label: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        raise PyMCBackendError(f"{label} must be finite")


def _validate_numeric_config(config: NumericModelConfig) -> None:
    if type(config) is not NumericModelConfig:
        raise PyMCBackendError("numeric model configuration type differs")
    for label, value in (
        ("direction intercept location", config.direction_intercept_location),
        ("direction edge location", config.direction_edge_location),
        ("return intercept location", config.return_intercept_location_pct),
        ("return edge location", config.return_edge_location),
    ):
        _finite_number(value, label)
    for label, value in (
        ("direction intercept scale", config.direction_intercept_scale),
        ("direction edge scale", config.direction_edge_scale),
        ("return intercept scale", config.return_intercept_scale_pct),
        ("return edge scale", config.return_edge_scale),
        ("return sigma scale", config.return_sigma_scale_pct),
        ("Student-t nu rate", config.student_t_nu_rate),
        ("Student-t nu offset", config.student_t_nu_offset),
    ):
        _finite_positive(value, label)
    # Exponential support is strictly positive, so an offset of exactly two
    # yields nu > 2 almost surely and therefore retains finite variance.
    if config.student_t_nu_offset < 2:
        raise PyMCBackendError("Student-t degrees of freedom must retain finite variance")
    expected = (
        "PARTIAL_POOLING_GLOBAL_EDGE_SCALE_AND_TARGET_INTERCEPTS",
        "BERNOULLI_LOGIT",
        "STUDENT_T_PERCENT",
        "INDEPENDENT_EXCHANGEABLE_NO_POSITIONAL_CHAIN",
        "TRAINING_ONLY_PER_TARGET_EDGE",
    )
    observed = (
        config.hierarchy, config.direction_likelihood, config.return_likelihood,
        config.edge_coefficients, config.standardization,
    )
    if observed != expected:
        raise PyMCBackendError("numeric model graph semantics differ")


def _validate_sampler_config(config: SamplerConfig) -> None:
    if type(config) is not SamplerConfig:
        raise PyMCBackendError("sampler configuration type differs")
    integer_values = (
        config.chains, config.draws, config.tune, config.cores,
        config.max_treedepth,
    )
    if any(type(value) is not int for value in integer_values):
        raise PyMCBackendError("sampler integer controls use an invalid type")
    if config.chains != 4 or config.draws < 1000 or config.tune < 1000:
        raise PyMCBackendError("sampler counts weaken the governed minimum")
    if not 1 <= config.cores <= config.chains:
        raise PyMCBackendError("sampler core count differs")
    if len(config.random_seeds) != config.chains or len(set(config.random_seeds)) != config.chains:
        raise PyMCBackendError("one unique deterministic seed per chain is required")
    if any(type(seed) is not int or seed <= 0 for seed in config.random_seeds):
        raise PyMCBackendError("sampler seeds must be positive integers")
    if not isinstance(config.target_accept, float) or not isfinite(config.target_accept) or not 0.9 <= config.target_accept < 1.0 or config.max_treedepth < 10:
        raise PyMCBackendError("NUTS convergence controls are weakened")
    if config.init != "jitter+adapt_diag" or config.progressbar is not False:
        raise PyMCBackendError("sampler initialization or noninteractive boundary differs")
    if config.compute_convergence_checks is not True or config.discard_tuned_samples is not True:
        raise PyMCBackendError("sampler evidence controls differ")


def _validate_binding(request: HierarchicalFitRequest, config: FrozenBackendConfig) -> None:
    if type(config) is not FrozenBackendConfig or config.backend_id != BACKEND_ID:
        raise PyMCBackendError("backend configuration identity differs")
    expected = freeze_backend_config(config.model, config.sampler)
    if config != expected:
        raise PyMCBackendError("backend configuration hash differs from numeric semantics")
    if request.preregistered_model_config_sha256 != config.model_config_sha256:
        raise PyMCBackendError("numeric model configuration is not the preregistered identity")
    if request.preregistered_sampler_sha256 != config.sampler_sha256:
        raise PyMCBackendError("sampler configuration is not the preregistered identity")
    if request.hierarchy != config.model.hierarchy:
        raise PyMCBackendError("request hierarchy differs from the frozen backend")
    forbidden = (
        request.persist_predictions, request.create_recommendations,
        request.create_orders, request.create_etf_outputs, request.activate_trading,
    )
    if request.research_only is not True or any(forbidden):
        raise PyMCBackendError("request crosses the research-only boundary")


def pack_design(request: HierarchicalFitRequest) -> PackedDesign:
    """Pack ragged per-target matrices without positional edge semantics."""
    if not request.target_matrices:
        raise PyMCBackendError("fit request has no targets")
    matrices = tuple(sorted(request.target_matrices, key=lambda item: item.ticker))
    tickers = tuple(item.ticker for item in matrices)
    if len(set(tickers)) != len(tickers):
        raise PyMCBackendError("target tickers are duplicated")
    edge_names: list[str] = []
    edge_lookup: dict[tuple[str, str, int], int] = {}
    for matrix in matrices:
        if not 1 <= len(matrix.edge_identities) <= 5:
            raise PyMCBackendError("target edge depth is outside 1-5")
        for source, lag in matrix.edge_identities:
            if type(lag) is not int or lag not in range(1, 8):
                raise PyMCBackendError("edge lag is outside 1-7")
            identity = (matrix.ticker, source, lag)
            if identity in edge_lookup:
                raise PyMCBackendError("independent target/source/lag edge is duplicated")
            edge_lookup[identity] = len(edge_names)
            edge_names.append(f"{matrix.ticker}<-{source}:lag{lag}")
    maximum_depth = 5
    x_rows: list[np.ndarray] = []
    edge_rows: list[np.ndarray] = []
    mask_rows: list[np.ndarray] = []
    target_rows: list[np.ndarray] = []
    direction_rows: list[np.ndarray] = []
    return_rows: list[np.ndarray] = []
    prediction_x = np.zeros((len(matrices), maximum_depth), dtype=float)
    prediction_edges = np.zeros((len(matrices), maximum_depth), dtype=np.int64)
    prediction_mask = np.zeros((len(matrices), maximum_depth), dtype=float)
    for target_position, matrix in enumerate(matrices):
        if matrix.x_train.ndim != 2 or matrix.x_predict.ndim != 2:
            raise PyMCBackendError("fit matrix rank differs")
        observations, depth = matrix.x_train.shape
        if observations < 126 or depth != len(matrix.edge_identities):
            raise PyMCBackendError("fit matrix geometry differs")
        arrays = (matrix.x_train, matrix.y_direction, matrix.y_return_pct, matrix.x_predict)
        if any(type(value) is not np.ndarray or not np.isfinite(value).all() for value in arrays):
            raise PyMCBackendError("fit matrix contains non-finite or non-array evidence")
        if matrix.x_predict.shape != (1, depth) or len(matrix.y_direction) != observations or len(matrix.y_return_pct) != observations:
            raise PyMCBackendError("fit matrix arrays do not align")
        if not set(np.unique(matrix.y_direction)).issubset({0, 1}):
            raise PyMCBackendError("direction outcome is not binary")
        padded_x = np.zeros((observations, maximum_depth), dtype=float)
        padded_edges = np.zeros((observations, maximum_depth), dtype=np.int64)
        padded_mask = np.zeros((observations, maximum_depth), dtype=float)
        ids = [edge_lookup[(matrix.ticker, source, lag)] for source, lag in matrix.edge_identities]
        padded_x[:, :depth] = matrix.x_train
        padded_edges[:, :depth] = np.asarray(ids, dtype=np.int64)
        padded_mask[:, :depth] = 1.0
        x_rows.append(padded_x)
        edge_rows.append(padded_edges)
        mask_rows.append(padded_mask)
        target_rows.append(np.full(observations, target_position, dtype=np.int64))
        direction_rows.append(np.asarray(matrix.y_direction, dtype=np.int8))
        return_rows.append(np.asarray(matrix.y_return_pct, dtype=float))
        prediction_x[target_position, :depth] = matrix.x_predict[0]
        prediction_edges[target_position, :depth] = ids
        prediction_mask[target_position, :depth] = 1.0
    return PackedDesign(
        tickers=tickers,
        target_index=np.concatenate(target_rows),
        x=np.concatenate(x_rows),
        edge_index=np.concatenate(edge_rows),
        feature_mask=np.concatenate(mask_rows),
        y_direction=np.concatenate(direction_rows),
        y_return_pct=np.concatenate(return_rows),
        prediction_x=prediction_x,
        prediction_edge_index=prediction_edges,
        prediction_feature_mask=prediction_mask,
        edge_names=tuple(edge_names),
    )


def build_pymc_model(pm: Any, packed: PackedDesign, config: NumericModelConfig) -> Any:
    """Build the exact joint direction/return graph; never sample it."""
    _validate_numeric_config(config)
    coords = {
        "target": packed.tickers,
        "edge": packed.edge_names,
        "observation": np.arange(len(packed.target_index)),
        "feature_slot": np.arange(5),
    }
    with pm.Model(coords=coords) as model:
        target_idx = pm.Data("target_index", packed.target_index, dims="observation")
        x = pm.Data("x_pct_standardized", packed.x, dims=("observation", "feature_slot"))
        edge_idx = pm.Data("edge_index", packed.edge_index, dims=("observation", "feature_slot"))
        feature_mask = pm.Data("feature_mask", packed.feature_mask, dims=("observation", "feature_slot"))
        prediction_x = pm.Data("prediction_x_pct_standardized", packed.prediction_x, dims=("target", "feature_slot"))
        prediction_edge_idx = pm.Data("prediction_edge_index", packed.prediction_edge_index, dims=("target", "feature_slot"))
        prediction_mask = pm.Data("prediction_feature_mask", packed.prediction_feature_mask, dims=("target", "feature_slot"))

        direction_alpha_mu = pm.Normal("direction_alpha_mu", mu=config.direction_intercept_location, sigma=config.direction_intercept_scale)
        direction_alpha_scale = pm.HalfNormal("direction_alpha_scale", sigma=config.direction_intercept_scale)
        direction_alpha = pm.Normal("direction_alpha", mu=direction_alpha_mu, sigma=direction_alpha_scale, dims="target")
        direction_beta_mu = pm.Normal("direction_beta_mu", mu=config.direction_edge_location, sigma=config.direction_edge_scale)
        direction_beta_scale = pm.HalfNormal("direction_beta_scale", sigma=config.direction_edge_scale)
        direction_beta = pm.Normal("direction_beta", mu=direction_beta_mu, sigma=direction_beta_scale, dims="edge")
        direction_eta = direction_alpha[target_idx] + pm.math.sum(direction_beta[edge_idx] * x * feature_mask, axis=1)
        pm.Bernoulli("direction_observed", logit_p=direction_eta, observed=packed.y_direction, dims="observation")

        return_alpha_mu = pm.Normal("return_alpha_mu_pct", mu=config.return_intercept_location_pct, sigma=config.return_intercept_scale_pct)
        return_alpha_scale = pm.HalfNormal("return_alpha_scale_pct", sigma=config.return_intercept_scale_pct)
        return_alpha = pm.Normal("return_alpha", mu=return_alpha_mu, sigma=return_alpha_scale, dims="target")
        return_beta_mu = pm.Normal("return_beta_mu", mu=config.return_edge_location, sigma=config.return_edge_scale)
        return_beta_scale = pm.HalfNormal("return_beta_scale", sigma=config.return_edge_scale)
        return_beta = pm.Normal("return_beta", mu=return_beta_mu, sigma=return_beta_scale, dims="edge")
        return_sigma = pm.HalfNormal("return_sigma", sigma=config.return_sigma_scale_pct, dims="target")
        return_nu = pm.Exponential("return_nu_minus_two", lam=config.student_t_nu_rate) + config.student_t_nu_offset
        return_mu = return_alpha[target_idx] + pm.math.sum(return_beta[edge_idx] * x * feature_mask, axis=1)
        pm.StudentT("return_observed_pct", nu=return_nu, mu=return_mu, sigma=return_sigma[target_idx], observed=packed.y_return_pct, dims="observation")

        prediction_direction_eta = direction_alpha + pm.math.sum(
            direction_beta[prediction_edge_idx] * prediction_x * prediction_mask, axis=1,
        )
        pm.Deterministic("prediction_probability_up", pm.math.sigmoid(prediction_direction_eta), dims="target")
        prediction_return = return_alpha + pm.math.sum(
            return_beta[prediction_edge_idx] * prediction_x * prediction_mask, axis=1,
        )
        pm.Deterministic("prediction_expected_return_pct", prediction_return, dims="target")
    return model


def _flatten_diagnostic(dataset: Any) -> np.ndarray:
    if hasattr(dataset, "to_array"):
        values = np.asarray(dataset.to_array().values, dtype=float).reshape(-1)
    elif hasattr(dataset, "to_dataset"):
        # ArviZ 1.2 / PyMC 6 may return DataTree diagnostics. Convert only
        # the selected node and never traverse unrelated inference groups.
        node = dataset.to_dataset()
        if not getattr(node, "data_vars", None):
            raise PyMCBackendError("sampler diagnostic DataTree node is empty")
        values = np.asarray(node.to_array().values, dtype=float).reshape(-1)
    elif hasattr(dataset, "values"):
        values = np.asarray(dataset.values, dtype=float).reshape(-1)
    else:
        values = np.asarray(dataset, dtype=float).reshape(-1)
    return values[np.isfinite(values)]


def extract_sampler_diagnostics(az: Any, idata: Any, config: SamplerConfig) -> SamplerDiagnosticsEvidence:
    variables = list(_DIRECTION_VARS + _RETURN_VARS)
    posterior = idata.posterior
    stats = idata.sample_stats
    if "energy" not in stats:
        raise PyMCBackendError("NUTS energy evidence is missing")
    rhat_values = _flatten_diagnostic(az.rhat(posterior, var_names=variables))
    bulk_values = _flatten_diagnostic(az.ess(posterior, var_names=variables, method="bulk"))
    tail_values = _flatten_diagnostic(az.ess(posterior, var_names=variables, method="tail"))
    bfmi_values = _flatten_diagnostic(az.bfmi(stats["energy"]))
    if not all(len(values) for values in (rhat_values, bulk_values, tail_values, bfmi_values)):
        raise PyMCBackendError("sampler diagnostic extraction returned no evidence")
    divergences = int(np.asarray(stats["diverging"]).sum())
    if "reached_max_treedepth" in stats:
        depth_fraction = float(np.asarray(stats["reached_max_treedepth"], dtype=float).mean())
    elif "tree_depth" in stats:
        depth_fraction = float((np.asarray(stats["tree_depth"]) >= config.max_treedepth).mean())
    else:
        raise PyMCBackendError("NUTS tree-depth evidence is missing")
    return SamplerDiagnosticsEvidence(
        chains=config.chains,
        draws=config.draws,
        tune=config.tune,
        max_rhat=float(np.max(rhat_values)),
        min_bulk_ess=float(np.min(bulk_values)),
        min_tail_ess=float(np.min(tail_values)),
        bfmi_min=float(np.min(bfmi_values)),
        divergences=divergences,
        max_treedepth_fraction=depth_fraction,
    )


def extract_posterior(
    idata: Any,
    packed: PackedDesign,
    diagnostics: SamplerDiagnosticsEvidence,
) -> Mapping[str, CanonicalPercentPosterior]:
    posterior = idata.posterior
    probability = np.asarray(posterior["prediction_probability_up"], dtype=float)
    expected_return = np.asarray(posterior["prediction_expected_return_pct"], dtype=float)
    sigma = np.asarray(posterior["return_sigma"], dtype=float)
    if probability.shape[-1] != len(packed.tickers) or expected_return.shape[-1] != len(packed.tickers) or sigma.shape[-1] != len(packed.tickers):
        raise PyMCBackendError("posterior target coordinates differ from request coverage")
    if not np.isfinite(probability).all() or not np.isfinite(expected_return).all() or not np.isfinite(sigma).all():
        raise PyMCBackendError("posterior contains non-finite values")
    result: dict[str, CanonicalPercentPosterior] = {}
    for index, ticker in enumerate(packed.tickers):
        p = probability[..., index].reshape(-1)
        r = expected_return[..., index].reshape(-1)
        s = sigma[..., index].reshape(-1)
        result[ticker] = CanonicalPercentPosterior(
            ticker=ticker,
            probability_up_mean=float(np.mean(p)),
            probability_up_std=float(np.std(p, ddof=1)),
            probability_up_q05=float(np.quantile(p, 0.05)),
            probability_up_q95=float(np.quantile(p, 0.95)),
            expected_return_pct_mean=float(np.mean(r)),
            expected_return_pct_std=float(np.std(r, ddof=1)),
            predictive_risk_pct=float(sqrt(float(np.mean(np.square(s))) + float(np.var(r, ddof=1)))),
            diagnostics=diagnostics,
        )
    return result


def make_pymc_backend(
    config: FrozenBackendConfig,
    *,
    importer: Callable[[str], Any] = importlib.import_module,
) -> Callable[[HierarchicalFitRequest], HierarchicalBackendResult]:
    """Return a concrete lazy PyMC NUTS backend bound to exact hashes."""
    expected = freeze_backend_config(config.model, config.sampler)
    if config != expected:
        raise PyMCBackendError("backend configuration is not content-addressed")

    def backend(request: HierarchicalFitRequest) -> HierarchicalBackendResult:
        _validate_binding(request, config)
        packed = pack_design(request)
        try:
            pm = importer("pymc")
            az = importer("arviz")
        except (ImportError, ModuleNotFoundError) as exc:
            raise PyMCBackendError("exact PyMC/ArviZ dependency closure is unavailable") from exc
        model = build_pymc_model(pm, packed, config.model)
        sampler = config.sampler
        with model:
            idata = pm.sample(
                chains=sampler.chains,
                draws=sampler.draws,
                tune=sampler.tune,
                cores=sampler.cores,
                random_seed=list(sampler.random_seeds),
                target_accept=sampler.target_accept,
                init=sampler.init,
                progressbar=sampler.progressbar,
                compute_convergence_checks=sampler.compute_convergence_checks,
                discard_tuned_samples=sampler.discard_tuned_samples,
                return_inferencedata=True,
                nuts={"max_treedepth": sampler.max_treedepth},
            )
        diagnostics = extract_sampler_diagnostics(az, idata, sampler)
        posteriors = extract_posterior(idata, packed, diagnostics)
        return HierarchicalBackendResult(
            model_run_id=request.model_run_id,
            selection_id=request.selection_id,
            model_topology=request.model_topology,
            hierarchy=request.hierarchy,
            graph_contract_sha256=request.graph_contract_sha256,
            preregistered_model_config_sha256=request.preregistered_model_config_sha256,
            preregistered_sampler_sha256=request.preregistered_sampler_sha256,
            posterior_by_ticker=posteriors,
        )

    return backend
