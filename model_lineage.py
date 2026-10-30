"""Turso model-lineage records and fail-closed validation.

This module is deliberately inert until the additive Turso migration is
approved and applied. It contains no filesystem fallbacks and does not invoke
models, brokers, or the intraday sniper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from math import isfinite
from typing import Protocol
from uuid import uuid4


class LineageError(ValueError):
    """A model input cannot be proven safe for use."""


class AssetClass(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    ARENA = "ARENA"


class RunStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


class Recommendation(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class UniverseDecision(StrEnum):
    RETAIN = "RETAIN"
    REPLACE = "REPLACE"
    CASH = "CASH"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4()}"


@dataclass(frozen=True)
class ModelRun:
    run_id: str
    model_name: str
    asset_class: AssetClass
    prediction_date: date
    source_session_date: date
    as_of_timestamp_utc: datetime
    code_version: str
    config_version: str
    status: RunStatus
    failure_reason: str | None = None

    def validate(self) -> None:
        if not self.run_id or not self.model_name:
            raise LineageError("A run requires immutable run_id and model_name.")
        if self.source_session_date >= self.prediction_date:
            raise LineageError(
                "source_session_date must precede prediction_date to prevent look-ahead."
            )
        if self.as_of_timestamp_utc.tzinfo is None:
            raise LineageError("as_of_timestamp_utc must be timezone-aware.")
        if self.status is RunStatus.FAILED and not self.failure_reason:
            raise LineageError("A failed run must retain its failure_reason.")


@dataclass(frozen=True)
class ModelScorecard:
    run_id: str
    ticker: str
    persona: str
    posterior_probability: float
    posterior_probability_std: float
    posterior_probability_q05: float
    posterior_probability_q95: float
    expected_return: float
    expected_return_std: float
    expected_risk: float
    recommendation: Recommendation
    proposed_allocation: float
    quarantine_reason: str | None = None

    def validate_for(self, run: ModelRun) -> None:
        if self.run_id != run.run_id:
            raise LineageError("Scorecard run ID must match its model run.")
        if not self.ticker or not self.persona:
            raise LineageError("Scorecard ticker and persona are required.")
        numeric = (
            self.posterior_probability,
            self.posterior_probability_std,
            self.posterior_probability_q05,
            self.posterior_probability_q95,
            self.expected_return,
            self.expected_return_std,
            self.expected_risk,
            self.proposed_allocation,
        )
        if not all(isfinite(value) for value in numeric):
            raise LineageError("Scorecard numerical evidence must be finite.")
        if not 0.0 < self.posterior_probability < 1.0:
            raise LineageError("Posterior probability must be in (0, 1).")
        if self.posterior_probability_std <= 0.0:
            raise LineageError("Posterior probability uncertainty must be positive.")
        if not (
            0.0 <= self.posterior_probability_q05
            <= self.posterior_probability
            <= self.posterior_probability_q95
            <= 1.0
        ):
            raise LineageError("Posterior interval must contain its mean within [0, 1].")
        if self.expected_return_std <= 0.0 or self.expected_risk < 0.0:
            raise LineageError("Return uncertainty must be positive and risk non-negative.")
        if not 0.0 <= self.proposed_allocation <= 1.0:
            raise LineageError("Proposed allocation must be between zero and one.")


@dataclass(frozen=True)
class ETFPrior:
    prior_id: str
    etf_run_id: str
    prior_type: str
    source_run_id: str | None
    source_ticker: str | None
    source_session_date: date
    available_at_utc: datetime
    constituent_weight: float | None
    transformed_value: float
    prior_sigma: float
    transformation: str

    def validate_for(self, etf_run: ModelRun) -> None:
        if etf_run.asset_class is not AssetClass.ETF:
            raise LineageError("ETF priors may only be attached to an ETF model run.")
        if not self.prior_id or self.etf_run_id != etf_run.run_id:
            raise LineageError("Prior must have a stable ID and matching ETF run ID.")
        if not self.prior_type or not self.transformation:
            raise LineageError("Prior type and transformation are mandatory evidence.")
        if self.available_at_utc.tzinfo is None:
            raise LineageError("available_at_utc must be timezone-aware.")
        if self.source_session_date >= etf_run.prediction_date:
            raise LineageError("Prior source session is not earlier than ETF prediction date.")
        if self.available_at_utc > etf_run.as_of_timestamp_utc:
            raise LineageError("Prior was not available at the ETF model cutoff.")
        if self.constituent_weight is not None and not 0.0 <= self.constituent_weight <= 1.0:
            raise LineageError("Constituent weight must be between zero and one.")
        if self.prior_sigma <= 0.0:
            raise LineageError("Prior uncertainty must be strictly positive.")


@dataclass(frozen=True)
class ReplacementAssessment:
    incumbent_ticker: str | None
    candidate_ticker: str | None
    expected_net_benefit: float | None
    expected_turnover_cost: float | None
    evidence_gate_passed: bool
    risk_gate_passed: bool
    candidate_independently_qualified: bool


def decide_etf_universe(assessment: ReplacementAssessment) -> UniverseDecision:
    """Return RETAIN, REPLACE, or CASH without ever forcing a replacement."""
    if not assessment.evidence_gate_passed or not assessment.risk_gate_passed:
        return UniverseDecision.CASH
    if not assessment.candidate_ticker:
        return UniverseDecision.RETAIN if assessment.incumbent_ticker else UniverseDecision.CASH
    if (
        assessment.candidate_independently_qualified
        and assessment.expected_net_benefit is not None
        and assessment.expected_turnover_cost is not None
        and assessment.expected_net_benefit > assessment.expected_turnover_cost
    ):
        return UniverseDecision.REPLACE
    return UniverseDecision.RETAIN if assessment.incumbent_ticker else UniverseDecision.CASH


class DatabaseWriter(Protocol):
    def execute_write(self, query: str, args: list[object]) -> None: ...


def save_model_run(db: DatabaseWriter, run: ModelRun, created_at: datetime | None = None) -> None:
    """Write a validated model run to the additive Turso schema."""
    run.validate()
    created = created_at or utc_now()
    db.execute_write(
        """
        INSERT INTO model_runs (
            run_id, model_name, asset_class, prediction_date, source_session_date,
            as_of_timestamp_utc, code_version, config_version, status,
            failure_reason, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run.run_id, run.model_name, run.asset_class.value,
            run.prediction_date.isoformat(), run.source_session_date.isoformat(),
            run.as_of_timestamp_utc.isoformat(), run.code_version,
            run.config_version, run.status.value, run.failure_reason,
            created.isoformat(),
        ],
    )


