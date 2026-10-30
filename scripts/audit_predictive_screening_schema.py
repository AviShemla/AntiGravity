"""Read-only verification of the additive predictive-screening schema."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from turso_read_pipeline import TursoReadPipeline


def main() -> int:
    load_dotenv(ROOT / ".env")
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    db = TursoReadPipeline(endpoint, token, timeout_seconds=15.0)
    expected = {
        "predictive_screening_runs",
        "predictive_screening_results",
        "predictive_screening_fold_metrics",
    }
    placeholders = ",".join("?" for _ in expected)
    result = db.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders}) ORDER BY name",
        sorted(expected),
    )
    actual = {str(row[0]) for row in result.rows}
    if actual != expected:
        raise SystemExit(f"Screening schema mismatch: missing={sorted(expected - actual)}")
    count_result = db.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM predictive_screening_runs) AS runs,"
        "(SELECT COUNT(*) FROM predictive_screening_results) AS results,"
        "(SELECT COUNT(*) FROM predictive_screening_fold_metrics) AS folds",
        [],
    )
    values = dict(zip(count_result.columns, count_result.rows[0]))
    print(
        "SCREENING_SCHEMA_VERIFIED "
        f"tables={len(actual)} runs={values['runs']} results={values['results']} folds={values['folds']}"
    )
    recent = db.execute(
        "SELECT r.screening_run_id,r.status,r.source_session_date,"
        "COUNT(s.ticker) AS result_count,COALESCE(SUM(s.eligible),0) AS eligible_count "
        "FROM predictive_screening_runs r LEFT JOIN predictive_screening_results s "
        "ON s.screening_run_id=r.screening_run_id GROUP BY r.screening_run_id,r.status,"
        "r.source_session_date ORDER BY r.started_at_utc DESC LIMIT 5",
        [],
    )
    for row in recent.rows:
        item = dict(zip(recent.columns, row))
        print(
            "SCREENING_RUN "
            f"id={item['screening_run_id']} status={item['status']} "
            f"source_session={item['source_session_date']} results={item['result_count']} "
            f"eligible={item['eligible_count']}"
        )
    current = db.execute(
        "SELECT screening_run_id FROM predictive_screening_runs "
        "ORDER BY started_at_utc DESC LIMIT 1",
        [],
    )
    if current.rows:
        current_id = str(current.rows[0][0])
        evaluated = db.execute(
            "SELECT COUNT(*) AS evaluated_count FROM predictive_screening_results "
            "WHERE screening_run_id=? AND oos_sessions>0",
            [current_id],
        )
        print(f"CURRENT_RUN_EVALUATED count={evaluated.rows[0][0]}")
        leaders = db.execute(
            "SELECT ticker,oos_sessions,oos_accuracy,brier_score,majority_accuracy,"
            "own_lag_accuracy,rejection_reason FROM predictive_screening_results "
            "WHERE screening_run_id=? AND oos_sessions>0 "
            "ORDER BY brier_score ASC,ticker ASC LIMIT 10",
            [current_id],
        )
        for row in leaders.rows:
            item = dict(zip(leaders.columns, row))
            print(
                "SCREENING_CANDIDATE "
                f"ticker={item['ticker']} oos={item['oos_sessions']} "
                f"accuracy={item['oos_accuracy']} brier={item['brier_score']} "
                f"majority_accuracy={item['majority_accuracy']} "
                f"own_lag_accuracy={item['own_lag_accuracy']} "
                f"rejection={item['rejection_reason']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
