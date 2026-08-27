#!/usr/bin/env python3
"""Produce one write-once, SELECT-only current-baseline readback.

The source evidence and canonical contract artifact are separate files.  This
program has no SQL write statement, model import, recommendation, or trading
path.  All caller-named inputs must be root-owned mode-0600 files and both
output parents must be root-owned mode-0700 directories.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Mapping, Sequence

try:  # Package import.
    from . import stock_model_preregistration_binding as binding
    from .current_baseline_readback_contract import (
        CurrentReadbackEvidence, EXPECTED_COVERAGE, EXPECTED_DOWNSTREAM,
        EXPECTED_SIDE_EFFECTS, ImmutableV4AuditLineage, NamedCount,
        ReadbackRequest, ReadbackStatus, REQUIRED_SELECT_QUERIES,
        SOURCE_AUDIT_CONTRACT_ID, build_verified_readback, canonical_sha,
    )
    from .stock_model_preregistration import (
        BaselineAuditEvidence, compute_baseline_audit_sha256,
    )
    from .stock_preregistration_runtime import (
        RuntimeBoundaryError, read_root_owned_json, write_json_once,
    )
except ImportError:  # Direct execution from an immutable closure.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import stock_model_preregistration_binding as binding
    from current_baseline_readback_contract import (
        CurrentReadbackEvidence, EXPECTED_COVERAGE, EXPECTED_DOWNSTREAM,
        EXPECTED_SIDE_EFFECTS, ImmutableV4AuditLineage, NamedCount,
        ReadbackRequest, ReadbackStatus, REQUIRED_SELECT_QUERIES,
        SOURCE_AUDIT_CONTRACT_ID, build_verified_readback, canonical_sha,
    )
    from stock_model_preregistration import (
        BaselineAuditEvidence, compute_baseline_audit_sha256,
    )
    from stock_preregistration_runtime import (
        RuntimeBoundaryError, read_root_owned_json, write_json_once,
    )

try:  # Canonical repository support modules.
    from scripts.audit_full_universe_simple_baselines import (
        DOWNSTREAM_COUNT_FRAGMENTS, DOWNSTREAM_TABLES, SCHEMA_SQL, SESSION_SQL,
        normalize_turso_pipeline_endpoint, production_credentials,
    )
    from turso_read_pipeline import TursoReadPipeline
except ImportError:  # Self-contained immutable deployment closure.
    try:
        from .audit_full_universe_simple_baselines import (
            DOWNSTREAM_COUNT_FRAGMENTS, DOWNSTREAM_TABLES, SCHEMA_SQL, SESSION_SQL,
            normalize_turso_pipeline_endpoint, production_credentials,
        )
        from .turso_read_pipeline import TursoReadPipeline
    except ImportError:
        from audit_full_universe_simple_baselines import (
            DOWNSTREAM_COUNT_FRAGMENTS, DOWNSTREAM_TABLES, SCHEMA_SQL, SESSION_SQL,
            normalize_turso_pipeline_endpoint, production_credentials,
        )
        from turso_read_pipeline import TursoReadPipeline


SOURCE_CONTRACT_ID = "codex-oracle-current-baseline-source-evidence-v1"
SCREENING_RUNS_SQL = """SELECT r.screening_run_id,r.market_snapshot_id,r.source_session_date,
 r.code_version,r.config_json,r.status,s.source_checksum_sha256,s.status AS snapshot_status,
 s.expected_ticker_count FROM predictive_screening_runs r JOIN model_input_snapshots s
 ON s.snapshot_id=r.market_snapshot_id WHERE r.screening_run_id IN (?,?,?)
 ORDER BY r.screening_run_id"""
TICKER_UNIVERSE_SQL = """SELECT screening_run_id,ticker
 FROM predictive_screening_results
 WHERE screening_run_id IN (?,?,?) ORDER BY screening_run_id,ticker"""
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|"
    r"PRAGMA|VACUUM)\b", re.IGNORECASE,
)


class ReadbackRuntimeError(RuntimeBoundaryError):
    """Raised before an unsafe query, ambiguous identity, or persistence."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if type(value) is datetime:
        if value.tzinfo is None:
            raise ReadbackRuntimeError("output timestamp must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {name: _json_value(item) for name, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(name): _json_value(item) for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _read_exact_0600(path: Path, label: str) -> tuple[dict[str, object], str]:
    if not path.is_absolute() or path.is_symlink():
        raise ReadbackRuntimeError(f"{label} must be an absolute non-symlink file")
    metadata = os.lstat(path)
    if (not hasattr(metadata, "st_uid") or metadata.st_uid != 0 or
            not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
            stat.S_IMODE(metadata.st_mode) != 0o600):
        raise ReadbackRuntimeError(f"{label} must be root-owned mode-0600 single-link")
    return read_root_owned_json(path, label)


def _query(db, sql: str, args: list[object], query_id: str):
    normalized = sql.lstrip()
    if (query_id not in REQUIRED_SELECT_QUERIES or not normalized.upper().startswith("SELECT") or
            ";" in normalized or _FORBIDDEN_SQL.search(normalized)):
        raise ReadbackRuntimeError("only the exact governed SELECT queries are allowed")
    return db.execute(sql, args)


def _records(result, expected_columns: Sequence[str], label: str) -> list[dict[str, object]]:
    columns = tuple(result.columns)
    if columns != tuple(expected_columns):
        raise ReadbackRuntimeError(f"{label} columns differ")
    rows: list[dict[str, object]] = []
    for row in result.rows:
        if len(row) != len(columns):
            raise ReadbackRuntimeError(f"{label} row width differs")
        rows.append(dict(zip(columns, row, strict=True)))
    return rows


def _config_sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON member")
        output[key] = value
    return output


def _immutable_lineage(
    final_manifest: Mapping[str, object], immutable_audit: Mapping[str, object],
    lineage_mapping: Mapping[str, object], final_raw_sha256: str,
    immutable_raw_sha256: str,
) -> tuple[ImmutableV4AuditLineage, tuple[str, ...], datetime, datetime]:
    if (final_raw_sha256 != binding.PINNED_FINAL_MANIFEST_RAW_SHA256 or
            immutable_raw_sha256 != binding.PINNED_IMMUTABLE_AUDIT_RAW_SHA256):
        raise ReadbackRuntimeError("immutable v4 raw artifact identity differs")
    lineage, tickers, sessions = binding._validate_lineage(lineage_mapping)
    executor_commit, completion = binding._validate_final_manifest(
        final_manifest, raw_sha256=final_raw_sha256, lineage=lineage, tickers=tickers,
    )
    immutable, observed = binding._validate_audit(
        immutable_audit, raw_sha256=immutable_raw_sha256,
        final_raw_sha256=final_raw_sha256,
        deterministic_sha256=final_manifest["deterministic_evidence_sha256"],
        executor_commit=executor_commit, completion=completion,
        sessions_sha256=lineage["sessions_sha256"], immutable=True,
    )
    universe_sha = lineage["ticker_universe_sha256"]
    universe_id = f"codex-oracle-stock-universe-v1:{binding.SNAPSHOT_ID}:{universe_sha}"
    model_dates = sessions[-416:]
    if canonical_sha(list(model_dates)) != binding.PINNED_MODEL_SLICE_SHA256:
        raise ReadbackRuntimeError("governed 416-session model slice differs")
    audit_evidence = BaselineAuditEvidence(
        status="VERIFIED", baseline_manifest_sha256=final_raw_sha256,
        snapshot_id=binding.SNAPSHOT_ID, snapshot_sha256=binding.SNAPSHOT_SHA256,
        universe_id=universe_id, universe_sha256=universe_sha,
        full_session_calendar_sha256=lineage["sessions_sha256"],
        model_session_dates_sha256=canonical_sha(list(model_dates)),
        source_audit_artifact_sha256=immutable_raw_sha256,
        embedded_audit_evidence_sha256=immutable["audit_evidence_sha256"],
        audit_sha256="0" * 64, completed_at_utc=completion,
        observed_at_utc=observed, ticker_count=474, fold_count=1_896,
        oos_observation_count=56_880, side_effects=dict(binding.ZERO_SIDE_EFFECTS),
        downstream_counts=dict(binding.ZERO_DOWNSTREAM),
    )
    audit_evidence = replace(
        audit_evidence, audit_sha256=compute_baseline_audit_sha256(audit_evidence),
    )
    return ImmutableV4AuditLineage(
        source_contract_id=SOURCE_AUDIT_CONTRACT_ID,
        snapshot_id=binding.SNAPSHOT_ID, snapshot_sha256=binding.SNAPSHOT_SHA256,
        universe_id=universe_id, universe_sha256=universe_sha,
        full_session_calendar_sha256=lineage["sessions_sha256"],
        model_session_dates_sha256=canonical_sha(list(model_dates)),
        baseline_manifest_sha256=final_raw_sha256,
        source_audit_artifact_sha256=immutable_raw_sha256,
        embedded_audit_evidence_sha256=immutable["audit_evidence_sha256"],
        audit_envelope_sha256=audit_evidence.audit_sha256,
        source_code_git_sha=executor_commit,
        audit_completed_at_utc=completion, audit_observed_at_utc=observed,
    ), tuple(sessions), completion, observed


def _live_selects(db, *, proposed_model_git_commit: str) -> tuple[
    tuple[str, ...], tuple[str, ...], list[dict[str, object]],
    dict[str, str], dict[str, int]
]:
    if type(proposed_model_git_commit) is not str or not _GIT_SHA.fullmatch(proposed_model_git_commit):
        raise ReadbackRuntimeError("proposed model Git commit must be an immutable SHA")
    session_rows = _records(
        _query(db, SESSION_SQL, [binding.SNAPSHOT_ID], "SELECT_SESSION_CALENDAR"),
        ("date",), "session calendar",
    )
    sessions = tuple(str(row["date"]) for row in session_rows)
    if (len(sessions) != 1_246 or len(set(sessions)) != 1_246 or
            tuple(sorted(sessions)) != sessions or
            canonical_sha(list(sessions)) != binding.SESSION_SHA256):
        raise ReadbackRuntimeError("live 1246-session calendar differs")

    run_ids = [item["run_id"] for item in binding.EXPECTED_ARMS]
    run_rows = _records(
        _query(db, SCREENING_RUNS_SQL, run_ids, "SELECT_SCREENING_RUNS"),
        ("screening_run_id", "market_snapshot_id", "source_session_date", "code_version",
         "config_json", "status", "source_checksum_sha256", "snapshot_status",
         "expected_ticker_count"), "screening run lineage",
    )
    by_id = {str(row["screening_run_id"]): row for row in run_rows}
    if len(by_id) != len(run_rows) or set(by_id) != set(run_ids):
        raise ReadbackRuntimeError("screening run coverage is not exact")
    configs: list[dict[str, object]] = []
    screening_readback: list[dict[str, object]] = []
    for expected in binding.EXPECTED_ARMS:
        row = by_id[expected["run_id"]]
        raw_config = row["config_json"]
        if (type(raw_config) is not str or
                _config_sha256(raw_config) != expected["config_sha256"]):
            raise ReadbackRuntimeError("screening configuration hash differs")
        try:
            config = json.loads(
                raw_config, object_pairs_hook=_strict_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant {value}")
                ),
            )
        except (TypeError, ValueError) as exc:
            raise ReadbackRuntimeError("screening configuration is not strict JSON") from exc
        exact = {
            **binding.EXPECTED_COMMON_CONFIG,
            "signal_lookback_sessions": expected["signal_lookback_sessions"],
        }
        if (type(config) is not dict or any(
                type(config.get(name)) is not int or config.get(name) != value
                for name, value in exact.items())):
            raise ReadbackRuntimeError("screening configuration differs from governed baseline")
        if (row["market_snapshot_id"] != binding.SNAPSHOT_ID or
                row["source_session_date"] != binding.SOURCE_SESSION_DATE or
                row["code_version"] != binding.SCREENING_CODE_VERSION or
                row["status"] != "VALIDATED" or row["snapshot_status"] != "VALIDATED" or
                row["source_checksum_sha256"] != binding.SNAPSHOT_SHA256 or
                type(row["expected_ticker_count"]) is not int or
                row["expected_ticker_count"] != 474):
            raise ReadbackRuntimeError("screening/snapshot lineage differs")
        configs.append(config)
        screening_readback.append({
            "screening_run_id": expected["run_id"],
            "market_snapshot_id": binding.SNAPSHOT_ID,
            "source_session_date": binding.SOURCE_SESSION_DATE,
            "code_version": binding.SCREENING_CODE_VERSION,
            "config_sha256": expected["config_sha256"],
            "status": "VALIDATED", "snapshot_status": "VALIDATED",
            "source_checksum_sha256": binding.SNAPSHOT_SHA256,
            "expected_ticker_count": 474,
        })
    common = [{name: value for name, value in config.items() if name not in {
        "signal_lookback_sessions", "signal_lookback_governance_status"
    }} for config in configs]
    if any(value != common[0] for value in common[1:]):
        raise ReadbackRuntimeError("screening arms differ beyond discovery lookback")

    ticker_rows = _records(
        _query(db, TICKER_UNIVERSE_SQL, run_ids, "SELECT_TICKER_UNIVERSE"),
        ("screening_run_id", "ticker"), "ticker universe",
    )
    by_run: dict[str, list[str]] = {run_id: [] for run_id in run_ids}
    for row in ticker_rows:
        run_id, ticker = row["screening_run_id"], row["ticker"]
        if (run_id not in by_run or type(ticker) is not str or
                not binding._TICKER.fullmatch(ticker)):
            raise ReadbackRuntimeError("live ticker universe identity differs")
        by_run[str(run_id)].append(ticker)
    universes: list[tuple[str, ...]] = []
    for run_id in run_ids:
        values = tuple(by_run[run_id])
        if len(values) != 474 or tuple(sorted(set(values))) != values:
            raise ReadbackRuntimeError("live ticker universe denominator differs")
        universes.append(values)
    if any(values != universes[0] for values in universes[1:]):
        raise ReadbackRuntimeError("screening arms do not share one ticker universe")

    schema_rows = _records(
        _query(db, SCHEMA_SQL, list(DOWNSTREAM_TABLES), "SELECT_DOWNSTREAM_SCHEMA"),
        ("name", "type"), "downstream schema",
    )
    present: set[str] = set()
    for row in schema_rows:
        if (row["name"] not in DOWNSTREAM_TABLES or row["type"] != "table" or row["name"] in present):
            raise ReadbackRuntimeError("downstream schema identity differs")
        present.add(str(row["name"]))
    ordered_present = [name for name in DOWNSTREAM_TABLES if name in present]
    if ordered_present:
        count_sql = "SELECT " + ", ".join(
            f"({DOWNSTREAM_COUNT_FRAGMENTS[name]}) AS {name}" for name in ordered_present
        )
        count_columns = tuple(ordered_present)
        count_args = [proposed_model_git_commit] * len(ordered_present)
    else:
        count_sql = "SELECT 0 AS no_present_downstream_tables"
        count_columns = ("no_present_downstream_tables",)
        count_args = []
    count_rows = _records(
        _query(db, count_sql, count_args, "SELECT_DOWNSTREAM_COUNTS"),
        count_columns, "downstream counts",
    )
    if len(count_rows) != 1:
        raise ReadbackRuntimeError("downstream count readback differs")
    returned = count_rows[0]
    if any(type(returned[name]) is not int or returned[name] != 0 for name in count_columns):
        raise ReadbackRuntimeError("proposed model commit already has downstream outputs")
    counts = {name: (returned[name] if name in present else 0) for name in DOWNSTREAM_TABLES}
    presence = {name: ("present" if name in present else "schema_absent") for name in DOWNSTREAM_TABLES}
    return sessions, universes[0], screening_readback, presence, counts


