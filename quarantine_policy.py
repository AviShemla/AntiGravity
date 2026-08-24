"""DB-first quarantine and fresh-start policy primitives.

Historical evidence is immutable. A reset changes only the earliest session
that may contribute strikes to a future eligibility decision. Model failures
remain scoped to their immutable model run.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable


class QuarantinePolicyError(ValueError):
    """Quarantine evidence is malformed or internally inconsistent."""


@dataclass(frozen=True)
class QuarantineReset:
    reset_id: str
    asset_class: str
    mechanism: str
    effective_session_date: date
    approved_by: str
    reason: str

    def validate(self) -> None:
        if not self.reset_id or not self.approved_by or not self.reason:
            raise QuarantinePolicyError("Reset ID, approver, and reason are required.")
        if self.asset_class not in {"STOCK", "ETF"}:
            raise QuarantinePolicyError("Reset asset class must be STOCK or ETF.")
        if self.mechanism not in {"LEGACY_STRIKE_BLACKLIST", "MODEL_FAILURE"}:
            raise QuarantinePolicyError("Unsupported quarantine-reset mechanism.")


def strike_counts_after_reset(
    ledger_rows: Iterable[tuple[str, str]],
    *,
    effective_session_date: date,
    lookback_sessions: int = 15,
) -> dict[str, int]:
    """Count negative-PnL sessions using only DB rows on/after a reset date.

    ``ledger_rows`` contains ``(session_date, daily_pnl_json)`` pairs for one
    persona. Duplicate dates are rejected because they would double-count a
    strike. Only the most recent ``lookback_sessions`` unique sessions in the
    post-reset window are evaluated.
    """
    if lookback_sessions <= 0:
        raise QuarantinePolicyError("Lookback sessions must be positive.")

    decoded: dict[date, dict[str, object]] = {}
    for raw_date, raw_pnl in ledger_rows:
        session = date.fromisoformat(str(raw_date))
        if session < effective_session_date:
            continue
        if session in decoded:
            raise QuarantinePolicyError(f"Duplicate ledger session: {session}.")
        try:
            pnl = json.loads(raw_pnl or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise QuarantinePolicyError(
                f"Invalid daily_pnl_json for {session}."
            ) from exc
        if not isinstance(pnl, dict):
            raise QuarantinePolicyError(
                f"daily_pnl_json for {session} must be an object."
            )
        decoded[session] = pnl

    selected = sorted(decoded, reverse=True)[:lookback_sessions]
    strikes: defaultdict[str, int] = defaultdict(int)
    for session in selected:
        for raw_ticker, raw_value in decoded[session].items():
            ticker = str(raw_ticker).strip().upper()
            if not ticker:
                raise QuarantinePolicyError(f"Blank ticker in {session} PnL evidence.")
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise QuarantinePolicyError(
                    f"Non-numeric PnL for {ticker} on {session}."
                ) from exc
            if value < 0:
                strikes[ticker] += 1
    return dict(sorted(strikes.items()))


def blocked_tickers(
    strike_counts: dict[str, int], *, strike_threshold: int = 3
) -> dict[str, int]:
    if strike_threshold <= 0:
        raise QuarantinePolicyError("Strike threshold must be positive.")
    return {
        ticker: count
        for ticker, count in sorted(strike_counts.items())
        if count >= strike_threshold
    }
