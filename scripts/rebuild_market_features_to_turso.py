"""Rebuild a complete-session market-feature snapshot directly into Turso.

No CSV, Excel, SQLite, or local data cache is read or written. The resulting
snapshot remains STAGING until separate database and provider QA promotes it.
"""

from __future__ import annotations

import argparse
import concurrent.futures
from collections import Counter
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data_provider import fetch_validated_daily_bars, resolve_tiingo_api_key
from scripts.stage_market_features_to_turso import COLUMN_MAP, clean, post_statements
from turso_read_pipeline import TursoReadPipeline
from market_staging_content import ENCODING, STAGING_COLUMNS, digest_rows


GapFallback = Callable[
    [str], tuple[pd.DataFrame | None, str | None, str | None]
]

TURSO_TIMEOUT_SECONDS = 120.0


def recent_nyse_sessions(source_session: date, *, rows: int = 130) -> list[date]:
    """Return the exact recent NYSE sessions required for every current ticker."""
    if not 1 <= rows <= 1000:
        raise ValueError("Recent NYSE session rows must be between 1 and 1000.")
    import pandas_market_calendars as mcal

    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(
        start_date=pd.Timestamp(source_session) - pd.Timedelta(days=rows * 3),
        end_date=source_session,
    )
    sessions = [pd.Timestamp(value).date() for value in schedule.index]
    if len(sessions) < rows or sessions[-1] != source_session:
        raise ValueError("NYSE calendar did not produce the required completed sessions.")
    return sessions[-rows:]


def missing_sessions(frame: pd.DataFrame, expected_sessions: list[date]) -> list[date]:
    observed = set(pd.to_datetime(frame["Date"], errors="raise").dt.date)
    return [session for session in expected_sessions if session not in observed]


def repair_recent_session_gaps(
    successes: dict[str, pd.DataFrame],
    providers: dict[str, str],
    expected_sessions: list[date],
    tiingo_fallback: GapFallback,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, str], list[str]]:
    """Replace a gapped ticker completely with Tiingo or fail closed."""
    repaired = dict(successes)
    repaired_providers = dict(providers)
    failures: dict[str, str] = {}
    replacements: list[str] = []
    for ticker in sorted(successes):
        gaps = missing_sessions(successes[ticker], expected_sessions)
        if not gaps:
            continue
        fallback, provider, error = tiingo_fallback(ticker)
        if fallback is None or provider != "TIINGO_EOD":
            failures[ticker] = (
                "Recent NYSE sessions missing from primary provider: "
                + ",".join(session.isoformat() for session in gaps)
                + f"; Tiingo replacement failed: {error or 'invalid provider'}"
            )
            continue
        remaining = missing_sessions(fallback, expected_sessions)
        if remaining:
            failures[ticker] = (
                "Recent NYSE sessions remain missing after Tiingo replacement: "
                + ",".join(session.isoformat() for session in remaining)
            )
            continue
        repaired[ticker] = fallback
        repaired_providers[ticker] = provider
        replacements.append(ticker)
    return repaired, repaired_providers, failures, replacements


def fetch_ticker(
    ticker: str,
    source_session: date,
    start_date: str,
    tiingo_api_key: str | None = None,
) -> tuple[str, pd.DataFrame | None, str | None, str | None]:
    return fetch_validated_daily_bars(
        ticker,
        source_session,
        start_date,
        tiingo_api_key=tiingo_api_key,
    )


