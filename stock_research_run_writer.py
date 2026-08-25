"""Atomic persistence for a completed, frozen stock-research run.

The writer records an immutable STARTED -> evidence -> COMPLETED lifecycle in
one conditional Turso batch. It never writes recommendations other than
NO_TRADE and never touches execution or order tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from model_lineage import (
    LineageError,
    ModelRun,
    ModelScorecard,
    Recommendation,
    RunStatus,
)
from model_run_writer import ModelRunWriter, _and_ok, _input_insert_sql, _validate_binding
from stock_model_preflight import StockModelPreflightEvidence


@dataclass(frozen=True)
class CompletedStockResearchReceipt:
    run_id: str
    scorecard_count: int
    market_snapshot_id: str
    universe_snapshot_id: str
    status: RunStatus
    created_at_utc: datetime
    unit_contract_version: str


class StockResearchRunWriter(ModelRunWriter):
    """Persist one fully computed research run without partial evidence."""

    UNIT_CONTRACT_VERSION = "statistical-units-v1"

    @staticmethod
    def _validate_scorecards(
        run: ModelRun,
        evidence: StockModelPreflightEvidence,
        scorecards: tuple[ModelScorecard, ...],
    ) -> None:
        expected_tickers = {entry.ticker for entry in evidence.universe}
        if not scorecards:
            raise LineageError("A completed stock research run requires scorecard evidence.")
        seen: set[tuple[str, str]] = set()
        actual_tickers: set[str] = set()
        for scorecard in scorecards:
            scorecard.validate_for(run)
            key = (scorecard.ticker, scorecard.persona)
            if key in seen:
                raise LineageError("Research scorecards contain duplicate ticker/persona evidence.")
            seen.add(key)
            actual_tickers.add(scorecard.ticker)
            if scorecard.recommendation is not Recommendation.NO_TRADE:
                raise LineageError("Frozen research persistence accepts NO_TRADE only.")
            if scorecard.proposed_allocation != 0.0:
                raise LineageError("Frozen research persistence requires zero allocation.")
            if not scorecard.quarantine_reason or "RESEARCH_ONLY" not in scorecard.quarantine_reason:
                raise LineageError("Frozen research scorecards require an explicit research-only reason.")
        if actual_tickers != expected_tickers:
            raise LineageError("Research scorecard tickers differ from the approved universe.")

    @staticmethod
    def _scorecard_insert(scorecard: ModelScorecard, created_text: str) -> tuple[str, list[object]]:
        return (
            """INSERT INTO model_scorecards (
            run_id,ticker,persona,posterior_probability,
            posterior_probability_std,posterior_probability_q05,
            posterior_probability_q95,expected_return,expected_return_std,
            expected_risk,recommendation,proposed_allocation,
            quarantine_reason,created_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                scorecard.run_id,
                scorecard.ticker,
                scorecard.persona,
                scorecard.posterior_probability,
                scorecard.posterior_probability_std,
                scorecard.posterior_probability_q05,
                scorecard.posterior_probability_q95,
                scorecard.expected_return,
                scorecard.expected_return_std,
                scorecard.expected_risk,
                scorecard.recommendation.value,
                scorecard.proposed_allocation,
                scorecard.quarantine_reason,
                created_text,
            ],
        )

    def _reconcile_completed(
        self,
        run: ModelRun,
        evidence: StockModelPreflightEvidence,
        scorecards: tuple[ModelScorecard, ...],
        created_at: datetime,
    ) -> CompletedStockResearchReceipt:
        result = self.reader.execute(
            """SELECT r.run_id,r.model_name,r.asset_class,r.prediction_date,
            r.source_session_date,r.as_of_timestamp_utc,r.code_version,
            r.config_version,r.status,
            (SELECT COUNT(*) FROM model_run_inputs i WHERE i.run_id=r.run_id) AS input_count,
            (SELECT COUNT(*) FROM model_scorecards s WHERE s.run_id=r.run_id) AS scorecard_count,
            (SELECT COUNT(*) FROM model_scorecards s WHERE s.run_id=r.run_id
             AND s.recommendation='NO_TRADE' AND s.proposed_allocation=0.0) AS frozen_count
            FROM model_runs r WHERE r.run_id=?""",
            [run.run_id],
        )
        if len(result.rows) != 1:
            raise LineageError("Completed stock research persistence was not proven by readback.")
        row = dict(zip(result.columns, result.rows[0]))
        expected = {
            "model_name": run.model_name,
            "asset_class": run.asset_class.value,
            "prediction_date": run.prediction_date.isoformat(),
            "source_session_date": run.source_session_date.isoformat(),
            "as_of_timestamp_utc": run.as_of_timestamp_utc.isoformat(),
            "code_version": run.code_version,
            "config_version": run.config_version,
            "status": RunStatus.COMPLETED.value,
        }
        if any(str(row[key]) != value for key, value in expected.items()):
            raise LineageError("Completed stock research readback metadata differs.")
        count = len(scorecards)
        if int(row["input_count"]) != 2:
            raise LineageError("Completed stock research run is not bound to exactly two inputs.")
        if int(row["scorecard_count"]) != count or int(row["frozen_count"]) != count:
            raise LineageError("Completed stock research scorecard reconciliation failed.")
        return CompletedStockResearchReceipt(
            run_id=run.run_id,
            scorecard_count=count,
            market_snapshot_id=evidence.market_snapshot.snapshot_id,
            universe_snapshot_id=evidence.universe_snapshot.snapshot_id,
            status=RunStatus.COMPLETED,
            created_at_utc=created_at,
            unit_contract_version=self.UNIT_CONTRACT_VERSION,
        )

    def persist_completed_stock_run(
        self,
        run: ModelRun,
        evidence: StockModelPreflightEvidence,
        scorecards: tuple[ModelScorecard, ...],
        *,
        created_at: datetime | None = None,
    ) -> CompletedStockResearchReceipt:
        _validate_binding(run, evidence)
        self._validate_scorecards(run, evidence, scorecards)
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

        steps = [self._step("BEGIN IMMEDIATE", [])]
        steps.append(self._step(
            """INSERT INTO model_runs (
            run_id,model_name,asset_class,prediction_date,source_session_date,
            as_of_timestamp_utc,code_version,config_version,status,
            failure_reason,created_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                run.run_id,
                run.model_name,
                run.asset_class.value,
                run.prediction_date.isoformat(),
                run.source_session_date.isoformat(),
                run.as_of_timestamp_utc.isoformat(),
                run.code_version,
                run.config_version,
                RunStatus.STARTED.value,
                None,
                created_text,
            ],
            _and_ok(0),
        ))
        steps.append(self._step(
            _input_insert_sql("MARKET_FEATURES", require_approval=False),
            market_args,
            _and_ok(0, 1),
        ))
        steps.append(self._step(
            _input_insert_sql("STOCK_UNIVERSE", require_approval=True),
            universe_args,
            _and_ok(0, 1, 2),
        ))
        for scorecard in scorecards:
            sql, args = self._scorecard_insert(scorecard, created_text)
            steps.append(self._step(sql, args, _and_ok(*range(len(steps)))))

        evidence_end = len(steps)
        steps.append(self._step(
            """UPDATE model_runs SET status='COMPLETED'
            WHERE run_id=? AND status='STARTED'
              AND (SELECT COUNT(*) FROM model_run_inputs WHERE run_id=?)=2
              AND (SELECT COUNT(*) FROM model_scorecards WHERE run_id=?)=?""",
            [run.run_id, run.run_id, run.run_id, len(scorecards)],
            _and_ok(*range(evidence_end)),
        ))
        update_index = len(steps) - 1
        steps.append(self._step("COMMIT", [], _and_ok(*range(update_index + 1))))
        commit_index = len(steps) - 1
        steps.append(self._step(
            "ROLLBACK",
            [],
            {
                "type": "and",
                "conds": [
                    {"type": "ok", "step": 0},
                    {"type": "not", "cond": {"type": "ok", "step": commit_index}},
                ],
            },
        ))

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
                raise LineageError(
                    f"Turso stock research write returned HTTP {response.status_code}."
                )
            item = response.json()["results"][0]
            if item.get("type") != "ok" or item["response"].get("type") != "batch":
                raise LineageError("Turso returned an invalid stock research batch response.")
            batch = item["response"]["result"]
            results = batch["step_results"]
            errors = batch["step_errors"]
            if len(results) != len(steps) or len(errors) != len(steps):
                raise LineageError("Turso returned incomplete stock research batch evidence.")
            for index in range(commit_index + 1):
                if results[index] is None or errors[index] is not None:
                    raise LineageError("Atomic stock research batch failed and was rolled back.")
            if results[-1] is not None or errors[-1] is not None:
                raise LineageError("Rollback unexpectedly executed after successful commit.")
        except (KeyError, IndexError, TypeError, ValueError, LineageError):
            return self._reconcile_completed(run, evidence, scorecards, created)

        return self._reconcile_completed(run, evidence, scorecards, created)
