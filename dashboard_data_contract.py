"""Fail-closed evidence helpers for the read-only dashboard.

The dashboard must never fabricate a benchmark or present an unapproved legacy
pending row as executable.  These helpers are intentionally pure so their
money-relevant behavior can be tested without network or database access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from execution_preflight import pending_order_from_row, pending_payload_sha256


@dataclass(frozen=True)
class BenchmarkResult:
    status: str
    values: tuple[float | None, ...]
    first_evidence_date: str | None
    last_evidence_date: str | None
    evidence_count: int


def resolve_model_alias_collisions(
    rows: Iterable[Mapping[str, object]],
    aliases: Mapping[str, str],
    source_priority: Mapping[str, int],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Resolve legacy model aliases deterministically and report collisions.

    The lowest numeric priority wins. Equal-priority disagreement is rejected
    because silently choosing one financial series would be arbitrary.
    """
    winners: dict[tuple[str, str], tuple[int, dict[str, object]]] = {}
    collisions: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        source_name = str(row["model_name"])
        display_name = aliases.get(source_name, source_name)
        date = str(row["Date"] if "Date" in row else row["date"])[:10]
        priority = int(source_priority.get(source_name, 1000))
        row["model_name"] = display_name
        key = (date, display_name)
        existing = winners.get(key)
        if existing is None:
            winners[key] = (priority, row)
            continue
        existing_priority, existing_row = existing
        collisions.append({
            "date": date,
            "display_model_name": display_name,
            "kept_source_priority": min(existing_priority, priority),
            "discarded_source_priority": max(existing_priority, priority),
        })
        if priority == existing_priority:
            if float(row["total_equity"]) != float(existing_row["total_equity"]):
                raise ValueError(f"Ambiguous equal-priority model collision for {date} {display_name}.")
        elif priority < existing_priority:
            winners[key] = (priority, row)
    ordered = [item[1] for _, item in sorted(winners.items())]
    return ordered, collisions


def normalize_benchmark(
    chart_dates: Sequence[object],
    price_rows: Iterable[Mapping[str, object]],
) -> BenchmarkResult:
    """Align and normalize DB prices without backfill or invented values.

    A missing price before the first evidenced observation stays ``None``.
    Later gaps may use the last known close, which is historical carry-forward
    and does not introduce future information.
    """
    requested_dates = [str(value)[:10] for value in chart_dates]
    price_by_date: dict[str, float] = {}
    for row in price_rows:
        day = str(row["date"])[:10]
        try:
            close = float(row["close_price"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Non-numeric benchmark close for {day}.") from exc
        if not math.isfinite(close) or close <= 0:
            raise ValueError(f"Invalid benchmark close for {day}.")
        price_by_date[day] = close

    evidence_dates = sorted(price_by_date)
    if not evidence_dates:
        return BenchmarkResult(
            status="UNAVAILABLE",
            values=tuple(None for _ in requested_dates),
            first_evidence_date=None,
            last_evidence_date=None,
            evidence_count=0,
        )

    first_value: float | None = None
    last_value: float | None = None
    normalized: list[float | None] = []
    for day in requested_dates:
        if day in price_by_date:
            last_value = price_by_date[day]
            if first_value is None:
                first_value = last_value
        if first_value is None or last_value is None:
            normalized.append(None)
        else:
            normalized.append(round((last_value / first_value) * 10000.0, 2))

    return BenchmarkResult(
        status="AVAILABLE" if any(value is not None for value in normalized) else "OUT_OF_RANGE",
        values=tuple(normalized),
        first_evidence_date=evidence_dates[0],
        last_evidence_date=evidence_dates[-1],
        evidence_count=len(evidence_dates),
    )


def approved_pending_row(
    pending_row: Mapping[str, object] | None,
    plan_row: Mapping[str, object] | None,
) -> tuple[Mapping[str, object] | None, str]:
    """Return a pending row only when its immutable approved plan proves it."""
    if pending_row is None:
        return None, "NO_PENDING_ROW"
    if plan_row is None:
        return None, "EXECUTION_LINEAGE_UNAVAILABLE"
    required = {
        "qa_status": "VALIDATED",
        "approval_decision": "APPROVED",
    }
    for field, expected in required.items():
        if str(plan_row.get(field, "")) != expected:
            return None, f"PLAN_{field.upper()}_{plan_row.get(field, 'MISSING')}"
    if plan_row.get("consumed_plan_id") is not None:
        return None, "PLAN_ALREADY_CONSUMED"

    order = pending_order_from_row(pending_row)
    if str(plan_row.get("persona")) != order.persona:
        return None, "PLAN_PERSONA_MISMATCH"
    if str(plan_row.get("target_date"))[:10] != order.target_date[:10]:
        return None, "PLAN_DATE_MISMATCH"
    if str(plan_row.get("pending_payload_sha256")) != pending_payload_sha256(order):
        return None, "PLAN_PAYLOAD_HASH_MISMATCH"
    return pending_row, "APPROVED"
