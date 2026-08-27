"""Pure exact-set reconciliation for one staged market-input snapshot.

The module has no I/O.  Incomplete-but-not-contradictory evidence is reported
as :class:`VisibilityPending` so the SELECT-only adapter may perform a bounded
visibility retry.  Contradictory evidence fails immediately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


REQUIRED_MACRO_TICKERS = frozenset({"^TNX", "^VIX"})


class PostflightError(ValueError):
    """Current evidence contradicts the exact postflight contract."""


class VisibilityPending(PostflightError):
    """Turso evidence is incomplete but has not contradicted the contract."""


@dataclass(frozen=True)
class SnapshotEvidence:
    snapshot_id: str
    status: str
    expected_rows: int
    expected_tickers: int
    checksum: str
    stored_code_version: str


@dataclass(frozen=True)
class FeatureEvidence:
    actual_rows: int
    ticker_rows: tuple[str, ...]
    first_date: str
    last_date: str


def _unique_nonblank(values: Iterable[object], *, label: str) -> set[str]:
    normalized = [str(value) for value in values]
    if any(not value for value in normalized):
        raise PostflightError(f"{label} contains a blank ticker")
    if len(set(normalized)) != len(normalized):
        raise PostflightError(f"{label} contains a duplicate ticker")
    return set(normalized)


def reconcile_staging_snapshot(
    *,
    snapshot: SnapshotEvidence,
    features: FeatureEvidence,
    lineage_rows: Sequence[Sequence[object]],
    source_session: str,
    expected_code_version: str,
    approval_count: int,
    screening_count: int,
) -> dict[str, object]:
    """Validate STAGING lifecycle, exact sets, lineage, and zero side effects."""

    if snapshot.status != "STAGING":
        raise PostflightError("snapshot status is not STAGING")
    if snapshot.stored_code_version != expected_code_version:
        raise PostflightError("snapshot code version does not match the executor")
    if snapshot.expected_rows <= 0 or snapshot.expected_tickers <= 0:
        raise PostflightError("snapshot metadata contains a non-positive count")
    if features.actual_rows > snapshot.expected_rows:
        raise PostflightError("feature row count exceeds snapshot metadata")
    if features.actual_rows < snapshot.expected_rows:
        raise VisibilityPending("feature rows are not fully visible")

    feature_tickers = _unique_nonblank(features.ticker_rows, label="features")
    if len(feature_tickers) > snapshot.expected_tickers:
        raise PostflightError("feature ticker count exceeds snapshot metadata")
    if len(feature_tickers) < snapshot.expected_tickers:
        raise VisibilityPending("feature tickers are not fully visible")
    if features.last_date != source_session:
        raise PostflightError("feature history does not end at the source session")

    if any(len(row) != 2 for row in lineage_rows):
        raise PostflightError("provider lineage rows do not match the ticker/session contract")
    lineage_tickers = _unique_nonblank(
        (row[0] for row in lineage_rows), label="provider lineage"
    )
    if any(str(row[1]) != source_session for row in lineage_rows):
        raise PostflightError("provider lineage contains the wrong source session")

    expected_lineage = feature_tickers | REQUIRED_MACRO_TICKERS
    extra = lineage_tickers - expected_lineage
    if extra:
        raise PostflightError(f"provider lineage ticker set has extra={sorted(extra)!r}")
    missing = expected_lineage - lineage_tickers
    if missing:
        raise VisibilityPending(f"provider lineage is not fully visible: missing={sorted(missing)!r}")
    if approval_count != 0 or screening_count != 0:
        raise PostflightError("unauthorized downstream outputs exist")

    return {
        "snapshot_id": snapshot.snapshot_id,
        "status": snapshot.status,
        "rows": features.actual_rows,
        "feature_tickers": len(feature_tickers),
        "provider_lineage_rows": len(lineage_tickers),
        "source_session": source_session,
        "first_date": features.first_date,
        "last_date": features.last_date,
        "approval_events": approval_count,
        "screening_runs": screening_count,
        "checksum": snapshot.checksum,
        "code_version": snapshot.stored_code_version,
    }


__all__ = [
    "FeatureEvidence",
    "PostflightError",
    "REQUIRED_MACRO_TICKERS",
    "SnapshotEvidence",
    "VisibilityPending",
    "reconcile_staging_snapshot",
]
