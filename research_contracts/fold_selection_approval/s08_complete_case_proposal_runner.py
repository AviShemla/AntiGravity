#!/usr/bin/env python3
"""Root-only, write-once wrapper for the inert S08 complete-case proposal."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from research_contracts.stock_model_preregistration.produce_current_baseline_readback import (
    TursoReadPipeline, normalize_turso_pipeline_endpoint, production_credentials,
)
from research_contracts.stock_model_preregistration.stock_preregistration_runtime import (
    RuntimeBoundaryError, write_json_once,
)

from .s08_complete_case_proposal_runtime import (
    AuditPins, SelectOnlyAssemblyError, assemble_v6_proposal,
    load_canonical_artifacts, load_installed_s07_artifacts,
)
from .training_fold_selection_approval_v4 import canonical_json_bytes


CONTRACT_ID = "codex-oracle-s08-complete-case-proposal-runner-v2"
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


class SelectOnlyRunnerError(RuntimeError):
    pass


def _root_directory(path: Path, label: str) -> None:
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise SelectOnlyRunnerError(f"{label} must be root:root mode 0700")


def _effective_uid() -> int:
    getter = getattr(os, "geteuid", None)
    if getter is None:
        raise SelectOnlyRunnerError("effective UID is unavailable")
    return getter()


def _write_once(path: Path, payload: dict[str, object]) -> str:
    _root_directory(path.parent, "output parent")
    try:
        return write_json_once(path, payload)
    except RuntimeBoundaryError as exc:
        raise SelectOnlyRunnerError(str(exc)) from exc


def _proposal_summary(proposal) -> dict[str, object]:
    return {
        "status": proposal.status,
        "selection_count": len(proposal.selections),
        "proposal_core_sha256": proposal.proposal_core_sha256,
        "approval_record_sha256": None,
        "artifact_sha256": dict(proposal.artifact_sha256),
    }


def run(
    *, client: object, repository_root: Path, s07_directory: Path,
    preregistration_manifest_path: Path, output_path: Path,
    runtime_git_commit: str, observed_at_utc: datetime,
    pins: AuditPins = AuditPins(),
) -> tuple[dict[str, object], str]:
    if _effective_uid() != 0:
        raise SelectOnlyRunnerError("runner must execute as root")
    if type(runtime_git_commit) is not str or not _GIT_SHA.fullmatch(runtime_git_commit):
        raise SelectOnlyRunnerError("runtime Git commit format differs")
    assembly = assemble_v6_proposal(
        client, artifacts=load_canonical_artifacts(repository_root),
        s07_artifacts=load_installed_s07_artifacts(
            s07_directory, preregistration_manifest_path=preregistration_manifest_path,
        ),
        observed_at_utc=observed_at_utc, runtime_git_commit=runtime_git_commit,
        pins=pins,
    )
    if (not assembly.s07_readback_fresh or assembly.execution_authorized
            or assembly.proposal.status != "APPROVAL_REQUIRED"
            or assembly.proposal.selections != ()
            or any((assembly.database_writes, assembly.selection_runs,
                    assembly.model_runs, assembly.predictions,
                    assembly.recommendations, assembly.orders,
                    assembly.downstream_outputs))):
        raise SelectOnlyRunnerError("assembly is not fresh and inert")
    payload = {
        "contract_id": CONTRACT_ID,
        "status": "VERIFIED_UNSIGNED_PROPOSAL_ONLY",
        "observed_at_utc": observed_at_utc.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "runtime_source_sha256": hashlib.sha256(
            Path(__file__).with_name("s08_complete_case_proposal_runtime.py").read_bytes()
        ).hexdigest(),
        "runner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "assembly": {
            key: value for key, value in asdict(assembly).items()
            if key != "proposal"
        },
        "proposal": _proposal_summary(assembly.proposal),
        "boundary": {
            "database_writes": 0, "selection_runs": 0, "model_runs": 0,
            "predictions": 0, "recommendations": 0, "orders": 0,
            "downstream_outputs": 0, "execution_authorized": False,
        },
    }
    digest = _write_once(output_path, payload)
    return payload, digest


def run_from_files(
    *, env_file: Path, repository_root: Path, s07_directory: Path,
    preregistration_manifest_path: Path, output_path: Path,
    runtime_git_commit: str, timeout_seconds: float = 120.0,
    now=lambda: datetime.now(timezone.utc),
) -> tuple[dict[str, object], str]:
    if not 10 <= timeout_seconds <= 300:
        raise SelectOnlyRunnerError("timeout is outside the governed range")
    endpoint, token = production_credentials(env_file)
    client = TursoReadPipeline(
        normalize_turso_pipeline_endpoint(endpoint), token,
        timeout_seconds=timeout_seconds,
    )
    return run(
        client=client, repository_root=repository_root,
        s07_directory=s07_directory,
        preregistration_manifest_path=preregistration_manifest_path,
        output_path=output_path, runtime_git_commit=runtime_git_commit,
        observed_at_utc=now(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--s07-directory", type=Path, required=True)
    parser.add_argument("--preregistration-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-git-commit", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    try:
        _payload, digest = run_from_files(
            env_file=args.env_file, repository_root=args.repository_root,
            s07_directory=args.s07_directory,
            preregistration_manifest_path=args.preregistration_manifest,
            output_path=args.output, runtime_git_commit=args.runtime_git_commit,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, SelectOnlyAssemblyError, SelectOnlyRunnerError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": "VERIFIED_UNSIGNED_PROPOSAL_ONLY",
        "artifact_sha256": digest, "database_writes": 0,
        "selection_runs": 0, "model_runs": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
