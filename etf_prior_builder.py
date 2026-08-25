"""Build auditable ETF priors exclusively from lineage-backed stock posteriors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import log

from model_lineage import AssetClass, ETFPrior, LineageError, ModelRun
from stock_etf_interlock import ETFDirectionalPrior, build_directional_prior
from stock_scorecard_reader import StockEvidenceBatch, load_stock_evidence_for_etf


@dataclass(frozen=True)
class PreparedETFStockPrior:
    stock_batch: StockEvidenceBatch
    aggregate: ETFDirectionalPrior
    lineage_records: tuple[ETFPrior, ...]


def _prior_id(etf_run_id: str, source_run_id: str, source_ticker: str, prior_type: str) -> str:
    material = f"{etf_run_id}|{source_run_id}|{source_ticker}|{prior_type}".encode("utf-8")
    return "etf_prior_" + hashlib.sha256(material).hexdigest()[:32]


def prepare_etf_stock_prior(
    db,
    *,
    etf_run: ModelRun,
    etf_persona: str,
    expected_market_snapshot_id: str,
    constituent_weights: dict[str, float],
    minimum_weight_coverage: float,
    calibrated_sigma_floor: float,
) -> PreparedETFStockPrior:
    etf_run.validate()
    if etf_run.asset_class is not AssetClass.ETF:
        raise LineageError("Stock-derived ETF priors require an ETF model run.")
    batch = load_stock_evidence_for_etf(
        db,
        etf_persona=etf_persona,
        prediction_date=etf_run.prediction_date,
        etf_cutoff_utc=etf_run.as_of_timestamp_utc,
        expected_market_snapshot_id=expected_market_snapshot_id,
        constituent_weights=constituent_weights,
    )
    if batch.source_session_date != etf_run.source_session_date:
        raise LineageError("Stock and ETF runs must use the same source session.")
    aggregate = build_directional_prior(
        batch.evidence,
        minimum_weight_coverage=minimum_weight_coverage,
        calibrated_sigma_floor=calibrated_sigma_floor,
    )
    records = []
    for item in batch.evidence:
        p = item.posterior_probability
        logit_value = log(p / (1.0 - p))
        logit_sigma = item.posterior_probability_std / (p * (1.0 - p))
        record = ETFPrior(
            prior_id=_prior_id(etf_run.run_id, batch.run_id, item.ticker, "STOCK_POSTERIOR"),
            etf_run_id=etf_run.run_id,
            prior_type="STOCK_POSTERIOR",
            source_run_id=batch.run_id,
            source_ticker=item.ticker,
            source_session_date=batch.source_session_date,
            available_at_utc=batch.available_at_utc,
            constituent_weight=item.constituent_weight,
            transformed_value=logit_value,
            prior_sigma=logit_sigma,
            transformation="logit(stock posterior); normalized constituent-weight pooling",
        )
        record.validate_for(etf_run)
        records.append(record)
        return_record = ETFPrior(
            prior_id=_prior_id(
                etf_run.run_id, batch.run_id, item.ticker, "STOCK_RETURN_POSTERIOR"
            ),
            etf_run_id=etf_run.run_id,
            # The applied Turso schema groups both stock posterior channels
            # under STOCK_POSTERIOR. The mandatory transformation and stable
            # ID distinguish return-scale evidence from direction log-odds.
            prior_type="STOCK_POSTERIOR",
            source_run_id=batch.run_id,
            source_ticker=item.ticker,
            source_session_date=batch.source_session_date,
            available_at_utc=batch.available_at_utc,
            constituent_weight=item.constituent_weight,
            transformed_value=item.expected_return_pp,
            prior_sigma=item.expected_return_pp_std,
            transformation="stock expected-return posterior; value/sigma in percentage points",
        )
        return_record.validate_for(etf_run)
        records.append(return_record)
    aggregate_record = ETFPrior(
        prior_id=_prior_id(
            etf_run.run_id, batch.run_id, "__AGGREGATE__", "SECTOR_AGGREGATE"
        ),
        etf_run_id=etf_run.run_id,
        prior_type="SECTOR_AGGREGATE",
        source_run_id=batch.run_id,
        source_ticker=None,
        source_session_date=batch.source_session_date,
        available_at_utc=batch.available_at_utc,
        constituent_weight=aggregate.weight_coverage,
        transformed_value=aggregate.mean_log_odds,
        prior_sigma=aggregate.sigma_log_odds,
        transformation="normalized weighted log-odds with posterior and disagreement variance",
    )
    aggregate_record.validate_for(etf_run)
    records.append(aggregate_record)
    aggregate_return_record = ETFPrior(
        prior_id=_prior_id(
            etf_run.run_id, batch.run_id, "__AGGREGATE__", "SECTOR_RETURN_AGGREGATE"
        ),
        etf_run_id=etf_run.run_id,
        # The applied schema groups both aggregate channels under
        # SECTOR_AGGREGATE; transformation preserves the statistical role.
        prior_type="SECTOR_AGGREGATE",
        source_run_id=batch.run_id,
        source_ticker=None,
        source_session_date=batch.source_session_date,
        available_at_utc=batch.available_at_utc,
        constituent_weight=aggregate.weight_coverage,
        transformed_value=aggregate.weighted_expected_return_pp,
        prior_sigma=aggregate.expected_return_sigma_pp,
        transformation=(
            "normalized weighted expected return in percentage points with posterior and "
            "cross-constituent disagreement variance"
        ),
    )
    aggregate_return_record.validate_for(etf_run)
    records.append(aggregate_return_record)
    return PreparedETFStockPrior(
        stock_batch=batch,
        aggregate=aggregate,
        lineage_records=tuple(records),
    )
