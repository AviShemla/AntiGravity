"""Executable Linux-only four-chain synthetic rehearsal; no real data or I/O."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import sys

import arviz as az
import numpy as np
import pymc as pm
import pytensor

try:
    from hierarchical_model_impl.independent_edge_hierarchy import (
        run_hierarchical_backend,
    )
except ModuleNotFoundError:
    from research_contracts.hierarchical_stock_model.independent_edge_hierarchy import (
        run_hierarchical_backend,
    )
from .linux_fixture_execution_contract import (
    build_dependency_lock, build_synthetic_convergence_evidence,
    verify_dependency_lock, verify_synthetic_convergence_evidence,
)
from .pymc_hierarchical_backend import freeze_backend_config, make_pymc_backend, pack_design
from .test_pymc_backend_runner import _request


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _records_sha() -> str:
    records = {}
    for name in ("pymc", "pytensor", "arviz", "numpy"):
        dist = importlib.metadata.distribution(name)
        text = dist.read_text("RECORD")
        if text is None:
            raise RuntimeError(f"{name} distribution RECORD is absent")
        records[name] = hashlib.sha256(text.encode()).hexdigest()
    raw = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _blas_sha() -> str:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        np.show_config()
    return hashlib.sha256(output.getvalue().encode()).hexdigest()


def _fixture_sha(packed) -> str:
    digest = hashlib.sha256()
    for label in (packed.tickers, packed.edge_names):
        digest.update(json.dumps(label, separators=(",", ":")).encode())
    for array in (packed.target_index, packed.x, packed.edge_index,
                  packed.feature_mask, packed.y_direction,
                  packed.y_return_pct, packed.prediction_x,
                  packed.prediction_edge_index, packed.prediction_feature_mask):
        value = np.ascontiguousarray(array)
        digest.update(str(value.dtype).encode())
        digest.update(json.dumps(value.shape).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def main() -> None:
    config = freeze_backend_config()
    request = _request(config)
    packed = pack_design(request)
    identity = {
        "platform_system": platform.system(), "platform_machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable_sha256": _file_sha(Path(sys.executable)),
        "pymc_version": pm.__version__, "pytensor_version": pytensor.__version__,
        "arviz_version": az.__version__, "numpy_version": np.__version__,
        "blas_identity_sha256": _blas_sha(),
        "distribution_records_sha256": _records_sha(),
    }
    lock = build_dependency_lock(**identity)
    verify_dependency_lock(lock, identity)
    result = run_hierarchical_backend(request, backend=make_pymc_backend(config))
    diagnostics = next(iter(result.posterior_by_ticker.values())).diagnostics
    evidence = build_synthetic_convergence_evidence(
        run_id="fixture-four-chain-linux", fixture_sha256=_fixture_sha(packed),
        lock=lock, config=config, diagnostics=diagnostics)
    verify_synthetic_convergence_evidence(
        evidence, lock=lock, config=config, fixture_sha256=evidence.fixture_sha256)
    print("FOUR_CHAIN_SYNTHETIC_CONVERGENCE_PASS")
    print(f"dependency_lock_sha256={lock.lock_sha256}")
    print(f"fixture_sha256={evidence.fixture_sha256}")
    print(f"model_config_sha256={evidence.model_config_sha256}")
    print(f"sampler_sha256={evidence.sampler_sha256}")
    print(f"evidence_sha256={evidence.evidence_sha256}")
    print(f"chains={diagnostics.chains}")
    print(f"draws={diagnostics.draws}")
    print(f"tune={diagnostics.tune}")
    print(f"max_rhat={diagnostics.max_rhat:.9f}")
    print(f"min_bulk_ess={diagnostics.min_bulk_ess:.3f}")
    print(f"min_tail_ess={diagnostics.min_tail_ess:.3f}")
    print(f"bfmi_min={diagnostics.bfmi_min:.9f}")
    print(f"divergences={diagnostics.divergences}")
    print(f"max_treedepth_fraction={diagnostics.max_treedepth_fraction:.9f}")
    print("fixture_only=true")
    print("scientific_evidence=false")
    print("posterior_persisted=false")
    print("database_write_scope=NONE")
    print("downstream_outputs=0")


if __name__ == "__main__":
    main()
