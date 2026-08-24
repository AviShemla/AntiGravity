"""Read-only completion audit for one full-universe screening run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from turso_read_pipeline import TursoReadPipeline


def _load_local_secret_env(path: Path) -> None:
    """Load the ignored local environment without printing credential values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def one(result, label: str) -> dict[str, object]:
    if len(result.rows) != 1:
        raise LineageError(f"{label} did not return exactly one row.")
    return dict(zip(result.columns, result.rows[0]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    _load_local_secret_env(ROOT / ".env")
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    db = TursoReadPipeline(
        raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline",
        token,
        timeout_seconds=30.0,
    )

    run = one(
        db.execute(
            """
            SELECT r.screening_run_id,r.market_snapshot_id,r.source_session_date,
                   r.cutoff_utc,r.code_version,r.config_json,r.status,
                   r.validation_notes,s.status AS snapshot_status,
                   s.expected_ticker_count,s.expected_row_count
            FROM predictive_screening_runs r
            JOIN model_input_snapshots s ON s.snapshot_id=r.market_snapshot_id
            WHERE r.screening_run_id=?
            """,
            [args.run_id],
        ),
        "screening run",
    )
    config = json.loads(str(run["config_json"]))
    results = one(
        db.execute(
            """
            SELECT COUNT(*) AS result_count,COUNT(DISTINCT ticker) AS distinct_tickers,
                   COALESCE(SUM(eligible),0) AS eligible_count,
                   SUM(CASE WHEN oos_sessions>0 THEN 1 ELSE 0 END) AS evaluated_count,
                   SUM(CASE WHEN oos_sessions=0 THEN 1 ELSE 0 END) AS data_rejection_count,
                   MIN(oos_sessions) AS min_oos_sessions,MAX(oos_sessions) AS max_oos_sessions
            FROM predictive_screening_results WHERE screening_run_id=?
            """,
            [args.run_id],
        ),
        "screening results",
    )
    folds = one(
        db.execute(
            """
            SELECT COUNT(*) AS fold_count,COUNT(DISTINCT ticker) AS fold_tickers,
                   MIN(fold_number) AS min_fold,MAX(fold_number) AS max_fold,
                   MIN(purge_sessions) AS min_purge,MAX(purge_sessions) AS max_purge,
                   SUM(CASE WHEN train_end_date>=test_start_date THEN 1 ELSE 0 END)
                       AS temporal_overlap_count
            FROM predictive_screening_fold_metrics WHERE screening_run_id=?
            """,
            [args.run_id],
        ),
        "screening folds",
    )
    rejection_categories = db.execute(
        """
        SELECT CASE
                 WHEN rejection_reason LIKE '%inner-fold specification%' THEN 'NO_ADMISSIBLE_INNER_SPEC'
                 WHEN rejection_reason LIKE '%outer-fold specification%' THEN 'NO_ADMISSIBLE_OUTER_SPEC'
                 WHEN rejection_reason LIKE '%missing returns%' THEN 'MISSING_OUTER_TARGET_RETURNS'
                 ELSE 'OTHER'
               END AS category,
               COUNT(*) AS rejection_count
        FROM predictive_screening_results
        WHERE screening_run_id=? AND oos_sessions=0
        GROUP BY category ORDER BY category
        """,
        [args.run_id],
    )
    rejected_examples = db.execute(
        """
        SELECT ticker,rejection_reason FROM predictive_screening_results
        WHERE screening_run_id=? AND oos_sessions=0 ORDER BY ticker LIMIT 10
        """,
        [args.run_id],
    )
    evaluated_rejection_reasons = db.execute(
        """
        SELECT rejection_reason,COUNT(*) AS ticker_count
        FROM predictive_screening_results
        WHERE screening_run_id=? AND oos_sessions>0
        GROUP BY rejection_reason
        ORDER BY ticker_count DESC,rejection_reason
        """,
        [args.run_id],
    )
    downstream = one(
        db.execute(
            """
            SELECT (SELECT COUNT(*) FROM model_runs) AS model_runs,
                   (SELECT COUNT(*) FROM model_scorecards) AS model_scorecards,
                   (SELECT COUNT(*) FROM etf_prior_lineage) AS etf_priors,
                   (SELECT COUNT(*) FROM pending_orders) AS pending_rows
            """,
            [],
        ),
        "downstream state",
    )

    expected_tickers = int(run["expected_ticker_count"])
    expected_folds = int(config["outer_folds"])
    evaluated = int(results["evaluated_count"])
    checks = {
        "run_validated": run["status"] == "VALIDATED",
        "snapshot_validated": run["snapshot_status"] == "VALIDATED",
        "complete_result_coverage": (
            int(results["result_count"]) == expected_tickers
            and int(results["distinct_tickers"]) == expected_tickers
        ),
        "familywise_hypotheses_cover_universe": (
            config.get("eligibility_hypotheses") is not None
            and int(config["eligibility_hypotheses"]) == expected_tickers
        ),
        "all_evaluated_folds_present": (
            int(folds["fold_count"]) == evaluated * expected_folds
            and int(folds["fold_tickers"]) == evaluated
        ),
        "fold_numbers_complete": (
            int(folds["min_fold"]) == 1 and int(folds["max_fold"]) == expected_folds
        ),
        "purge_matches_max_lag": (
            int(folds["min_purge"]) >= int(config["max_depth"])
            and int(folds["max_purge"]) >= int(config["max_depth"])
        ),
        "no_temporal_overlap": int(folds["temporal_overlap_count"]) == 0,
        "no_eligible_candidates": int(results["eligible_count"]) == 0,
        "no_model_or_prior_outputs": (
            int(downstream["model_runs"]) == 0
            and int(downstream["model_scorecards"]) == 0
            and int(downstream["etf_priors"]) == 0
        ),
    }
    payload = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "run_id": args.run_id,
        "code_version": run["code_version"],
        "source_session_date": run["source_session_date"],
        "market_snapshot_id": run["market_snapshot_id"],
        "checks": checks,
        "config": {
            key: config.get(key)
            for key in (
                "model_family", "min_train_sessions", "training_window_sessions",
                "test_sessions", "outer_folds", "min_oos_sessions", "min_depth",
                "max_depth", "purge_sessions", "eligibility_hypotheses",
            )
        },
        "results": results,
        "folds": folds,
        "data_rejection_categories": [
            dict(zip(rejection_categories.columns, row)) for row in rejection_categories.rows
        ],
        "data_rejection_examples": [
            dict(zip(rejected_examples.columns, row)) for row in rejected_examples.rows
        ],
        "evaluated_rejection_reason_combinations": [
            dict(zip(evaluated_rejection_reasons.columns, row))
            for row in evaluated_rejection_reasons.rows
        ],
        "downstream_state": downstream,
        "validation_notes": run["validation_notes"],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
