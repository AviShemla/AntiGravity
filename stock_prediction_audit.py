"""Pure append-only record construction for AG-versus-Codex audits.

This module performs no database I/O and never authorizes an order.  It turns
one already-evaluated eligibility comparison into deterministic records for
the review-only Turso audit tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re

from model_lineage import LineageError
from stock_prediction_eligibility import (
    DecisionContext,
    PredictionEvidence,
    compare_stock_prediction,
)


IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


@dataclass(frozen=True)
class DecisionAuditRecord:
    values: tuple[object, ...]


@dataclass(frozen=True)
class CriterionAuditRecord:
    values: tuple[object, ...]


@dataclass(frozen=True)
class StockPredictionAuditRecords:
    audit_id: str
    decision: DecisionAuditRecord
    criteria: tuple[CriterionAuditRecord, ...]


def _identifier(value: str, *, label: str) -> str:
    normalized = str(value).strip()
    if not IDENTIFIER.fullmatch(normalized):
        raise LineageError(f"{label} is invalid.")
    return normalized


def build_stock_prediction_audit_records(
    *,
    model_run_id: str,
    ticker: str,
    persona: str,
    resolved_base_persona: str,
    evidence: PredictionEvidence,
    context: DecisionContext,
    created_at_utc: datetime | None = None,
) -> StockPredictionAuditRecords:
    """Create deterministic decision and criterion records for one prediction."""
    run_id = _identifier(model_run_id, label="Model run identifier")
    normalized_ticker = str(ticker).strip().upper()
    if not TICKER.fullmatch(normalized_ticker):
        raise LineageError("Prediction audit ticker is invalid.")
    normalized_persona = _identifier(persona, label="Prediction audit persona")
    base_persona = _identifier(
        resolved_base_persona, label="Resolved prediction audit base persona"
    )
    if base_persona not in {"Conservative", "Neutral", "BallsForBrains"}:
        raise LineageError("Prediction audit base persona is not governed.")
    # Recompute the comparison from the supplied evidence and resolved policy.
    # Accepting a caller-provided comparison would permit an audit row that did
    # not correspond to the recorded posterior or decision context.
    comparison = compare_stock_prediction(
        evidence,
        context,
        persona_name=base_persona,
    )
    timestamp = created_at_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise LineageError("Prediction audit timestamp must be timezone-aware.")
    timestamp_text = timestamp.astimezone(timezone.utc).isoformat()
    audit_material = json.dumps(
        [run_id, normalized_ticker, normalized_persona],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    audit_id = "stock_prediction_audit_" + hashlib.sha256(
        audit_material.encode("utf-8")
    ).hexdigest()[:24]
    failures_json = json.dumps(
        list(comparison.hard_gate_failures),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    decision = DecisionAuditRecord((
        audit_id,
        run_id,
        normalized_ticker,
        normalized_persona,
        base_persona,
        evidence.probability_up_mean,
        evidence.probability_up_q05,
        evidence.probability_up_q95,
        evidence.expected_return,
        evidence.expected_risk,
        context.round_trip_cost,
        context.vix_close,
        comparison.raw_model_signal.value,
        comparison.ag_action.value,
        comparison.codex_action.value,
        comparison.balanced_action.value,
        comparison.legacy_allocation_fraction,
        comparison.shadow_allocation_fraction,
        comparison.legacy_vix_multiplier,
        comparison.shadow_vix_multiplier,
        failures_json,
        0,
        timestamp_text,
    ))
    criteria = tuple(
        CriterionAuditRecord((
            audit_id,
            ordinal,
            row.criterion,
            row.ag_rule,
            row.ag_result,
            row.codex_rule,
            row.codex_result,
            row.balanced_rule,
            row.balanced_result,
        ))
        for ordinal, row in enumerate(comparison.rows)
    )
    if not criteria:
        raise LineageError("Prediction audit contains no comparison criteria.")
    return StockPredictionAuditRecords(
        audit_id=audit_id,
        decision=decision,
        criteria=criteria,
    )
