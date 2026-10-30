"""Fail-closed planning for exact feature recomputation after EOD changes.

The planner performs no I/O. Current features include recursive EWM and
cumulative calculations, so every changed ticker must be recomputed from its
full canonical input history. Only rows on or after that ticker's earliest
changed session are candidates for replacement. Cross-market features are
recomputed from the earliest changed session through the latest known session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from canonical_market_history import CanonicalReconciliation
from model_lineage import LineageError


@dataclass(frozen=True)
class TickerRecompute:
    ticker: str
    first_changed_session: date
    write_sessions: tuple[date, ...]
    requires_full_input_history: bool


@dataclass(frozen=True)
class FeatureRecomputePlan:
    ticker_plans: tuple[TickerRecompute, ...]
    cross_market_write_sessions: tuple[date, ...]
    changed_keys: tuple[tuple[str, str], ...]
    unchanged_keys: tuple[tuple[str, str], ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_keys)


def _sessions(values: Iterable[date | str]) -> tuple[date, ...]:
    parsed: list[date] = []
    for value in values:
        try:
            parsed.append(value if isinstance(value, date) else date.fromisoformat(str(value)))
        except ValueError as exc:
            raise LineageError("Feature session calendar contains an invalid date.") from exc
    if len(parsed) != len(set(parsed)) or parsed != sorted(parsed):
        raise LineageError("Feature session calendar must be unique and ordered.")
    if not parsed:
        raise LineageError("Feature session calendar cannot be empty.")
    return tuple(parsed)


def plan_feature_recomputation(
    reconciliation: CanonicalReconciliation,
    *,
    available_sessions: Iterable[date | str],
) -> FeatureRecomputePlan:
    """Plan exact recomputation without pretending recursive features are local."""
    sessions = _sessions(available_sessions)
    session_set = set(sessions)
    changed = tuple(sorted(reconciliation.appended_keys + reconciliation.revised_keys))
    if not changed:
        return FeatureRecomputePlan(
            ticker_plans=(),
            cross_market_write_sessions=(),
            changed_keys=(),
            unchanged_keys=reconciliation.unchanged_keys,
        )

    changes_by_ticker: dict[str, list[date]] = {}
    for ticker, text_session in changed:
        try:
            session = date.fromisoformat(text_session)
        except ValueError as exc:
            raise LineageError("Canonical reconciliation contains an invalid date.") from exc
        if session not in session_set:
            raise LineageError(
                f"Changed canonical session {session.isoformat()} is absent from the calendar."
            )
        normalized_ticker = str(ticker).strip().upper()
        if not normalized_ticker:
            raise LineageError("Canonical reconciliation contains a blank ticker.")
        changes_by_ticker.setdefault(normalized_ticker, []).append(session)

    ticker_plans: list[TickerRecompute] = []
    for ticker, ticker_changes in sorted(changes_by_ticker.items()):
        first = min(ticker_changes)
        ticker_plans.append(
            TickerRecompute(
                ticker=ticker,
                first_changed_session=first,
                write_sessions=tuple(session for session in sessions if session >= first),
                requires_full_input_history=True,
            )
        )
    first_global_change = min(plan.first_changed_session for plan in ticker_plans)
    return FeatureRecomputePlan(
        ticker_plans=tuple(ticker_plans),
        cross_market_write_sessions=tuple(
            session for session in sessions if session >= first_global_change
        ),
        changed_keys=changed,
        unchanged_keys=reconciliation.unchanged_keys,
    )
