"""SELECT-only CLI for immutable stored simple-screening baseline evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from normalized_edge_extraction import VALIDATED_20260825_ARMS
from model_lineage import LineageError
from scripts.audit_normalized_screening_edges import _write_durable_evidence
from scripts.run_oracle_research_dataset_isolated_matrix_lifecycle import (
    _production_credentials,
)
from simple_screening_baseline_audit import read_simple_baseline_audit
from turso_read_pipeline import TursoReadPipeline


_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _stamp_runtime(
    evidence: dict[str, object], *, executor_git_commit: str, observed_at: datetime
) -> dict[str, object]:
    if not _COMMIT_RE.fullmatch(executor_git_commit):
        raise LineageError("Audit executor Git commit must be an exact lowercase SHA-1.")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise LineageError("Audit observation timestamp must be timezone-aware.")
    result = dict(evidence)
    result.pop("evidence_sha256", None)
    result["audit_runtime"] = {
        "executor_git_commit": executor_git_commit,
        "observed_at_utc": observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    result["evidence_sha256"] = hashlib.sha256(_canonical_json(result)).hexdigest()
    return result


def run_audit_cli(
    argv: list[str] | None = None,
    *,
    credentials_loader=_production_credentials,
    pipeline_factory=TursoReadPipeline,
    evidence_reader=read_simple_baseline_audit,
    evidence_writer=_write_durable_evidence,
    effective_uid=os.geteuid,
    time_source=lambda: datetime.now(timezone.utc),
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--expected-snapshot-id", required=True)
    parser.add_argument("--expected-source-session-date", required=True)
    parser.add_argument("--expected-cutoff-utc", required=True)
    parser.add_argument("--expected-code-version", required=True)
    parser.add_argument("--executor-git-commit", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    expected_ids = {arm.run_id for arm in VALIDATED_20260825_ARMS}
    if len(args.run_id) != len(expected_ids) or set(args.run_id) != expected_ids:
        raise LineageError("Run IDs differ from the immutable baseline-audit contract.")
    if not _COMMIT_RE.fullmatch(args.executor_git_commit):
        raise LineageError("Audit executor Git commit must be an exact lowercase SHA-1.")
    if not 10 <= args.timeout_seconds <= 300:
        raise LineageError("Timeout is outside the allowed range.")
    if effective_uid() != 0:
        raise LineageError("Simple-baseline audit must run as root.")
    if not args.env_file.is_absolute():
        raise LineageError("Production credential path must be absolute.")
    _, token, endpoint = credentials_loader(args.env_file)
    db = pipeline_factory(endpoint, token, timeout_seconds=args.timeout_seconds)
    evidence = evidence_reader(
        db,
        expected_arms=VALIDATED_20260825_ARMS,
        expected_snapshot_id=args.expected_snapshot_id,
        expected_source_session_date=args.expected_source_session_date,
        expected_cutoff_utc=args.expected_cutoff_utc,
        expected_code_version=args.expected_code_version,
    )
    evidence = _stamp_runtime(
        evidence,
        executor_git_commit=args.executor_git_commit,
        observed_at=time_source(),
    )
    evidence_writer(args.evidence_json, _canonical_json(evidence) + b"\n")
    return 0


def main(argv: list[str] | None = None, **injected) -> int:
    try:
        return run_audit_cli(argv, **injected)
    except Exception:
        print("Simple-baseline audit failed; inspect redacted durable logs.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
