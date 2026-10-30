"""SELECT-only immutable audit of stored simple screening baselines.

This module never fits a model and never creates a prediction, recommendation,
order, or ETF prior.  It only distinguishes already-stored candidate screening
metrics from the two already-stored baseline families.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable, Mapping

from model_lineage import LineageError
from normalized_edge_extraction import (
    ExpectedArm,
    VALIDATED_20260825_ARMS,
    _canonical_utc_timestamp,
    _required_text,
    _result_rows,
    _select,
    _validate_config,
    _validate_lineage_date,
)


EVIDENCE_CONTRACT = "simple-screening-baseline-audit-v1"
TERMINAL_DISPOSITION = "STORED_SIMPLE_BASELINES_OBSERVED"

RUN_SQL = """SELECT r.screening_run_id,r.market_snapshot_id,r.source_session_date,
       r.cutoff_utc,r.code_version,r.config_json,r.status,
       s.status AS snapshot_status,s.expected_ticker_count
FROM predictive_screening_runs r
JOIN model_input_snapshots s ON s.snapshot_id=r.market_snapshot_id
WHERE r.screening_run_id IN ({placeholders})
ORDER BY r.screening_run_id"""

RESULT_SQL = """SELECT screening_run_id,ticker,eligible,rejection_reason,oos_sessions,
       oos_accuracy,accuracy_ci_low,accuracy_ci_high,brier_score,log_loss,
       calibration_error,majority_accuracy,own_lag_accuracy,own_lag_brier
