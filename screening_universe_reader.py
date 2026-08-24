"""Fail-closed bridge from validated screening evidence to stock candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass

from model_input_reader import StockUniverseEntry
from model_lineage import LineageError


@dataclass(frozen=True)
class ScreeningUniverse:
    screening_run_id: str
    market_snapshot_id: str
    source_session_date: str
    candidates: tuple[StockUniverseEntry, ...]
    disposition: str


def load_screening_universe(
    db,
    *,
    screening_run_id: str,
    expected_market_snapshot_id: str,
    expected_source_session_date: str,
    maximum_candidates: int = 10,
) -> ScreeningUniverse:
    if not 1 <= maximum_candidates <= 100:
        raise LineageError("Maximum screening candidates must be between 1 and 100.")
    run = db.execute(
        """SELECT screening_run_id,market_snapshot_id,source_session_date,status
        FROM predictive_screening_runs WHERE screening_run_id=?""",
        [screening_run_id],
    )
    if len(run.rows) != 1:
        raise LineageError("Screening run is missing or duplicated.")
    run_row = dict(zip(run.columns, run.rows[0]))
    if str(run_row["status"]) != "VALIDATED":
        raise LineageError("Screening run is not validated.")
    if str(run_row["market_snapshot_id"]) != expected_market_snapshot_id:
        raise LineageError("Screening run market snapshot mismatch.")
    if str(run_row["source_session_date"]) != expected_source_session_date:
        raise LineageError("Screening run source session mismatch.")
    result = db.execute(
        """SELECT ticker,oos_accuracy,selected_depth,lag1_ticker,lag2_ticker,
        lag3_ticker,lag4_ticker,lag5_ticker,feature_spec_json
        FROM predictive_screening_results
        WHERE screening_run_id=? AND eligible=1
        ORDER BY brier_score ASC,calibration_error ASC,ticker ASC LIMIT ?""",
        [screening_run_id, maximum_candidates],
    )
    candidates = []
    for rank, raw in enumerate(result.rows, start=1):
        row = dict(zip(result.columns, raw))
        depth = int(row["selected_depth"])
        if not 1 <= depth <= 5:
            raise LineageError("Eligible screening row has invalid depth.")
        lags = tuple(str(row[f"lag{i}_ticker"] or "").strip().upper() for i in range(1, depth + 1))
        if any(not ticker for ticker in lags):
            raise LineageError("Eligible screening row has incomplete lag chain.")
        try:
            feature_spec = json.loads(str(row["feature_spec_json"]))
        except (TypeError, ValueError) as exc:
            raise LineageError("Eligible screening row has invalid feature specification.") from exc
        if not isinstance(feature_spec, dict) or int(feature_spec.get("depth", 0)) != depth:
            raise LineageError("Eligible screening feature specification disagrees with depth.")
        candidates.append(StockUniverseEntry(
            ticker=str(row["ticker"]).strip().upper(),
            selection_rank=rank,
            oos_accuracy=float(row["oos_accuracy"]),
            causal_depth=depth,
            lag_tickers=lags,
        ))
    return ScreeningUniverse(
        screening_run_id=screening_run_id,
        market_snapshot_id=expected_market_snapshot_id,
        source_session_date=expected_source_session_date,
        candidates=tuple(candidates),
        disposition="MODEL_CANDIDATES" if candidates else "NO_TRADE",
    )