def _lineage_mapping(sessions: tuple[str, ...], tickers: tuple[str, ...]) -> dict[str, object]:
    return {
        "snapshot_id": binding.SNAPSHOT_ID,
        "snapshot_sha256": binding.SNAPSHOT_SHA256,
        "source_session_date": binding.SOURCE_SESSION_DATE,
        "screening_code_version": binding.SCREENING_CODE_VERSION,
        "screening_runs": [dict(item) for item in binding.EXPECTED_ARMS],
        "common_config": dict(binding.EXPECTED_COMMON_CONFIG),
        "ticker_universe": list(tickers),
        "ticker_universe_sha256": canonical_sha(list(tickers)),
        "sessions": list(sessions),
        "sessions_sha256": canonical_sha(list(sessions)),
    }


def produce(
    *, db, final_manifest: Mapping[str, object], immutable_audit: Mapping[str, object],
    final_raw_sha256: str, immutable_raw_sha256: str, proposed_model_git_commit: str,
    source_output: Path, artifact_output: Path, now=_utc_now,
) -> tuple[dict[str, object], dict[str, object], str, str]:
    query_started = now()
    live_sessions, live_tickers, screening_readback, schema_presence, downstream_counts = _live_selects(
        db, proposed_model_git_commit=proposed_model_git_commit,
    )
    query_completed = now()
    if query_started.tzinfo is None or query_completed.tzinfo is None:
        raise ReadbackRuntimeError("query timestamps must be timezone-aware")
    query_started = query_started.astimezone(timezone.utc)
    query_completed = query_completed.astimezone(timezone.utc)
    if query_completed < query_started:
        raise ReadbackRuntimeError("live query chronology differs")
    lineage_mapping = _lineage_mapping(live_sessions, live_tickers)
    lineage, immutable_sessions, _completion, _immutable_observed = _immutable_lineage(
        final_manifest, immutable_audit, lineage_mapping,
        final_raw_sha256, immutable_raw_sha256,
    )
    if live_sessions != immutable_sessions:
        raise ReadbackRuntimeError("live calendar differs from immutable v4")

    source_payload: dict[str, object] = {
        "contract_id": SOURCE_CONTRACT_ID,
        "status": ReadbackStatus.VERIFIED_SELECT_ONLY.value,
        "proposed_model_git_commit": proposed_model_git_commit,
        "query_started_at_utc": query_started.isoformat(),
        "query_completed_at_utc": query_completed.isoformat(),
        "select_query_ids": list(REQUIRED_SELECT_QUERIES),
        "lineage_mapping": lineage_mapping,
        "screening_runs_readback": screening_readback,
        "immutable_lineage": _json_value(lineage),
        "full_session_calendar_dates": list(live_sessions),
        "model_session_dates": list(live_sessions[-416:]),
        "coverage": dict(EXPECTED_COVERAGE),
        "side_effects": dict(EXPECTED_SIDE_EFFECTS),
        "downstream_schema_presence": schema_presence,
        "downstream_counts": downstream_counts,
        "database_writes": 0,
        "model_fit_authorized": False,
    }
    source_embedded = canonical_sha(source_payload)
    source_payload["source_evidence_sha256"] = source_embedded
    source_raw = write_json_once(source_output, source_payload)
    if source_raw == source_embedded:
        raise ReadbackRuntimeError("source raw and embedded identities are conflated")

    evidence = CurrentReadbackEvidence(
        status=ReadbackStatus.VERIFIED_SELECT_ONLY,
        snapshot_id=lineage.snapshot_id, snapshot_sha256=lineage.snapshot_sha256,
        universe_id=lineage.universe_id, universe_sha256=lineage.universe_sha256,
        full_session_calendar_sha256=lineage.full_session_calendar_sha256,
        model_session_dates_sha256=lineage.model_session_dates_sha256,
        baseline_manifest_sha256=lineage.baseline_manifest_sha256,
        source_audit_artifact_sha256=lineage.source_audit_artifact_sha256,
        embedded_audit_evidence_sha256=lineage.embedded_audit_evidence_sha256,
        audit_envelope_sha256=lineage.audit_envelope_sha256,
        source_readback_artifact_sha256=source_raw,
        source_readback_embedded_evidence_sha256=source_embedded,
        query_started_at_utc=query_started, query_completed_at_utc=query_completed,
        source_readback_observed_at_utc=query_completed,
        select_query_ids=REQUIRED_SELECT_QUERIES,
        coverage=tuple(NamedCount(*item) for item in EXPECTED_COVERAGE),
        side_effects=tuple(NamedCount(*item) for item in EXPECTED_SIDE_EFFECTS),
        downstream_counts=tuple(NamedCount(*item) for item in EXPECTED_DOWNSTREAM),
    )
    request = ReadbackRequest(lineage, live_sessions, live_sessions[-416:], evidence)
    artifact = build_verified_readback(request, observed_at_utc=now().astimezone(timezone.utc))
    artifact_payload = _json_value(artifact)
    if type(artifact_payload) is not dict:
        raise ReadbackRuntimeError("verified artifact serialization differs")
    artifact_raw = write_json_once(artifact_output, artifact_payload)
    return source_payload, artifact_payload, source_raw, artifact_raw


