"""Fail-closed stock posterior aggregation for ETF Bayesian priors.

The functions here are pure and production-inert. They do not read files,
query external APIs, write Turso, or invoke a model. Database rows and whale
weights must already have passed the lineage contract before being supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log, sqrt

from model_lineage import LineageError


ETF_TO_STOCK_PERSONA = {
    "ETF_BallsForBrains": "BallsForBrains",
    "ETF_Dynamic": "Dynamic",
    "ETF_Neutral": "Neutral",
    "ETF_Conservative": "Conservative",
}


def stock_persona_for(etf_persona: str) -> str:
    try:
        return ETF_TO_STOCK_PERSONA[etf_persona]
    except KeyError as exc:
        raise LineageError(f"Unsupported ETF persona: {etf_persona}") from exc


@dataclass(frozen=True)
class StockPosteriorEvidence:
    ticker: str
    posterior_probability: float
    posterior_probability_std: float | None
    expected_return_pp: float
    expected_return_pp_std: float | None
    constituent_weight: float

    def validate(self) -> None:
        if not self.ticker:
            raise LineageError("Stock evidence requires a ticker.")
        if (
            not isfinite(self.posterior_probability)
            or not 0.0 < self.posterior_probability < 1.0
        ):
            raise LineageError(f"{self.ticker}: probability must be strictly between 0 and 1.")
        if (
            self.posterior_probability_std is None
            or not isfinite(self.posterior_probability_std)
            or self.posterior_probability_std <= 0.0
        ):
            raise LineageError(f"{self.ticker}: posterior uncertainty is required.")
        if not isfinite(self.expected_return_pp):
            raise LineageError(f"{self.ticker}: expected return must be finite.")
        if (
            self.expected_return_pp_std is None
            or not isfinite(self.expected_return_pp_std)
            or self.expected_return_pp_std <= 0.0
        ):
            raise LineageError(f"{self.ticker}: expected-return uncertainty is required.")
        if (
            not isfinite(self.constituent_weight)
            or not 0.0 < self.constituent_weight <= 1.0
        ):
            raise LineageError(f"{self.ticker}: constituent weight must be in (0, 1].")


@dataclass(frozen=True)
class ETFDirectionalPrior:
    mean_log_odds: float
    sigma_log_odds: float
    weighted_expected_return_pp: float
    expected_return_sigma_pp: float
    weight_coverage: float
    contributor_count: int


def build_directional_prior(
    evidence: list[StockPosteriorEvidence],
    *,
    minimum_weight_coverage: float,
    calibrated_sigma_floor: float,
) -> ETFDirectionalPrior:
    """Pool stock posterior evidence on the ETF GLM's log-odds scale.

    The uncertainty calculation combines propagated posterior uncertainty with
    cross-constituent disagreement. The sigma floor is intentionally supplied
    by the caller because it must be chosen using walk-forward calibration.
    """
    if not 0.0 < minimum_weight_coverage <= 1.0:
        raise LineageError("minimum_weight_coverage must be in (0, 1].")
    if not isfinite(calibrated_sigma_floor) or calibrated_sigma_floor <= 0.0:
        raise LineageError("calibrated_sigma_floor must be positive.")
    if not evidence:
        raise LineageError("At least one stock posterior is required.")

    tickers: set[str] = set()
    for item in evidence:
        item.validate()
        if item.ticker in tickers:
            raise LineageError(f"Duplicate stock evidence for {item.ticker}.")
        tickers.add(item.ticker)

    coverage = sum(item.constituent_weight for item in evidence)
    if coverage + 1e-12 < minimum_weight_coverage:
        raise LineageError(
            f"Whale-weight coverage {coverage:.4f} is below required "
            f"{minimum_weight_coverage:.4f}."
        )
    if coverage > 1.0 + 1e-9:
        raise LineageError("Constituent weights exceed 100%.")

    normalized = [item.constituent_weight / coverage for item in evidence]
    logits = [log(item.posterior_probability / (1.0 - item.posterior_probability)) for item in evidence]
    mean_log_odds = sum(weight * value for weight, value in zip(normalized, logits))

    propagated_variance = 0.0
    for weight, item in zip(normalized, evidence):
        p = item.posterior_probability
        logit_std = item.posterior_probability_std / (p * (1.0 - p))
        propagated_variance += (weight * logit_std) ** 2

    disagreement_variance = sum(
        weight * (value - mean_log_odds) ** 2
        for weight, value in zip(normalized, logits)
    )
    sigma_log_odds = max(
        calibrated_sigma_floor,
        sqrt(propagated_variance + disagreement_variance),
    )
    weighted_return = sum(
        weight * item.expected_return_pp for weight, item in zip(normalized, evidence)
    )
    propagated_return_variance = sum(
        (weight * item.expected_return_pp_std) ** 2
        for weight, item in zip(normalized, evidence)
    )
    return_disagreement_variance = sum(
        weight * (item.expected_return_pp - weighted_return) ** 2
        for weight, item in zip(normalized, evidence)
    )
    expected_return_sigma_pp = sqrt(
        propagated_return_variance + return_disagreement_variance
    )
    if expected_return_sigma_pp <= 0.0 or not isfinite(expected_return_sigma_pp):
        raise LineageError("Pooled expected-return uncertainty is invalid.")

    return ETFDirectionalPrior(
        mean_log_odds=mean_log_odds,
        sigma_log_odds=sigma_log_odds,
        weighted_expected_return_pp=weighted_return,
        expected_return_sigma_pp=expected_return_sigma_pp,
        weight_coverage=coverage,
        contributor_count=len(evidence),
    )
