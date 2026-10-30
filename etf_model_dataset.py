"""Leakage-safe ETF-model matrices built only from a validated DB frame."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from model_lineage import LineageError


@dataclass(frozen=True)
class ETFModelDataset:
    ticker: str
    source_session_date: date
    prediction_date: date
    feature_names: tuple[str, ...]
    training_dates: tuple[date, ...]
    x_train: np.ndarray
    y_direction: np.ndarray
    y_return_pp: np.ndarray
    x_predict: np.ndarray
    train_mean: np.ndarray
    train_scale: np.ndarray


TECHNICAL_COLUMNS = (
    "RSI_14d", "ADX_14d", "Plus_DI_14d", "Minus_DI_14d",
    "ATR_14d", "Sector_Momentum_Score", "VIX_Close", "TNX_Trend_5d",
)


def build_etf_model_dataset(
    market_frame: pd.DataFrame,
    ticker: str,
    *,
    source_session_date: date,
    prediction_date: date,
    lookback_sessions: int = 30,
) -> ETFModelDataset:
    """Build an ETF history model where all predictors predate each target.

    For training target session ``t``, ETF return, volume and technical inputs
    use ``t-1``.  The prediction row uses the completed source-session state.
    The caller must supply a frame read from a validated Turso snapshot.
    """
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise LineageError("ETF ticker is required.")
    if prediction_date <= source_session_date:
        raise LineageError("Prediction date must follow the completed source session.")
    if lookback_sessions < 30:
        raise LineageError("Research lookback must contain at least 30 completed sessions.")
    required = {
        "Ticker", "Date", "Daily_Return_%", "Volume", "Close", *TECHNICAL_COLUMNS,
    }
    missing = sorted(required - set(market_frame.columns))
    if missing:
        raise LineageError(f"Market snapshot is missing required columns: {missing}.")

    frame = market_frame.copy()
    frame["Ticker"] = frame["Ticker"].astype(str).str.upper()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    if frame["Date"].isna().any():
        raise LineageError("Market snapshot contains invalid dates.")
    source_ts = pd.Timestamp(source_session_date)
    if frame["Date"].max() > source_ts:
        raise LineageError("Market frame contains observations after the declared source session.")
    if frame.duplicated(["Ticker", "Date"]).any():
        raise LineageError("Market frame contains duplicate ticker/session keys.")

    target = frame[frame["Ticker"] == normalized_ticker].set_index("Date").sort_index()
    if target.empty:
        raise LineageError(f"ETF {normalized_ticker} is absent from the snapshot.")
    if source_ts not in target.index:
        raise LineageError("ETF has no row for the completed source session.")

    volume_mean = target["Volume"].rolling(30, min_periods=30).mean()
    raw_features = pd.DataFrame(index=target.index)
    raw_features[f"{normalized_ticker}_Return_lag1"] = target["Daily_Return_%"].shift(1)
    raw_features[f"{normalized_ticker}_Volume_Ratio_lag1"] = (
        target["Volume"] / volume_mean
    ).shift(1)
    raw_features[f"{normalized_ticker}_RSI_lag1"] = target["RSI_14d"].shift(1)
    raw_features[f"{normalized_ticker}_ADX_lag1"] = target["ADX_14d"].shift(1)
    raw_features[f"{normalized_ticker}_DI_Spread_lag1"] = (
        target["Plus_DI_14d"] - target["Minus_DI_14d"]
    ).shift(1)
    raw_features[f"{normalized_ticker}_ATR_Ratio_lag1"] = (
        target["ATR_14d"] / target["Close"]
    ).shift(1)
    raw_features[f"{normalized_ticker}_Sector_Momentum_lag1"] = target[
        "Sector_Momentum_Score"
    ].shift(1)
    raw_features["VIX_Close_lag1"] = target["VIX_Close"].shift(1)
    raw_features["TNX_Trend_5d_lag1"] = target["TNX_Trend_5d"].shift(1)

    combined = raw_features.join(target["Daily_Return_%"].rename("target_return"))
    completed = combined.loc[:source_ts].dropna()
    if len(completed) < lookback_sessions:
        raise LineageError(
            f"Only {len(completed)} complete ETF model rows; requested {lookback_sessions}."
        )
    training = completed.tail(lookback_sessions)

    source = target.loc[source_ts]
    source_volume_window = target.loc[:source_ts, "Volume"].tail(30)
    if len(source_volume_window) != 30 or source_volume_window.isna().any():
        raise LineageError("ETF prediction volume history is incomplete.")
    volume_average = float(source_volume_window.mean())
    if volume_average <= 0.0:
        raise LineageError("ETF prediction volume history is invalid.")
    prediction = np.asarray(
        [
            float(source["Daily_Return_%"]),
            float(source["Volume"]) / volume_average,
            float(source["RSI_14d"]),
            float(source["ADX_14d"]),
            float(source["Plus_DI_14d"] - source["Minus_DI_14d"]),
            float(source["ATR_14d"] / source["Close"]),
            float(source["Sector_Momentum_Score"]),
            float(source["VIX_Close"]),
            float(source["TNX_Trend_5d"]),
        ],
        dtype=float,
    )
    feature_names = tuple(raw_features.columns)
    raw_x = training[list(feature_names)].to_numpy(dtype=float)
    y_return = training["target_return"].to_numpy(dtype=float)
    values = (raw_x, prediction, y_return)
    if not all(np.isfinite(value).all() for value in values):
        raise LineageError("ETF model inputs contain missing or non-finite values.")

    mean = raw_x.mean(axis=0)
    scale = raw_x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    return ETFModelDataset(
        ticker=normalized_ticker,
        source_session_date=source_session_date,
        prediction_date=prediction_date,
        feature_names=feature_names,
        training_dates=tuple(ts.date() for ts in training.index),
        x_train=(raw_x - mean) / scale,
        y_direction=(y_return > 0).astype(int),
        y_return_pp=y_return,
        x_predict=((prediction - mean) / scale).reshape(1, -1),
        train_mean=mean,
        train_scale=scale,
    )
