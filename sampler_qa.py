"""Central fail-closed QA for PyMC posterior traces."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np


@dataclass(frozen=True)
class SamplerDiagnostics:
    max_rhat: float
    min_ess_bulk: float
    min_ess_tail: float
    min_bfmi: float
    divergences: int
    tree_depth_saturation_fraction: float
    chains: int


def validate_sampler_diagnostics(
    diagnostics: SamplerDiagnostics,
    *,
    max_rhat: float = 1.05,
    min_ess_bulk: float = 200.0,
    min_ess_tail: float = 100.0,
    min_bfmi: float = 0.20,
    max_divergences: int = 0,
    max_tree_depth_saturation_fraction: float = 0.01,
) -> None:
    values = (
        diagnostics.max_rhat,
        diagnostics.min_ess_bulk,
        diagnostics.min_ess_tail,
        diagnostics.min_bfmi,
        diagnostics.tree_depth_saturation_fraction,
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("PyMC sampler diagnostics contain non-finite values.")
    failures: list[str] = []
    if diagnostics.chains < 2:
        failures.append("fewer than two chains")
    if diagnostics.max_rhat > max_rhat:
        failures.append(f"R-hat {diagnostics.max_rhat:.4f} > {max_rhat:.4f}")
    if diagnostics.min_ess_bulk < min_ess_bulk:
        failures.append(f"bulk ESS {diagnostics.min_ess_bulk:.1f} < {min_ess_bulk:.1f}")
    if diagnostics.min_ess_tail < min_ess_tail:
        failures.append(f"tail ESS {diagnostics.min_ess_tail:.1f} < {min_ess_tail:.1f}")
    if diagnostics.min_bfmi < min_bfmi:
        failures.append(f"E-BFMI {diagnostics.min_bfmi:.4f} < {min_bfmi:.4f}")
    if diagnostics.divergences > max_divergences:
        failures.append(f"divergences {diagnostics.divergences} > {max_divergences}")
    if diagnostics.tree_depth_saturation_fraction > max_tree_depth_saturation_fraction:
        failures.append(
            "tree-depth saturation "
            f"{diagnostics.tree_depth_saturation_fraction:.4f} > "
            f"{max_tree_depth_saturation_fraction:.4f}"
        )
    if failures:
        raise ValueError("PyMC sampler QA failed: " + "; ".join(failures))


def sampler_diagnostics(trace) -> SamplerDiagnostics:
    """Extract diagnostics from an ArviZ InferenceData object."""
    import arviz as az

    summary = az.summary(trace, kind="diagnostics")
    required = {"r_hat", "ess_bulk", "ess_tail"}
    if not required.issubset(summary.columns):
        raise ValueError("PyMC trace is missing R-hat or ESS diagnostics.")
    sample_stats = trace.sample_stats
    if "energy" not in sample_stats:
        raise ValueError("PyMC trace is missing energy diagnostics for E-BFMI.")
    # ArviZ 1.2 returns an xarray DataTree when bfmi() receives the complete
    # PyMC 6 InferenceData object.  Passing the explicit energy DataArray keeps
    # the result an array-like diagnostic across both legacy and current APIs.
    bfmi = np.asarray(az.bfmi(sample_stats["energy"]), dtype=float).reshape(-1)
    divergences = int(np.asarray(sample_stats["diverging"], dtype=int).sum())
    tree_fraction = 0.0
    if "tree_depth" in sample_stats:
        tree_depth = np.asarray(sample_stats["tree_depth"], dtype=float)
        observed_max = float(np.nanmax(tree_depth))
        tree_fraction = float(np.mean(tree_depth >= observed_max)) if observed_max >= 10 else 0.0
    return SamplerDiagnostics(
        max_rhat=float(summary["r_hat"].max()),
        min_ess_bulk=float(summary["ess_bulk"].min()),
        min_ess_tail=float(summary["ess_tail"].min()),
        min_bfmi=float(bfmi.min()),
        divergences=divergences,
        tree_depth_saturation_fraction=tree_fraction,
        chains=int(trace.posterior.sizes.get("chain", 0)),
    )


def validate_sampler_trace(trace) -> SamplerDiagnostics:
    diagnostics = sampler_diagnostics(trace)
    validate_sampler_diagnostics(diagnostics)
    return diagnostics
