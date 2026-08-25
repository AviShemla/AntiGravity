"""Atomic, fail-closed persistence for a stock model run and its inputs.

This module does not execute PyMC, create scorecards, recommendations, or orders.
It binds a STARTED stock run to exact validated Turso snapshots in one
conditional Hrana batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from model_lineage import AssetClass, LineageError, ModelRun, RunStatus
from stock_model_preflight import StockModelPreflightEvidence
from turso_read_pipeline import TursoReadPipeline, _encode_arg


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BoundModelRunReceipt:
    run_id: str
    market_snapshot_id: str
    universe_snapshot_id: str
    created_at_utc: datetime


def _and_ok(*steps: int) -> dict[str, object]:
    return {"type": "and", "conds": [{"type": "ok", "step": step} for step in steps]}


def _validate_binding(run: ModelRun, evidence: StockModelPreflightEvidence) -> None:
    run.validate()
    if run.asset_class is not AssetClass.STOCK or run.status is not RunStatus.STARTED:
        raise LineageError("Only a STARTED stock run can be bound.")
    if run.source_session_date != evidence.source_session_date:
        raise LineageError("Run source session differs from preflight evidence.")
    if run.prediction_date != evidence.prediction_date:
        raise LineageError("Run prediction date differs from preflight evidence.")
    if run.as_of_timestamp_utc.astimezone(timezone.utc) != evidence.cutoff_utc:
        raise LineageError("Run cutoff differs from preflight evidence.")
    for label, snapshot in (
        ("market", evidence.market_snapshot),
        ("universe", evidence.universe_snapshot),
    ):
        if snapshot.source_session_date != evidence.source_session_date:
            raise LineageError(f"{label.title()} snapshot source session differs from preflight.")
        if snapshot.available_at_utc > evidence.cutoff_utc:
            raise LineageError(f"{label.title()} snapshot was unavailable at the model cutoff.")
        if not _SHA256.fullmatch(snapshot.source_checksum_sha256):
            raise LineageError(f"{label.title()} snapshot checksum is not a SHA-256.")
    approval = evidence.universe_approval
    if approval.decision != "APPROVED":
        raise LineageError("Universe evidence is not approved.")
    if approval.snapshot_checksum_sha256 != evidence.universe_snapshot.source_checksum_sha256:
        raise LineageError("Universe approval checksum differs from the snapshot.")
    if approval.decided_at_utc > evidence.cutoff_utc:
        raise LineageError("Universe approval occurred after the model cutoff.")


def _input_insert_sql(role: str, *, require_approval: bool) -> str:
    approval_clause = ""
    if require_approval:
        approval_clause = """
          AND EXISTS (
              SELECT 1
              FROM model_input_approval_events approval
              WHERE approval.event_id=?
                AND approval.snapshot_id=model_input_snapshots.snapshot_id
                AND approval.decision='APPROVED'
                AND approval.decided_at_utc<=?
                AND approval.snapshot_checksum_sha256=model_input_snapshots.source_checksum_sha256
                AND approval.event_id=(
                    SELECT latest.event_id
                    FROM model_input_approval_events latest
                    WHERE latest.snapshot_id=model_input_snapshots.snapshot_id
                      AND latest.decided_at_utc<=?
                    ORDER BY latest.decided_at_utc DESC,latest.event_id DESC
                    LIMIT 1
                )
          )
        """
    return f"""
        INSERT INTO model_run_inputs (
            run_id,input_role,snapshot_id,snapshot_checksum_sha256,created_at_utc
        ) VALUES (
            ?,'{role}',
            (
                SELECT snapshot_id
                FROM model_input_snapshots
                WHERE snapshot_id=?
                  AND dataset_type=?
                  AND status='VALIDATED'
                  AND source_session_date=?
                  AND available_at_utc<=?
                  AND source_checksum_sha256=?
                  {approval_clause}
            ),
            ?,?
        )
    """


class ModelRunWriter:
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

    @staticmethod
    def _step(sql: str, args: list[object], condition=None) -> dict[str, object]:
        result: dict[str, object] = {
            "stmt": {"sql": sql, "args": [_encode_arg(value) for value in args]}
        }
        if condition is not None:
            result["condition"] = condition
        return result

    def _reconcile(
        self,
        run: ModelRun,
        evidence: StockModelPreflightEvidence,
        created_at: datetime,
    ) -> BoundModelRunReceipt:
        result = self.reader.execute(
            """SELECT r.run_id,r.model_name,r.asset_class,r.prediction_date,
            r.source_session_date,r.as_of_timestamp_utc,r.code_version,
            r.config_version,r.status,mri.input_role,mri.snapshot_id,
            mri.snapshot_checksum_sha256
            FROM model_runs r
            LEFT JOIN model_run_inputs mri ON mri.run_id=r.run_id
            WHERE r.run_id=? ORDER BY mri.input_role""",
            [run.run_id],
        )
        if not result.rows:
            raise LineageError("Atomic model-run persistence was not proven by readback.")
        rows = [dict(zip(result.columns, raw)) for raw in result.rows]
        expected_run = {
            "model_name": run.model_name,
            "asset_class": run.asset_class.value,
            "prediction_date": run.prediction_date.isoformat(),
            "source_session_date": run.source_session_date.isoformat(),
            "as_of_timestamp_utc": run.as_of_timestamp_utc.isoformat(),
            "code_version": run.code_version,
            "config_version": run.config_version,
            "status": run.status.value,
        }
        for row in rows:
            if any(str(row[key]) != value for key, value in expected_run.items()):
                raise LineageError("Model-run readback metadata differs from the requested run.")
        inputs = {
            str(row["input_role"]): (
                str(row["snapshot_id"]),
                str(row["snapshot_checksum_sha256"]),
            )
            for row in rows
            if row["input_role"] is not None
        }
        expected_inputs = {
            "MARKET_FEATURES": (
                evidence.market_snapshot.snapshot_id,
                evidence.market_snapshot.source_checksum_sha256,
            ),
            "STOCK_UNIVERSE": (
                evidence.universe_snapshot.snapshot_id,
                evidence.universe_snapshot.source_checksum_sha256,
            ),
        }
        if inputs != expected_inputs or len(rows) != 2:
            raise LineageError("Model run is not bound to exactly the two approved inputs.")
        return BoundModelRunReceipt(
            run_id=run.run_id,
            market_snapshot_id=evidence.market_snapshot.snapshot_id,
            universe_snapshot_id=evidence.universe_snapshot.snapshot_id,
            created_at_utc=created_at,
        )

    def create_bound_stock_run(
        self,
        run: ModelRun,
        evidence: StockModelPreflightEvidence,
        *,
        created_at: datetime | None = None,
    ) -> BoundModelRunReceipt:
        _validate_binding(run, evidence)
        created = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        created_text = created.isoformat()
        cutoff_text = evidence.cutoff_utc.isoformat()

        market_args = [
            run.run_id,
            evidence.market_snapshot.snapshot_id,
            "MARKET_FEATURES",
            run.source_session_date.isoformat(),
            cutoff_text,
            evidence.market_snapshot.source_checksum_sha256,
            evidence.market_snapshot.source_checksum_sha256,
            created_text,
        ]
        universe_args = [
            run.run_id,
            evidence.universe_snapshot.snapshot_id,
            "STOCK_UNIVERSE",
            run.source_session_date.isoformat(),
            cutoff_text,
            evidence.universe_snapshot.source_checksum_sha256,
            evidence.universe_approval.event_id,
            cutoff_text,
            cutoff_text,
            evidence.universe_snapshot.source_checksum_sha256,
            created_text,
        ]
        steps = [
            self._step("BEGIN IMMEDIATE", []),
            self._step(
                """INSERT INTO model_runs (
                run_id,model_name,asset_class,prediction_date,source_session_date,
                as_of_timestamp_utc,code_version,config_version,status,
                failure_reason,created_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    run.run_id, run.model_name, run.asset_class.value,
                    run.prediction_date.isoformat(), run.source_session_date.isoformat(),
                    run.as_of_timestamp_utc.isoformat(), run.code_version,
                    run.config_version, run.status.value, run.failure_reason, created_text,
                ],
                _and_ok(0),
            ),
            self._step(
                _input_insert_sql("MARKET_FEATURES", require_approval=False),
                market_args,
                _and_ok(0, 1),
            ),
            self._step(
                _input_insert_sql("STOCK_UNIVERSE", require_approval=True),
                universe_args,
                _and_ok(0, 1, 2),
            ),
            self._step("COMMIT", [], _and_ok(0, 1, 2, 3)),
            self._step(
                "ROLLBACK",
                [],
                {
                    "type": "and",
                    "conds": [
                        {"type": "ok", "step": 0},
                        {"type": "not", "cond": {"type": "ok", "step": 4}},
                    ],
                },
            ),
        ]
        try:
            response = self.session.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [{"type": "batch", "batch": {"steps": steps}}, {"type": "close"}]},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                raise LineageError(f"Turso model-run write returned HTTP {response.status_code}.")
            item = response.json()["results"][0]
            if item.get("type") != "ok" or item["response"].get("type") != "batch":
                raise LineageError("Turso returned an invalid model-run batch response.")
            batch = item["response"]["result"]
            results = batch["step_results"]
            errors = batch["step_errors"]
            if len(results) != 6 or len(errors) != 6:
                raise LineageError("Turso returned incomplete model-run batch evidence.")
            if any(results[index] is None or errors[index] is not None for index in range(5)):
                raise LineageError("Atomic model-run batch failed and was rolled back.")
            if results[5] is not None or errors[5] is not None:
                raise LineageError("Rollback unexpectedly executed after a successful commit.")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LineageError("Turso returned malformed model-run batch evidence.") from exc
        except LineageError:
            return self._reconcile(run, evidence, created)

        return self._reconcile(run, evidence, created)
