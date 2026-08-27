"""Governed synthetic-only sampling rehearsal with durable evidence.

This deliberately cannot emit a canonical research posterior. Its result is a
fixture API/liveness observation with ``scientific_evidence=False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .checkpoint_quarantine_contract import DurableFixtureStore, FixtureTerminal
from .pymc_hierarchical_backend import (
    FrozenBackendConfig,
    PackedDesign,
    PyMCBackendError,
    build_pymc_model,
)


@dataclass(frozen=True)
class SyntheticSamplerRehearsal:
    chains: int = 1
    tune: int = 5
    draws: int = 5
    cores: int = 1
    seed: int = 1729
    target_accept: float = 0.8
    max_treedepth: int = 5
    fixture_only: bool = True
    scientific_evidence: bool = False
    persist_posterior: bool = False


def _validate_rehearsal(spec: SyntheticSamplerRehearsal, packed: PackedDesign) -> None:
    if type(spec) is not SyntheticSamplerRehearsal:
        raise PyMCBackendError("synthetic rehearsal type differs")
    if (
        spec.chains != 1 or not 1 <= spec.tune <= 20 or not 1 <= spec.draws <= 20
        or spec.cores != 1 or type(spec.seed) is not int or spec.seed <= 0
        or not 0.7 <= spec.target_accept <= 0.9 or not 4 <= spec.max_treedepth <= 8
    ):
        raise PyMCBackendError("synthetic rehearsal resource envelope differs")
    if spec.fixture_only is not True or spec.scientific_evidence is not False or spec.persist_posterior is not False:
        raise PyMCBackendError("synthetic rehearsal claim boundary differs")
    if not 1 <= len(packed.tickers) <= 4 or len(packed.target_index) > 512:
        raise PyMCBackendError("synthetic rehearsal fixture is too large")


def rehearse_synthetic_sampling(
    *,
    root: Path,
    run_id: str,
    plan_sha256: str,
    packed: PackedDesign,
    backend_config: FrozenBackendConfig,
    started_at_utc: datetime,
    importer: Callable[[str], Any],
    rehearsal: SyntheticSamplerRehearsal = SyntheticSamplerRehearsal(),
) -> FixtureTerminal:
    """Run a bounded smoke and retain only durable non-scientific evidence."""
    _validate_rehearsal(rehearsal, packed)
    store = DurableFixtureStore.create(
        root, run_id=run_id, plan_sha256=plan_sha256,
        created_at_utc=started_at_utc,
    )
    total_targets = len(packed.tickers)
    store.append_checkpoint(
        observed_at_utc=started_at_utc,
        completed_targets=0, total_targets=total_targets,
        completed_folds=0, total_folds=1, divergences=0,
    )
    try:
        pm = importer("pymc")
        model = build_pymc_model(pm, packed, backend_config.model)
        initial = model.initial_point()
        initial_logp = float(model.compile_logp()(initial))
        if not __import__("math").isfinite(initial_logp):
            raise PyMCBackendError("synthetic fixture initial log probability is non-finite")
        with model:
            idata = pm.sample(
                chains=1, tune=rehearsal.tune, draws=rehearsal.draws, cores=1,
                random_seed=[rehearsal.seed], target_accept=rehearsal.target_accept,
                init="jitter+adapt_diag", progressbar=False,
                compute_convergence_checks=False, discard_tuned_samples=True,
                return_inferencedata=True,
                nuts={"max_treedepth": rehearsal.max_treedepth},
            )
        expected_shape = (1, rehearsal.draws, total_targets)
        for variable in ("prediction_probability_up", "prediction_expected_return_pct"):
            if tuple(idata.posterior[variable].shape) != expected_shape:
                raise PyMCBackendError("synthetic fixture posterior shape differs")
        store.append_checkpoint(
            observed_at_utc=datetime.now(started_at_utc.tzinfo),
            completed_targets=total_targets, total_targets=total_targets,
            completed_folds=1, total_folds=1, divergences=0,
        )
        return store.finish(
            observed_at_utc=datetime.now(started_at_utc.tzinfo), success=True,
            completed_targets=total_targets, total_targets=total_targets,
            completed_folds=1, total_folds=1,
            failure_class=None,
        )
    except BaseException as exc:
        # Preserve a typed durable terminal without retaining or exposing any
        # partial posterior object. The original exception remains visible.
        store.finish(
            observed_at_utc=datetime.now(started_at_utc.tzinfo), success=False,
            completed_targets=0, total_targets=total_targets,
            completed_folds=0, total_folds=1,
            failure_class=type(exc).__name__,
        )
        raise
