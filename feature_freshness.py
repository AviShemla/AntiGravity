"""Bounded forward-fill policy for dated model features."""

from __future__ import annotations

import pandas as pd


SLOW_FEATURE_SUFFIXES = ("_AC", "_ANALYST", "_UPSIDE")


def bounded_forward_fill(
    frame: pd.DataFrame,
    *,
    default_limit: int = 5,
    slow_feature_limit: int = 63,
) -> pd.DataFrame:
    """Forward-fill without allowing observations to live indefinitely.

    Daily technical, market, and sector evidence may be carried for at most
    five rows. Analyst fields are explicitly slower-moving and may be carried
    for at most one trading quarter. Remaining gaps stay missing so downstream
    model folds fail closed or drop them explicitly.
    """
    if default_limit < 1 or slow_feature_limit < default_limit:
        raise ValueError("Feature freshness limits are invalid.")
    result = frame.copy()
    for column in result.columns:
        limit = (
            slow_feature_limit
            if str(column).upper().endswith(SLOW_FEATURE_SUFFIXES)
            else default_limit
        )
        result[column] = result[column].ffill(limit=limit)
    return result
