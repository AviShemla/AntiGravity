from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from .noncentered_model_variant import (
    ConvergenceAmendmentError, audit_preregistration_amendment,
    build_noncentered_pymc_model, build_preregistration_amendment,
)
from .pymc_hierarchical_backend import (
    NumericModelConfig, PackedDesign,
)


class Expr:
    def __init__(self, label): self.label = label
    def __add__(self, other): return Expr(f"({self.label}+{getattr(other, 'label', other)})")
    __radd__ = __add__
    def __mul__(self, other): return Expr(f"({self.label}*{getattr(other, 'label', other)})")
    __rmul__ = __mul__
    def __getitem__(self, item): return Expr(f"{self.label}[{getattr(item, 'label', item)}]")


class Model:
    def __init__(self, **kwargs): self.coords = kwargs["coords"]
    def __enter__(self): return self
    def __exit__(self, *_): return False


class Math:
    @staticmethod
    def sum(value, axis): return Expr(f"sum({value.label},axis={axis})")
    @staticmethod
    def sigmoid(value): return Expr(f"sigmoid({value.label})")


class FakePM:
    math = Math()
    def __init__(self): self.calls = []
    def Model(self, **kwargs): self.model = Model(**kwargs); return self.model
    def _rv(self, kind, name, *args, **kwargs):
        self.calls.append((kind, name, args, kwargs)); return Expr(name)
    def Data(self, name, *args, **kwargs): return self._rv("Data", name, *args, **kwargs)
    def Normal(self, name, *args, **kwargs): return self._rv("Normal", name, *args, **kwargs)
    def HalfNormal(self, name, *args, **kwargs): return self._rv("HalfNormal", name, *args, **kwargs)
    def Exponential(self, name, *args, **kwargs): return self._rv("Exponential", name, *args, **kwargs)
    def Deterministic(self, name, *args, **kwargs): return self._rv("Deterministic", name, *args, **kwargs)
    def Bernoulli(self, name, *args, **kwargs): return self._rv("Bernoulli", name, *args, **kwargs)
    def StudentT(self, name, *args, **kwargs): return self._rv("StudentT", name, *args, **kwargs)


def packed():
    return PackedDesign(
        tickers=("AAA",), target_index=np.array([0, 0]),
        x=np.ones((2, 5)), edge_index=np.zeros((2, 5), dtype=int),
        feature_mask=np.array([[1, 0, 0, 0, 0]] * 2),
        y_direction=np.array([0, 1]), y_return_pct=np.array([-1.0, 1.0]),
        prediction_x=np.ones((1, 5)),
        prediction_edge_index=np.zeros((1, 5), dtype=int),
        prediction_feature_mask=np.array([[1, 0, 0, 0, 0]]),
        edge_names=("AAA<-BBB:lag1",),
    )


def calls_by_name(pm): return {name: (kind, args, kwargs) for kind, name, args, kwargs in pm.calls}


def test_amendment_is_hash_bound_and_execution_blocked():
    amendment = build_preregistration_amendment()
    audit_preregistration_amendment(amendment)
    assert amendment.changed_priors == ()
    assert len(amendment.changed_parameterization) == 4
    assert amendment.execution_authorized is False
    assert amendment.independent_approval_required is True
    assert amendment.failure_evidence_sha256 == "aa2100860767421576dde2947d0ab78e827e91c2108631786db1ff12f60e5602"
    assert amendment.run_log_sha256 == "b98b4d2f5d442889a4e43a9f5888986585025e02f898a360d87fbcb39bc117b4"
    assert amendment.sampling_completed is True
    assert amendment.scientific_convergence_accepted is False
    assert amendment.durable_progress_observed is False
    assert amendment.terminal_postprocessing_failure == "ARVIZ_DATATREE_DIAGNOSTIC_EXTRACTION"
    with pytest.raises(ConvergenceAmendmentError):
        audit_preregistration_amendment(replace(amendment, execution_authorized=True))


