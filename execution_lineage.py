"""Pure validation and persistence helpers for append-only execution evidence.

This module does not activate services or execute orders. It validates evidence
that an execution service may append only after a separately approved plan has
passed the read-only preflight.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping, Protocol

from model_lineage import LineageError


MONEY_TOLERANCE = 0.10


class ExecutionAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    ABORT_BUY = "ABORT_BUY"
    ABORT_SELL = "ABORT_SELL"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    KILL_SWITCH = "KILL_SWITCH"


TRADE_ACTIONS = {
    ExecutionAction.BUY,
    ExecutionAction.SELL,
    ExecutionAction.TAKE_PROFIT,
    ExecutionAction.STOP_LOSS,
}
SELL_ACTIONS = {
    ExecutionAction.SELL,
    ExecutionAction.TAKE_PROFIT,
    ExecutionAction.STOP_LOSS,
}


class DatabaseWriter(Protocol):
    def execute_write(self, query: str, args: list[object]) -> None: ...


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{label} must be numeric.") from exc
    if not math.isfinite(result):
        raise LineageError(f"{label} must be finite.")
    return result


def _canonical_json(value: Mapping[str, object], label: str) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{label} is not canonically serializable.") from exc


@dataclass(frozen=True)
class ExecutionEvent:
    event_id: str
    plan_id: str
    sequence_number: int
    persona: str
    target_date: str
    ticker: str | None
    action: ExecutionAction
    units: float | None
    reference_price: float | None
    execution_price: float | None
    fees: float
    cash_delta: float
    holdings_value_delta: float
    realized_pnl: float | None
    reference_quote_timestamp_utc: str | None
    before_state_sha256: str
    after_state_sha256: str
    previous_event_sha256: str | None
    decision_evidence: Mapping[str, object]
    created_at_utc: str

    def canonical_payload(self) -> str:
        return _canonical_json(
            {
                "event_id": self.event_id,
                "plan_id": self.plan_id,
                "sequence_number": self.sequence_number,
                "persona": self.persona,
                "target_date": self.target_date,
                "ticker": self.ticker,
                "action": self.action.value,
                "units": self.units,
                "reference_price": self.reference_price,
                "execution_price": self.execution_price,
                "fees": self.fees,
                "cash_delta": self.cash_delta,
                "holdings_value_delta": self.holdings_value_delta,
                "realized_pnl": self.realized_pnl,
                "reference_quote_timestamp_utc": self.reference_quote_timestamp_utc,
                "before_state_sha256": self.before_state_sha256,
                "after_state_sha256": self.after_state_sha256,
                "previous_event_sha256": self.previous_event_sha256,
                "decision_evidence": self.decision_evidence,
                "created_at_utc": self.created_at_utc,
            },
            "execution event",
        )

    def event_sha256(self) -> str:
        return hashlib.sha256(self.canonical_payload().encode("utf-8")).hexdigest()

    def validate(self) -> None:
        if not self.event_id or not self.plan_id or not self.persona:
            raise LineageError("Execution event identifiers and persona are required.")
        if self.sequence_number <= 0:
            raise LineageError("Execution event sequence must be positive.")
        try:
            datetime.fromisoformat(self.created_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LineageError("Execution event timestamp is invalid.") from exc
        for value, label in (
            (self.fees, "fees"),
            (self.cash_delta, "cash_delta"),
            (self.holdings_value_delta, "holdings_value_delta"),
        ):
            _finite(value, label)
        if self.fees < 0.0:
            raise LineageError("Execution fees must be nonnegative.")
        for value, label in (
            (self.before_state_sha256, "before_state_sha256"),
            (self.after_state_sha256, "after_state_sha256"),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise LineageError(f"{label} must be lowercase SHA-256.")
        if self.previous_event_sha256 is not None and (
            len(self.previous_event_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.previous_event_sha256)
        ):
            raise LineageError("previous_event_sha256 must be lowercase SHA-256.")
        _canonical_json(self.decision_evidence, "decision_evidence")

        if self.action in TRADE_ACTIONS:
            if not self.ticker:
                raise LineageError("Trade execution requires a ticker.")
            units = _finite(self.units, "units")
            reference = _finite(self.reference_price, "reference_price")
            execution = _finite(self.execution_price, "execution_price")
            if units <= 0.0 or reference <= 0.0 or execution <= 0.0:
                raise LineageError("Trade units and prices must be positive.")
            if self.reference_quote_timestamp_utc is None:
                raise LineageError("Trade execution requires a quote timestamp.")
            if self.action is ExecutionAction.BUY:
                if self.cash_delta >= 0.0 or self.holdings_value_delta <= 0.0:
                    raise LineageError("BUY deltas have invalid signs.")
            elif self.cash_delta <= 0.0 or self.holdings_value_delta >= 0.0:
                raise LineageError("SELL deltas have invalid signs.")
            if abs(self.cash_delta + self.holdings_value_delta + self.fees) > MONEY_TOLERANCE:
                raise LineageError("Trade deltas do not reconcile after fees.")
            if self.action in SELL_ACTIONS and self.realized_pnl is None:
                raise LineageError("Sell execution requires realized PnL evidence.")
        else:
            if any(value not in (None, 0, 0.0) for value in (
                self.units, self.execution_price, self.realized_pnl
            )):
                raise LineageError("Non-trade event cannot contain fill or PnL values.")
            if abs(self.cash_delta) > MONEY_TOLERANCE or abs(self.holdings_value_delta) > MONEY_TOLERANCE:
                raise LineageError("Non-trade event cannot change cash or holdings.")


def save_execution_event(db: DatabaseWriter, event: ExecutionEvent) -> str:
    """Append one validated event; callers cannot update or delete evidence."""
    event.validate()
    event_hash = event.event_sha256()
    db.execute_write(
        """INSERT INTO execution_events (
        event_id,plan_id,sequence_number,persona,target_date,ticker,action,units,
        reference_price,execution_price,fees,cash_delta,holdings_value_delta,
        realized_pnl,reference_quote_timestamp_utc,before_state_sha256,
        after_state_sha256,previous_event_sha256,event_sha256,
        decision_evidence_json,created_at_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            event.event_id, event.plan_id, event.sequence_number, event.persona,
            event.target_date, event.ticker, event.action.value, event.units,
            event.reference_price, event.execution_price, event.fees,
            event.cash_delta, event.holdings_value_delta, event.realized_pnl,
            event.reference_quote_timestamp_utc, event.before_state_sha256,
            event.after_state_sha256, event.previous_event_sha256, event_hash,
            _canonical_json(event.decision_evidence, "decision_evidence"),
            event.created_at_utc,
        ],
    )
    return event_hash
