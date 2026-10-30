"""Pure validation for versioned DB-backed instrument governance."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping

from model_lineage import AssetClass, LineageError


class RegistryStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class InstrumentUsage(StrEnum):
    MODEL_CANDIDATE = "MODEL_CANDIDATE"
    VALUATION_ONLY = "VALUATION_ONLY"
    BENCHMARK = "BENCHMARK"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class RegistryVersion:
    registry_id: str
    status: RegistryStatus
    evidence_as_of_date: str
    source_evidence: Mapping[str, object]
    approved_by: str | None = None
    approved_at_utc: str | None = None

    def canonical_evidence(self) -> str:
        try:
            return json.dumps(
                self.source_evidence,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise LineageError("Registry source evidence is not canonical JSON.") from exc

    def evidence_sha256(self) -> str:
        return hashlib.sha256(self.canonical_evidence().encode("utf-8")).hexdigest()

    def validate(self) -> None:
        if not self.registry_id or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.evidence_as_of_date):
            raise LineageError("Registry ID and evidence date are required.")
        self.canonical_evidence()
        if self.status is RegistryStatus.APPROVED and (
            not self.approved_by or not self.approved_at_utc
        ):
            raise LineageError("Approved registry requires approver and timestamp.")


@dataclass(frozen=True)
class InstrumentSpec:
    registry_id: str
    ticker: str
    asset_class: AssetClass
    sector: str | None
    usage: InstrumentUsage
    minimum_history_rows: int
    classification_reason: str

    def validate_for(self, version: RegistryVersion) -> None:
        version.validate()
        if self.registry_id != version.registry_id:
            raise LineageError("Instrument registry ID does not match its version.")
        if not re.fullmatch(r"(?:\^[A-Z0-9]{1,8}|[A-Z][A-Z0-9.\-]{0,14})", self.ticker):
            raise LineageError("Instrument ticker is invalid.")
        if self.minimum_history_rows <= 0:
            raise LineageError("Instrument minimum history must be positive.")
        if not self.classification_reason:
            raise LineageError("Instrument classification requires evidence.")


def validate_registry_for_model_use(
    version: RegistryVersion,
    instruments: Iterable[InstrumentSpec],
) -> tuple[InstrumentSpec, ...]:
    if version.status is not RegistryStatus.APPROVED:
        raise LineageError("Only an approved registry may control a model run.")
    items = tuple(instruments)
    tickers = set()
    for item in items:
        item.validate_for(version)
        if item.ticker in tickers:
            raise LineageError("Registry contains duplicate tickers.")
        tickers.add(item.ticker)
    if not any(item.asset_class is AssetClass.STOCK for item in items):
        raise LineageError("Registry must contain a stock universe.")
    if not any(
        item.asset_class is AssetClass.ETF
        and item.usage is InstrumentUsage.MODEL_CANDIDATE
        for item in items
    ):
        raise LineageError("Registry must contain at least one ETF model candidate.")
    return items