FROM predictive_screening_results
WHERE screening_run_id IN ({placeholders})
ORDER BY screening_run_id,ticker"""

CANDIDATE_FIELDS = (
    "oos_accuracy",
    "accuracy_ci_low",
    "accuracy_ci_high",
    "brier_score",
    "log_loss",
    "calibration_error",
)
BASELINE_FIELDS = ("majority_accuracy", "own_lag_accuracy", "own_lag_brier")
ALL_METRIC_FIELDS = CANDIDATE_FIELDS + BASELINE_FIELDS
PROBABILITY_METRICS = {
    "oos_accuracy",
    "accuracy_ci_low",
    "accuracy_ci_high",
    "brier_score",
    "calibration_error",
    "majority_accuracy",
    "own_lag_accuracy",
    "own_lag_brier",
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _exact_integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LineageError(f"{label} must be an integer >= {minimum}.")
    return value


def _metric(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LineageError(f"{label} must be a stored finite numeric metric.")
    result = float(value)
    if not math.isfinite(result):
        raise LineageError(f"{label} must be finite.")
    if label in PROBABILITY_METRICS and not 0.0 <= result <= 1.0:
        raise LineageError(f"{label} must be within [0,1].")
    if label == "log_loss" and result < 0.0:
        raise LineageError("log_loss must be non-negative.")
    return result


def _mean(records: list[dict[str, float]], field: str) -> float | None:
    if not records:
        return None
    return math.fsum(record[field] for record in records) / len(records)


def build_simple_baseline_audit(
    *,
    run_rows: Iterable[Mapping[str, object]],
    result_rows: Iterable[Mapping[str, object]],
    expected_arms: tuple[ExpectedArm, ...],
    expected_snapshot_id: str,
    expected_source_session_date: str,
    expected_cutoff_utc: str,
    expected_code_version: str,
) -> dict[str, object]:
    """Validate exact immutable arm coverage and summarize stored baseline evidence."""
    if not expected_arms:
        raise LineageError("At least one expected screening arm is required.")
    expected_by_id = {arm.run_id: arm for arm in expected_arms}
    if len(expected_by_id) != len(expected_arms):
        raise LineageError("Expected screening run IDs are duplicated.")
    _validate_lineage_date(expected_source_session_date, "expected source_session_date")
    canonical_cutoff = _canonical_utc_timestamp(expected_cutoff_utc, "expected cutoff_utc")
    expected_snapshot_id = _required_text(expected_snapshot_id, "expected snapshot_id")
    expected_code_version = _required_text(expected_code_version, "expected code_version")

    runs: dict[str, dict[str, object]] = {}
    for raw in run_rows:
        row = dict(raw)
        required = {
            "screening_run_id", "market_snapshot_id", "source_session_date", "cutoff_utc",
            "code_version", "config_json", "status", "snapshot_status",
            "expected_ticker_count",
        }
        if set(row) != required:
            raise LineageError("Screening run evidence columns are not exact.")
        run_id = _required_text(row["screening_run_id"], "screening_run_id")
        if run_id not in expected_by_id or run_id in runs:
            raise LineageError("Screening run evidence is unexpected or duplicated.")
        arm = expected_by_id[run_id]
        if (
            row["market_snapshot_id"] != expected_snapshot_id
            or row["source_session_date"] != expected_source_session_date
            or _canonical_utc_timestamp(row["cutoff_utc"], "screening cutoff_utc")
            != canonical_cutoff
            or row["code_version"] != expected_code_version
            or row["status"] != "VALIDATED"
            or row["snapshot_status"] != "VALIDATED"
            or _exact_integer(row["expected_ticker_count"], "expected_ticker_count", minimum=1)
            != arm.expected_ticker_count
        ):
            raise LineageError("Screening run or snapshot lineage differs from the expected contract.")
        config_sha = _validate_config(row["config_json"], arm)
        runs[run_id] = {
            "run_id": run_id,
            "signal_lookback_sessions": arm.signal_lookback_sessions,
            "expected_ticker_count": arm.expected_ticker_count,
            "expected_evaluated_count": arm.expected_evaluated_count,
            "config_sha256": config_sha,
        }
    if set(runs) != set(expected_by_id):
        raise LineageError("Screening run coverage is incomplete.")

    rows_by_run: dict[str, list[dict[str, object]]] = {run_id: [] for run_id in runs}
    identities: set[tuple[str, str]] = set()
    for raw in result_rows:
        row = dict(raw)
        required = {
            "screening_run_id", "ticker", "eligible", "rejection_reason", "oos_sessions",
            *ALL_METRIC_FIELDS,
        }
        if set(row) != required:
            raise LineageError("Screening result evidence columns are not exact.")
        run_id = row["screening_run_id"]
        if run_id not in rows_by_run:
            raise LineageError("Screening result references an unexpected run.")
        ticker = _required_text(row["ticker"], "ticker")
        if ticker != ticker.strip().upper():
            raise LineageError("Ticker is not normalized uppercase.")
        identity = (str(run_id), ticker)
        if identity in identities:
            raise LineageError("Screening result identity is duplicated.")
        identities.add(identity)
        if _exact_integer(row["eligible"], "eligible") != 0:
            raise LineageError("Baseline audit requires zero eligible screening rows.")
        rows_by_run[str(run_id)].append(row)

    arm_records = []
    evaluated_records = []
    common_tickers: set[str] | None = None
    total_evaluated = 0
    total_unevaluated = 0
    for run_id in sorted(runs):
        arm = expected_by_id[run_id]
        rows = sorted(rows_by_run[run_id], key=lambda value: str(value["ticker"]))
        if len(rows) != arm.expected_ticker_count:
            raise LineageError("Screening result denominator differs from the immutable arm contract.")
        tickers = {str(row["ticker"]) for row in rows}
        if len(tickers) != len(rows):
            raise LineageError("Screening result ticker coverage is duplicated.")
        if common_tickers is None:
            common_tickers = tickers
        elif tickers != common_tickers:
            raise LineageError("Screening arms do not share the exact ticker universe.")

        metrics_for_arm: list[dict[str, float]] = []
        unevaluated = 0
        for row in rows:
            rejection_reason = _required_text(row["rejection_reason"], "rejection_reason")
            oos_sessions = _exact_integer(row["oos_sessions"], "oos_sessions")
            if oos_sessions == 0:
                if any(row[field] is not None for field in ALL_METRIC_FIELDS):
                    raise LineageError("Unevaluated row contains fabricated candidate or baseline metrics.")
                unevaluated += 1
                continue
            values = {field: _metric(row[field], field) for field in ALL_METRIC_FIELDS}
            if not values["accuracy_ci_low"] <= values["oos_accuracy"] <= values["accuracy_ci_high"]:
                raise LineageError("Candidate accuracy is outside its stored confidence interval.")
            metrics_for_arm.append(values)
            evaluated_records.append(
                {
                    "run_id": run_id,
                    "ticker": row["ticker"],
                    "oos_sessions": oos_sessions,
                    "rejection_reason": rejection_reason,
                    "candidate_screening_metrics": {
                        field: values[field] for field in CANDIDATE_FIELDS
                    },
                    "simple_baselines": {
                        "training_fold_majority_direction_accuracy": values["majority_accuracy"],
                        "own_lag_direction_accuracy": values["own_lag_accuracy"],
                        "own_lag_direction_brier": values["own_lag_brier"],
                    },
                }
            )
        if len(metrics_for_arm) != arm.expected_evaluated_count:
            raise LineageError("Evaluated-row denominator differs from the immutable arm contract.")
        total_evaluated += len(metrics_for_arm)
        total_unevaluated += unevaluated
        arm_records.append(
            {
                **runs[run_id],
                "observed_ticker_count": len(rows),
                "evaluated_count": len(metrics_for_arm),
                "unevaluated_count": unevaluated,
                "candidate_screening_metric_means": {
                    field: _mean(metrics_for_arm, field) for field in CANDIDATE_FIELDS
                },
                "simple_baseline_means": {
                    "training_fold_majority_direction_accuracy": _mean(metrics_for_arm, "majority_accuracy"),
                    "own_lag_direction_accuracy": _mean(metrics_for_arm, "own_lag_accuracy"),
                    "own_lag_direction_brier": _mean(metrics_for_arm, "own_lag_brier"),
                },
            }
        )

    result = {
        "contract": EVIDENCE_CONTRACT,
        "disposition": TERMINAL_DISPOSITION,
        "lineage": {
            "market_snapshot_id": expected_snapshot_id,
            "source_session_date": expected_source_session_date,
            "cutoff_utc": canonical_cutoff,
            "screening_code_version": expected_code_version,
        },
        "coverage": {
            "runs_observed": len(runs),
            "runs_expected": len(expected_arms),
            "result_rows_observed": sum(len(value) for value in rows_by_run.values()),
            "result_rows_expected": sum(arm.expected_ticker_count for arm in expected_arms),
            "evaluated_rows_observed": total_evaluated,
            "evaluated_rows_expected": sum(arm.expected_evaluated_count for arm in expected_arms),
            "unevaluated_rows_observed": total_unevaluated,
            "unevaluated_rows_expected": sum(
                arm.expected_ticker_count - arm.expected_evaluated_count
                for arm in expected_arms
            ),
            "eligible_rows": 0,
        },
        "baseline_definitions": {
            "training_fold_majority_direction_accuracy": "Stored fold-local training majority-class direction baseline.",
            "own_lag_direction_accuracy": "Stored lag-1 own-ticker direction baseline accuracy.",
            "own_lag_direction_brier": "Stored lag-1 own-ticker direction baseline Brier score.",
        },
        "arms": arm_records,
        "evaluated_screening_records": sorted(
            evaluated_records, key=lambda value: (str(value["run_id"]), str(value["ticker"]))
        ),
        "side_effects": {
            "database_writes": 0,
            "model_fits": 0,
            "predictions_created": 0,
            "recommendations_created": 0,
            "orders_created": 0,
            "etf_priors_created": 0,
        },
    }
    result["evidence_sha256"] = hashlib.sha256(_canonical_json(result)).hexdigest()
    return result


def read_simple_baseline_audit(
    db,
    *,
    expected_arms: tuple[ExpectedArm, ...] = VALIDATED_20260825_ARMS,
    expected_snapshot_id: str,
    expected_source_session_date: str,
    expected_cutoff_utc: str,
    expected_code_version: str,
) -> dict[str, object]:
    run_ids = sorted(arm.run_id for arm in expected_arms)
    placeholders = ",".join("?" for _ in run_ids)
    runs = _result_rows(
        _select(db, RUN_SQL.format(placeholders=placeholders), run_ids, "screening run query"),
        "screening run query",
    )
    results = _result_rows(
        _select(db, RESULT_SQL.format(placeholders=placeholders), run_ids, "screening result query"),
        "screening result query",
    )
    return build_simple_baseline_audit(
        run_rows=runs,
        result_rows=results,
        expected_arms=expected_arms,
        expected_snapshot_id=expected_snapshot_id,
        expected_source_session_date=expected_source_session_date,
        expected_cutoff_utc=expected_cutoff_utc,
        expected_code_version=expected_code_version,
    )
