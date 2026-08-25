"""Explicit unit conversions for statistical evidence and broker boundaries.

Canonical research units:
- return and volatility evidence: percentage points (1% == 1.0)
- probability, Kelly, allocation, and weights: fractions (100% == 1.0)
- transaction costs: basis points (10 bp == 10.0)
- dollar PnL input returns: decimal fractions (1% == 0.01)

Every scale change must call one of these functions exactly once.
"""

from __future__ import annotations

from math import isfinite

from model_lineage import LineageError


PERCENTAGE_POINTS_PER_FRACTION = 100.0
BASIS_POINTS_PER_PERCENTAGE_POINT = 100.0


def _finite(value: float, *, label: str) -> float:
    normalized = float(value)
    if not isfinite(normalized):
        raise LineageError(f"{label} must be finite.")
    return normalized


def fraction_to_percentage_points(value_fraction: float) -> float:
    """Convert a decimal return fraction to percentage points."""
    return _finite(value_fraction, label="Return fraction") * PERCENTAGE_POINTS_PER_FRACTION


def percentage_points_to_fraction(value_pp: float) -> float:
    """Convert percentage-point evidence to a decimal return fraction."""
    return _finite(value_pp, label="Percentage-point value") / PERCENTAGE_POINTS_PER_FRACTION


def basis_points_to_percentage_points(cost_bps: float) -> float:
    """Convert transaction costs in basis points to percentage points."""
    cost = _finite(cost_bps, label="Transaction cost")
    if cost < 0.0:
        raise LineageError("Transaction cost cannot be negative.")
    return cost / BASIS_POINTS_PER_PERCENTAGE_POINT