def calculate_features(raw: pd.DataFrame, *, ticker: str, sector: str) -> pd.DataFrame:
    frame = normalize_ohlc_envelope(
        raw.copy().sort_values("Date").reset_index(drop=True)
    )
    frame["Ticker"] = ticker
    frame["Sector"] = sector
    for column in ("Adj Close", "Dividends", "Stock Splits"):
        if column not in frame:
            frame[column] = frame["Close"] if column == "Adj Close" else 0.0
    frame["Daily_Return_%"] = frame["Close"].pct_change(fill_method=None) * 100.0
    frame["Daily_STDEV"] = frame[["Open", "High", "Low", "Close"]].std(axis=1)
    for window in (5, 10, 20):
        frame[f"STDEV_{window}d"] = frame["Close"].rolling(window).std()
    frame["Max_High_20d"] = frame["High"].rolling(20).max()
    frame["Min_Low_20d"] = frame["Low"].rolling(20).min()

    delta = frame["Close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(com=13, min_periods=14).mean()
    avg_loss = loss.ewm(com=13, min_periods=14).mean().replace(0.0, 0.00001)
    rs = avg_gain / avg_loss
    frame["RSI_14d"] = 100.0 - (100.0 / (1.0 + rs))

    previous_high = frame["High"].shift(1)
    previous_low = frame["Low"].shift(1)
    previous_close = frame["Close"].shift(1)
    true_range = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous_close).abs(),
            (frame["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["ATR_14d"] = true_range.ewm(com=13, min_periods=14).mean()
    up_move = frame["High"] - previous_high
    down_move = previous_low - frame["Low"]
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index
    )
    smoothed_plus = plus_dm.ewm(com=13, min_periods=14).mean()
    smoothed_minus = minus_dm.ewm(com=13, min_periods=14).mean()
    safe_atr = frame["ATR_14d"].replace(0.0, 0.00001)
    frame["Plus_DI_14d"] = 100.0 * smoothed_plus / safe_atr
    frame["Minus_DI_14d"] = 100.0 * smoothed_minus / safe_atr
    denominator = (frame["Plus_DI_14d"] + frame["Minus_DI_14d"]).replace(0.0, 0.00001)
    dx = 100.0 * (frame["Plus_DI_14d"] - frame["Minus_DI_14d"]).abs() / denominator
    frame["ADX_14d"] = dx.ewm(com=13, min_periods=14).mean()
    raw_stop = frame["Max_High_20d"] - 2.5 * frame["ATR_14d"]
    frame["Dynamic_Stop_Loss"] = raw_stop.fillna(0.0).cummax()
    frame.loc[frame["ATR_14d"].isna(), "Dynamic_Stop_Loss"] = np.nan
    frame["RAS_Signal"] = np.where(
        frame["Plus_DI_14d"] > frame["Minus_DI_14d"],
        "BUY",
        np.where(frame["Minus_DI_14d"] > frame["Plus_DI_14d"], "SELL", "HOLD"),
    )
    frame["Analyst_Consensus"] = "N/A"
    frame["Analyst_Upside_%"] = np.nan
    return frame.dropna(subset=["Close", "RSI_14d", "ADX_14d"]).reset_index(drop=True)


def merge_cross_market_features(frame: pd.DataFrame, vix: pd.DataFrame, tnx: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    stock_rows = result[result["Sector"] != "ETF"]
    if stock_rows.empty:
        raise ValueError("Cross-market features require a non-ETF stock universe.")
    daily_market = stock_rows.groupby("Date")["Daily_Return_%"].mean().sort_index()
    market_60 = daily_market.rolling(60, min_periods=1).mean().rename("Market_Mean_60d")
    sector_daily = (
        result.groupby(["Date", "Sector"])["Daily_Return_%"].mean().rename("sector_daily").reset_index()
    )
    sector_daily = sector_daily.sort_values(["Sector", "Date"])
    sector_daily["Sector_Mean_60d"] = sector_daily.groupby("Sector")["sector_daily"].transform(
        lambda values: values.rolling(60, min_periods=1).mean()
    )
    result = result.merge(market_60, on="Date", how="left")
    result = result.merge(
        sector_daily[["Date", "Sector", "Sector_Mean_60d"]], on=["Date", "Sector"], how="left"
    )
    result["Sector_Momentum_Score"] = result["Sector_Mean_60d"] - result["Market_Mean_60d"]
    result["Sector_Regime"] = np.where(
        result["Sector_Momentum_Score"] >= 0.0, "BULL_REGIME", "BEAR_REGIME"
    )
    result = result.drop(columns=["Market_Mean_60d", "Sector_Mean_60d"])

    vix_values = vix[["Date", "Close"]].rename(columns={"Close": "VIX_Close"})
    vix_values["Market_Fear_Level"] = np.where(
        vix_values["VIX_Close"] >= 30.0,
        "Extreme Panic",
        np.where(vix_values["VIX_Close"] >= 20.0, "High Volatility", "Complacency / Calm"),
    )
    tnx_values = tnx[["Date", "Close"]].rename(columns={"Close": "TNX_Close"})
    tnx_values["TNX_Lag1_Return"] = tnx_values["TNX_Close"].pct_change(fill_method=None)
    tnx_values["TNX_Trend_5d"] = tnx_values["TNX_Close"].rolling(5).mean()
    result = result.merge(vix_values, on="Date", how="left").merge(tnx_values, on="Date", how="left")
    return result


def build_controlled_universe(
    stock_rows,
    etf_scorecard_rows,
    etf_ledger_rows,
    etf_pending_rows,
) -> dict[str, str]:
    """Merge the DB-backed stock and ETF universes without a file fallback."""
    sector_by_ticker = {
        str(row[0]).upper(): str(row[1] or "Unknown") for row in stock_rows
    }
    etf_tickers = {str(row[0]).upper() for row in etf_scorecard_rows}
    for rows, field in (
        (etf_ledger_rows, "holdings_json"),
        (etf_pending_rows, "target_holdings_json"),
    ):
        for row in rows:
            try:
                decoded = json.loads(str(row[0]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} contains invalid JSON.") from exc
            if not isinstance(decoded, dict):
                raise ValueError(f"{field} must be a JSON object.")
            etf_tickers.update(str(ticker).upper() for ticker in decoded)
    for ticker in sorted(etf_tickers):
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
            raise ValueError(f"Invalid DB-backed ETF ticker: {ticker!r}.")
        sector_by_ticker.setdefault(ticker, "ETF")
    return sector_by_ticker


def apply_symbol_lifecycle(
    universe: dict[str, str],
    lifecycle_rows,
    *,
    source_session: date,
) -> tuple[dict[str, str], dict[str, str]]:
    """Apply dated DB lifecycle events and return universe plus replacements."""
    def sector_key(value: str) -> str:
        return re.sub(r"[\s_]+", "_", value.strip().upper())

    controlled = dict(universe)
    replacements: dict[str, str] = {}
    for raw in lifecycle_rows:
        ticker, event_type, effective_date, successor, sector = raw
        ticker = str(ticker).strip().upper()
        event_type = str(event_type).strip().upper()
        event_date = date.fromisoformat(str(effective_date))
        successor = None if successor is None else str(successor).strip().upper()
        sector = str(sector).strip()
        for symbol in (ticker, successor):
            if symbol is not None and not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
                raise ValueError(f"Invalid lifecycle ticker: {symbol!r}.")
        if not sector:
            raise ValueError(f"Lifecycle sector is blank for {ticker}.")
        if event_date > source_session:
            continue
        if event_type == "ACTIVATED":
            if successor is not None:
                raise ValueError(f"Activated ticker {ticker} cannot name a successor.")
            existing = controlled.get(ticker)
            if existing is not None and sector_key(existing) != sector_key(sector):
                raise ValueError(f"Lifecycle sector conflicts with universe for {ticker}.")
            controlled.setdefault(ticker, sector)
        elif event_type == "RETIRED":
            if successor is None or successor == ticker:
                raise ValueError(f"Retired ticker {ticker} requires a distinct successor.")
            inherited_sector = controlled.pop(ticker, sector)
            successor_sector = controlled.get(successor)
            if (
                successor_sector is not None
                and sector_key(successor_sector) != sector_key(inherited_sector)
            ):
                raise ValueError(
                    f"Lifecycle successor sector conflicts for {ticker}->{successor}."
                )
            controlled.setdefault(successor, inherited_sector)
            replacements[ticker] = successor
        else:
            raise ValueError(f"Unsupported lifecycle event type: {event_type!r}.")
    return controlled, replacements


def resolve_lifecycle_tickers(
    tickers: list[str], replacements: dict[str, str]
) -> list[str]:
    """Resolve required symbols through successor chains, rejecting cycles."""
    resolved: list[str] = []
    for original in tickers:
        ticker = str(original).strip().upper()
        seen: set[str] = set()
        while ticker in replacements:
            if ticker in seen:
                raise ValueError(f"Lifecycle replacement cycle includes {ticker}.")
            seen.add(ticker)
            ticker = replacements[ticker]
        if ticker not in resolved:
            resolved.append(ticker)
    return resolved


def apply_approved_instrument_registry(
    universe: dict[str, str],
    registry_version_rows,
    registry_rows,
) -> dict[str, str]:
    """Replace legacy ETF membership with one approved DB registry version."""
    registry_ids = {str(row[0]) for row in registry_version_rows}
    if len(registry_ids) != 1:
        raise ValueError("Exactly one approved instrument registry is required.")
    registry_id = next(iter(registry_ids))
    currently_required_etfs = {
        ticker for ticker, sector in universe.items() if sector == "ETF"
    }
    controlled = {
        ticker: sector for ticker, sector in universe.items() if sector != "ETF"
    }
    allowed_usages = {"MODEL_CANDIDATE", "VALUATION_ONLY", "BENCHMARK"}
    seen: set[str] = set()
    model_candidates = 0
    for raw in registry_rows:
        row_registry_id, ticker, asset_class, sector, usage, minimum_rows = raw
        if str(row_registry_id) != registry_id:
            raise ValueError("Instrument row belongs to a different registry version.")
        ticker = str(ticker).strip().upper()
        asset_class = str(asset_class).strip().upper()
        usage = str(usage).strip().upper()
        if ticker in seen:
            raise ValueError(f"Instrument registry duplicates ticker {ticker}.")
        seen.add(ticker)
        if not re.fullmatch(r"(?:\^[A-Z0-9]{1,8}|[A-Z][A-Z0-9.\-]{0,14})", ticker):
            raise ValueError(f"Invalid instrument-registry ticker: {ticker!r}.")
        if int(minimum_rows) <= 0:
            raise ValueError(f"Invalid minimum history for {ticker}.")
        if asset_class == "ETF":
            if usage == "MODEL_CANDIDATE":
                model_candidates += 1
            if usage in {"MODEL_CANDIDATE", "BENCHMARK"} or (
                usage == "VALUATION_ONLY" and ticker in currently_required_etfs
            ):
                controlled[ticker] = "ETF" if sector is None else str(sector)
        elif asset_class == "STOCK":
            if ticker not in controlled:
                raise ValueError(f"Registry stock {ticker} is absent from the base universe.")
        elif asset_class != "MACRO":
            raise ValueError(f"Unsupported registry asset class: {asset_class!r}.")
    if model_candidates == 0:
        raise ValueError("Approved registry has no ETF model candidate.")
    return controlled


def normalize_ohlc_envelope(frame: pd.DataFrame) -> pd.DataFrame:
    """Assert that validated OHLC is already canonical; never silently repair."""
    required = ["Open", "High", "Low", "Close"]
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise ValueError(
            "Canonical OHLC normalization is missing columns: " + ", ".join(missing)
        )
    result = frame.copy()
    numeric = result[required].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Canonical OHLC contains null or non-numeric values.")
    expected_high = numeric.max(axis=1, skipna=False)
    expected_low = numeric.min(axis=1, skipna=False)
    if not numeric["High"].equals(expected_high) or not numeric["Low"].equals(expected_low):
        raise ValueError("Validated provider OHLC would change under canonical normalization.")
    return result


def content_checksum(frame: pd.DataFrame) -> str:
    if tuple(target for _, target in COLUMN_MAP) != STAGING_COLUMNS:
        raise ValueError("Staging checksum column contract differs from writer COLUMN_MAP.")
    ordered = frame.sort_values(["Ticker", "Date"], kind="mergesort")
    clean_rows = (
        tuple(clean(value) for value in row)
        for row in ordered[[source for source, _ in COLUMN_MAP]].itertuples(index=False, name=None)
    )
    return digest_rows(clean_rows)


def provider_source_checksum(frame: pd.DataFrame) -> str:
    columns = [
        "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume",
        "Dividends", "Stock Splits",
    ]
    ordered = frame.sort_values("Date").reset_index(drop=True)
    values = pd.util.hash_pandas_object(ordered[columns], index=False)
    return hashlib.sha256(values.to_numpy().tobytes()).hexdigest()


def build_provider_lineage(
    sources: dict[str, pd.DataFrame],
    providers: dict[str, str],
    *,
    source_session: date,
) -> list[list[object]]:
    if set(sources) != set(providers):
        raise ValueError("Provider lineage source/provider ticker sets do not match.")
    rows = []
    for ticker in sorted(sources):
        frame = sources[ticker]
        if frame.empty:
            raise ValueError(f"Provider lineage source is empty for {ticker}.")
        dates = pd.to_datetime(frame["Date"], errors="raise")
        rows.append(
            [
                ticker,
                providers[ticker],
                source_session.isoformat(),
                dates.min().date().isoformat(),
                dates.max().date().isoformat(),
                len(frame),
                provider_source_checksum(frame),
            ]
        )
    return rows


def provider_lineage_checksum(rows: list[list[object]]) -> str:
    """Hash sorted provider evidence using a process-independent JSON encoding."""
    ordered = sorted(rows, key=lambda row: str(row[0]))
    payload = json.dumps(ordered, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare_provider_lineage(
    fresh_rows: list[list[object]], stored_rows, *, sample_size: int = 20
) -> dict[str, object]:
    """Compare exact provider evidence without exposing source data or secrets."""
    fresh = {str(row[0]): tuple(row[1:]) for row in fresh_rows}
    stored = {str(row[0]): tuple(row[1:]) for row in stored_rows}
    missing = sorted(set(stored).difference(fresh))
    unexpected = sorted(set(fresh).difference(stored))
    changed = sorted(
        ticker for ticker in set(fresh).intersection(stored)
        if fresh[ticker] != stored[ticker]
    )
    return {
        "missing_from_fresh_count": len(missing),
        "missing_from_fresh_sample": missing[:sample_size],
        "unexpected_in_fresh_count": len(unexpected),
        "unexpected_in_fresh_sample": unexpected[:sample_size],
        "changed_ticker_count": len(changed),
        "changed_ticker_sample": changed[:sample_size],
    }


def require_complete_rebuild(
    successes: dict[str, pd.DataFrame],
    failures: dict[str, str | None],
    required_tickers: list[str],
) -> None:
    missing_required = sorted(set(required_tickers).difference(successes))
    if missing_required:
        raise ValueError(
            "Required target tickers failed fresh ingestion: " + ", ".join(missing_required)
        )
    if failures:
        raise ValueError(
            "Fresh rebuild is incomplete; no snapshot may be staged while any "
            "controlled-universe ticker failed ingestion."
        )


def stage_frame(
    db,
    endpoint,
    token,
    frame,
    *,
    source_session: date,
    provider: str,
    provider_lineage: list[list[object]],
    notes: str,
) -> str:
    frame = normalize_ohlc_envelope(frame)
    checksum = content_checksum(frame)
    snapshot_id = f"market_features_{source_session.isoformat()}_{checksum[:16]}"
    expected_rows = len(frame)
    expected_tickers = int(frame["Ticker"].nunique())
    created_at = datetime.now(timezone.utc).isoformat()
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    session = requests.Session()
    post_statements(session, endpoint, token, [(
        """INSERT OR IGNORE INTO model_input_snapshots
        (snapshot_id,dataset_type,source_session_date,available_at_utc,provider,code_version,
         source_checksum_sha256,expected_row_count,expected_ticker_count,status,validation_notes,created_at_utc)
        VALUES (?,'MARKET_FEATURES',?,?,?,?,?,?,?,'STAGING',?,?)""",
        [snapshot_id, source_session.isoformat(), created_at, provider, code_hash, checksum,
         expected_rows, expected_tickers, f"checksum_encoding={ENCODING}; {notes}", created_at],
    )])
    lineage_prefix = (
        "INSERT OR IGNORE INTO market_data_provider_lineage "
        "(snapshot_id,ticker,provider,requested_source_session_date,first_available_date,"
        "last_available_date,source_row_count,source_checksum_sha256,created_at_utc) VALUES "
    )
    for offset in range(0, len(provider_lineage), 250):
        batch = provider_lineage[offset:offset + 250]
        placeholders = ",".join("(?,?,?,?,?,?,?,?,?)" for _ in batch)
        arguments = []
        for row in batch:
            arguments.extend([snapshot_id] + row + [created_at])
        post_statements(session, endpoint, token, [(lineage_prefix + placeholders, arguments)])
    target_columns = [target for _, target in COLUMN_MAP]
    row_placeholders = "(" + ",".join("?" for _ in range(len(target_columns) + 1)) + ")"
    prefix = (
        "INSERT OR IGNORE INTO market_daily_features "
        f"(snapshot_id,{','.join(target_columns)}) VALUES "
    )
    batch_args = []
    batch_rows = 0
    for position, row in enumerate(frame.itertuples(index=False, name=None), start=1):
        source = dict(zip(frame.columns, row))
        batch_args.extend([snapshot_id] + [clean(source[name]) for name, _ in COLUMN_MAP])
        batch_rows += 1
        if batch_rows == 500:
            post_statements(
                session, endpoint, token,
                [(prefix + ",".join(row_placeholders for _ in range(batch_rows)), batch_args)],
            )
            batch_args, batch_rows = [], 0
        if position % 10000 == 0:
            print(f"staged_rebuilt_rows={position}/{expected_rows}", flush=True)
    if batch_rows:
        post_statements(
            session, endpoint, token,
            [(prefix + ",".join(row_placeholders for _ in range(batch_rows)), batch_args)],
        )
    result = db.execute(
        "SELECT COUNT(*) AS n,COUNT(DISTINCT ticker) AS t,MIN(date),MAX(date) "
        "FROM market_daily_features WHERE snapshot_id=?",
        [snapshot_id],
    ).rows[0]
    if int(result[0]) != expected_rows or int(result[1]) != expected_tickers:
        raise RuntimeError("Rebuilt snapshot counts do not match the in-memory source.")
    print(
        f"REBUILT_STAGED_NOT_VALIDATED snapshot_id={snapshot_id} rows={result[0]} "
        f"tickers={result[1]} first_date={result[2]} latest_date={result[3]} checksum={checksum}"
    )
    return snapshot_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--universe-snapshot", required=True)
    parser.add_argument("--required-tickers", nargs="+", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--tiingo-token-file")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--compare-lineage-snapshot",
        help="Read-only comparison against provider lineage stored for a snapshot.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, validate, and calculate the complete snapshot without Turso writes.",
    )
    args = parser.parse_args()
    source_session = date.fromisoformat(args.source_session)
    if not 1 <= args.workers <= 12:
        raise SystemExit("Worker count must be between 1 and 12.")
    root = Path(__file__).resolve().parents[1]
    load_dotenv(args.env_file or (root / ".env"))
    raw_url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    tiingo_api_key = resolve_tiingo_api_key(args.tiingo_token_file)
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    # The guarded wrapper proves Turso reachability with a 120-second timeout.
    # Keep the writer on the same contract: a cold replica/clone can require
    # more than 30 seconds for its first pinned-universe read even though the
    # database is reachable and the identical preflight succeeds.
    db = TursoReadPipeline(endpoint, token, timeout_seconds=TURSO_TIMEOUT_SECONDS)
    stock_universe = db.execute(
        "SELECT ticker,MAX(sector) AS sector FROM market_daily_features "
        "WHERE snapshot_id=? GROUP BY ticker ORDER BY ticker",
        [args.universe_snapshot],
    )
    etf_scorecard_universe = db.execute(
        "SELECT DISTINCT ticker FROM etf_scorecards_master "
        "WHERE persona LIKE 'ETF_%' AND date=(SELECT MAX(date) "
        "FROM etf_scorecards_master WHERE persona LIKE 'ETF_%') ORDER BY ticker",
        [],
    )
    etf_latest_ledgers = db.execute(
        """SELECT cl.holdings_json FROM capital_ledgers cl
        JOIN (SELECT persona,MAX(date) AS max_date FROM capital_ledgers
              WHERE persona LIKE 'ETF_%' GROUP BY persona) latest
          ON latest.persona=cl.persona AND latest.max_date=cl.date
        ORDER BY cl.persona""",
        [],
    )
    etf_pending = db.execute(
        "SELECT target_holdings_json FROM pending_orders "
        "WHERE persona LIKE 'ETF_%' ORDER BY persona",
        [],
    )
    try:
        sector_by_ticker = build_controlled_universe(
            stock_universe.rows,
            etf_scorecard_universe.rows,
            etf_latest_ledgers.rows,
            etf_pending.rows,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    lifecycle = db.execute(
        "SELECT ticker,event_type,effective_date,successor_ticker,sector "
        "FROM market_symbol_lifecycle_events WHERE effective_date<=? "
        "ORDER BY effective_date,event_id",
        [source_session.isoformat()],
    )
    try:
        sector_by_ticker, lifecycle_replacements = apply_symbol_lifecycle(
            sector_by_ticker, lifecycle.rows, source_session=source_session
        )
        registry_versions = db.execute(
            "SELECT registry_id FROM market_instrument_registry_versions "
            "WHERE status='APPROVED' ORDER BY evidence_as_of_date DESC,registry_id",
            [],
        )
        if len(registry_versions.rows) != 1:
            raise ValueError("Exactly one approved instrument registry is required.")
        registry_id = str(registry_versions.rows[0][0])
        registry = db.execute(
            "SELECT registry_id,ticker,asset_class,sector,usage,minimum_history_rows "
            "FROM market_instrument_registry WHERE registry_id=? ORDER BY ticker",
            [registry_id],
        )
        sector_by_ticker = apply_approved_instrument_registry(
            sector_by_ticker, registry_versions.rows, registry.rows
        )
        required_tickers = resolve_lifecycle_tickers(
            args.required_tickers, lifecycle_replacements
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not sector_by_ticker:
        raise SystemExit("Recovery universe is empty.")
    print(
        f"recovery_universe_tickers={len(sector_by_ticker)} "
        f"lifecycle_replacements={lifecycle_replacements} registry_id={registry_id}",
        flush=True,
    )

    successes = {}
    providers = {}
    failures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_ticker, ticker, source_session, "2021-08-01", tiingo_api_key
            ): ticker
            for ticker in sector_by_ticker
        }
        for count, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            ticker, raw, provider, error = future.result()
            if raw is None:
                failures[ticker] = error
            else:
                successes[ticker] = raw
                providers[ticker] = str(provider)
            if count % 25 == 0:
                print(
                    f"fetched={count}/{len(futures)} accepted={len(successes)} failed={len(failures)}",
                    flush=True,
                )
    print(f"accepted_tickers={len(successes)} rejected_tickers={len(failures)}", flush=True)
    if failures:
        print("rejected_ticker_sample=" + repr(sorted(failures.items())[:20]), flush=True)
    expected_sessions = recent_nyse_sessions(source_session, rows=130)

    def fetch_tiingo_replacement(
        ticker: str,
    ) -> tuple[pd.DataFrame | None, str | None, str | None]:
        _, bars, provider, error = fetch_validated_daily_bars(
            ticker,
            source_session,
            "2021-08-01",
            tiingo_api_key=tiingo_api_key,
            yahoo_attempts=0,
        )
        return bars, provider, error

    successes, providers, gap_failures, gap_replacements = repair_recent_session_gaps(
        successes,
        providers,
        expected_sessions,
        fetch_tiingo_replacement,
    )
    failures.update(gap_failures)
    print(
        f"session_gap_replacements={gap_replacements} "
        f"session_gap_failures={sorted(gap_failures)}",
        flush=True,
    )
    try:
        require_complete_rebuild(successes, failures, required_tickers)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    feature_frames = [
        calculate_features(raw, ticker=ticker, sector=sector_by_ticker[ticker])
        for ticker, raw in sorted(successes.items())
    ]
    combined = pd.concat(feature_frames, ignore_index=True)
    _, vix, vix_provider, vix_error = fetch_ticker(
        "^VIX", source_session, "2021-08-01", tiingo_api_key
    )
    _, tnx, tnx_provider, tnx_error = fetch_ticker(
        "^TNX", source_session, "2021-08-01", tiingo_api_key
    )
    if vix is None or tnx is None:
        raise SystemExit(f"Macro ingestion failed: VIX={vix_error}; TNX={tnx_error}")
    final = normalize_ohlc_envelope(
        merge_cross_market_features(combined, vix, tnx)
    )
    latest = final[final["Date"].dt.date == source_session]
    if latest.empty or latest[["VIX_Close", "TNX_Close"]].isna().any().any():
        raise SystemExit("Latest rebuilt session has missing macro features.")
    provider_counts = Counter(providers.values())
    provider_counts.update([str(vix_provider), str(tnx_provider)])
    fallback_tickers = sorted(
        ticker for ticker, provider in providers.items() if provider == "TIINGO_EOD"
    )
    provider_label = "+".join(sorted(provider_counts))
    lineage_sources = dict(successes)
    lineage_sources.update({"^VIX": vix, "^TNX": tnx})
    lineage_providers = dict(providers)
    lineage_providers.update({"^VIX": str(vix_provider), "^TNX": str(tnx_provider)})
    provider_lineage = build_provider_lineage(
        lineage_sources, lineage_providers, source_session=source_session
    )
    lineage_comparison = None
    if args.compare_lineage_snapshot:
        stored_lineage = db.execute(
            "SELECT ticker,provider,requested_source_session_date,first_available_date,"
            "last_available_date,source_row_count,source_checksum_sha256 "
            "FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker",
            [args.compare_lineage_snapshot],
        )
        lineage_comparison = compare_provider_lineage(
            provider_lineage, stored_lineage.rows
        )
    if args.dry_run:
        first_content_checksum = content_checksum(final)
        second_content_checksum = content_checksum(final)
        print(json.dumps({
            "status": "DRY_RUN_PASS_NO_WRITES",
            "source_session": source_session.isoformat(),
            "row_count": len(final),
            "ticker_count": int(final["Ticker"].nunique()),
            "first_date": str(final["Date"].min().date()),
            "last_date": str(final["Date"].max().date()),
            "content_checksum_sha256": first_content_checksum,
            "content_checksum_repeat_sha256": second_content_checksum,
            "content_checksum_stable_in_process": (
                first_content_checksum == second_content_checksum
            ),
            "provider_counts": dict(sorted(provider_counts.items())),
            "fallback_tickers": fallback_tickers,
            "lifecycle_replacements": lifecycle_replacements,
            "provider_lineage_rows": len(provider_lineage),
            "provider_lineage_checksum_sha256": provider_lineage_checksum(provider_lineage),
            "lineage_comparison": lineage_comparison,
        }, indent=2, sort_keys=True), flush=True)
        return 0
    stage_frame(
        db,
        endpoint,
        token,
        final,
        source_session=source_session,
        provider=provider_label,
        provider_lineage=provider_lineage,
        notes=(
            f"Fresh full-history rebuild. Accepted {len(successes)} tickers; rejected "
            f"{len(failures)} stale/invalid tickers. Recovery universe sectors came from "
            f"{args.universe_snapshot}. Provider counts={dict(provider_counts)}; "
            f"Tiingo fallback tickers={fallback_tickers}. Independent QA required before validation."
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
