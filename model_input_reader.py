"""Fail-closed Turso readers for versioned stock-model inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from model_lineage import LineageError


_DATASET_TYPES = {"MARKET_FEATURES", "STOCK_UNIVERSE", "STOCK_FUNDAMENTALS"}


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LineageError("Model-input timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise LineageError("Model-input timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class InputSnapshot:
    snapshot_id: str
    dataset_type: str
    source_session_date: date
    available_at_utc: datetime
    provider: str
    code_version: str
    expected_row_count: int
    expected_ticker_count: int
    source_checksum_sha256: str | None = None


@dataclass(frozen=True)
class StockUniverseEntry:
    ticker: str
    selection_rank: int
    oos_accuracy: float | None
    causal_depth: int
    lag_tickers: tuple[str, ...]
    lag_sessions: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.lag_sessions:
            object.__setattr__(
                self, "lag_sessions", tuple(range(1, self.causal_depth + 1))
            )
        if self.causal_depth != len(self.lag_tickers) or self.causal_depth != len(self.lag_sessions):
            raise LineageError("Universe depth, lag tickers, and lag sessions must agree.")
        if not 1 <= self.causal_depth <= 5:
            raise LineageError("Universe chain length must be between 1 and 5.")
        if any(not ticker.strip() for ticker in self.lag_tickers):
            raise LineageError("Universe contains a blank lag ticker.")
        if any(not isinstance(lag, int) or lag <= 0 for lag in self.lag_sessions):
            raise LineageError("Universe lag sessions must be positive integers.")
        if len(set(zip(self.lag_tickers, self.lag_sessions))) != self.causal_depth:
            raise LineageError("Universe contains a duplicate ticker/lag edge.")


def select_validated_snapshot(
    db,
    *,
    dataset_type: str,
    source_session_date: date,
    cutoff_utc: datetime,
) -> InputSnapshot:
    if dataset_type not in _DATASET_TYPES:
        raise LineageError(f"Unsupported model-input dataset type: {dataset_type!r}.")
    if cutoff_utc.tzinfo is None:
        raise LineageError("Model-input cutoff must be timezone-aware.")
    result = db.execute(
        """
        SELECT snapshot_id, dataset_type, source_session_date, available_at_utc,
               provider, code_version, expected_row_count, expected_ticker_count,
               source_checksum_sha256
        FROM model_input_snapshots
        WHERE dataset_type = ? AND source_session_date = ? AND status = 'VALIDATED'
              AND available_at_utc <= ?
        ORDER BY available_at_utc DESC, snapshot_id DESC
        LIMIT 1
        """,
        [dataset_type, source_session_date.isoformat(), cutoff_utc.astimezone(timezone.utc).isoformat()],
    )
    if not result.rows:
        raise LineageError(
            f"No validated {dataset_type} snapshot exists for {source_session_date.isoformat()} "
            "before the model cutoff."
        )
    row = dict(zip(result.columns, result.rows[0]))
    available_at = _parse_utc(str(row["available_at_utc"]))
    if available_at > cutoff_utc.astimezone(timezone.utc):
        raise LineageError("Model-input snapshot became available after the cutoff.")
    return InputSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        dataset_type=str(row["dataset_type"]),
        source_session_date=date.fromisoformat(str(row["source_session_date"])),
        available_at_utc=available_at,
        provider=str(row["provider"]),
        code_version=str(row["code_version"]),
        expected_row_count=int(row["expected_row_count"]),
        expected_ticker_count=int(row["expected_ticker_count"]),
        source_checksum_sha256=(
            None
            if row.get("source_checksum_sha256") is None
            else str(row["source_checksum_sha256"])
        ),
    )


def verify_snapshot_counts(db, snapshot: InputSnapshot, *, table_name: str) -> None:
    allowed = {
        "MARKET_FEATURES": "market_daily_features",
        "STOCK_UNIVERSE": "stock_universe_config",
        "STOCK_FUNDAMENTALS": "stock_fundamental_features",
    }
    expected_table = allowed[snapshot.dataset_type]
    if table_name != expected_table:
        raise LineageError("Snapshot dataset type does not match the requested input table.")
    result = db.execute(
        f"SELECT COUNT(*) AS row_count, COUNT(DISTINCT ticker) AS ticker_count "
        f"FROM {expected_table} WHERE snapshot_id = ?",
        [snapshot.snapshot_id],
    )
    row = dict(zip(result.columns, result.rows[0]))
    if int(row["row_count"]) != snapshot.expected_row_count:
        raise LineageError("Model-input row count does not match validated snapshot metadata.")
    if int(row["ticker_count"]) != snapshot.expected_ticker_count:
        raise LineageError("Model-input ticker count does not match validated snapshot metadata.")


def load_stock_universe_config(db, snapshot: InputSnapshot) -> list[StockUniverseEntry]:
    if snapshot.dataset_type != "STOCK_UNIVERSE":
        raise LineageError("Stock universe requires a STOCK_UNIVERSE snapshot.")
    verify_snapshot_counts(db, snapshot, table_name="stock_universe_config")
    result = db.execute(
        """
        SELECT ticker, selection_rank, oos_accuracy, causal_depth,
               lag1_ticker, lag2_ticker, lag3_ticker, lag4_ticker, lag5_ticker,
               lag1_sessions, lag2_sessions, lag3_sessions, lag4_sessions, lag5_sessions
        FROM stock_universe_config
        WHERE snapshot_id = ? AND active = 1
        ORDER BY selection_rank
        """,
        [snapshot.snapshot_id],
    )
    entries: list[StockUniverseEntry] = []
    seen_tickers: set[str] = set()
    seen_ranks: set[int] = set()
    for raw in result.rows:
        row = dict(zip(result.columns, raw))
        ticker = str(row["ticker"]).strip().upper()
        rank = int(row["selection_rank"])
        depth = int(row["causal_depth"])
        if not ticker or ticker in seen_tickers or rank in seen_ranks:
            raise LineageError("Stock universe contains blank or duplicate ticker/rank values.")
        lags = tuple(
            str(row[f"lag{i}_ticker"]).strip().upper()
            for i in range(1, depth + 1)
            if row[f"lag{i}_ticker"] is not None and str(row[f"lag{i}_ticker"]).strip()
        )
        lag_sessions = tuple(
            int(row[f"lag{i}_sessions"])
            for i in range(1, depth + 1)
            if row[f"lag{i}_sessions"] is not None
        )
        if len(lags) != depth or len(lag_sessions) != depth:
            raise LineageError(f"Stock universe has an incomplete lag specification for {ticker}.")
        seen_tickers.add(ticker)
        seen_ranks.add(rank)
        entries.append(
            StockUniverseEntry(
                ticker=ticker,
                selection_rank=rank,
                oos_accuracy=None if row["oos_accuracy"] is None else float(row["oos_accuracy"]),
                causal_depth=depth,
                lag_tickers=lags,
                lag_sessions=lag_sessions,
            )
        )
    if not entries:
        raise LineageError("Validated stock universe contains no active entries.")
    return entries
