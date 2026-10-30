"""Fail-closed validation for lineage-backed pending execution plans.

This module does not write to Turso, activate services, or execute orders. Its
only successful outcome is evidence that a separately controlled activation
workflow may proceed to the next approval gate.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from model_lineage import LineageError


MONEY_TOLERANCE = 0.10


@dataclass(frozen=True)
class PendingOrder:
    persona: str
    target_date: str
    target_cash: float
    target_total_equity: float
    target_holdings: Mapping[str, object]
    daily_pnl: Mapping[str, object]
    executed_intraday_trades: Mapping[str, object]


@dataclass(frozen=True)
class PlanEvidence:
    plan_id: str
    persona: str
    asset_class: str
    target_date: str
    source_session_date: str
    market_snapshot_id: str
    snapshot_status: str
    snapshot_source_session_date: str
    model_run_id: str
    model_run_status: str
    model_prediction_date: str
    model_source_session_date: str
    pending_payload_sha256: str
    qa_status: str
    approval_decision: str | None
    approved_by: str | None
    consumed_plan_id: str | None


@dataclass(frozen=True)
class PreflightReport:
    passed: bool
    failures: tuple[str, ...]
    checked_personas: tuple[str, ...]


def _json_object(value: object, label: str) -> Mapping[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{label} is not valid JSON.") from exc
    if not isinstance(decoded, dict):
        raise LineageError(f"{label} must be a JSON object.")
    return decoded


def pending_order_from_row(row: Mapping[str, object]) -> PendingOrder:
    return PendingOrder(
        persona=str(row["persona"]),
        target_date=str(row["date"]),
        target_cash=float(row["target_cash"]),
        target_total_equity=float(row["target_total_equity"]),
        target_holdings=_json_object(row["target_holdings_json"], "target_holdings_json"),
        daily_pnl=_json_object(row["daily_pnl_json"], "daily_pnl_json"),
        executed_intraday_trades=_json_object(
            row["executed_intraday_trades_json"], "executed_intraday_trades_json"
        ),
    )


def _finite_nonnegative(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{label} must be numeric.") from exc
    if not math.isfinite(result) or result < 0.0:
        raise LineageError(f"{label} must be finite and nonnegative.")
    return result


def canonical_pending_payload(order: PendingOrder) -> str:
    payload = {
        "persona": order.persona,
        "date": order.target_date,
        "target_cash": order.target_cash,
        "target_total_equity": order.target_total_equity,
        "target_holdings": order.target_holdings,
        "daily_pnl": order.daily_pnl,
        "executed_intraday_trades": order.executed_intraday_trades,
    }
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LineageError("Pending payload is not canonically serializable.") from exc


def pending_payload_sha256(order: PendingOrder) -> str:
    return hashlib.sha256(canonical_pending_payload(order).encode("utf-8")).hexdigest()


def validate_pending_accounting(order: PendingOrder) -> tuple[str, ...]:
    failures = []
    try:
        cash = _finite_nonnegative(order.target_cash, "target_cash")
        equity = _finite_nonnegative(order.target_total_equity, "target_total_equity")
        holdings_value = 0.0
        for ticker, raw_holding in order.target_holdings.items():
            if ticker == "Cash":
                failures.append("Cash must not be encoded as a holding.")
                continue
            if not isinstance(raw_holding, dict):
                failures.append(f"Holding {ticker} must be an object.")
                continue
            dollars = _finite_nonnegative(raw_holding.get("dollars"), f"{ticker}.dollars")
            units = _finite_nonnegative(raw_holding.get("units"), f"{ticker}.units")
            price = _finite_nonnegative(raw_holding.get("price"), f"{ticker}.price")
            if abs(dollars - units * price) > MONEY_TOLERANCE:
                failures.append(f"Holding {ticker} dollars do not equal units times price.")
            holdings_value += dollars
        if abs(equity - (cash + holdings_value)) > MONEY_TOLERANCE:
            failures.append("Target equity does not equal cash plus holdings.")
        if order.executed_intraday_trades:
            failures.append("Proposed plan already contains intraday executions.")
    except LineageError as exc:
        failures.append(str(exc))
    return tuple(failures)


def validate_execution_preflight(
    pending_orders: Iterable[PendingOrder],
    plan_evidence: Iterable[PlanEvidence],
    *,
    expected_personas: set[str],
    expected_source_session: date,
    expected_target_date: date,
    expected_approver: str,
    latest_ledger_dates: Mapping[str, str],
) -> PreflightReport:
    failures: list[str] = []
    pending_list = list(pending_orders)
    evidence_list = list(plan_evidence)
    pending_by_persona = {item.persona: item for item in pending_list}
    evidence_by_persona = {item.persona: item for item in evidence_list}
    if len(pending_by_persona) != len(pending_list):
        failures.append("Duplicate pending-order persona rows detected.")
    if len(evidence_by_persona) != len(evidence_list):
        failures.append("Duplicate execution-plan persona rows detected.")
    if set(pending_by_persona) != expected_personas:
        failures.append("Pending-order persona coverage is not exact.")
    if set(evidence_by_persona) != expected_personas:
        failures.append("Execution-plan persona coverage is not exact.")
    if set(latest_ledger_dates) != expected_personas:
        failures.append("Ledger persona coverage is not exact.")

    source_date = expected_source_session.isoformat()
    target_date = expected_target_date.isoformat()
    for persona in sorted(expected_personas):
        order = pending_by_persona.get(persona)
        evidence = evidence_by_persona.get(persona)
        if order is None or evidence is None:
            continue
        failures.extend(f"{persona}: {item}" for item in validate_pending_accounting(order))
        if order.target_date != target_date or evidence.target_date != target_date:
            failures.append(f"{persona}: target date mismatch.")
        expected_asset_class = "ETF" if persona.startswith("ETF_") else "STOCK"
        if evidence.asset_class != expected_asset_class:
            failures.append(f"{persona}: asset class does not match persona.")
        if latest_ledger_dates.get(persona) != source_date:
            failures.append(f"{persona}: latest ledger date does not match source session.")
        if evidence.source_session_date != source_date:
            failures.append(f"{persona}: execution-plan source session mismatch.")
        if evidence.snapshot_status != "VALIDATED":
            failures.append(f"{persona}: market snapshot is not validated.")
        if evidence.snapshot_source_session_date != source_date:
            failures.append(f"{persona}: market snapshot source session mismatch.")
        if evidence.model_run_status != "COMPLETED":
            failures.append(f"{persona}: model run is not completed.")
        if evidence.model_prediction_date != target_date:
            failures.append(f"{persona}: model prediction date mismatch.")
        if evidence.model_source_session_date != source_date:
            failures.append(f"{persona}: model source session mismatch.")
        if evidence.qa_status != "VALIDATED":
            failures.append(f"{persona}: execution plan did not pass QA.")
        if evidence.approval_decision != "APPROVED":
            failures.append(f"{persona}: execution plan is not approved.")
        if evidence.approved_by != expected_approver:
            failures.append(f"{persona}: execution-plan approver mismatch.")
        if evidence.consumed_plan_id is not None:
            failures.append(f"{persona}: execution plan was already consumed.")
        try:
            actual_checksum = pending_payload_sha256(order)
        except LineageError as exc:
            failures.append(f"{persona}: {exc}")
        else:
            if actual_checksum != evidence.pending_payload_sha256:
                failures.append(f"{persona}: pending payload checksum mismatch.")

    return PreflightReport(
        passed=not failures,
        failures=tuple(failures),
        checked_personas=tuple(sorted(set(pending_by_persona) & set(evidence_by_persona))),
    )
