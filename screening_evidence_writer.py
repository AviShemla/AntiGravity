"""Append-only Turso evidence writer for predictive screening runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from model_lineage import LineageError
from predictive_screener import TickerEvaluation
from turso_read_pipeline import TursoReadPipeline, _encode_arg


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spec_json(spec) -> str | None:
    if spec is None:
        return None
    return json.dumps(
        {
            "depth": spec.depth,
            "lag_tickers": list(spec.lag_tickers),
            "technical_features": list(spec.technical_features),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class ScreeningEvidenceWriter:
    def __init__(self, endpoint: str, token: str, *, timeout_seconds: float = 30.0, session=None):
        if not endpoint.startswith("https://") or not endpoint.endswith("/v2/pipeline"):
            raise LineageError("Turso endpoint must be an HTTPS /v2/pipeline URL.")
        if not token or timeout_seconds <= 0:
            raise LineageError("Valid Turso credentials and timeout are required.")
        if session is None:
            import requests
            session = requests.Session()
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout_seconds
        self.session = session
        self.reader = TursoReadPipeline(
            endpoint, token, timeout_seconds=timeout_seconds, session=session
        )

    def _post(self, statements: list[tuple[str, list[object]]]) -> list[dict]:
        if not statements:
            raise LineageError("Turso evidence transaction cannot be empty.")
        requests_payload = [{"type": "execute", "stmt": {"sql": "BEGIN", "args": []}}]
        requests_payload.extend(
            {
                "type": "execute",
                "stmt": {"sql": sql, "args": [_encode_arg(value) for value in args]},
            }
            for sql, args in statements
        )
        requests_payload.extend([
            {"type": "execute", "stmt": {"sql": "COMMIT", "args": []}},
            {"type": "close"},
        ])
        response = self.session.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json={"requests": requests_payload},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise LineageError(f"Turso screening evidence write failed with HTTP {response.status_code}.")
        try:
            results = response.json()["results"]
        except (KeyError, TypeError, ValueError) as exc:
            raise LineageError("Turso returned invalid screening-write JSON.") from exc
        expected = len(statements) + 2
        if len(results) < expected or any(item.get("type") != "ok" for item in results[:expected]):
            raise LineageError("Turso rejected a screening evidence transaction.")
        return results

    def start_run(
        self,
        *,
        screening_run_id: str,
        market_snapshot_id: str,
        source_session_date: str,
        cutoff_utc: str,
        code_version: str,
        config_json: str,
    ) -> None:
        if not all([screening_run_id, market_snapshot_id, source_session_date, cutoff_utc, code_version, config_json]):
            raise LineageError("Screening run metadata is incomplete.")
        self._post([(
            "INSERT INTO predictive_screening_runs "
            "(screening_run_id,market_snapshot_id,source_session_date,cutoff_utc,"
            "code_version,config_json,status,started_at_utc) "
            "VALUES (?,?,?,?,?,?,'RUNNING',?)",
            [screening_run_id, market_snapshot_id, source_session_date, cutoff_utc,
             code_version, config_json, _utc_now()],
        )])

    def record_evaluation(self, screening_run_id: str, evaluation: TickerEvaluation) -> None:
        spec = evaluation.final_spec
        lags = list(spec.lag_tickers if spec else ()) + [None] * 5
        statements: list[tuple[str, list[object]]] = [(
            "INSERT INTO predictive_screening_results "
            "(screening_run_id,ticker,eligible,rejection_reason,oos_sessions,oos_accuracy,"
            "accuracy_ci_low,accuracy_ci_high,brier_score,log_loss,calibration_error,"
            "majority_accuracy,own_lag_accuracy,own_lag_brier,selected_depth,"
            "lag1_ticker,lag2_ticker,lag3_ticker,lag4_ticker,lag5_ticker,feature_spec_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [screening_run_id, evaluation.ticker, int(evaluation.eligible),
             ",".join(evaluation.rejection_reasons) or None,
             sum(len(fold.y_true) for fold in evaluation.folds),
             evaluation.model_metrics.accuracy, evaluation.accuracy_ci_low,
             evaluation.accuracy_ci_high, evaluation.model_metrics.brier,
             evaluation.model_metrics.log_loss, evaluation.model_metrics.calibration_error,
             evaluation.majority_accuracy, evaluation.own_lag_metrics.accuracy,
             evaluation.own_lag_metrics.brier, None if spec is None else spec.depth,
             *lags[:5], _spec_json(spec)],
        )]
        for fold in evaluation.folds:
            statements.append((
                "INSERT INTO predictive_screening_fold_metrics "
                "(screening_run_id,ticker,fold_number,train_start_date,train_end_date,"
                "test_start_date,test_end_date,purge_sessions,test_sessions,accuracy,"
                "brier_score,log_loss,majority_accuracy,own_lag_accuracy,own_lag_brier,"
                "selected_depth,feature_spec_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [screening_run_id, evaluation.ticker, fold.fold_number,
                 fold.train_start_date, fold.train_end_date, fold.test_start_date,
                 fold.test_end_date, fold.purge_sessions, len(fold.y_true), fold.model_metrics.accuracy,
                 fold.model_metrics.brier, fold.model_metrics.log_loss,
                 fold.majority_accuracy, fold.own_lag_metrics.accuracy,
                 fold.own_lag_metrics.brier, fold.spec.depth, _spec_json(fold.spec)],
            ))
        self._post(statements)

    def record_rejection(self, screening_run_id: str, ticker: str, reason: str) -> None:
        if not ticker.strip() or not reason.strip():
            raise LineageError("Rejected ticker requires a ticker and evidence reason.")
        self._post([(
            "INSERT INTO predictive_screening_results "
            "(screening_run_id,ticker,eligible,rejection_reason,oos_sessions) "
            "VALUES (?,?,0,?,0)",
            [screening_run_id, ticker.strip().upper(), reason.strip()],
        )])

    def finish_run(self, screening_run_id: str, *, expected_tickers: int, evidence: str) -> None:
        if expected_tickers <= 0 or not evidence.strip():
            raise LineageError("Screening completion requires counts and validation evidence.")
        count_result = self.reader.execute(
            "SELECT COUNT(*) AS n FROM predictive_screening_results WHERE screening_run_id=?",
            [screening_run_id],
        )
        if int(count_result.rows[0][0]) != expected_tickers:
            raise LineageError("Screening result count does not match the requested universe.")
        results = self._post([(
            "UPDATE predictive_screening_runs SET status='VALIDATED',completed_at_utc=?,"
            "validation_notes=? WHERE screening_run_id=? AND status='RUNNING'",
            [_utc_now(), evidence.strip(), screening_run_id],
        )])
        affected = int(results[1]["response"]["result"].get("affected_row_count", 0))
        if affected != 1:
            raise LineageError("Screening completion did not update exactly one RUNNING row.")

    def fail_run(self, screening_run_id: str, reason: str) -> None:
        if not reason.strip():
            raise LineageError("Failed screening run requires an evidence reason.")
        self._post([(
            "UPDATE predictive_screening_runs SET status='FAILED',completed_at_utc=?,"
            "validation_notes=? WHERE screening_run_id=? AND status='RUNNING'",
            [_utc_now(), reason.strip(), screening_run_id],
        )])
