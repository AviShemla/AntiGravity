"""Approval-blocked, build-only non-centered candidate for the S08 PyMC graph.

This module only constructs a graph from injected in-memory values.  It has no
sampler, filesystem, network, database, persistence, or execution path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

import numpy as np

try:
    from .pymc_hierarchical_backend import (
        NumericModelConfig, PackedDesign, _validate_numeric_config,
    )
except ImportError:  # isolated fixture review before canonical integration
    from research_contracts.pymc_stock_model_backend.pymc_hierarchical_backend import (
        NumericModelConfig, PackedDesign, _validate_numeric_config,
    )


AMENDMENT_ID = "codex-oracle-s08-noncentered-preregistration-v1"
BASE_BACKEND_ID = "codex-oracle-pymc-independent-edge-hierarchy-v1"
CANDIDATE_BACKEND_ID = "codex-oracle-pymc-independent-edge-hierarchy-noncentered-v2"
V6_INVOCATION_ID = "e8a9f0c2b3834aaf88c3ffbd333a77a6"
V6_TERMINAL_STATUS = 1
V6_FAILURE_EVIDENCE_SHA256 = "aa2100860767421576dde2947d0ab78e827e91c2108631786db1ff12f60e5602"
V6_RUN_LOG_SHA256 = "b98b4d2f5d442889a4e43a9f5888986585025e02f898a360d87fbcb39bc117b4"


class ConvergenceAmendmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreregistrationAmendment:
    amendment_id: str
    base_backend_id: str
    candidate_backend_id: str
    v6_invocation_id: str
    v6_terminal_status: int
    failure_evidence_sha256: str
    run_log_sha256: str
    systemd_started_at_utc: str
    systemd_exited_at_utc: str
    sampling_elapsed_seconds: int
    cpu_quota_percent: int
    memory_peak_bytes: int
    cpu_usage_nsec: int
    chains: int
    tune_per_chain: int
    draws_per_chain: int
    sampling_completed: bool
    all_chains_hit_max_treedepth: bool
    some_rhat_above_1_01: bool
    ess_per_chain_below_100: bool
    exact_max_rhat: float | None
    exact_min_ess_per_chain: float | None
    scientific_convergence_accepted: bool
    durable_progress_observed: bool
    maximum_checkpoint_gap_seconds: int | None
    terminal_postprocessing_failure: str
    changed_parameterization: tuple[str, ...]
    changed_priors: tuple[str, ...]
    preserved_semantics: tuple[str, ...]
    convergence_gates: tuple[str, ...]
    execution_authorized: bool
    independent_approval_required: bool
    amendment_sha256: str


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_preregistration_amendment() -> PreregistrationAmendment:
    payload = {
        "amendment_id": AMENDMENT_ID,
        "base_backend_id": BASE_BACKEND_ID,
        "candidate_backend_id": CANDIDATE_BACKEND_ID,
        "v6_invocation_id": V6_INVOCATION_ID,
        "v6_terminal_status": V6_TERMINAL_STATUS,
        "failure_evidence_sha256": V6_FAILURE_EVIDENCE_SHA256,
        "run_log_sha256": V6_RUN_LOG_SHA256,
        "systemd_started_at_utc": "2026-08-27T12:52:22Z",
        "systemd_exited_at_utc": "2026-08-27T14:58:32Z",
        "sampling_elapsed_seconds": 7425,
        "cpu_quota_percent": 200,
        "memory_peak_bytes": 1404485632,
        "cpu_usage_nsec": 14782971921000,
        "chains": 4,
        "tune_per_chain": 1000,
        "draws_per_chain": 1000,
        "sampling_completed": True,
        "all_chains_hit_max_treedepth": True,
        "some_rhat_above_1_01": True,
        "ess_per_chain_below_100": True,
        # The preserved warning establishes threshold failures but not exact
        # extrema; those values must remain UNKNOWN rather than reconstructed.
        "exact_max_rhat": None,
        "exact_min_ess_per_chain": None,
        "scientific_convergence_accepted": False,
        "durable_progress_observed": False,
        "maximum_checkpoint_gap_seconds": None,
        "terminal_postprocessing_failure": "ARVIZ_DATATREE_DIAGNOSTIC_EXTRACTION",
        "changed_parameterization": (
            "direction_alpha=direction_alpha_mu+direction_alpha_scale*direction_alpha_raw",
            "direction_beta=direction_beta_mu+direction_beta_scale*direction_beta_raw",
            "return_alpha=return_alpha_mu_pct+return_alpha_scale_pct*return_alpha_raw",
            "return_beta=return_beta_mu+return_beta_scale*return_beta_raw",
        ),
        # The transformation is exactly distribution-preserving conditional on
        # the unchanged hyperparameters; no prior scale/location is amended.
        "changed_priors": (),
        "preserved_semantics": (
            "SAME_DIRECTION_BERNOULLI_LOGIT_TARGET",
            "SAME_RETURN_STUDENT_T_PERCENT_TARGET",
            "SAME_TRAINING_ONLY_STANDARDIZED_INPUTS",
            "SAME_INDEPENDENT_TARGET_SOURCE_LAG_EDGES_LAGS_1_7_DEPTH_1_5",
            "SAME_DATA_AND_OUTCOME_DEFINITIONS",
            "SAME_FOUR_CHAIN_1000_TUNE_1000_DRAW_SAMPLER_MINIMUM",
            "NO_POSITIONAL_LAG_INFERENCE",
            "NO_CAUSAL_CLAIM",
        ),
        "convergence_gates": (
            "MAX_RHAT_LE_1.01", "MIN_BULK_ESS_GE_400",
            "MIN_TAIL_ESS_GE_400", "MIN_BFMI_GE_0.3",
            "DIVERGENCES_EQ_0", "MAX_TREEDEPTH_FRACTION_LE_0.01",
        ),
        "execution_authorized": False,
        "independent_approval_required": True,
    }
    return PreregistrationAmendment(
        **payload, amendment_sha256=_canonical_sha256(payload),
    )


def audit_preregistration_amendment(value: PreregistrationAmendment) -> None:
    if type(value) is not PreregistrationAmendment:
        raise ConvergenceAmendmentError("amendment type differs")
    if value != build_preregistration_amendment():
        raise ConvergenceAmendmentError("amendment identity or safety boundary differs")


def build_noncentered_pymc_model(
    pm: Any, packed: PackedDesign, config: NumericModelConfig,
) -> Any:
    """Build the candidate graph without sampling or authorizing execution."""
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
        direction_alpha_raw = pm.Normal("direction_alpha_raw", mu=0.0, sigma=1.0, dims="target")
        direction_alpha = pm.Deterministic("direction_alpha", direction_alpha_mu + direction_alpha_scale * direction_alpha_raw, dims="target")
        direction_beta_mu = pm.Normal("direction_beta_mu", mu=config.direction_edge_location, sigma=config.direction_edge_scale)
        direction_beta_scale = pm.HalfNormal("direction_beta_scale", sigma=config.direction_edge_scale)
        direction_beta_raw = pm.Normal("direction_beta_raw", mu=0.0, sigma=1.0, dims="edge")
        direction_beta = pm.Deterministic("direction_beta", direction_beta_mu + direction_beta_scale * direction_beta_raw, dims="edge")
        direction_eta = direction_alpha[target_idx] + pm.math.sum(direction_beta[edge_idx] * x * feature_mask, axis=1)
        pm.Bernoulli("direction_observed", logit_p=direction_eta, observed=packed.y_direction, dims="observation")

        return_alpha_mu = pm.Normal("return_alpha_mu_pct", mu=config.return_intercept_location_pct, sigma=config.return_intercept_scale_pct)
        return_alpha_scale = pm.HalfNormal("return_alpha_scale_pct", sigma=config.return_intercept_scale_pct)
        return_alpha_raw = pm.Normal("return_alpha_raw", mu=0.0, sigma=1.0, dims="target")
        return_alpha = pm.Deterministic("return_alpha", return_alpha_mu + return_alpha_scale * return_alpha_raw, dims="target")
        return_beta_mu = pm.Normal("return_beta_mu", mu=config.return_edge_location, sigma=config.return_edge_scale)
        return_beta_scale = pm.HalfNormal("return_beta_scale", sigma=config.return_edge_scale)
        return_beta_raw = pm.Normal("return_beta_raw", mu=0.0, sigma=1.0, dims="edge")
        return_beta = pm.Deterministic("return_beta", return_beta_mu + return_beta_scale * return_beta_raw, dims="edge")
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

