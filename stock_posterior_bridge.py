"""Pure bridge from PyMC posterior evidence to frozen decision-policy evidence.

This module performs no I/O, persistence, model fitting, recommendation
promotion, order creation, or service activation.
"""

from __future__ import annotations

from dataclasses import replace

from model_lineage import LineageError
from sampler_qa import validate_sampler_diagnostics
from stock_prediction_eligibility import (
    DecisionContext,
    EligibilityComparison,
    PredictionEvidence,
    compare_stock_prediction,
)
from stock_pymc_core import StockPosteriorEvidence


def posterior_to_prediction_evidence(
    posterior: StockPosteriorEvidence,
) -> PredictionEvidence:
    """Preserve percentage-point posterior units without implicit scaling."""
    if not str(posterior.ticker).strip():
        raise LineageError("Stock posterior ticker is required.")
    validate_sampler_diagnostics(posterior.diagnostics)
    return PredictionEvidence(
        probability_up_mean=posterior.probability_up_mean,
        probability_up_q05=posterior.probability_up_q05,
        probability_up_q95=posterior.probability_up_q95,
        expected_return_pp=posterior.expected_return_pp_mean,
        expected_risk_pp=posterior.predictive_risk_pp,
    )


def compare_research_only_posterior(
    posterior: StockPosteriorEvidence,
    context: DecisionContext,
    *,
    persona_name: str,
) -> EligibilityComparison:
    """Evaluate transparent lanes while forcing the promotion gate closed."""
    evidence = posterior_to_prediction_evidence(posterior)
    frozen_context = replace(context, research_promotion_approved=False)
    return compare_stock_prediction(
        evidence,
        frozen_context,
        persona_name=persona_name,
    )
