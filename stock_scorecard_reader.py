"""Turso-only reader for stock posterior evidence used by ETF models.

This module has no legacy-table, CSV, Excel, or SQLite fallback.  It accepts a
libsql-compatible executor so callers and tests can supply the connection
explicitly.  Missing, ambiguous, stale, or incomplete evidence fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, Sequence

from model_lineage import LineageError
from stock_etf_interlock import StockPosteriorEvidence, stock_persona_for


class QueryResult(Protocol):
    columns: Sequence[str]
    rows: Sequence[Sequence[object]]


class QueryExecutor(Protocol):
    def execute(self, query: str, args: list[object]) -> QueryResult: ...


@dataclass(frozen=True)
class StockEvidenceBatch:
    run_id: str
    stock_persona: str
    prediction_date: date
    source_session_date: date
    available_at_utc: datetime
    market_snapshot_id: str
    universe_snapshot_id: str
    evidence: list[StockPosteriorEvidence]


def _aware_utc(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise LineageError(f"Invalid {field}: {value!r}.") from exc
    if parsed.tzinfo is None:
        raise LineageError(f"{field} must be timezone-aware.")
    return parsed


def _row_dicts(result: QueryResult) -> list[dict[str, object]]:
    return [dict(zip(result.columns, row)) for row in result.rows]


def load_stock_evidence_for_etf(
    db: QueryExecutor,
    *,
    etf_persona: str,
    prediction_date: date,
    etf_cutoff_utc: datetime,
    expected_market_snapshot_id: str,
    constituent_weights: dict[str, float],
) -> StockEvidenceBatch:
    """Load one proven stock run and its scorecards from the additive schema.

    The newest completed stock run available by the ETF cutoff is selected.
    All returned scorecards must belong to that one run.  Missing constituents
    are omitted here and must subsequently fail or pass the explicit coverage
    gate in ``build_directional_prior``.
    """
    if etf_cutoff_utc.tzinfo is None:
        raise LineageError("ETF cutoff must be timezone-aware.")
    if not constituent_weights:
        raise LineageError("At least one constituent weight is required.")
    if any(not ticker for ticker in constituent_weights):
        raise LineageError("Constituent tickers cannot be empty.")
    if any(weight <= 0.0 or weight > 1.0 for weight in constituent_weights.values()):
        raise LineageError("Constituent weights must be in (0, 1].")
    if sum(constituent_weights.values()) > 1.0 + 1e-9:
        raise LineageError("Constituent weights exceed 100%.")
    if not expected_market_snapshot_id:
        raise LineageError("ETF prior requires an exact market snapshot ID.")

    stock_persona = stock_persona_for(etf_persona)
    run_result = db.execute(
        """
        SELECT run.run_id, run.source_session_date,
               MAX(score.created_at_utc) AS completed_at_utc
        FROM model_runs run
        JOIN model_scorecards score ON score.run_id = run.run_id
        WHERE run.asset_class = ?
          AND run.prediction_date = ?
          AND run.status = ?
          AND score.created_at_utc <= ?
        GROUP BY run.run_id, run.source_session_date
        ORDER BY completed_at_utc DESC, run.run_id DESC
        LIMIT 2
        """,
        ["STOCK", prediction_date.isoformat(), "COMPLETED", etf_cutoff_utc.isoformat()],
    )
    runs = _row_dicts(run_result)
    if not runs:
        raise LineageError("No completed stock model run is available for the ETF cutoff.")
    if len(runs) > 1 and runs[0]["completed_at_utc"] == runs[1]["completed_at_utc"]:
        raise LineageError("Ambiguous stock runs share the latest availability timestamp.")

    selected = runs[0]
    source_session = date.fromisoformat(str(selected["source_session_date"]))
    if source_session >= prediction_date:
        raise LineageError("Stock source session must precede the prediction date.")
    available_at = _aware_utc(selected["completed_at_utc"], "completed_at_utc")
    if available_at > etf_cutoff_utc:
        raise LineageError("Stock run was not available at the ETF cutoff.")

    input_result = db.execute(
        """
        SELECT mri.input_role,mri.snapshot_id,mri.snapshot_checksum_sha256,
               mis.source_checksum_sha256,mis.source_session_date,mis.available_at_utc,mis.status
        FROM model_run_inputs mri
        JOIN model_input_snapshots mis ON mis.snapshot_id=mri.snapshot_id
        WHERE mri.run_id=? AND mri.input_role IN ('MARKET_FEATURES','STOCK_UNIVERSE')
        ORDER BY mri.input_role
        """,
        [selected["run_id"]],
    )
    input_rows = _row_dicts(input_result)
    inputs: dict[str, str] = {}
    for row in input_rows:
        role = str(row["input_role"])
        if role in inputs:
            raise LineageError(f"Stock run has duplicate {role} input lineage.")
        if str(row["status"]) != "VALIDATED":
            raise LineageError(f"Stock run {role} snapshot is not validated.")
        if str(row["source_session_date"]) != source_session.isoformat():
            raise LineageError(f"Stock run {role} snapshot source session mismatch.")
        if row["source_checksum_sha256"] is None or (
            str(row["snapshot_checksum_sha256"]) != str(row["source_checksum_sha256"])
        ):
            raise LineageError(f"Stock run {role} snapshot checksum mismatch.")
        if _aware_utc(row["available_at_utc"], f"{role} available_at_utc") > available_at:
            raise LineageError(f"Stock run used {role} before it was available.")
        inputs[role] = str(row["snapshot_id"])
    required_roles = {"MARKET_FEATURES", "STOCK_UNIVERSE"}
    if set(inputs) != required_roles:
        raise LineageError("Stock run lacks exact market/universe input lineage.")
    if inputs["MARKET_FEATURES"] != expected_market_snapshot_id:
        raise LineageError("Stock and ETF stages use different market snapshots.")

    tickers = sorted(constituent_weights)
    placeholders = ", ".join("?" for _ in tickers)
    score_result = db.execute(
        f"""
        SELECT ticker, posterior_probability, posterior_probability_std,
               expected_return, expected_return_std, created_at_utc
        FROM model_scorecards
        WHERE run_id = ?
          AND persona = ?
          AND ticker IN ({placeholders})
          AND quarantine_reason IS NULL
        ORDER BY ticker
        """,
        [selected["run_id"], stock_persona, *tickers],
    )
    score_rows = _row_dicts(score_result)
    seen: set[str] = set()
    evidence: list[StockPosteriorEvidence] = []
    for row in score_rows:
        ticker = str(row["ticker"])
        if ticker in seen:
            raise LineageError(f"Duplicate stock scorecard for {ticker}.")
        seen.add(ticker)
        created_at = _aware_utc(row["created_at_utc"], "scorecard created_at_utc")
        if created_at > etf_cutoff_utc:
            raise LineageError(f"{ticker}: scorecard was created after the ETF cutoff.")
        if row["posterior_probability"] is None or row["expected_return"] is None:
            raise LineageError(f"{ticker}: posterior probability and expected return are required.")
        evidence.append(
            StockPosteriorEvidence(
                ticker=ticker,
                posterior_probability=float(row["posterior_probability"]),
                posterior_probability_std=(
                    None
                    if row["posterior_probability_std"] is None
                    else float(row["posterior_probability_std"])
                ),
                expected_return=float(row["expected_return"]),
                expected_return_std=(
                    None
                    if row["expected_return_std"] is None
                    else float(row["expected_return_std"])
                ),
                constituent_weight=float(constituent_weights[ticker]),
            )
        )

    if not evidence:
        raise LineageError("Selected stock run has no usable Turso scorecards for this ETF.")
    for item in evidence:
        item.validate()

    return StockEvidenceBatch(
        run_id=str(selected["run_id"]),
        stock_persona=stock_persona,
        prediction_date=prediction_date,
        source_session_date=source_session,
        available_at_utc=available_at,
        market_snapshot_id=inputs["MARKET_FEATURES"],
        universe_snapshot_id=inputs["STOCK_UNIVERSE"],
        evidence=evidence,
    )
