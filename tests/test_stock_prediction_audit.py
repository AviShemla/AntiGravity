from datetime import datetime, timezone
import json

import pytest

from model_lineage import LineageError
from stock_prediction_audit import build_stock_prediction_audit_records
from stock_prediction_eligibility import (
    DecisionContext,
    PredictionEvidence,
)


def evidence():
    return PredictionEvidence(0.72, 0.55, 0.84, 1.2, 2.0)


def context(**changes):
    values = {
        "snapshot_validated": True,
        "universe_approved": True,
        "source_date_aligned": True,
        "model_run_completed": True,
        "sampler_qa_passed": True,
        "research_promotion_approved": True,
        "available_capital": 10_000.0,
        "vix_close": 18.0,
        "round_trip_cost_bps": 10.0,
    }
    values.update(changes)
    return DecisionContext(**values)


def records(**changes):
    ev = evidence()
    ctx = context(**changes)
    return build_stock_prediction_audit_records(
        model_run_id="run-1",
        ticker="ndaq",
        persona="Dynamic",
        resolved_base_persona="Neutral",
        evidence=ev,
        context=ctx,
        created_at_utc=datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc),
    )


def test_builds_one_decision_and_every_comparison_criterion():
    result = records()
    assert result.audit_id.startswith("stock_prediction_audit_")
    assert result.decision.values[2:5] == ("NDAQ", "Dynamic", "Neutral")
    assert len(result.criteria) == 6
    assert [item.values[1] for item in result.criteria] == list(range(6))
    assert result.decision.values[-2] == 0


def test_audit_id_is_stable_for_run_ticker_persona():
    assert records().audit_id == records().audit_id


def test_hard_gate_failures_are_preserved_as_json():
    result = records(snapshot_validated=False, sampler_qa_passed=False)
    assert json.loads(result.decision.values[20]) == [
        "SNAPSHOT_NOT_VALIDATED",
        "SAMPLER_QA_FAILED",
    ]


def test_dynamic_persona_requires_explicit_governed_base_persona():
    ev = evidence()
    ctx = context()
    with pytest.raises(LineageError, match="base persona is not governed"):
        build_stock_prediction_audit_records(
            model_run_id="run-1",
            ticker="NDAQ",
            persona="Dynamic",
            resolved_base_persona="Dynamic",
            evidence=ev,
            context=ctx,
        )


def test_naive_timestamp_fails_closed():
    ev = evidence()
    ctx = context()
    with pytest.raises(LineageError, match="timezone-aware"):
        build_stock_prediction_audit_records(
            model_run_id="run-1",
            ticker="NDAQ",
            persona="Neutral",
            resolved_base_persona="Neutral",
            evidence=ev,
            context=ctx,
            created_at_utc=datetime(2026, 8, 24, 18, 0),
        )
