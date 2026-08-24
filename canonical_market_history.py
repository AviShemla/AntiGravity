"""Deterministic, in-memory canonical selection for immutable EOD revisions.

This module does not choose a provider policy.  The caller must preregister an
ordered provider priority and a timezone-aware evidence cutoff.  It performs no
database writes and does not create model-input snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

import pandas as pd

from model_lineage import LineageError


SHA256 = re.compile(r"^[0-9a-f]{64}$")
BAR_VALUE_COLUMNS = (
    "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume",
    "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close",
    "adjusted_volume", "dividend_cash", "split_factor",
)
REQUIRED_COLUMNS = (
    "run_id", "run_status", "provider", "ingestion_mode", "ticker", "date",
    *BAR_VALUE_COLUMNS, "source_value_sha256", "observed_at_utc",
)
CANONICAL_COLUMNS = (
    "ticker", "date", *BAR_VALUE_COLUMNS, "source_value_sha256",
    "canonical_provider", "canonical_run_id", "canonical_observed_at_utc",
)


@dataclass(frozen=True)
class CanonicalSelectionPolicy:
    provider_priority: tuple[str, ...]
    evidence_cutoff_utc: datetime

    def validate(self) -> None:
        if not self.provider_priority:
            raise LineageError("Canonical provider priority cannot be empty.")
        if len(set(self.provider_priority)) != len(self.provider_priority):
            raise LineageError("Canonical provider priority contains duplicates.")
        if any(not str(provider).strip() for provider in self.provider_priority):
            raise LineageError("Canonical provider priority contains a blank value.")
        if self.evidence_cutoff_utc.tzinfo is None:
            raise LineageError("Canonical evidence cutoff must be timezone-aware.")


@dataclass(frozen=True)
class CanonicalReconciliation:
    history: pd.DataFrame
    appended_keys: tuple[tuple[str, str], ...]
    revised_keys: tuple[tuple[str, str], ...]
    unchanged_keys: tuple[tuple[str, str], ...]


def _validate_canonical_frame(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(CANONICAL_COLUMNS).difference(frame.columns))
    if missing:
        raise LineageError(f"{label} is missing canonical columns: {missing}.")
    clean = frame[list(CANONICAL_COLUMNS)].copy()
    clean["ticker"] = clean["ticker"].astype(str).str.strip().str.upper()
    clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.date
    if clean["ticker"].eq("").any() or clean["date"].isna().any():
        raise LineageError(f"{label} contains an invalid ticker/date key.")
    if clean.duplicated(["ticker", "date"]).any():
        raise LineageError(f"{label} contains duplicate ticker/date keys.")
    if not clean["source_value_sha256"].astype(str).map(SHA256.fullmatch).all():
        raise LineageError(f"{label} contains an invalid source hash.")
    return clean.sort_values(["ticker", "date"]).reset_index(drop=True)


def select_canonical_bar_revisions(
    evidence: pd.DataFrame,
    policy: CanonicalSelectionPolicy,
) -> pd.DataFrame:
    """Select one reproducible revision for each ticker/session key."""
    policy.validate()
    missing = sorted(set(REQUIRED_COLUMNS).difference(evidence.columns))
    if missing:
        raise LineageError(f"EOD revision evidence is missing columns: {missing}.")
    clean = evidence[list(REQUIRED_COLUMNS)].copy()
    if clean.empty:
        raise LineageError("EOD revision evidence is empty.")
    if not clean["run_status"].astype(str).eq("COMPLETE").all():
        raise LineageError("Canonical selection received non-COMPLETE ingestion evidence.")
    clean["ticker"] = clean["ticker"].astype(str).str.strip().str.upper()
    clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.date
    clean["observed_at_utc"] = pd.to_datetime(
        clean["observed_at_utc"], errors="coerce", utc=True, format="mixed"
    )
    if clean["ticker"].eq("").any() or clean["date"].isna().any():
        raise LineageError("EOD revision evidence contains an invalid ticker/date key.")
    if clean["observed_at_utc"].isna().any():
        raise LineageError("EOD revision evidence contains an invalid observation timestamp.")
    if clean.duplicated(["run_id", "ticker", "date"]).any():
        raise LineageError("EOD revision evidence duplicates a run/ticker/date key.")
    if not clean["source_value_sha256"].astype(str).map(SHA256.fullmatch).all():
        raise LineageError("EOD revision evidence contains an invalid source hash.")
    present_providers = set(clean["provider"].astype(str))
    missing_policy = sorted(present_providers.difference(policy.provider_priority))
    if missing_policy:
        raise LineageError(f"Canonical policy does not rank providers: {missing_policy}.")
    cutoff = pd.Timestamp(policy.evidence_cutoff_utc.astimezone(timezone.utc))
    clean = clean.loc[clean["observed_at_utc"] <= cutoff].copy()
    if clean.empty:
        raise LineageError("No COMPLETE EOD evidence exists before the canonical cutoff.")
    provider_rank = {provider: rank for rank, provider in enumerate(policy.provider_priority)}
    clean["_provider_rank"] = clean["provider"].map(provider_rank)
    clean = clean.sort_values(
        ["ticker", "date", "_provider_rank", "observed_at_utc", "run_id"],
        ascending=[True, True, True, False, False],
    )
    selected = clean.drop_duplicates(["ticker", "date"], keep="first").copy()
    selected = selected.rename(columns={
        "provider": "canonical_provider",
        "run_id": "canonical_run_id",
        "observed_at_utc": "canonical_observed_at_utc",
    })
    return _validate_canonical_frame(selected, label="Canonical selection")


def reconcile_canonical_history(
    existing_history: pd.DataFrame,
    selected_revisions: pd.DataFrame,
) -> CanonicalReconciliation:
    """Append new keys and replace only keys backed by a different source hash."""
    existing = _validate_canonical_frame(existing_history, label="Existing canonical history")
    selected = _validate_canonical_frame(selected_revisions, label="Selected revisions")
    existing_by_key = existing.set_index(["ticker", "date"], drop=False)
    selected_by_key = selected.set_index(["ticker", "date"], drop=False)
    appended: list[tuple[str, str]] = []
    revised: list[tuple[str, str]] = []
    unchanged: list[tuple[str, str]] = []
    for key, row in selected_by_key.iterrows():
        text_key = (str(key[0]), key[1].isoformat())
        if key not in existing_by_key.index:
            appended.append(text_key)
        elif str(existing_by_key.at[key, "source_value_sha256"]) == str(row["source_value_sha256"]):
            unchanged.append(text_key)
        else:
            revised.append(text_key)
        existing_by_key.loc[key, list(CANONICAL_COLUMNS)] = row[list(CANONICAL_COLUMNS)]
    merged = existing_by_key.reset_index(drop=True)
    merged = _validate_canonical_frame(merged, label="Reconciled canonical history")
    return CanonicalReconciliation(
        history=merged,
        appended_keys=tuple(sorted(appended)),
        revised_keys=tuple(sorted(revised)),
        unchanged_keys=tuple(sorted(unchanged)),
    )
