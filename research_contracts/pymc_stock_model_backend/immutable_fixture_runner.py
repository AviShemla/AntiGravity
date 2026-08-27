"""No-I/O runner gate joining an immutable execution artifact to PyMC.

The only executable path in this isolated package requires ``fixture_only``.
The future immutable production runner must replace this gate after its release,
checkpoint, resource, and independent-readback integration is reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable

try:
    from model_fit_contract_impl.execution_contract import (
        AuthorizationStatus,
        ExecutionAuthorizationArtifact,
    )
except ImportError:
    from research_contracts.stock_model_fit_execution.execution_contract import (
        AuthorizationStatus,
        ExecutionAuthorizationArtifact,
    )

try:
    from hierarchical_model_impl.independent_edge_hierarchy import (
        HierarchicalFitRequest,
        ValidatedHierarchicalResult,
        run_hierarchical_backend,
    )
except ImportError:
    from research_contracts.hierarchical_stock_model.independent_edge_hierarchy import (
        HierarchicalFitRequest,
        ValidatedHierarchicalResult,
        run_hierarchical_backend,
    )

from .pymc_hierarchical_backend import FrozenBackendConfig, PyMCBackendError, make_pymc_backend


RUNNER_ID = "codex-oracle-s08-immutable-fixture-runner-v1"


@dataclass(frozen=True)
class ImmutableFixtureRunPlan:
    runner_id: str
    execution_artifact_id: str
    run_id: str
    model_run_id: str
    model_config_sha256: str
    sampler_sha256: str
    output_root: str
    fixture_only: bool
    database_write_scope: str
    downstream_authorized: bool
    plan_sha256: str


def _plan_payload(
    artifact: ExecutionAuthorizationArtifact,
    request: HierarchicalFitRequest,
    config: FrozenBackendConfig,
) -> dict[str, object]:
    return {
        "runner_id": RUNNER_ID,
        "execution_artifact_id": artifact.artifact_id,
        "run_id": artifact.run_id,
        "model_run_id": request.model_run_id,
        "model_config_sha256": config.model_config_sha256,
        "sampler_sha256": config.sampler_sha256,
        "output_root": artifact.output_root,
        "fixture_only": True,
        "database_write_scope": "NONE",
        "downstream_authorized": False,
    }


def build_fixture_run_plan(
    artifact: ExecutionAuthorizationArtifact,
    request: HierarchicalFitRequest,
    config: FrozenBackendConfig,
) -> ImmutableFixtureRunPlan:
    if type(artifact) is not ExecutionAuthorizationArtifact:
        raise PyMCBackendError("execution artifact type differs")
    if artifact.status is not AuthorizationStatus.AUTHORIZED_NOT_STARTED:
        raise PyMCBackendError("execution artifact is not authorized-not-started")
    if artifact.model_fit_started or artifact.launch_performed:
        raise PyMCBackendError("execution artifact already records a launch")
    if artifact.database_writes_authorized or artifact.downstream_authorized:
        raise PyMCBackendError("execution artifact crosses the research-only boundary")
    if artifact.run_id != request.model_run_id:
        raise PyMCBackendError("execution artifact and model request run IDs differ")
    if request.preregistered_model_config_sha256 != config.model_config_sha256 or request.preregistered_sampler_sha256 != config.sampler_sha256:
        raise PyMCBackendError("model request differs from frozen backend hashes")
    payload = _plan_payload(artifact, request, config)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return ImmutableFixtureRunPlan(**payload, plan_sha256=hashlib.sha256(raw).hexdigest())


def run_fixture_plan(
    plan: ImmutableFixtureRunPlan,
    artifact: ExecutionAuthorizationArtifact,
    request: HierarchicalFitRequest,
    config: FrozenBackendConfig,
    *,
    importer: Callable[[str], object],
) -> ValidatedHierarchicalResult:
    expected = build_fixture_run_plan(artifact, request, config)
    if plan != expected or plan.fixture_only is not True:
        raise PyMCBackendError("fixture run plan identity differs")
    backend = make_pymc_backend(config, importer=importer)
    return run_hierarchical_backend(request, backend=backend)
