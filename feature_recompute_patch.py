"""Build an exact, side-effect-free feature replacement patch.

The feature engine recomputes from full canonical history because several
indicators are recursive.  This module narrows that complete result to the
exact canonical keys authorized by :class:`FeatureRecomputePlan`.  It performs
no database I/O and deliberately fails closed when even one expected key is
missing or an unexpected key is requested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from typing import Iterable

import numpy as np
import pandas as pd

from feature_recompute_plan import FeatureRecomputePlan
from model_lineage import LineageError


@dataclass(frozen=True)
class FeatureReplacementPatch:
    frame: pd.DataFrame
    replacement_keys: tuple[tuple[str, str], ...]
    content_sha256: str


def _normalized_keys(
    values: Iterable[tuple[str, date | str]], *, label: str
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for ticker_value, session_value in values:
        ticker = str(ticker_value).strip().upper()
        if not ticker:
            raise LineageError(f"{label} contains a blank ticker.")
        try:
            session = (
                session_value
                if isinstance(session_value, date)
                else date.fromisoformat(str(session_value))
            )
        except ValueError as exc:
            raise LineageError(f"{label} contains an invalid session date.") from exc
        normalized.append((ticker, session.isoformat()))
    if len(normalized) != len(set(normalized)):
        raise LineageError(f"{label} contains duplicate ticker/session keys.")
    return tuple(sorted(normalized))


def _json_value(value):
    if value is None or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            raise LineageError("Feature replacement patch contains an infinite value.")
    if isinstance(value, (str, int, float, bool)):
        return value
    raise LineageError(
        f"Feature replacement patch contains unsupported value type {type(value).__name__}."
    )


def _content_sha256(frame: pd.DataFrame) -> str:
    columns = tuple(str(column) for column in frame.columns)
    records = [
        [_json_value(value) for value in row]
        for row in frame.itertuples(index=False, name=None)
    ]
    payload = json.dumps(
        {"columns": columns, "records": records},
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_feature_replacement_patch(
    recomputed_features: pd.DataFrame,
    plan: FeatureRecomputePlan,
    *,
    canonical_keys: Iterable[tuple[str, date | str]],
    ticker_column: str = "Ticker",
    session_column: str = "Date",
) -> FeatureReplacementPatch:
    """Return only feature rows whose canonical inputs may have changed.

    ``canonical_keys`` is the authoritative key set for the recomputed input
    history.  Cross-market aggregates can affect every ticker on and after the
    first changed session, while ticker-local recursive indicators affect the
    changed ticker on its planned sessions.  The union is exact and must be
    fully present in ``recomputed_features`` before a patch is returned.
    """
    canonical = _normalized_keys(canonical_keys, label="Canonical feature input")
    if not plan.has_changes:
        if plan.ticker_plans or plan.cross_market_write_sessions:
            raise LineageError("No-change feature plan contains replacement sessions.")
        return FeatureReplacementPatch(
            frame=recomputed_features.iloc[0:0].copy(),
            replacement_keys=(),
            content_sha256=_content_sha256(recomputed_features.iloc[0:0].copy()),
        )

    if ticker_column not in recomputed_features or session_column not in recomputed_features:
        raise LineageError("Recomputed feature frame is missing its ticker/session key columns.")
    frame = recomputed_features.copy()
    frame[ticker_column] = frame[ticker_column].astype(str).str.strip().str.upper()
    parsed_sessions = pd.to_datetime(frame[session_column], errors="coerce")
    if frame[ticker_column].eq("").any() or parsed_sessions.isna().any():
        raise LineageError("Recomputed feature frame contains an invalid ticker/session key.")
    frame[session_column] = parsed_sessions.dt.date.astype(str)
    if frame.duplicated([ticker_column, session_column]).any():
        raise LineageError("Recomputed feature frame contains duplicate ticker/session keys.")

    canonical_set = set(canonical)
    frame_keys = set(zip(frame[ticker_column], frame[session_column]))
    unexpected_frame_keys = frame_keys.difference(canonical_set)
    if unexpected_frame_keys:
        raise LineageError("Recomputed feature frame contains keys absent from canonical history.")

    requested: set[tuple[str, str]] = set()
    cross_market_sessions = {session.isoformat() for session in plan.cross_market_write_sessions}
    requested.update(key for key in canonical if key[1] in cross_market_sessions)
    for ticker_plan in plan.ticker_plans:
        if not ticker_plan.requires_full_input_history:
            raise LineageError("Recursive feature recomputation must use full ticker history.")
        requested.update(
            (ticker_plan.ticker, session.isoformat())
            for session in ticker_plan.write_sessions
            if (ticker_plan.ticker, session.isoformat()) in canonical_set
        )
    if not requested:
        raise LineageError("Changed feature plan selected no canonical replacement keys.")
    missing = requested.difference(frame_keys)
    if missing:
        raise LineageError(
            f"Recomputed feature frame is missing {len(missing)} planned canonical keys."
        )

    mask = pd.MultiIndex.from_frame(frame[[ticker_column, session_column]]).isin(requested)
    patch = frame.loc[mask].sort_values([ticker_column, session_column]).reset_index(drop=True)
    replacement_keys = tuple(zip(patch[ticker_column], patch[session_column]))
    if replacement_keys != tuple(sorted(requested)):
        raise LineageError("Feature replacement patch key set is not exact.")
    return FeatureReplacementPatch(
        frame=patch,
        replacement_keys=replacement_keys,
        content_sha256=_content_sha256(patch),
    )
