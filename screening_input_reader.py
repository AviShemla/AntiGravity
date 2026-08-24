"""Narrow Turso reader and matrix builder for predictive screening."""

from __future__ import annotations

import pandas as pd

from model_input_reader import InputSnapshot, verify_snapshot_counts
from model_lineage import LineageError
from feature_freshness import bounded_forward_fill


SCREENING_COLUMNS = [
    "ticker", "date", "daily_return_pct", "daily_stdev", "rsi_14d",
    "atr_14d", "plus_di_14d", "minus_di_14d", "adx_14d", "ras_signal",
    "analyst_consensus", "analyst_upside_pct", "sector_momentum_score",
    "sector_regime", "vix_close", "market_fear_level", "tnx_trend_5d",
]


def load_screening_frame(db, snapshot: InputSnapshot, *, page_size: int = 5000) -> pd.DataFrame:
    if snapshot.dataset_type != "MARKET_FEATURES":
        raise LineageError("Screening input requires a MARKET_FEATURES snapshot.")
    if not 1 <= page_size <= 5000:
        raise LineageError("Screening page size must be between 1 and 5000.")
    verify_snapshot_counts(db, snapshot, table_name="market_daily_features")
    rows: list[object] = []
    last_ticker = ""
    last_date = ""
    while True:
        result = db.execute(
            f"SELECT {','.join(SCREENING_COLUMNS)} FROM market_daily_features "
            "WHERE snapshot_id=? AND (ticker>? OR (ticker=? AND date>?)) "
            "ORDER BY ticker,date LIMIT ?",
            [snapshot.snapshot_id, last_ticker, last_ticker, last_date, page_size],
        )
        if not result.rows:
            break
        rows.extend(result.rows)
        ticker_index = result.columns.index("ticker")
        date_index = result.columns.index("date")
        last_ticker = str(result.rows[-1][ticker_index])
        last_date = str(result.rows[-1][date_index])
        if len(result.rows) < page_size:
            break
    if len(rows) != snapshot.expected_row_count:
        raise LineageError("Screening row count does not match validated snapshot metadata.")
    frame = pd.DataFrame(rows, columns=SCREENING_COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any() or frame.duplicated(["ticker", "date"]).any():
        raise LineageError("Screening input contains invalid or duplicate keys.")
    if frame["ticker"].nunique() != snapshot.expected_ticker_count:
        raise LineageError("Screening ticker count does not match validated snapshot metadata.")
    frame.attrs.update({
        "snapshot_id": snapshot.snapshot_id,
        "source_session_date": snapshot.source_session_date.isoformat(),
        "available_at_utc": snapshot.available_at_utc.isoformat(),
    })
    return frame


def build_return_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    returns = frame.pivot(index="date", columns="ticker", values="daily_return_pct").sort_index()
    if returns.empty or returns.columns.duplicated().any():
        raise LineageError("Screening return matrix is empty or has duplicate tickers.")
    return returns


def build_target_features(
    frame: pd.DataFrame,
    ticker: str,
    *,
    return_index: pd.Index,
) -> pd.DataFrame:
    ticker = ticker.strip().upper()
    if ticker not in set(frame["ticker"].astype(str)):
        raise LineageError(f"Ticker {ticker!r} is absent from screening input.")
    target = frame.loc[frame["ticker"] == ticker].set_index("date").sort_index()
    feature_map = {
        "daily_stdev": f"{ticker}_STDEV",
        "rsi_14d": f"{ticker}_RSI",
        "atr_14d": f"{ticker}_ATR",
        "plus_di_14d": f"{ticker}_PLUS_DI",
        "minus_di_14d": f"{ticker}_MINUS_DI",
        "adx_14d": f"{ticker}_ADX",
        "analyst_upside_pct": f"{ticker}_UPSIDE",
        "sector_momentum_score": f"{ticker}_SEC_MOM",
        "vix_close": "VIX_CLOSE",
        "tnx_trend_5d": "TNX_TREND_5D",
    }
    features = target[list(feature_map)].rename(columns=feature_map)
    features[f"{ticker}_RAS"] = target["ras_signal"].map(
        {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}
    )
    features[f"{ticker}_ANALYST"] = target["analyst_consensus"].map(
        {"Strong Buy": 2.0, "Buy": 1.0, "Hold": 0.0, "Sell": -1.0, "Strong Sell": -2.0}
    )
    features[f"{ticker}_SEC_REG"] = target["sector_regime"].map(
        {"BULL_REGIME": 1.0, "BEAR_REGIME": -1.0}
    )
    features["MARKET_FEAR"] = target["market_fear_level"].map(
        {"Complacency / Calm": 0.0, "High Volatility": 1.0}
    )
    features = bounded_forward_fill(
        features.replace([float("inf"), float("-inf")], pd.NA)
    )
    return features.reindex(return_index)


def build_screening_matrices(frame: pd.DataFrame, ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = build_return_matrix(frame)
    return returns, build_target_features(frame, ticker, return_index=returns.index)
