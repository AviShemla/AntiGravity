"""Canonical frozen ETF-research orchestration.

The runner is DB-read-only and production-inert. It consumes one validated
Turso market snapshot, one validated ETF constituent snapshot, and one complete
frozen stock-research posterior lineage. It returns raw Bayesian evidence plus
an explicitly NO_TRADE scorecard. It never persists, promotes, orders, emails,
deploys, or controls services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from etf_model_dataset import build_etf_model_dataset
from etf_model_preflight import ETFModelPreflightEvidence, build_etf_model_preflight
from etf_posterior_bridge import (
    FrozenETFResearchEvidence,
    build_frozen_etf_research_evidence,
)
from etf_pymc_core import ETFPosteriorEvidence, fit_etf_posterior
from model_lineage import LineageError
from stock_model_input_reader import load_stock_model_market_frame


@dataclass(frozen=True)
class FrozenETFResearchConfig:
    run_id: str
    etf_ticker: str
    etf_persona: str
    source_session_date: date
    prediction_date: date
    cutoff_utc: datetime
    code_version: str
    config_version: str
    lookback_sessions: int = 30
    minimum_history_sessions: int = 252
    minimum_weight_coverage: float = 0.60
    calibrated_sigma_floor: float = 0.20


@dataclass(frozen=True)
class FrozenETFResearchResult:
    preflight: ETFModelPreflightEvidence
    research_evidence: FrozenETFResearchEvidence


PosteriorFitter = Callable[[object, object], ETFPosteriorEvidence]


def _validate_config(config: FrozenETFResearchConfig) -> None:
    if not config.run_id.strip() or not config.etf_ticker.strip():
        raise LineageError("Frozen ETF research requires exact run and ticker identifiers.")
    if not config.etf_persona.strip():
        raise LineageError("Frozen ETF research requires an explicit ETF persona.")
    if not config.code_version.strip() or not config.config_version.strip():
        raise LineageError("Frozen ETF research requires exact code and config versions.")
    if config.cutoff_utc.tzinfo is None:
        raise LineageError("Frozen ETF research cutoff must be timezone-aware.")
    if config.source_session_date >= config.prediction_date:
        raise LineageError("Frozen ETF research source session must precede prediction date.")
    if config.lookback_sessions < 30:
        raise LineageError("Frozen ETF research lookback cannot be below 30 sessions.")
    if config.minimum_history_sessions < config.lookback_sessions:
        raise LineageError("Frozen ETF preflight history cannot be shorter than its lookback.")
    if not 0.0 < config.minimum_weight_coverage <= 1.0:
        raise LineageError("Frozen ETF constituent coverage must be in (0, 1].")
    if config.calibrated_sigma_floor <= 0.0:
        raise LineageError("Frozen ETF calibrated sigma floor must be positive.")


def run_frozen_etf_research(
    db,
    config: FrozenETFResearchConfig,
    *,
    posterior_fitter: PosteriorFitter = fit_etf_posterior,
) -> FrozenETFResearchResult:
    """Run one DB-backed ETF research comparison without any write path."""
    _validate_config(config)
    preflight = build_etf_model_preflight(
        db,
        run_id=config.run_id,
        etf_ticker=config.etf_ticker,
        etf_persona=config.etf_persona,
        source_session_date=config.source_session_date,
        prediction_date=config.prediction_date,
        cutoff_utc=config.cutoff_utc,
        code_version=config.code_version,
        config_version=config.config_version,
        minimum_history_sessions=config.minimum_history_sessions,
        minimum_weight_coverage=config.minimum_weight_coverage,
        calibrated_sigma_floor=config.calibrated_sigma_floor,
    )
    market_frame = load_stock_model_market_frame(
        db,
        preflight.market_snapshot,
        required_tickers=(config.etf_ticker.strip().upper(),),
    )
    dataset = build_etf_model_dataset(
        market_frame,
        config.etf_ticker,
        source_session_date=config.source_session_date,
        prediction_date=config.prediction_date,
        lookback_sessions=config.lookback_sessions,
    )
    posterior = posterior_fitter(dataset, preflight.prepared_stock_prior)
    if posterior.ticker != config.etf_ticker.strip().upper():
        raise LineageError("ETF posterior ticker differs from the requested ETF.")
    evidence = build_frozen_etf_research_evidence(
        etf_run=preflight.etf_run,
        prepared_stock_prior=preflight.prepared_stock_prior,
        posterior=posterior,
        persona_name=config.etf_persona,
    )
    return FrozenETFResearchResult(
        preflight=preflight,
        research_evidence=evidence,
    )
