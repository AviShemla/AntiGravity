"""Leakage-safe stock-model matrices built only from a validated DB frame."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd

from model_input_reader import StockUniverseEntry
from model_lineage import LineageError


@dataclass(frozen=True)
class StockModelDataset:
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


def _finite_frame(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    values = frame[list(columns)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise LineageError(f"{label} contains missing or non-finite values.")


def build_stock_model_dataset(
    market_frame: pd.DataFrame,
    universe_entry: StockUniverseEntry,
    *,
    source_session_date: date,
    prediction_date: date,
    lookback_sessions: int = 30,
    research_features: pd.DataFrame | None = None,
    required_research_features: Sequence[str] = (),
) -> StockModelDataset:
    """Build train/predict matrices whose every predictor predates its target.

    For a training target on session ``t``, technical features use ``t-1``.
    Configured causal-chain feature ``d`` uses the configured lag ticker's
    return and 30-session volume ratio at ``t-d``.  The prediction row uses the
    completed source session and has no fabricated outcome.
    """
    if prediction_date <= source_session_date:
        raise LineageError("Prediction date must follow the completed source session.")
    if lookback_sessions < 30:
        raise LineageError("Research lookback must contain at least 30 completed sessions.")
    required = {"Ticker", "Date", "Daily_Return_%", "Volume", "Close", *TECHNICAL_COLUMNS}
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

    required_tickers = {universe_entry.ticker, *universe_entry.lag_tickers}
    available_tickers = set(frame["Ticker"].unique())
    absent = sorted(required_tickers - available_tickers)
    if absent:
        raise LineageError(f"Causal-chain tickers are absent from the snapshot: {absent}.")

    returns = frame.pivot(index="Date", columns="Ticker", values="Daily_Return_%").sort_index()
    volumes = frame.pivot(index="Date", columns="Ticker", values="Volume").sort_index()
    target_rows = frame[frame["Ticker"] == universe_entry.ticker].set_index("Date").sort_index()
    if source_ts not in target_rows.index:
        raise LineageError("Target ticker has no row for the completed source session.")

    features: dict[str, pd.Series] = {}
    for lag_ticker, lag in zip(universe_entry.lag_tickers, universe_entry.lag_sessions):
        volume_mean = volumes[lag_ticker].rolling(30, min_periods=30).mean()
        volume_ratio = volumes[lag_ticker] / volume_mean
        name = f"{lag_ticker}_return_x_volume_ratio_lag{lag}"
        features[name] = (returns[lag_ticker] * volume_ratio).shift(lag)

    technical = target_rows[list(TECHNICAL_COLUMNS)].copy()
    technical["DI_Spread"] = technical["Plus_DI_14d"] - technical["Minus_DI_14d"]
    technical["ATR_Ratio"] = technical["ATR_14d"] / target_rows["Close"] if "Close" in target_rows else np.nan
    technical = technical.drop(columns=["Plus_DI_14d", "Minus_DI_14d", "ATR_14d"])
    for column in technical.columns:
        features[f"{universe_entry.ticker}_{column}_lag1"] = technical[column].shift(1)

    if required_research_features and research_features is None:
        raise LineageError("Required research features were not supplied.")
    if research_features is not None:
        research = research_features.copy()
        if "Date" in research.columns:
            research["Date"] = pd.to_datetime(research["Date"], errors="coerce")
            research = research.set_index("Date")
        research.index = pd.to_datetime(research.index, errors="coerce")
        if research.index.isna().any():
            raise LineageError("Research feature frame contains invalid dates.")
        if research.index.duplicated().any():
            raise LineageError("Research feature frame contains duplicate sessions.")
        if research.index.max() > source_ts:
            raise LineageError("Research feature frame contains observations after the source session.")
        missing_research = sorted(set(required_research_features) - set(research.columns))
        if missing_research:
            raise LineageError(f"Required research features are missing: {missing_research}.")
        selected_research = (
            list(required_research_features)
            if required_research_features
            else list(research.columns)
        )
        for column in selected_research:
            numeric = pd.to_numeric(research[column], errors="coerce")
            features[f"research_{column}_lag1"] = numeric.reindex(returns.index).shift(1)

    feature_frame = pd.DataFrame(features).sort_index()
    target_return = returns[universe_entry.ticker].rename("target_return")
    combined = feature_frame.join(target_return, how="left")
    completed = combined.loc[:source_ts].dropna()
    if len(completed) < lookback_sessions:
        raise LineageError(
            f"Only {len(completed)} complete model rows; requested {lookback_sessions}."
        )
    training = completed.tail(lookback_sessions)

    # A prediction for the next session uses exactly the source-session state.
    prediction_raw: dict[str, float] = {}
    for lag_ticker, lag in zip(universe_entry.lag_tickers, universe_entry.lag_sessions):
        history_date_position = returns.index.get_loc(source_ts) - (lag - 1)
        if history_date_position < 29:
            raise LineageError("Insufficient history for prediction volume ratios.")
        observed_date = returns.index[history_date_position]
        volume_window = volumes[lag_ticker].iloc[history_date_position - 29:history_date_position + 1]
        if volume_window.isna().any() or float(volume_window.mean()) <= 0:
            raise LineageError(f"Invalid prediction volume history for {lag_ticker}.")
        name = f"{lag_ticker}_return_x_volume_ratio_lag{lag}"
        prediction_raw[name] = float(returns.at[observed_date, lag_ticker]) * (
            float(volumes.at[observed_date, lag_ticker]) / float(volume_window.mean())
        )
    source_technical = technical.loc[source_ts]
    for column in technical.columns:
        prediction_raw[f"{universe_entry.ticker}_{column}_lag1"] = float(source_technical[column])
    if research_features is not None:
        if source_ts not in research.index:
            raise LineageError("Research feature frame has no completed source-session row.")
        for column in selected_research:
            prediction_raw[f"research_{column}_lag1"] = float(research.at[source_ts, column])

    feature_names = tuple(feature_frame.columns)
    prediction_values = np.asarray([prediction_raw[name] for name in feature_names], dtype=float)
    _finite_frame(training, feature_names, "Training features")
    if not np.isfinite(prediction_values).all():
        raise LineageError("Prediction features contain missing or non-finite values.")

    raw_x = training[list(feature_names)].to_numpy(dtype=float)
    mean = raw_x.mean(axis=0)
    scale = raw_x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    x_train = (raw_x - mean) / scale
    x_predict = ((prediction_values - mean) / scale).reshape(1, -1)
    y_return = training["target_return"].to_numpy(dtype=float)
    y_direction = (y_return > 0).astype(int)
    return StockModelDataset(
        ticker=universe_entry.ticker,
        source_session_date=source_session_date,
        prediction_date=prediction_date,
        feature_names=feature_names,
        training_dates=tuple(ts.date() for ts in training.index),
        x_train=x_train,
        y_direction=y_direction,
        y_return_pp=y_return,
        x_predict=x_predict,
        train_mean=mean,
        train_scale=scale,
    )
