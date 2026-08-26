"""Read-only lifecycle audit for the validated 2026-08-25 replacement snapshot.

This is deliberately separate from ``audit_market_snapshot_integrity.py``.
That audit proves STAGING creation integrity; this audit proves the later,
explicit validation event and the exact evidence-only screening descendants.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from scripts.audit_screening_completion import _load_local_secret_env
from turso_read_pipeline import TursoReadPipeline


SNAPSHOT_ID = "market_features_2026-08-25_5b1044ee45605a3d"
SNAPSHOT_CHECKSUM = "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011"
SOURCE_SESSION = "2026-08-25"
SNAPSHOT_CODE_VERSION = "1e28786832b633c8b63163e7954e3297b0b9ec0e"
SNAPSHOT_PROVIDER = "TIINGO_EOD+YAHOO_FINANCE"
EXPECTED_ROWS = 586_710
EXPECTED_TICKERS = 474
FIRST_DATE = "2021-09-08"
PROVIDER_LINEAGE_SHA256 = "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a"

APPROVAL_EVENT_ID = "validate-20260826-5b1044ee45605a3d"
APPROVAL_ACTOR = "AviShemla"
APPROVAL_EVIDENCE_ID = "avi-20260826-validate-5b1044ee45605a3d"
APPROVAL_TIMESTAMP = "2026-08-26T07:40:43Z"
APPROVAL_AUDIT_HEAD = "dcbd4848d906457670e8fbe573a5d3892d200212"
APPROVAL_AUDIT_SHA256 = "6315425942edc8ca3ba419aa189d8253c8cb6ef30179e7735278cba33bde57c3"
APPROVAL_NOTE_KEYS = frozenset({
    "approval_id", "audit_check_count", "audit_git_head", "audit_sha256",
    "audit_status", "owner_approval", "snapshot_checksum_sha256",
})

SCREENING_CODE_VERSION = "2ef4a1082c91c023b9b0204611730492f03ad576"
SCREENING_CUTOFF = "2026-08-26T07:00:00+00:00"
SCREENING_EXPECTATIONS = {
    "predictive_screening_2026-08-25_w060_2ef4a10": (60, 474, 474, 0, 0),
    "predictive_screening_2026-08-25_w126_2ef4a10": (126, 474, 474, 0, 12),
    "predictive_screening_2026-08-25_w252_2ef4a10": (252, 474, 474, 0, 80),
}

PROVIDER_SUMMARY = {
    "TIINGO_EOD": (24, 30_528, 24, "2021-08-02", SOURCE_SESSION),
    "YAHOO_FINANCE": (452, 571_051, 452, "2021-08-02", SOURCE_SESSION),
}


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def provider_lineage_checksum(rows: list[list[object]]) -> str:
    ordered = sorted(rows, key=lambda row: str(row[0]))
    payload = json.dumps(ordered, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_lifecycle_checks(evidence: dict[str, object]) -> dict[str, bool]:
    """Evaluate pinned lifecycle evidence without I/O or state transitions."""
    snapshot = evidence["snapshot"]
    counts = evidence["counts"]
    approvals = evidence["approval_events"]
    provider = evidence["provider"]
    screening = evidence["screening_runs"]
    downstream = evidence["downstream"]

    creation_notes = _json_object(snapshot.get("validation_notes"))
    approval = approvals[0] if len(approvals) == 1 else {}
    approval_notes = _json_object(approval.get("approval_notes"))
    actual_provider_summary = {
        str(row.get("provider")): (
            int(row.get("ticker_count", -1)),
            int(row.get("source_rows", -1)),
            int(row.get("checksum_count", -1)),
            str(row.get("first_min", "")),
            str(row.get("last_max", "")),
        )
        for row in provider.get("summary", [])
    }
    screening_by_id = {
        str(row.get("screening_run_id")): row for row in screening
    }
    screening_ids_exact = (
        len(screening_by_id) == len(screening)
        and set(screening_by_id) == set(SCREENING_EXPECTATIONS)
    )
    screening_counts_exact = screening_ids_exact
    screening_lineage_exact = screening_ids_exact
    if screening_ids_exact:
        for run_id, expected in SCREENING_EXPECTATIONS.items():
            window, result_rows, result_tickers, eligible, fold_rows = expected
            row = screening_by_id[run_id]
            config = _json_object(row.get("config_json"))
            screening_counts_exact = screening_counts_exact and (
                int(row.get("result_rows", -1)) == result_rows
                and int(row.get("result_tickers", -1)) == result_tickers
                and int(row.get("eligible_count", -1)) == eligible
                and int(row.get("fold_rows", -1)) == fold_rows
            )
            screening_lineage_exact = screening_lineage_exact and (
                row.get("market_snapshot_id") == SNAPSHOT_ID
                and row.get("source_session_date") == SOURCE_SESSION
                and row.get("cutoff_utc") == SCREENING_CUTOFF
                and row.get("code_version") == SCREENING_CODE_VERSION
                and row.get("status") == "VALIDATED"
                and config.get("signal_lookback_sessions") == window
                and config.get("training_window_sessions") == 289
                and config.get("test_sessions") == 30
                and config.get("outer_folds") == 4
                and config.get("min_oos_sessions") == 120
                and config.get("eligibility_hypotheses") == EXPECTED_TICKERS
                and config.get("candidate_lags") == [1, 2, 3, 4, 5, 6, 7]
                and config.get("model_family") == "selected_chain"
                and config.get("terminology") == "predictive_lead_lag_not_causal_identification"
                and config.get("window_semantics_contract_id")
                == "screening-window-separation-v1-20260825"
                and config.get("lag_horizon_contract_id")
                == "stock-lag-horizon-v1-20260824"
            )

    return {
        "one_exact_snapshot": (
            snapshot.get("snapshot_rows") == 1
            and snapshot.get("snapshot_id") == SNAPSHOT_ID
            and snapshot.get("dataset_type") == "MARKET_FEATURES"
            and snapshot.get("source_session_date") == SOURCE_SESSION
        ),
        "snapshot_is_explicitly_validated": snapshot.get("status") == "VALIDATED",
        "snapshot_checksum_and_counts_exact": (
            snapshot.get("source_checksum_sha256") == SNAPSHOT_CHECKSUM
            and snapshot.get("expected_row_count") == EXPECTED_ROWS
            and snapshot.get("expected_ticker_count") == EXPECTED_TICKERS
            and counts.get("row_count") == EXPECTED_ROWS
            and counts.get("ticker_count") == EXPECTED_TICKERS
            and counts.get("first_date") == FIRST_DATE
            and counts.get("last_date") == SOURCE_SESSION
        ),
        "snapshot_provider_and_code_exact": (
            snapshot.get("provider") == SNAPSHOT_PROVIDER
            and snapshot.get("code_version") == SNAPSHOT_CODE_VERSION
            and creation_notes.get("repair") == "CANONICAL_OHLC_ENVELOPE"
            and creation_notes.get("repair_code_version") == SNAPSHOT_CODE_VERSION
            and creation_notes.get("provider_lineage_sha256") == PROVIDER_LINEAGE_SHA256
            and creation_notes.get("validation_state") == "STAGING_NOT_VALIDATED"
        ),
        "provider_lineage_exact": (
            provider.get("lineage_rows") == 476
            and provider.get("ticker_count") == 476
            and provider.get("checksum_sha256") == PROVIDER_LINEAGE_SHA256
            and actual_provider_summary == PROVIDER_SUMMARY
            and all(
                row.get("requested_min") == SOURCE_SESSION
                and row.get("requested_max") == SOURCE_SESSION
                for row in provider.get("summary", [])
            )
        ),
        "single_validation_only_approval": (
            len(approvals) == 1
            and approval.get("event_id") == APPROVAL_EVENT_ID
            and approval.get("snapshot_id") == SNAPSHOT_ID
            and approval.get("decision") == "APPROVED"
            and approval.get("approved_by") == APPROVAL_ACTOR
            and approval.get("decided_at_utc") == APPROVAL_TIMESTAMP
            and approval.get("created_at_utc") == APPROVAL_TIMESTAMP
            and approval.get("snapshot_checksum_sha256") == SNAPSHOT_CHECKSUM
            and approval.get("source_evidence_type") == "MANUAL_RESEARCH_REVIEW"
            and approval.get("source_evidence_id") == APPROVAL_EVIDENCE_ID
        ),
        "approval_actor_and_evidence_bound": (
            set(approval_notes) == APPROVAL_NOTE_KEYS
            and approval_notes.get("approval_id") == APPROVAL_EVIDENCE_ID
            and approval_notes.get("snapshot_checksum_sha256") == SNAPSHOT_CHECKSUM
            and approval_notes.get("audit_check_count") == 17
            and approval_notes.get("audit_git_head") == APPROVAL_AUDIT_HEAD
            and approval_notes.get("audit_sha256") == APPROVAL_AUDIT_SHA256
            and approval_notes.get("audit_status") == "PASS"
            and approval_notes.get("owner_approval")
            == "Avi explicitly approved validation only"
        ),
        "screening_run_set_exact": screening_ids_exact,
        "screening_counts_exact": bool(screening_counts_exact),
        "screening_lineage_exact": bool(screening_lineage_exact),
        "zero_model_and_etf_outputs": (
            downstream.get("model_runs") == 0
            and downstream.get("model_scorecards") == 0
            and downstream.get("etf_priors") == 0
        ),
    }


def _one(db, query: str, args: list[object], label: str) -> dict[str, object]:
    result = db.execute(query, args)
    if len(result.rows) != 1:
        raise LineageError(f"{label} did not return exactly one row.")
    return dict(zip(result.columns, result.rows[0]))


def _rows(db, query: str, args: list[object]) -> list[dict[str, object]]:
    result = db.execute(query, args)
    return [dict(zip(result.columns, row)) for row in result.rows]


def collect_lifecycle_evidence(db) -> dict[str, object]:
    """Collect only SELECT-backed evidence for the pinned replacement."""
    snapshot = _one(db, """
        SELECT COUNT(*) AS snapshot_rows,MIN(snapshot_id) AS snapshot_id,
               MIN(dataset_type) AS dataset_type,
               MIN(source_session_date) AS source_session_date,
               MIN(provider) AS provider,MIN(code_version) AS code_version,
               MIN(expected_row_count) AS expected_row_count,
               MIN(expected_ticker_count) AS expected_ticker_count,
               MIN(source_checksum_sha256) AS source_checksum_sha256,
               MIN(status) AS status,MIN(validation_notes) AS validation_notes
        FROM model_input_snapshots WHERE snapshot_id=?
    """, [SNAPSHOT_ID], "snapshot")
    counts = _one(db, """
        SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,
               MIN(date) AS first_date,MAX(date) AS last_date
        FROM market_daily_features WHERE snapshot_id=?
    """, [SNAPSHOT_ID], "market rows")
    approvals = _rows(db, """
        SELECT event_id,snapshot_id,decision,approved_by,decided_at_utc,
               snapshot_checksum_sha256,source_evidence_type,source_evidence_id,
               approval_notes,created_at_utc
        FROM model_input_approval_events WHERE snapshot_id=?
        ORDER BY decided_at_utc,event_id
    """, [SNAPSHOT_ID])
    lineage_result = db.execute(
        "SELECT ticker,provider,requested_source_session_date,first_available_date,"
        "last_available_date,source_row_count,source_checksum_sha256 "
        "FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker",
        [SNAPSHOT_ID],
    )
    lineage_rows = [list(row) for row in lineage_result.rows]
    provider_counts = _one(db, """
        SELECT COUNT(*) AS lineage_rows,COUNT(DISTINCT ticker) AS ticker_count
        FROM market_data_provider_lineage WHERE snapshot_id=?
    """, [SNAPSHOT_ID], "provider counts")
    provider_summary = _rows(db, """
        SELECT provider,COUNT(*) AS ticker_count,SUM(source_row_count) AS source_rows,
               MIN(requested_source_session_date) AS requested_min,
               MAX(requested_source_session_date) AS requested_max,
               MIN(first_available_date) AS first_min,MAX(last_available_date) AS last_max,
               COUNT(DISTINCT source_checksum_sha256) AS checksum_count
        FROM market_data_provider_lineage WHERE snapshot_id=?
        GROUP BY provider ORDER BY provider
    """, [SNAPSHOT_ID])
    screening = _rows(db, """
        SELECT r.screening_run_id,r.market_snapshot_id,r.source_session_date,
               r.cutoff_utc,r.code_version,r.config_json,r.status,
               (SELECT COUNT(*) FROM predictive_screening_results x
                WHERE x.screening_run_id=r.screening_run_id) AS result_rows,
               (SELECT COUNT(DISTINCT x.ticker) FROM predictive_screening_results x
                WHERE x.screening_run_id=r.screening_run_id) AS result_tickers,
               (SELECT COALESCE(SUM(x.eligible),0) FROM predictive_screening_results x
                WHERE x.screening_run_id=r.screening_run_id) AS eligible_count,
               (SELECT COUNT(*) FROM predictive_screening_fold_metrics f
                WHERE f.screening_run_id=r.screening_run_id) AS fold_rows
        FROM predictive_screening_runs r WHERE r.market_snapshot_id=?
        ORDER BY r.screening_run_id
    """, [SNAPSHOT_ID])
    downstream = _one(db, """
        SELECT (SELECT COUNT(*) FROM model_runs) AS model_runs,
               (SELECT COUNT(*) FROM model_scorecards) AS model_scorecards,
               (SELECT COUNT(*) FROM etf_prior_lineage) AS etf_priors
    """, [], "downstream state")
    return {
        "snapshot": snapshot,
        "counts": counts,
        "approval_events": approvals,
        "provider": {
            **provider_counts,
            "checksum_sha256": provider_lineage_checksum(lineage_rows),
            "summary": provider_summary,
        },
        "screening_runs": screening,
        "downstream": downstream,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path("/opt/antigravity/.env"))
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not 10.0 <= args.timeout_seconds <= 300.0:
        raise SystemExit("Timeout must be between 10 and 300 seconds.")
    _load_local_secret_env(args.env_file)
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    db = TursoReadPipeline(
        raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline",
        token,
        timeout_seconds=args.timeout_seconds,
    )
    evidence = collect_lifecycle_evidence(db)
    checks = build_lifecycle_checks(evidence)
    screening_summary = [
        {
            key: row.get(key)
            for key in (
                "screening_run_id", "market_snapshot_id", "source_session_date",
                "cutoff_utc", "code_version", "status", "result_rows",
                "result_tickers", "eligible_count", "fold_rows",
            )
        } | {
            "signal_lookback_sessions": _json_object(
                row.get("config_json")
            ).get("signal_lookback_sessions")
        }
        for row in evidence["screening_runs"]
    ]
    payload = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "snapshot_id": SNAPSHOT_ID,
        "snapshot_checksum_sha256": SNAPSHOT_CHECKSUM,
        "checks": checks,
        "counts": evidence["counts"],
        "provider": evidence["provider"],
        "approval_event_count": len(evidence["approval_events"]),
        "screening_runs": screening_summary,
        "downstream": evidence["downstream"],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
