"""Point-in-time research features derived from governed market snapshots.

The builders in this module are deliberately side-effect free.  They neither
write Turso evidence nor activate a model.  A feature dated ``t`` may use only
market rows dated at or before ``t``; the stock-model dataset is responsible
for applying the final one-session predictor lag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Iterable

import numpy as np
import pandas as pd

from model_lineage import LineageError
from predictive_screener import TickerEvaluation


@dataclass(frozen=True)
class FeatureAvailability:
    feature_name: str
    available: bool
    reason: str


@dataclass(frozen=True)
class ResearchFeatureSet:
    frame: pd.DataFrame
    availability: tuple[FeatureAvailability, ...]


@dataclass(frozen=True)
class PredictiveEdgeStability:
    target_ticker: str
    driver_ticker: str
    lag_sessions: int
    selected_folds: int
    evaluated_folds: int
    selection_frequency: float


@dataclass(frozen=True)
class PredictiveNodeStability:
    ticker: str
    stable_outgoing_weight: float
    stable_incoming_weight: float


@dataclass(frozen=True)
class PredictiveNetworkSummary:
    edges: tuple[PredictiveEdgeStability, ...]
    nodes: tuple[PredictiveNodeStability, ...]


def _column(frame: pd.DataFrame, *names: str) -> str | None:
    lookup = {str(name).casefold(): str(name) for name in frame.columns}
    for name in names:
        if name.casefold() in lookup:
            return lookup[name.casefold()]
    return None


def _validated_market_frame(
    market_frame: pd.DataFrame, *, source_session_date: date
) -> tuple[pd.DataFrame, dict[str, str]]:
    aliases = {
        "ticker": _column(market_frame, "Ticker", "ticker"),
        "date": _column(market_frame, "Date", "date"),
        "return": _column(market_frame, "Daily_Return_%", "daily_return_pct"),
        "volume": _column(market_frame, "Volume", "volume"),
        "close": _column(market_frame, "Close", "close_price"),
        "sector": _column(market_frame, "Sector", "sector"),
        "vix": _column(market_frame, "VIX_Close", "vix_close"),
    }
    required = ("ticker", "date", "return", "volume", "close", "vix")
    missing = [name for name in required if aliases[name] is None]
    if missing:
        raise LineageError(f"Research feature input is missing columns: {missing}.")
    clean = market_frame.copy()
    clean[aliases["ticker"]] = clean[aliases["ticker"]].astype(str).str.upper()
    clean[aliases["date"]] = pd.to_datetime(clean[aliases["date"]], errors="coerce")
    if clean[aliases["date"]].isna().any():
        raise LineageError("Research feature input contains invalid dates.")
    if clean[aliases["date"]].max() > pd.Timestamp(source_session_date):
        raise LineageError("Research feature input contains a future observation.")
    if clean.duplicated([aliases["ticker"], aliases["date"]]).any():
        raise LineageError("Research feature input contains duplicate ticker/session keys.")
    for logical in ("return", "volume", "close", "vix"):
        clean[aliases[logical]] = pd.to_numeric(clean[aliases[logical]], errors="coerce")
    return clean, {key: value for key, value in aliases.items() if value is not None}


def build_market_regime_features(
    market_frame: pd.DataFrame,
    *,
    source_session_date: date,
    benchmark_ticker: str = "SPY",
    moving_average_sessions: int = 20,
    realized_volatility_sessions: int = 20,
) -> ResearchFeatureSet:
    """Build auditable breadth, dispersion, and available volatility features.

    Proper volatility-term-structure features are emitted only when their
    explicit source columns exist.  VIX is never fabricated into VIX9D/VIX3M,
    VVIX, or SKEW.
    """
    if moving_average_sessions < 2 or realized_volatility_sessions < 2:
        raise LineageError("Research feature windows must contain at least two sessions.")
    clean, columns = _validated_market_frame(
        market_frame, source_session_date=source_session_date
    )
    ticker_col, date_col = columns["ticker"], columns["date"]
    return_col, volume_col, close_col = (
        columns["return"], columns["volume"], columns["close"]
    )
    returns = clean.pivot(index=date_col, columns=ticker_col, values=return_col).sort_index()
    volumes = clean.pivot(index=date_col, columns=ticker_col, values=volume_col).sort_index()
    closes = clean.pivot(index=date_col, columns=ticker_col, values=close_col).sort_index()
    if benchmark_ticker.upper() not in returns.columns:
        raise LineageError(f"Benchmark ticker {benchmark_ticker!r} is absent from the snapshot.")

    positive = returns.gt(0).where(returns.notna())
    up_volume = volumes.where(positive).sum(axis=1, min_count=1)
    total_volume = volumes.where(volumes.ge(0)).sum(axis=1, min_count=1)
    moving_average = closes.rolling(
        moving_average_sessions, min_periods=moving_average_sessions
    ).mean()
    above_average = closes.gt(moving_average).where(closes.notna() & moving_average.notna())

    features = pd.DataFrame(index=returns.index)
    features["breadth_advance_fraction"] = positive.mean(axis=1)
    features["breadth_up_volume_fraction"] = up_volume / total_volume.replace(0, np.nan)
    features[f"breadth_above_sma{moving_average_sessions}_fraction"] = above_average.mean(axis=1)
    features["breadth_cross_sectional_return_dispersion"] = returns.std(axis=1, ddof=1)

    sector_col = columns.get("sector")
    availability: list[FeatureAvailability] = []
    if sector_col is not None and clean[sector_col].notna().any():
        sector_returns = clean.pivot_table(
            index=date_col, columns=sector_col, values=return_col, aggfunc="mean"
        ).sort_index()
        features["breadth_positive_sector_fraction"] = (
            sector_returns.gt(0).where(sector_returns.notna()).mean(axis=1)
        )
        availability.append(FeatureAvailability(
            "breadth_positive_sector_fraction", True, "Derived from point-in-time sector returns."
        ))
    else:
        availability.append(FeatureAvailability(
            "breadth_positive_sector_fraction", False, "No point-in-time sector field is available."
        ))

    vix_by_date = clean.groupby(date_col)[columns["vix"]]
    vix_spread = vix_by_date.max() - vix_by_date.min()
    if (vix_spread.dropna().abs() > 1e-9).any():
        raise LineageError("VIX values disagree across tickers for the same session.")
    vix = vix_by_date.first().reindex(features.index)
    features["volatility_vix_change_1d"] = vix.diff()
    features["volatility_vix_acceleration_1d"] = vix.diff().diff()
    features["volatility_vix_change_5d"] = vix.diff(5)
    benchmark_return = returns[benchmark_ticker.upper()]
    realized = benchmark_return.rolling(
        realized_volatility_sessions, min_periods=realized_volatility_sessions
    ).std(ddof=1) * sqrt(252.0)
    features[f"volatility_{benchmark_ticker.upper()}_realized_{realized_volatility_sessions}d"] = realized
    features[f"volatility_vix_minus_{benchmark_ticker.upper()}_realized_{realized_volatility_sessions}d"] = vix - realized

    optional_sources = {
        "VIX9D_Close": ("VIX9D_Close", "vix9d_close"),
        "VIX3M_Close": ("VIX3M_Close", "vix3m_close"),
        "VVIX_Close": ("VVIX_Close", "vvix_close"),
        "SKEW_Close": ("SKEW_Close", "skew_close"),
    }
    optional_series: dict[str, pd.Series] = {}
    for logical, names in optional_sources.items():
        raw_column = _column(clean, *names)
        if raw_column is None:
            availability.append(FeatureAvailability(
                logical, False, "Source series is not present in the governed market snapshot."
            ))
            continue
        numeric = pd.to_numeric(clean[raw_column], errors="coerce")
        series = numeric.groupby(clean[date_col]).first().reindex(features.index)
        optional_series[logical] = series
        availability.append(FeatureAvailability(
            logical, True, "Source series is present in the governed market snapshot."
        ))
    if "VIX9D_Close" in optional_series:
        features["volatility_vix9d_to_vix_ratio"] = optional_series["VIX9D_Close"] / vix
    if "VIX3M_Close" in optional_series:
        features["volatility_vix_to_vix3m_ratio"] = vix / optional_series["VIX3M_Close"]
    if "VVIX_Close" in optional_series:
        features["volatility_vvix_close"] = optional_series["VVIX_Close"]
    if "SKEW_Close" in optional_series:
        features["volatility_skew_close"] = optional_series["SKEW_Close"]

    features = features.apply(pd.to_numeric, errors="coerce").astype(float)
    if features.index.max() > pd.Timestamp(source_session_date):
        raise LineageError("Derived feature frame extends beyond the source session.")
    availability.extend(
        FeatureAvailability(name, True, "Derived from the governed market snapshot.")
        for name in features.columns
        if not any(item.feature_name == name for item in availability)
    )
    return ResearchFeatureSet(
        frame=features.sort_index(),
        availability=tuple(sorted(availability, key=lambda item: item.feature_name)),
    )


def summarize_predictive_network(
    evaluations: Iterable[TickerEvaluation],
) -> PredictiveNetworkSummary:
    """Summarize fold-selection stability without claiming causal identification."""
    counts: dict[tuple[str, str, int], int] = {}
    fold_counts: dict[str, int] = {}
    for evaluation in evaluations:
        target = evaluation.ticker.strip().upper()
        if not evaluation.folds:
            raise LineageError(f"Predictive network evaluation for {target} has no folds.")
        fold_counts[target] = len(evaluation.folds)
        for fold in evaluation.folds:
            for driver, lag in zip(fold.spec.lag_tickers, fold.spec.lag_sessions):
                key = (target, driver.strip().upper(), int(lag))
                counts[key] = counts.get(key, 0) + 1
    edges = tuple(
        PredictiveEdgeStability(
            target_ticker=target,
            driver_ticker=driver,
            lag_sessions=lag,
            selected_folds=selected,
            evaluated_folds=fold_counts[target],
            selection_frequency=selected / fold_counts[target],
        )
        for (target, driver, lag), selected in sorted(counts.items())
    )
    tickers = sorted({edge.target_ticker for edge in edges} | {edge.driver_ticker for edge in edges})
    nodes = tuple(
        PredictiveNodeStability(
            ticker=ticker,
            stable_outgoing_weight=sum(
                edge.selection_frequency for edge in edges if edge.driver_ticker == ticker
            ),
            stable_incoming_weight=sum(
                edge.selection_frequency for edge in edges if edge.target_ticker == ticker
            ),
        )
        for ticker in tickers
    )
    return PredictiveNetworkSummary(edges=edges, nodes=nodes)
