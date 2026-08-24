"""Read-only, fail-closed preflight for the DB-backed ETF PyMC stage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from etf_prior_builder import PreparedETFStockPrior, prepare_etf_stock_prior
from model_input_reader import InputSnapshot, select_validated_snapshot, verify_snapshot_counts
from model_lineage import AssetClass, LineageError, ModelRun, RunStatus


@dataclass(frozen=True)
class ETFConstituentSnapshot:
    snapshot_id: str
    source_session_date: date
    available_at_utc: datetime
    provider: str
    code_version: str
    source_checksum_sha256: str
    expected_row_count: int
    expected_etf_count: int


@dataclass(frozen=True)
class ETFModelPreflightEvidence:
    etf_run: ModelRun
    market_snapshot: InputSnapshot
    constituent_snapshot: ETFConstituentSnapshot
    constituent_weights: dict[str, float]
    prepared_stock_prior: PreparedETFStockPrior
    minimum_history_sessions: int


def _parse_utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LineageError("ETF constituent timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise LineageError("ETF constituent timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _select_constituent_snapshot(
    db,
    *,
    source_session_date: date,
    cutoff_utc: datetime,
) -> ETFConstituentSnapshot:
    result = db.execute(
        """SELECT snapshot_id,source_session_date,available_at_utc,provider,
        code_version,source_checksum_sha256,expected_row_count,expected_etf_count
        FROM etf_constituent_snapshots
        WHERE source_session_date=? AND status='VALIDATED' AND available_at_utc<=?
        ORDER BY available_at_utc DESC,snapshot_id DESC LIMIT 1""",
        [source_session_date.isoformat(), cutoff_utc.astimezone(timezone.utc).isoformat()],
    )
    if not result.rows:
        raise LineageError("No validated ETF constituent snapshot exists before the cutoff.")
    row = dict(zip(result.columns, result.rows[0]))
    snapshot = ETFConstituentSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        source_session_date=date.fromisoformat(str(row["source_session_date"])),
        available_at_utc=_parse_utc(row["available_at_utc"]),
        provider=str(row["provider"]),
        code_version=str(row["code_version"]),
        source_checksum_sha256=str(row["source_checksum_sha256"]),
        expected_row_count=int(row["expected_row_count"]),
        expected_etf_count=int(row["expected_etf_count"]),
    )
    if not snapshot.source_checksum_sha256:
        raise LineageError("ETF constituent snapshot has no immutable checksum.")
    counts = db.execute(
        """SELECT COUNT(*) AS row_count,COUNT(DISTINCT etf_ticker) AS etf_count
        FROM etf_constituent_weights WHERE snapshot_id=?""",
        [snapshot.snapshot_id],
    )
    count_row = dict(zip(counts.columns, counts.rows[0]))
    if int(count_row["row_count"]) != snapshot.expected_row_count:
        raise LineageError("ETF constituent row count differs from validated metadata.")
    if int(count_row["etf_count"]) != snapshot.expected_etf_count:
        raise LineageError("ETF constituent ticker count differs from validated metadata.")
    return snapshot


def _load_constituents(
    db,
    *,
    snapshot: ETFConstituentSnapshot,
    etf_ticker: str,
    source_session_date: date,
    minimum_weight_coverage: float,
) -> dict[str, float]:
    result = db.execute(
        """SELECT constituent_ticker,constituent_rank,constituent_weight,effective_date
        FROM etf_constituent_weights WHERE snapshot_id=? AND etf_ticker=?
        ORDER BY constituent_rank""",
        [snapshot.snapshot_id, etf_ticker],
    )
    weights: dict[str, float] = {}
    ranks: set[int] = set()
    for raw in result.rows:
        row = dict(zip(result.columns, raw))
        ticker = str(row["constituent_ticker"]).strip().upper()
        rank = int(row["constituent_rank"])
        weight = float(row["constituent_weight"])
        effective = date.fromisoformat(str(row["effective_date"]))
        if not ticker or ticker in weights or rank in ranks:
            raise LineageError("ETF constituent snapshot contains blank or duplicate keys.")
        if not 0.0 < weight <= 1.0:
            raise LineageError("ETF constituent weight must be in (0, 1].")
        if effective > source_session_date:
            raise LineageError("ETF constituent weight was not effective by the source session.")
        weights[ticker] = weight
        ranks.add(rank)
    coverage = sum(weights.values())
    if not weights:
        raise LineageError(f"ETF {etf_ticker} has no validated constituent weights.")
    if coverage > 1.0 + 1e-9:
        raise LineageError("ETF constituent weights exceed 100%.")
    if coverage + 1e-12 < minimum_weight_coverage:
        raise LineageError(
            f"ETF constituent coverage {coverage:.6f} is below {minimum_weight_coverage:.6f}."
        )
    return weights


def _verify_etf_market_history(
    db,
    *,
    market_snapshot: InputSnapshot,
    etf_ticker: str,
    source_session_date: date,
    minimum_history_sessions: int,
) -> None:
    result = db.execute(
        """SELECT COUNT(*) AS row_count,MAX(date) AS latest_date,
        SUM(CASE WHEN close_price IS NULL OR close_price<=0 THEN 1 ELSE 0 END) AS bad_close_rows,
        SUM(CASE WHEN volume IS NULL OR volume<0 THEN 1 ELSE 0 END) AS bad_volume_rows
        FROM market_daily_features WHERE snapshot_id=? AND ticker=?""",
        [market_snapshot.snapshot_id, etf_ticker],
    )
    row = dict(zip(result.columns, result.rows[0]))
    if int(row["row_count"]) < minimum_history_sessions:
        raise LineageError(f"ETF {etf_ticker} lacks sufficient validated market history.")
    if str(row["latest_date"]) != source_session_date.isoformat():
        raise LineageError(f"ETF {etf_ticker} market history is stale.")
    if int(row["bad_close_rows"]) or int(row["bad_volume_rows"]):
        raise LineageError(f"ETF {etf_ticker} contains invalid market evidence.")


def build_etf_model_preflight(
    db,
    *,
    run_id: str,
    etf_ticker: str,
    etf_persona: str,
    source_session_date: date,
    prediction_date: date,
    cutoff_utc: datetime,
    code_version: str,
    config_version: str,
    minimum_history_sessions: int = 252,
    minimum_weight_coverage: float = 0.60,
    calibrated_sigma_floor: float = 0.20,
) -> ETFModelPreflightEvidence:
    ticker = etf_ticker.strip().upper()
    if not run_id or not ticker or not code_version or not config_version:
        raise LineageError("ETF preflight requires stable run, ticker, code, and config identifiers.")
    if source_session_date >= prediction_date:
        raise LineageError("ETF source session must precede prediction date.")
    if cutoff_utc.tzinfo is None:
        raise LineageError("ETF cutoff must be timezone-aware.")
    if minimum_history_sessions < 30:
        raise LineageError("ETF history gate cannot be below 30 sessions.")
    if not 0.0 < minimum_weight_coverage <= 1.0:
        raise LineageError("ETF constituent coverage gate must be in (0, 1].")

    market = select_validated_snapshot(
        db,
        dataset_type="MARKET_FEATURES",
        source_session_date=source_session_date,
        cutoff_utc=cutoff_utc,
    )
    verify_snapshot_counts(db, market, table_name="market_daily_features")
    constituents = _select_constituent_snapshot(
        db,
        source_session_date=source_session_date,
        cutoff_utc=cutoff_utc,
    )
    weights = _load_constituents(
        db,
        snapshot=constituents,
        etf_ticker=ticker,
        source_session_date=source_session_date,
        minimum_weight_coverage=minimum_weight_coverage,
    )
    _verify_etf_market_history(
        db,
        market_snapshot=market,
        etf_ticker=ticker,
        source_session_date=source_session_date,
        minimum_history_sessions=minimum_history_sessions,
    )
    etf_run = ModelRun(
        run_id=run_id,
        model_name=f"ETF_PYMC_{ticker}",
        asset_class=AssetClass.ETF,
        prediction_date=prediction_date,
        source_session_date=source_session_date,
        as_of_timestamp_utc=cutoff_utc.astimezone(timezone.utc),
        code_version=code_version,
        config_version=config_version,
        status=RunStatus.STARTED,
    )
    etf_run.validate()
    prepared = prepare_etf_stock_prior(
        db,
        etf_run=etf_run,
        etf_persona=etf_persona,
        expected_market_snapshot_id=market.snapshot_id,
        constituent_weights=weights,
        minimum_weight_coverage=minimum_weight_coverage,
        calibrated_sigma_floor=calibrated_sigma_floor,
    )
    return ETFModelPreflightEvidence(
        etf_run=etf_run,
        market_snapshot=market,
        constituent_snapshot=constituents,
        constituent_weights=weights,
        prepared_stock_prior=prepared,
        minimum_history_sessions=minimum_history_sessions,
    )
