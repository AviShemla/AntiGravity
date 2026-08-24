"""Fail-closed, read-only preflight for a DB-backed stock-model run.

The preflight does not run PyMC and cannot create a recommendation or order.
It proves that the market input and stock universe are immutable validated
Turso snapshots, that the latest universe decision is an explicit approval,
that its screening evidence matches the market snapshot, and that every target
and lag ticker has sufficient data through the exact source session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from model_input_reader import (
    InputSnapshot,
    StockUniverseEntry,
    load_stock_universe_config,
    select_validated_snapshot,
    verify_snapshot_counts,
)
from model_lineage import LineageError


@dataclass(frozen=True)
class SnapshotApproval:
    event_id: str
    decision: str
    approved_by: str
    decided_at_utc: datetime
    snapshot_checksum_sha256: str
    source_evidence_type: str
    source_evidence_id: str


@dataclass(frozen=True)
class StockModelPreflightEvidence:
    source_session_date: date
    prediction_date: date
    cutoff_utc: datetime
    market_snapshot: InputSnapshot
    universe_snapshot: InputSnapshot
    universe_approval: SnapshotApproval
    screening_run_id: str
    universe: tuple[StockUniverseEntry, ...]
    required_market_tickers: tuple[str, ...]
    minimum_history_sessions: int


def _parse_utc(value: object, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{field} is invalid.") from exc
    if parsed.tzinfo is None:
        raise LineageError(f"{field} must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _latest_approval(db, snapshot: InputSnapshot, cutoff_utc: datetime) -> SnapshotApproval:
    if not snapshot.source_checksum_sha256:
        raise LineageError("Universe snapshot has no immutable source checksum.")
    result = db.execute(
        """
        SELECT event_id,decision,approved_by,decided_at_utc,
               snapshot_checksum_sha256,source_evidence_type,source_evidence_id
        FROM model_input_approval_events
        WHERE snapshot_id=? AND decided_at_utc<=?
        ORDER BY decided_at_utc DESC,event_id DESC
        LIMIT 1
        """,
        [snapshot.snapshot_id, cutoff_utc.astimezone(timezone.utc).isoformat()],
    )
    if not result.rows:
        raise LineageError("Stock universe has no approval decision before the model cutoff.")
    row = dict(zip(result.columns, result.rows[0]))
    approval = SnapshotApproval(
        event_id=str(row["event_id"]),
        decision=str(row["decision"]),
        approved_by=str(row["approved_by"]).strip(),
        decided_at_utc=_parse_utc(row["decided_at_utc"], field="Approval timestamp"),
        snapshot_checksum_sha256=str(row["snapshot_checksum_sha256"]),
        source_evidence_type=str(row["source_evidence_type"]),
        source_evidence_id=str(row["source_evidence_id"]),
    )
    if approval.decision != "APPROVED":
        raise LineageError(f"Latest stock-universe decision is {approval.decision}, not APPROVED.")
    if not approval.approved_by:
        raise LineageError("Stock-universe approval has no accountable actor.")
    if approval.snapshot_checksum_sha256 != snapshot.source_checksum_sha256:
        raise LineageError("Stock-universe approval checksum does not match the snapshot.")
    if approval.source_evidence_type != "PREDICTIVE_SCREENING":
        raise LineageError("Production stock universe is not backed by predictive-screening evidence.")
    return approval


def _verify_screening_source(
    db,
    *,
    approval: SnapshotApproval,
    market_snapshot: InputSnapshot,
    universe: list[StockUniverseEntry],
) -> str:
    result = db.execute(
        """SELECT screening_run_id,market_snapshot_id,source_session_date,status
        FROM predictive_screening_runs WHERE screening_run_id=?""",
        [approval.source_evidence_id],
    )
    if len(result.rows) != 1:
        raise LineageError("Approved predictive-screening run is missing or duplicated.")
    run = dict(zip(result.columns, result.rows[0]))
    if str(run["status"]) != "VALIDATED":
        raise LineageError("Approved predictive-screening run is not validated.")
    if str(run["market_snapshot_id"]) != market_snapshot.snapshot_id:
        raise LineageError("Approved screening run uses a different market snapshot.")
    if str(run["source_session_date"]) != market_snapshot.source_session_date.isoformat():
        raise LineageError("Approved screening run uses a different source session.")

    eligible = db.execute(
        """SELECT ticker,selected_depth,lag1_ticker,lag2_ticker,lag3_ticker,
        lag4_ticker,lag5_ticker FROM predictive_screening_results
        WHERE screening_run_id=? AND eligible=1 ORDER BY ticker""",
        [approval.source_evidence_id],
    )
    expected = {}
    for raw in eligible.rows:
        row = dict(zip(eligible.columns, raw))
        ticker = str(row["ticker"]).strip().upper()
        depth = int(row["selected_depth"])
        lags = tuple(
            str(row[f"lag{i}_ticker"] or "").strip().upper()
            for i in range(1, depth + 1)
        )
        expected[ticker] = (depth, lags)
    actual = {entry.ticker: (entry.causal_depth, entry.lag_tickers) for entry in universe}
    if not expected:
        raise LineageError("Approved screening run contains zero eligible stock candidates.")
    if actual != expected:
        raise LineageError("Stock-universe members or lag chains differ from approved screening evidence.")
    return str(run["screening_run_id"])


def _verify_market_coverage(
    db,
    *,
    market_snapshot: InputSnapshot,
    required_tickers: tuple[str, ...],
    source_session_date: date,
    minimum_history_sessions: int,
) -> None:
    result = db.execute(
        """SELECT ticker,COUNT(*) AS row_count,MIN(date) AS first_date,
        MAX(date) AS latest_date,
        SUM(CASE WHEN close_price IS NULL OR close_price<=0 THEN 1 ELSE 0 END) AS bad_close_rows,
        SUM(CASE WHEN volume IS NULL OR volume<0 THEN 1 ELSE 0 END) AS bad_volume_rows
        FROM market_daily_features WHERE snapshot_id=? GROUP BY ticker""",
        [market_snapshot.snapshot_id],
    )
    coverage = {
        str(raw[result.columns.index("ticker")]).strip().upper():
        dict(zip(result.columns, raw))
        for raw in result.rows
    }
    missing = sorted(set(required_tickers).difference(coverage))
    if missing:
        raise LineageError(f"Validated market snapshot lacks required tickers: {', '.join(missing)}.")
    for ticker in required_tickers:
        row = coverage[ticker]
        if str(row["latest_date"]) != source_session_date.isoformat():
            raise LineageError(f"{ticker} market history is stale at {row['latest_date']}.")
        if int(row["row_count"]) < minimum_history_sessions:
            raise LineageError(
                f"{ticker} has {row['row_count']} sessions; {minimum_history_sessions} are required."
            )
        if int(row["bad_close_rows"]) or int(row["bad_volume_rows"]):
            raise LineageError(f"{ticker} contains invalid close or volume evidence.")


def build_stock_model_preflight(
    db,
    *,
    source_session_date: date,
    prediction_date: date,
    cutoff_utc: datetime,
    minimum_history_sessions: int = 252,
) -> StockModelPreflightEvidence:
    """Return immutable input evidence or raise ``LineageError``.

    This function is intentionally read-only. A caller must not start a model
    run until it returns successfully.
    """
    if source_session_date >= prediction_date:
        raise LineageError("Stock source session must precede the prediction date.")
    if cutoff_utc.tzinfo is None:
        raise LineageError("Stock-model cutoff must be timezone-aware.")
    if minimum_history_sessions < 30:
        raise LineageError("Stock-model history gate cannot be below 30 sessions.")

    market = select_validated_snapshot(
        db,
        dataset_type="MARKET_FEATURES",
        source_session_date=source_session_date,
        cutoff_utc=cutoff_utc,
    )
    universe_snapshot = select_validated_snapshot(
        db,
        dataset_type="STOCK_UNIVERSE",
        source_session_date=source_session_date,
        cutoff_utc=cutoff_utc,
    )
    verify_snapshot_counts(db, market, table_name="market_daily_features")
    universe = load_stock_universe_config(db, universe_snapshot)
    if len(universe) != universe_snapshot.expected_ticker_count:
        raise LineageError("Validated stock universe contains inactive or unaccounted members.")
    approval = _latest_approval(db, universe_snapshot, cutoff_utc)
    screening_run_id = _verify_screening_source(
        db,
        approval=approval,
        market_snapshot=market,
        universe=universe,
    )
    required_tickers = tuple(sorted({
        ticker
        for entry in universe
        for ticker in (entry.ticker, *entry.lag_tickers)
    }))
    _verify_market_coverage(
        db,
        market_snapshot=market,
        required_tickers=required_tickers,
        source_session_date=source_session_date,
        minimum_history_sessions=minimum_history_sessions,
    )
    return StockModelPreflightEvidence(
        source_session_date=source_session_date,
        prediction_date=prediction_date,
        cutoff_utc=cutoff_utc.astimezone(timezone.utc),
        market_snapshot=market,
        universe_snapshot=universe_snapshot,
        universe_approval=approval,
        screening_run_id=screening_run_id,
        universe=tuple(universe),
        required_market_tickers=required_tickers,
        minimum_history_sessions=minimum_history_sessions,
    )
