"""Research-only bridge from ETF posterior evidence to inert scorecards.

This module is pure. It performs no I/O, persistence, model fitting, broker
interaction, recommendation promotion, order creation, email, deployment, or
service control.
"""

from __future__ import annotations

from dataclasses import dataclass

from etf_prior_builder import PreparedETFStockPrior
from etf_pymc_core import ETFPosteriorEvidence
from model_lineage import (
    AssetClass,
    ETFPrior,
    LineageError,
    ModelRun,
    ModelScorecard,
    Recommendation,
    RunStatus,
)
from sampler_qa import validate_sampler_diagnostics


ETF_RESEARCH_POLICY_MARKER = (
    "RESEARCH_ONLY;PROMOTION_DISABLED;ACTION_LANES_NO_TRADE;"
    "UNIT_CONTRACT=statistical-units-v1;"
    "STOCK_PRIOR_LINEAGE=COMPLETE"
)


@dataclass(frozen=True)
class FrozenETFResearchEvidence:
    """Raw Bayesian ETF evidence plus its forced-inert scorecard."""

    posterior: ETFPosteriorEvidence
    stock_prior_lineage: tuple[ETFPrior, ...]
    scorecard: ModelScorecard
    probability_unit: str = "fraction"
    expected_return_unit: str = "percentage_points"
    expected_risk_unit: str = "percentage_points"
    allocation_unit: str = "fraction"
    action_policy: str = "RESEARCH_ONLY_ALL_LANES_NO_TRADE"


def _validate_complete_stock_prior_lineage(
    etf_run: ModelRun,
    prepared: PreparedETFStockPrior,
) -> None:
    batch = prepared.stock_batch
    if batch.prediction_date != etf_run.prediction_date:
        raise LineageError("ETF run and stock prior prediction dates do not match.")
    if batch.source_session_date != etf_run.source_session_date:
        raise LineageError("ETF run and stock prior source sessions do not match.")
    if not batch.run_id or not batch.market_snapshot_id or not batch.universe_snapshot_id:
        raise LineageError("ETF stock prior lacks exact source-run/input lineage.")
    evidence_tickers = {item.ticker for item in batch.evidence}
    if len(evidence_tickers) != len(batch.evidence):
        raise LineageError("ETF stock prior contains duplicate constituent evidence.")
    if len(batch.evidence) != prepared.aggregate.contributor_count:
        raise LineageError("ETF stock prior contributor count does not reconcile.")

    records = prepared.lineage_records
    expected_count = 2 * len(batch.evidence) + 2
    if len(records) != expected_count:
        raise LineageError(
            f"ETF stock prior lineage is incomplete: expected {expected_count}, "
            f"received {len(records)}."
        )
    prior_ids: set[str] = set()
    constituent_counts = {ticker: 0 for ticker in evidence_tickers}
    aggregate_count = 0
    for record in records:
        record.validate_for(etf_run)
        if record.prior_id in prior_ids:
            raise LineageError("ETF stock prior lineage contains duplicate prior IDs.")
        prior_ids.add(record.prior_id)
        if record.source_run_id != batch.run_id:
            raise LineageError("ETF stock prior lineage references a different stock run.")
        if record.source_session_date != batch.source_session_date:
            raise LineageError("ETF stock prior lineage source session mismatch.")
        if record.source_ticker is None:
            aggregate_count += 1
        elif record.source_ticker not in constituent_counts:
            raise LineageError("ETF stock prior lineage contains an unexpected constituent.")
        else:
            constituent_counts[record.source_ticker] += 1
    if aggregate_count != 2 or any(count != 2 for count in constituent_counts.values()):
        raise LineageError("ETF stock prior direction/return channels are incomplete.")


def build_frozen_etf_research_evidence(
    *,
    etf_run: ModelRun,
    prepared_stock_prior: PreparedETFStockPrior,
    posterior: ETFPosteriorEvidence,
    persona_name: str,
) -> FrozenETFResearchEvidence:
    """Retain raw posterior evidence while forcing all action fields inert."""
    etf_run.validate()
    if etf_run.asset_class is not AssetClass.ETF:
        raise LineageError("Frozen ETF research requires an ETF model run.")
    if etf_run.status is not RunStatus.STARTED:
        raise LineageError("Frozen ETF research bridge requires a STARTED run.")
    if not persona_name.strip() or not posterior.ticker.strip():
        raise LineageError("Frozen ETF research requires ticker and persona.")
    validate_sampler_diagnostics(posterior.diagnostics)
    _validate_complete_stock_prior_lineage(etf_run, prepared_stock_prior)

    aggregate = prepared_stock_prior.aggregate
    if posterior.stock_direction_prior_mean_log_odds != aggregate.mean_log_odds:
        raise LineageError("ETF posterior direction prior differs from audited lineage.")
    if posterior.stock_direction_prior_sigma_log_odds != aggregate.sigma_log_odds:
        raise LineageError("ETF posterior direction uncertainty differs from audited lineage.")
    if posterior.stock_return_prior_mean_pp != aggregate.weighted_expected_return_pp:
        raise LineageError("ETF posterior return prior differs from audited lineage.")
    if posterior.stock_return_prior_sigma_pp != aggregate.expected_return_sigma_pp:
        raise LineageError("ETF posterior return uncertainty differs from audited lineage.")
    if posterior.stock_contributor_count != aggregate.contributor_count:
        raise LineageError("ETF posterior contributor count differs from audited lineage.")
    if posterior.stock_weight_coverage != aggregate.weight_coverage:
        raise LineageError("ETF posterior weight coverage differs from audited lineage.")

    scorecard = ModelScorecard(
        run_id=etf_run.run_id,
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
        quarantine_reason=ETF_RESEARCH_POLICY_MARKER,
    )
    scorecard.validate_for(etf_run)
    return FrozenETFResearchEvidence(
        posterior=posterior,
        stock_prior_lineage=prepared_stock_prior.lineage_records,
        scorecard=scorecard,
    )