def run_from_files(
    *, env_file: Path, final_manifest_path: Path, immutable_audit_path: Path,
    source_output: Path, artifact_output: Path,
    proposed_model_git_commit: str, timeout_seconds: float,
    credentials_loader=production_credentials, client_factory=TursoReadPipeline,
    effective_uid=lambda: os.geteuid(), now=_utc_now,
):
    if effective_uid() != 0:
        raise ReadbackRuntimeError("current readback producer must execute as root")
    if not 10 <= timeout_seconds <= 300:
        raise ReadbackRuntimeError("timeout is outside the governed range")
    final, final_sha = _read_exact_0600(final_manifest_path, "final manifest")
    audit, audit_sha = _read_exact_0600(immutable_audit_path, "immutable audit")
    endpoint, token = credentials_loader(env_file)
    endpoint = normalize_turso_pipeline_endpoint(endpoint)
    db = client_factory(endpoint, token, timeout_seconds=timeout_seconds)
    return produce(
        db=db, final_manifest=final, immutable_audit=audit,
        final_raw_sha256=final_sha,
        immutable_raw_sha256=audit_sha,
        proposed_model_git_commit=proposed_model_git_commit,
        source_output=source_output, artifact_output=artifact_output, now=now,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument("--immutable-audit", type=Path, required=True)
    parser.add_argument("--source-output", type=Path, required=True)
    parser.add_argument("--artifact-output", type=Path, required=True)
    parser.add_argument("--model-git-commit", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    try:
        _source, _artifact, source_sha, artifact_sha = run_from_files(
            env_file=args.env_file, final_manifest_path=args.final_manifest,
            immutable_audit_path=args.immutable_audit,
            source_output=args.source_output, artifact_output=args.artifact_output,
            proposed_model_git_commit=args.model_git_commit,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": "VERIFIED_SELECT_ONLY", "source_file_sha256": source_sha,
        "artifact_file_sha256": artifact_sha, "database_writes": 0,
        "model_fit_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