@pytest.mark.parametrize(
    "changed",
    [
        {"failure_evidence_sha256": "0" * 64},
        {"run_log_sha256": "0" * 64},
        {"sampling_completed": False},
        {"scientific_convergence_accepted": True},
        {"durable_progress_observed": True},
        {"maximum_checkpoint_gap_seconds": 600},
        {"terminal_postprocessing_failure": "SAMPLING_DID_NOT_COMPLETE"},
        {"all_chains_hit_max_treedepth": False},
        {"some_rhat_above_1_01": False},
        {"ess_per_chain_below_100": False},
        {"exact_max_rhat": 1.5},
        {"exact_min_ess_per_chain": 42.0},
    ],
)
def test_failure_evidence_tamper_or_conflation_is_rejected(changed):
    with pytest.raises(ConvergenceAmendmentError, match="identity"):
        audit_preregistration_amendment(
            replace(build_preregistration_amendment(), **changed)
        )


def test_measured_resources_and_sampler_counts_are_exact_not_inferred():
    value = build_preregistration_amendment()
    assert (value.chains, value.tune_per_chain, value.draws_per_chain) == (4, 1000, 1000)
    assert value.sampling_elapsed_seconds == 7425
    assert value.cpu_quota_percent == 200
    assert value.memory_peak_bytes == 1404485632
    assert value.cpu_usage_nsec == 14782971921000
    assert value.exact_max_rhat is value.exact_min_ess_per_chain is None


def test_noncentered_graph_uses_unit_raw_latents_and_preserves_named_coefficients():
    pm = FakePM()
    build_noncentered_pymc_model(pm, packed(), NumericModelConfig())
    calls = calls_by_name(pm)
    for raw, dim in (("direction_alpha_raw", "target"), ("direction_beta_raw", "edge"),
                     ("return_alpha_raw", "target"), ("return_beta_raw", "edge")):
        kind, _, kwargs = calls[raw]
        assert kind == "Normal"
        assert kwargs == {"mu": 0.0, "sigma": 1.0, "dims": dim}
    for name in ("direction_alpha", "direction_beta", "return_alpha", "return_beta"):
        assert calls[name][0] == "Deterministic"


def test_hyperpriors_likelihoods_and_prediction_names_are_unchanged():
    pm = FakePM(); config = NumericModelConfig()
    build_noncentered_pymc_model(pm, packed(), config)
    calls = calls_by_name(pm)
    assert calls["direction_alpha_mu"] == ("Normal", (), {"mu": 0.0, "sigma": 1.0})
    assert calls["direction_alpha_scale"] == ("HalfNormal", (), {"sigma": 1.0})
    assert calls["direction_beta_mu"] == ("Normal", (), {"mu": 0.0, "sigma": 0.5})
    assert calls["direction_beta_scale"] == ("HalfNormal", (), {"sigma": 0.5})
    assert calls["return_alpha_mu_pct"] == ("Normal", (), {"mu": 0.0, "sigma": 1.0})
    assert calls["return_alpha_scale_pct"] == ("HalfNormal", (), {"sigma": 1.0})
    assert calls["return_beta_mu"] == ("Normal", (), {"mu": 0.0, "sigma": 0.5})
    assert calls["return_beta_scale"] == ("HalfNormal", (), {"sigma": 0.5})
    assert calls["return_sigma"] == ("HalfNormal", (), {"sigma": 2.0, "dims": "target"})
    assert calls["return_nu_minus_two"] == ("Exponential", (), {"lam": 0.1})
    assert calls["direction_observed"][0] == "Bernoulli"
    assert calls["return_observed_pct"][0] == "StudentT"
    assert calls["prediction_probability_up"][0] == "Deterministic"
    assert calls["prediction_expected_return_pct"][0] == "Deterministic"


def test_input_geometry_and_semantic_coordinates_are_unchanged():
    pm = FakePM(); build_noncentered_pymc_model(pm, packed(), NumericModelConfig())
    assert pm.model.coords["feature_slot"].tolist() == [0, 1, 2, 3, 4]
    assert pm.model.coords["target"] == ("AAA",)
    assert pm.model.coords["edge"] == ("AAA<-BBB:lag1",)
    assert "x_pct_standardized" in calls_by_name(pm)


def test_invalid_numeric_semantics_remain_rejected():
    with pytest.raises(Exception, match="semantics differ"):
        build_noncentered_pymc_model(
            FakePM(), packed(), NumericModelConfig(edge_coefficients="POSITIONAL_CHAIN"),
        )


def test_module_exposes_no_sampler_or_io_path():
    from . import noncentered_model_variant as module
    names = set(vars(module))
    assert names.isdisjoint({"sample", "open", "Path", "subprocess", "socket", "requests", "sqlite3"})
