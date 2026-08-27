"""Fail-closed bridge audit from a frozen dataset readback to S08 inputs.

The production freeze reader proves immutable dataset identity, coverage, and
provider lineage.  It intentionally does not return market feature rows or
fold-local edge selections.  Consequently that readback alone cannot produce
the 474-target x four-fold normalized-edge bundle.  This module records that
boundary as canonical, machine-readable evidence without performing I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
from typing import Mapping


CONTRACT_ID = "codex-oracle-s08-freeze-readback-gap-v1"
NORMALIZED_EDGE_INPUT_CONTRACT_ID = "codex-oracle-s08-normalized-edge-input-v1"
EXPECTED_TARGETS = 474
EXPECTED_FOLDS = 4
EXPECTED_PAYLOADS = EXPECTED_TARGETS * EXPECTED_FOLDS

FREEZE_READBACK_FIELDS = (
    "dataset_version_id",
    "market_snapshot_id",
    "market_snapshot_checksum_sha256",
    "source_session_date",
    "evidence_cutoff_utc",
    "first_session_date",
    "last_session_date",
    "expected_row_count",
    "expected_ticker_count",
    "expected_session_count",
    "expected_provider_lineage_count",
    "content_sha256",
    "ticker_universe_sha256",
    "provider_lineage_sha256",
    "schema_version",
    "code_version",
    "freeze_approval_id",
    "frozen_by",
    "frozen_at_utc",
    "provider_lineage",
)


class FreezeReadbackGapError(RuntimeError):
    """Raised when metadata-only freeze evidence is used as model input."""

    def __init__(self, report: "FreezeReadbackGapReport") -> None:
        super().__init__(
            "frozen dataset readback is identity evidence, not the 474x4 "
            "normalized-edge input dataset"
        )
        self.report = report


@dataclass(frozen=True)
class FreezeReadbackGapReport:
    contract_id: str
    normalized_edge_input_contract_id: str
    freeze_readback_type: str
    observed_freeze_fields: tuple[str, ...]
    expected_targets: int
    expected_folds: int
    expected_payloads: int
    sufficient: bool
    missing_inputs: tuple[Mapping[str, object], ...]
    prohibited_inferences: tuple[str, ...]
    side_effects: Mapping[str, int]
    evidence_sha256: str


def _primitive(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    return value


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _primitive(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


def _missing_inputs() -> tuple[Mapping[str, object], ...]:
    return (
        {
            "input_id": "model_session_calendar",
            "required_fields": (
                "session_dates[416]", "full_session_calendar_sha256",
                "model_session_dates_sha256",
            ),
            "required_contract": "exact S07 preregistered 416-session slice",
            "reason": "freeze metadata supplies only first/last/count, not ordered sessions",
        },
        {
            "input_id": "market_feature_rows",
            "required_fields": (
                "snapshot_id", "ticker", "date", "daily_return_pct",
            ),
            "required_contract": (
                "injected canonical rows bound to market_snapshot_id and content_sha256; "
                "complete 474-ticker x 416-session model slice"
            ),
            "reason": "freeze readback reconciles row digests/counts but retains zero content rows",
        },
        {
            "input_id": "fold_local_normalized_edge_selections",
            "required_fields": (
                "target_ticker", "fold_number", "source_ticker", "lag_sessions",
                "lag_semantics", "selection_end_ordinal",
                "selection_artifact_sha256",
            ),
            "required_contract": (
                "training-only independent ticker/lag edges; lags 1-7; depth 1-5; "
                "exact 474 targets x four leakage-free folds"
            ),
            "reason": "freeze readback contains no screening or fold-local edge records",
        },
        {
            "input_id": "s07_preregistration_proof",
            "required_fields": (
                "preregistration_raw_sha256", "checkpoint_identity_sha256",
                "model_code_git_commit", "model_config_sha256", "sampler_sha256",
                "current_readback_observed_at_utc",
            ),
            "required_contract": (
                "fresh verified S07 proof that remains fixture_only=true and "
                "model_fit_authorized=false; a separate exact-run authorization is required"
            ),
            "reason": "freeze approval proves dataset immutability, not model-run authorization",
        },
        {
            "input_id": "fold_payload_lineage",
            "required_fields": (
                "payload_key", "payload_sha256", "payload_size_bytes",
                "train_start_ordinal", "train_end_ordinal", "test_start_ordinal",
                "test_end_ordinal", "purge_sessions",
            ),
            "required_contract": "1,896 deterministic binary payload descriptors and bodies",
            "reason": "freeze readback contains no materialized fold payloads",
        },
    )


def audit_freeze_readback_gap(freeze_readback: object) -> FreezeReadbackGapReport:
    """Return canonical evidence that the exact freeze shape is insufficient.

    ``freeze_readback`` is injected.  The function has no filesystem, network,
    database, process, model, or persistence capability.
    """
    if freeze_readback is None or not is_dataclass(freeze_readback):
        raise TypeError("freeze_readback must be an exact frozen dataclass instance")
    observed = tuple(field.name for field in fields(freeze_readback))
    if observed != FREEZE_READBACK_FIELDS:
        raise TypeError("freeze_readback field contract differs from the reviewed frozen shape")

    payload = {
        "contract_id": CONTRACT_ID,
        "normalized_edge_input_contract_id": NORMALIZED_EDGE_INPUT_CONTRACT_ID,
        "freeze_readback_type": type(freeze_readback).__name__,
        "observed_freeze_fields": observed,
        "expected_targets": EXPECTED_TARGETS,
        "expected_folds": EXPECTED_FOLDS,
        "expected_payloads": EXPECTED_PAYLOADS,
        "sufficient": False,
        "missing_inputs": _missing_inputs(),
        "prohibited_inferences": (
            "do not infer ordered market rows from content_sha256",
            "do not infer model sessions from first/last/count metadata",
            "do not reuse positional lag1_ticker through lag5_ticker fields",
            "do not infer fold-local edges from provider lineage",
            "do not launch or authorize a fit from dataset freeze approval",
        ),
        "side_effects": {
            "database_reads": 0, "database_writes": 0, "network_calls": 0,
            "model_fits": 0, "predictions": 0, "recommendations": 0,
            "orders": 0, "etf_outputs": 0,
        },
    }
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return FreezeReadbackGapReport(**payload, evidence_sha256=digest)


def require_normalized_edge_inputs(freeze_readback: object) -> None:
    """Fail closed until the separately governed injected inputs exist."""
    raise FreezeReadbackGapError(audit_freeze_readback_gap(freeze_readback))
