#!/usr/bin/env python3
"""Independently verify source evidence and its canonical readback artifact."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

try:
    from . import stock_model_preregistration_binding as binding
    from .audit_stock_preregistration_manifest import parse_verified_readback
    from .current_baseline_readback_contract import (
        EXPECTED_COVERAGE, EXPECTED_DOWNSTREAM, EXPECTED_SIDE_EFFECTS,
        REQUIRED_SELECT_QUERIES, SOURCE_AUDIT_CONTRACT_ID, canonical_sha,
    )
    from .stock_model_preregistration import (
        BaselineAuditEvidence, compute_baseline_audit_sha256,
    )
    from .stock_preregistration_runtime import (
        RuntimeBoundaryError, read_root_owned_json,
    )
except ImportError:
    import stock_model_preregistration_binding as binding
    from audit_stock_preregistration_manifest import parse_verified_readback
    from current_baseline_readback_contract import (
        EXPECTED_COVERAGE, EXPECTED_DOWNSTREAM, EXPECTED_SIDE_EFFECTS,
        REQUIRED_SELECT_QUERIES, SOURCE_AUDIT_CONTRACT_ID, canonical_sha,
    )
    from stock_model_preregistration import (
        BaselineAuditEvidence, compute_baseline_audit_sha256,
    )
    from stock_preregistration_runtime import (
        RuntimeBoundaryError, read_root_owned_json,
    )


SOURCE_CONTRACT_ID = "codex-oracle-current-baseline-source-evidence-v1"
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


class IndependentReadbackVerificationError(RuntimeBoundaryError):
    """Raised when either persisted evidence layer differs."""


def _read_exact_0600(path: Path, label: str):
    if not path.is_absolute() or path.is_symlink():
        raise IndependentReadbackVerificationError(f"{label} path differs")
    metadata = os.lstat(path)
    if (not hasattr(metadata, "st_uid") or metadata.st_uid != 0 or
            not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
            stat.S_IMODE(metadata.st_mode) != 0o600):
        raise IndependentReadbackVerificationError(
            f"{label} must be root-owned mode-0600 single-link"
        )
    return read_root_owned_json(path, label)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise IndependentReadbackVerificationError(f"{label} schema differs")
    return value


def _expected_lineage(final, final_sha, audit, audit_sha, mapping):
    if (final_sha != binding.PINNED_FINAL_MANIFEST_RAW_SHA256 or
            audit_sha != binding.PINNED_IMMUTABLE_AUDIT_RAW_SHA256):
        raise IndependentReadbackVerificationError("immutable raw v4 identity differs")
    lineage, tickers, sessions = binding._validate_lineage(mapping)
    executor, completed = binding._validate_final_manifest(
        final, raw_sha256=final_sha, lineage=lineage, tickers=tickers,
    )
    immutable, observed = binding._validate_audit(
        audit, raw_sha256=audit_sha, final_raw_sha256=final_sha,
        deterministic_sha256=final["deterministic_evidence_sha256"],
        executor_commit=executor, completion=completed,
        sessions_sha256=lineage["sessions_sha256"], immutable=True,
    )
    universe_sha = lineage["ticker_universe_sha256"]
    universe_id = f"codex-oracle-stock-universe-v1:{binding.SNAPSHOT_ID}:{universe_sha}"
    model_dates = tuple(sessions[-416:])
    evidence = BaselineAuditEvidence(
        status="VERIFIED", baseline_manifest_sha256=final_sha,
        snapshot_id=binding.SNAPSHOT_ID, snapshot_sha256=binding.SNAPSHOT_SHA256,
        universe_id=universe_id, universe_sha256=universe_sha,
        full_session_calendar_sha256=lineage["sessions_sha256"],
        model_session_dates_sha256=canonical_sha(list(model_dates)),
        source_audit_artifact_sha256=audit_sha,
        embedded_audit_evidence_sha256=immutable["audit_evidence_sha256"],
        audit_sha256="0" * 64, completed_at_utc=completed,
        observed_at_utc=observed, ticker_count=474, fold_count=1_896,
        oos_observation_count=56_880, side_effects=dict(binding.ZERO_SIDE_EFFECTS),
        downstream_counts=dict(binding.ZERO_DOWNSTREAM),
    )
    envelope = compute_baseline_audit_sha256(evidence)
    return {
        "source_contract_id": SOURCE_AUDIT_CONTRACT_ID,
        "snapshot_id": binding.SNAPSHOT_ID,
        "snapshot_sha256": binding.SNAPSHOT_SHA256,
        "universe_id": universe_id,
        "universe_sha256": universe_sha,
        "full_session_calendar_sha256": lineage["sessions_sha256"],
        "model_session_dates_sha256": canonical_sha(list(model_dates)),
        "baseline_manifest_sha256": final_sha,
        "source_audit_artifact_sha256": audit_sha,
        "embedded_audit_evidence_sha256": immutable["audit_evidence_sha256"],
        "audit_envelope_sha256": envelope,
        "source_code_git_sha": executor,
        "audit_completed_at_utc": completed.astimezone(timezone.utc).isoformat(),
        "audit_observed_at_utc": observed.astimezone(timezone.utc).isoformat(),
    }, tuple(sessions), model_dates


def verify(
    *, source: dict[str, object], source_raw_sha256: str,
    artifact: dict[str, object], artifact_raw_sha256: str,
    final_manifest: dict[str, object], final_raw_sha256: str,
    immutable_audit: dict[str, object], immutable_audit_raw_sha256: str,
    proposed_model_git_commit: str,
) -> dict[str, object]:
    if type(proposed_model_git_commit) is not str or not _GIT_SHA.fullmatch(proposed_model_git_commit):
        raise IndependentReadbackVerificationError("proposed model Git identity differs")
    lineage_mapping = source.get("lineage_mapping")
    if type(lineage_mapping) is not dict:
        raise IndependentReadbackVerificationError("source lineage mapping is absent")
    expected_lineage, full_dates, model_dates = _expected_lineage(
        final_manifest, final_raw_sha256, immutable_audit,
        immutable_audit_raw_sha256, lineage_mapping,
    )
    source = _exact(source, {
        "contract_id", "status", "proposed_model_git_commit",
        "query_started_at_utc", "query_completed_at_utc", "select_query_ids",
        "lineage_mapping", "screening_runs_readback", "immutable_lineage",
        "full_session_calendar_dates", "model_session_dates",
        "coverage", "side_effects", "downstream_schema_presence",
        "downstream_counts", "database_writes", "model_fit_authorized",
        "source_evidence_sha256",
    }, "source evidence")
    embedded = source["source_evidence_sha256"]
    body = dict(source)
    body.pop("source_evidence_sha256")
    if (type(embedded) is not str or embedded != canonical_sha(body) or
            source_raw_sha256 == embedded):
        raise IndependentReadbackVerificationError("source raw/embedded identity differs")
    if (source["contract_id"] != SOURCE_CONTRACT_ID or
            source["status"] != "VERIFIED_SELECT_ONLY" or
            source["proposed_model_git_commit"] != proposed_model_git_commit or
            source["select_query_ids"] != list(REQUIRED_SELECT_QUERIES) or
            source["immutable_lineage"] != expected_lineage or
            source["full_session_calendar_dates"] != list(full_dates) or
            source["model_session_dates"] != list(model_dates) or
            source["coverage"] != dict(EXPECTED_COVERAGE) or
            source["side_effects"] != dict(EXPECTED_SIDE_EFFECTS) or
            source["downstream_counts"] != dict(EXPECTED_DOWNSTREAM) or
            source["database_writes"] != 0 or
            source["model_fit_authorized"] is not False):
        raise IndependentReadbackVerificationError("source evidence semantics differ")
    expected_screening = [{
        "screening_run_id": item["run_id"],
        "market_snapshot_id": binding.SNAPSHOT_ID,
        "source_session_date": binding.SOURCE_SESSION_DATE,
        "code_version": binding.SCREENING_CODE_VERSION,
        "config_sha256": item["config_sha256"],
        "status": "VALIDATED", "snapshot_status": "VALIDATED",
        "source_checksum_sha256": binding.SNAPSHOT_SHA256,
        "expected_ticker_count": 474,
    } for item in binding.EXPECTED_ARMS]
    if source["screening_runs_readback"] != expected_screening:
        raise IndependentReadbackVerificationError("screening run readback differs")
    presence = _exact(
        source["downstream_schema_presence"], set(dict(EXPECTED_DOWNSTREAM)),
        "downstream schema presence",
    )
    if any(value not in {"present", "schema_absent"} for value in presence.values()):
        raise IndependentReadbackVerificationError("downstream schema presence differs")

    request, verified = parse_verified_readback(artifact)
    if (artifact_raw_sha256 in {source_raw_sha256, embedded} or
            verified.evidence.source_readback_artifact_sha256 != source_raw_sha256 or
            verified.evidence.source_readback_embedded_evidence_sha256 != embedded or
            list(verified.full_session_calendar_dates) != source["full_session_calendar_dates"] or
            list(verified.model_session_dates) != source["model_session_dates"] or
            verified.lineage.__dict__ != {
                **expected_lineage,
                "audit_completed_at_utc": verified.lineage.audit_completed_at_utc,
                "audit_observed_at_utc": verified.lineage.audit_observed_at_utc,
            }):
        raise IndependentReadbackVerificationError("canonical artifact is not bound to source")
    if (verified.lineage.audit_completed_at_utc.isoformat() != expected_lineage["audit_completed_at_utc"] or
            verified.lineage.audit_observed_at_utc.isoformat() != expected_lineage["audit_observed_at_utc"]):
        raise IndependentReadbackVerificationError("artifact immutable chronology differs")
    if (verified.evidence.query_started_at_utc.isoformat() != source["query_started_at_utc"] or
            verified.evidence.query_completed_at_utc.isoformat() != source["query_completed_at_utc"]):
        raise IndependentReadbackVerificationError("artifact query chronology differs")
    return {
        "status": "VERIFIED_SELECT_ONLY",
        "source_file_sha256": source_raw_sha256,
        "source_embedded_evidence_sha256": embedded,
        "artifact_file_sha256": artifact_raw_sha256,
        "artifact_id": verified.artifact_id,
        "request_sha256": verified.request_sha256,
        "select_query_ids": list(REQUIRED_SELECT_QUERIES),
        "database_writes": 0,
        "model_fit_authorized": False,
    }


def verify_from_files(
    *, source_path: Path, artifact_path: Path, final_manifest_path: Path,
    immutable_audit_path: Path,
    proposed_model_git_commit: str,
):
    source, source_sha = _read_exact_0600(source_path, "source evidence")
    artifact, artifact_sha = _read_exact_0600(artifact_path, "canonical readback artifact")
    final, final_sha = _read_exact_0600(final_manifest_path, "final manifest")
    audit, audit_sha = _read_exact_0600(immutable_audit_path, "immutable audit")
    return verify(
        source=source, source_raw_sha256=source_sha,
        artifact=artifact, artifact_raw_sha256=artifact_sha,
        final_manifest=final, final_raw_sha256=final_sha,
        immutable_audit=audit, immutable_audit_raw_sha256=audit_sha,
        proposed_model_git_commit=proposed_model_git_commit,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument("--immutable-audit", type=Path, required=True)
    parser.add_argument("--model-git-commit", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_from_files(
            source_path=args.source, artifact_path=args.artifact,
            final_manifest_path=args.final_manifest,
            immutable_audit_path=args.immutable_audit,
            proposed_model_git_commit=args.model_git_commit,
        )
    except Exception as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
