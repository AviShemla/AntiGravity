"""Canonical frozen stock-research runner.

The runner consumes only approved Turso model-input snapshots, fits the
Bayesian stochastic stock model, preserves posterior evidence, and persists
only NO_TRADE research scorecards. It has no broker, order, email, deployment,
filesystem-data, or service-control path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Callable

from model_lineage import (
    AssetClass,
    LineageError,
    ModelRun,
    ModelScorecard,
    Recommendation,
    RunStatus,
)
from stock_model_dataset import build_stock_model_dataset
from stock_model_input_reader import load_stock_model_market_frame
from stock_model_preflight import StockModelPreflightEvidence, build_stock_model_preflight
from stock_posterior_bridge import compare_research_only_posterior
from stock_prediction_eligibility import (
    DecisionContext,
    EligibilityComparison,
    LEGACY_PERSONAS,
)
from stock_pymc_core import StockPosteriorEvidence, fit_stock_posterior
from stock_research_run_writer import (
    CompletedStockResearchReceipt,
    StockResearchRunWriter,
)


@dataclass(frozen=True)
class FrozenStockResearchConfig:
    run_id: str
    prediction_date: date
    source_session_date: date
    cutoff_utc: datetime
    code_version: str
    config_version: str
    model_name: str = "STOCK_PYMC_RESEARCH"
    persona_names: tuple[str, ...] = ("Conservative", "Neutral", "BallsForBrains")
    lookback_sessions: int = 30
    minimum_history_sessions: int = 252
    round_trip_cost_bps: float = 0.0


@dataclass(frozen=True)
class StockResearchTickerEvidence:
    ticker: str
    posterior: StockPosteriorEvidence
    persona_comparisons: tuple[tuple[str, EligibilityComparison], ...]


@dataclass(frozen=True)
class StockResearchLineage:
    run_id: str
    model_name: str
    code_version: str
    config_version: str
    source_session_date: date
    prediction_date: date
    cutoff_utc: datetime
    market_snapshot_id: str
    market_snapshot_checksum_sha256: str
    market_provider: str
    universe_snapshot_id: str
    universe_snapshot_checksum_sha256: str
    universe_approval_event_id: str
    predictive_screening_run_id: str
    probability_unit: str = "fraction"
    expected_return_unit: str = "percentage_points"
    expected_risk_unit: str = "percentage_points"
    transaction_cost_unit: str = "basis_points"
    allocation_unit: str = "fraction"
    action_policy: str = "RESEARCH_ONLY_ALL_LANES_NO_TRADE"


@dataclass(frozen=True)
class FrozenStockResearchResult:
    lineage: StockResearchLineage
    ticker_evidence: tuple[StockResearchTickerEvidence, ...]
    receipt: CompletedStockResearchReceipt


PosteriorFitter = Callable[[object], StockPosteriorEvidence]


def _validate_config(config: FrozenStockResearchConfig) -> None:
    if not config.run_id.strip() or not config.model_name.strip():
        raise LineageError("Frozen stock research requires an explicit run ID and model name.")
    if not config.code_version.strip() or not config.config_version.strip():
        raise LineageError("Frozen stock research requires exact code and config versions.")
    if config.cutoff_utc.tzinfo is None:
        raise LineageError("Frozen stock research cutoff must be timezone-aware.")
    if config.source_session_date >= config.prediction_date:
        raise LineageError("Frozen stock research source session must precede prediction date.")
    if config.lookback_sessions < 30:
        raise LineageError("Frozen stock research lookback cannot be below 30 sessions.")
    if config.minimum_history_sessions < config.lookback_sessions:
        raise LineageError("Preflight history cannot be shorter than the model lookback.")
    if (
        not isfinite(config.round_trip_cost_bps)
        or config.round_trip_cost_bps < 0.0
    ):
        raise LineageError("Frozen stock research transaction cost must be finite and non-negative.")
    if not config.persona_names or len(set(config.persona_names)) != len(config.persona_names):
        raise LineageError("Frozen stock research personas must be non-empty and unique.")
    unknown = sorted(set(config.persona_names).difference(LEGACY_PERSONAS))
    if unknown:
        raise LineageError("Unknown frozen stock research personas: " + ", ".join(unknown) + ".")


def _run_record(config: FrozenStockResearchConfig) -> ModelRun:
    run = ModelRun(
        run_id=config.run_id,
        model_name=config.model_name,
        asset_class=AssetClass.STOCK,
        prediction_date=config.prediction_date,
        source_session_date=config.source_session_date,
        as_of_timestamp_utc=config.cutoff_utc.astimezone(timezone.utc),
        code_version=config.code_version,
        config_version=config.config_version,
        status=RunStatus.STARTED,
    )
    run.validate()
    return run


def _decision_context(
    *,
    vix_close: float,
    round_trip_cost_bps: float,
) -> DecisionContext:
    return DecisionContext(
        snapshot_validated=True,
        universe_approved=True,
        source_date_aligned=True,
        model_run_completed=True,
        sampler_qa_passed=True,
        research_promotion_approved=False,
        quarantined=False,
        legacy_blacklisted=False,
        available_capital=0.0,
        vix_close=vix_close,
        price_available=True,
        round_trip_cost_bps=round_trip_cost_bps,
    )


def _research_scorecard(
    run: ModelRun,
    posterior: StockPosteriorEvidence,
    *,
    persona_name: str,
) -> ModelScorecard:
    return ModelScorecard(
        run_id=run.run_id,
        ticker=posterior.ticker,
        persona=persona_name,
        posterior_probability=posterior.probability_up_mean,
        posterior_probability_std=posterior.probability_up_std,
        posterior_probability_q05=posterior.probability_up_q05,
        posterior_probability_q95=posterior.probability_up_q95,
        expected_return=posterior.expected_return_pp_mean,
        expected_return_std=posterior.expected_return_pp_std,
        expected_risk=posterior.predictive_risk_pp,
        recommendation=Recommendation.NO_TRADE,
        proposed_allocation=0.0,
        quarantine_reason=(
            "RESEARCH_ONLY;PROMOTION_DISABLED;ACTION_LANES_NO_TRADE;"
            "UNIT_CONTRACT=statistical-units-v1"
        ),
    )


def _lineage(
    config: FrozenStockResearchConfig,
    evidence: StockModelPreflightEvidence,
) -> StockResearchLineage:
    market_checksum = evidence.market_snapshot.source_checksum_sha256
    universe_checksum = evidence.universe_snapshot.source_checksum_sha256
    if not market_checksum or not universe_checksum:
        raise LineageError("Frozen stock research inputs require immutable checksums.")
    return StockResearchLineage(
        run_id=config.run_id,
        model_name=config.model_name,
        code_version=config.code_version,
        config_version=config.config_version,
        source_session_date=config.source_session_date,
        prediction_date=config.prediction_date,
        cutoff_utc=config.cutoff_utc.astimezone(timezone.utc),
        market_snapshot_id=evidence.market_snapshot.snapshot_id,
        market_snapshot_checksum_sha256=market_checksum,
        market_provider=evidence.market_snapshot.provider,
        universe_snapshot_id=evidence.universe_snapshot.snapshot_id,
        universe_snapshot_checksum_sha256=universe_checksum,
        universe_approval_event_id=evidence.universe_approval.event_id,
        predictive_screening_run_id=evidence.screening_run_id,
    )


def run_frozen_stock_research(
    db,
    writer: StockResearchRunWriter,
    config: FrozenStockResearchConfig,
    *,
    posterior_fitter: PosteriorFitter = fit_stock_posterior,
) -> FrozenStockResearchResult:
    """Fit and atomically persist one frozen Bayesian stock-research run.

    All posterior computation completes before the first write. Any preflight,
    input, model, sampler, or policy failure therefore leaves no persisted run.
    Persistence itself is one conditional transaction and readback is required.
    """
    _validate_config(config)
    run = _run_record(config)
    preflight = build_stock_model_preflight(
        db,
        source_session_date=config.source_session_date,
        prediction_date=config.prediction_date,
        cutoff_utc=config.cutoff_utc,
        minimum_history_sessions=config.minimum_history_sessions,
    )
    market_frame = load_stock_model_market_frame(
        db,
        preflight.market_snapshot,
        required_tickers=preflight.required_market_tickers,
    )

    ticker_evidence: list[StockResearchTickerEvidence] = []
    scorecards: list[ModelScorecard] = []
    for entry in preflight.universe:
        dataset = build_stock_model_dataset(
            market_frame,
            entry,
            source_session_date=config.source_session_date,
            prediction_date=config.prediction_date,
            lookback_sessions=config.lookback_sessions,
        )
        posterior = posterior_fitter(dataset)
        if posterior.ticker != entry.ticker:
            raise LineageError("Posterior ticker differs from the approved universe entry.")
        vix_rows = market_frame[
            (market_frame["Ticker"] == entry.ticker)
            & (market_frame["Date"].dt.date == config.source_session_date)
        ]
        if len(vix_rows) != 1:
            raise LineageError("Target ticker lacks one exact source-session VIX value.")
        vix_close = float(vix_rows.iloc[0]["VIX_Close"])
        context = _decision_context(
            vix_close=vix_close,
            round_trip_cost_bps=config.round_trip_cost_bps,
        )

        comparisons: list[tuple[str, EligibilityComparison]] = []
        for persona_name in config.persona_names:
            comparison = compare_research_only_posterior(
                posterior,
                context,
                persona_name=persona_name,
            )
            if (
                comparison.codex_action is not Recommendation.NO_TRADE
                or comparison.balanced_action is not Recommendation.NO_TRADE
            ):
                raise LineageError("Frozen research action lane escaped NO_TRADE.")
            comparisons.append((persona_name, comparison))
            scorecards.append(
                _research_scorecard(run, posterior, persona_name=persona_name)
            )
        ticker_evidence.append(
            StockResearchTickerEvidence(
                ticker=entry.ticker,
                posterior=posterior,
                persona_comparisons=tuple(comparisons),
            )
        )

    receipt = writer.persist_completed_stock_run(
        run,
        preflight,
        tuple(scorecards),
    )
    if receipt.status is not RunStatus.COMPLETED:
        raise LineageError("Frozen stock research persistence is not COMPLETED.")
    return FrozenStockResearchResult(
        lineage=_lineage(config, preflight),
        ticker_evidence=tuple(ticker_evidence),
        receipt=receipt,
    )