def save_model_scorecard(
    db: DatabaseWriter,
    run: ModelRun,
    scorecard: ModelScorecard,
    created_at: datetime | None = None,
) -> None:
    """Write one validated posterior scorecard to the additive schema."""
    run.validate()
    scorecard.validate_for(run)
    created = created_at or utc_now()
    db.execute_write(
        """
        INSERT INTO model_scorecards (
            run_id, ticker, persona, posterior_probability,
            posterior_probability_std, posterior_probability_q05,
            posterior_probability_q95, expected_return, expected_return_std,
            expected_risk, recommendation, proposed_allocation,
            quarantine_reason, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            scorecard.run_id, scorecard.ticker, scorecard.persona,
            scorecard.posterior_probability, scorecard.posterior_probability_std,
            scorecard.posterior_probability_q05, scorecard.posterior_probability_q95,
            scorecard.expected_return, scorecard.expected_return_std,
            scorecard.expected_risk, scorecard.recommendation.value,
            scorecard.proposed_allocation, scorecard.quarantine_reason,
            created.isoformat(),
        ],
    )


def save_etf_prior(db: DatabaseWriter, etf_run: ModelRun, prior: ETFPrior, created_at: datetime | None = None) -> None:
    """Write one validated, auditable ETF prior to the additive Turso schema."""
    etf_run.validate()
    prior.validate_for(etf_run)
    created = created_at or utc_now()
    db.execute_write(
        """
        INSERT INTO etf_prior_lineage (
            prior_id, etf_run_id, prior_type, source_run_id, source_ticker,
            source_session_date, available_at_utc, constituent_weight,
            transformed_value, prior_sigma, transformation, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            prior.prior_id, prior.etf_run_id, prior.prior_type, prior.source_run_id,
            prior.source_ticker, prior.source_session_date.isoformat(),
            prior.available_at_utc.isoformat(), prior.constituent_weight,
            prior.transformed_value, prior.prior_sigma, prior.transformation,
            created.isoformat(),
        ],
    )
