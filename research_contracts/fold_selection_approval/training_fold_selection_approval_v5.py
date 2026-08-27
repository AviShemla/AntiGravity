"""Fail-closed S08 proposal v5 with reconstructable lineage and fold geometry.

This module only creates an approval proposal.  Its pinned trust root is absent,
so preflight can only return APPROVAL_REQUIRED with zero selections.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
from types import MappingProxyType
from typing import Mapping

from .training_fold_selection_approval_v4 import (
    ApprovalProposal as V4Proposal, ProposalInputs as V4Inputs, ProposalError,
    build_proposal as build_v4_proposal, canonical_json_bytes, sha256,
)


CONTRACT_ID = "codex-oracle-s08-approval-proposal-v5"
PINNED_APPROVAL_RECORD_BYTES: bytes | None = None
PINNED_APPROVAL_RECORD_SHA256: str | None = None
STATUS = "APPROVAL_REQUIRED"
EXPECTED_CANDIDATES_PER_FOLD = 1_569_414
EXPECTED_TOTAL_HYPOTHESES = 6_277_656
ENUMERATION_ORDER = "TARGET_ASC_SOURCE_ASC_LAG_ASC"
FOLD_GEOMETRY = (
    {"fold": 1, "train_start_index": 0, "train_end_index": 288,
     "purge_start_index": 289, "purge_end_index": 295,
     "test_start_index": 296, "test_end_index": 325},
    {"fold": 2, "train_start_index": 30, "train_end_index": 318,
     "purge_start_index": 319, "purge_end_index": 325,
     "test_start_index": 326, "test_end_index": 355},
    {"fold": 3, "train_start_index": 60, "train_end_index": 348,
     "purge_start_index": 349, "purge_end_index": 355,
     "test_start_index": 356, "test_end_index": 385},
    {"fold": 4, "train_start_index": 90, "train_end_index": 378,
     "purge_start_index": 379, "purge_end_index": 385,
     "test_start_index": 386, "test_end_index": 415},
)
_RFC3339_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_SHA = re.compile(r"[0-9a-f]{64}")


def parse_rfc3339_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not _RFC3339_Z.fullmatch(value):
        raise ProposalError(f"{label} must be strict RFC3339 UTC ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProposalError(f"{label} is not a real UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ProposalError(f"{label} must be UTC")
    return parsed


def parse_canonical_object(raw: bytes, label: str) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw:
        raise ProposalError(f"{label} bytes are absent")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalError(f"{label} is not strict UTF-8 JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProposalError(f"{label} must be a canonical JSON object")
    return MappingProxyType(value)


@dataclass(frozen=True)
class ProposalInputs:
    tickers: tuple[str, ...]
    frozen_session_dates: tuple[str, ...]
    universe_lineage_bytes: bytes
    derivation_cutoff_utc: str
    frozen_dataset_version: str
    frozen_content_sha256: str
    frozen_readback_sha256: str
    frozen_readback_at_utc: str
    snapshot_id: str
    snapshot_sha256: str
    preregistration_sha256: str
    selector_source_bytes: bytes
    selector_git_commit: str
    selector_release_bytes: bytes
    dependency_lock_bytes: bytes
    verifier_source_bytes: bytes


@dataclass(frozen=True)
class ApprovalProposal:
    status: str
    selections: tuple[()]
    proposal_core_bytes: bytes
    proposal_core_sha256: str
    approval_record_bytes: bytes
    approval_record_sha256: str
    artifacts: Mapping[str, bytes]
    artifact_sha256: Mapping[str, str]


@dataclass(frozen=True)
class PreflightResult:
    status: str
    selections: tuple[()]
    proposal_core_sha256: str
    pinned_approval_record_sha256: None
    reason: str


def candidate_ordinal(target_rank: int, source_rank: int, lag: int) -> int:
    """Zero-based ordinal for TARGET_ASC_SOURCE_ASC_LAG_ASC, excluding self."""
    if not (0 <= target_rank < 474 and 0 <= source_rank < 474):
        raise ProposalError("ticker rank outside 0..473")
    if target_rank == source_rank:
        raise ProposalError("self edge is excluded")
    if lag not in range(1, 8):
        raise ProposalError("lag outside 1..7")
    compact_source = source_rank if source_rank < target_rank else source_rank - 1
    return target_rank * (473 * 7) + compact_source * 7 + lag - 1


def reconstruct_candidate(ordinal: int) -> tuple[int, int, int]:
    if not (0 <= ordinal < EXPECTED_CANDIDATES_PER_FOLD):
        raise ProposalError("candidate ordinal outside complete family")
    target, remainder = divmod(ordinal, 473 * 7)
    compact_source, lag0 = divmod(remainder, 7)
    source = compact_source if compact_source < target else compact_source + 1
    return target, source, lag0 + 1


def _validate_lineage(p: ProposalInputs, ticker_raw: bytes) -> None:
    lineage = parse_canonical_object(p.universe_lineage_bytes, "universe lineage")
    expected = {
        "contract": "exact-frozen-ticker-universe-lineage-v1",
        "frozen_dataset_version": p.frozen_dataset_version,
        "snapshot_id": p.snapshot_id,
        "snapshot_sha256": p.snapshot_sha256,
        "ticker_count": 474,
        "ticker_universe_bytes_sha256": sha256(ticker_raw),
    }
    if dict(lineage) != expected:
        raise ProposalError("universe lineage contradicts exact ticker/snapshot/dataset bytes")


def _validate_geometry() -> None:
    for g in FOLD_GEOMETRY:
        if g["train_end_index"] + 1 != g["purge_start_index"]:
            raise AssertionError("train/purge geometry gap or overlap")
        if g["purge_end_index"] + 1 != g["test_start_index"]:
            raise AssertionError("purge/test geometry gap or overlap")
        if g["purge_end_index"] - g["purge_start_index"] + 1 != 7:
            raise AssertionError("purge must be exactly seven sessions")
        if g["test_end_index"] - g["test_start_index"] + 1 != 30:
            raise AssertionError("test must be exactly thirty sessions")
        if g["train_end_index"] - g["train_start_index"] + 1 != 289:
            raise AssertionError("train must be exactly 289 sessions")


def build_proposal(p: ProposalInputs) -> ApprovalProposal:
    ticker_raw = canonical_json_bytes(list(p.tickers))
    if not _SHA.fullmatch(p.snapshot_sha256):
        raise ProposalError("snapshot_sha256 must be exact lowercase SHA-256")
    cutoff = parse_rfc3339_utc(p.derivation_cutoff_utc, "derivation cutoff")
    readback = parse_rfc3339_utc(p.frozen_readback_at_utc, "frozen readback time")
    if readback < cutoff:
        raise ProposalError("frozen readback cannot precede derivation cutoff")
    _validate_lineage(p, ticker_raw)
    _validate_geometry()
    if len(p.frozen_session_dates) < 416 or len(set(p.frozen_session_dates)) != len(p.frozen_session_dates):
        raise ProposalError("frozen session calendar must contain at least 416 unique dates")
    try:
        parsed_dates = tuple(date.fromisoformat(x) for x in p.frozen_session_dates)
    except ValueError as exc:
        raise ProposalError("frozen session calendar contains an invalid ISO date") from exc
    if tuple(sorted(parsed_dates)) != parsed_dates or any(d.isoformat() != raw for d, raw in zip(parsed_dates, p.frozen_session_dates)):
        raise ProposalError("frozen session calendar must be strictly increasing canonical ISO dates")
    calendar_raw = canonical_json_bytes(list(p.frozen_session_dates))
    v4: V4Proposal = build_v4_proposal(V4Inputs(
        tickers=p.tickers, derivation_cutoff_utc=p.derivation_cutoff_utc,
        frozen_dataset_version=p.frozen_dataset_version,
        frozen_content_sha256=p.frozen_content_sha256,
        frozen_readback_sha256=p.frozen_readback_sha256,
        frozen_readback_at_utc=p.frozen_readback_at_utc,
        snapshot_id=p.snapshot_id, universe_lineage_sha256=sha256(p.universe_lineage_bytes),
        preregistration_sha256=p.preregistration_sha256,
        selector_source_bytes=p.selector_source_bytes,
        selector_git_commit=p.selector_git_commit,
        selector_release_bytes=p.selector_release_bytes,
        dependency_lock_bytes=p.dependency_lock_bytes,
        verifier_source_bytes=p.verifier_source_bytes))
    enumeration_raw = canonical_json_bytes({
        "contract": "complete-candidate-enumeration-v1",
        "count": EXPECTED_CANDIDATES_PER_FOLD,
        "exclusion": "SOURCE_EQUALS_TARGET",
        "lags": [1, 2, 3, 4, 5, 6, 7],
        "ordinal_formula": "target_rank*3311+(source_rank-(source_rank>target_rank))*7+(lag-1)",
        "order": ENUMERATION_ORDER,
        "reconstruction": "target=ordinal//3311; r=ordinal%3311; compact_source=r//7; source=compact_source+(compact_source>=target); lag=r%7+1",
    })
    dated_geometry = []
    for g in FOLD_GEOMETRY:
        bound = dict(g)
        for prefix in ("train", "purge", "test"):
            bound[f"{prefix}_start_date"] = p.frozen_session_dates[g[f"{prefix}_start_index"]]
            bound[f"{prefix}_end_date"] = p.frozen_session_dates[g[f"{prefix}_end_index"]]
        dated_geometry.append(bound)
    geometry_raw = canonical_json_bytes({
        "calendar_binding": "FROZEN_SESSION_CALENDAR_INDEX_ZERO_BASED_INCLUSIVE",
        "calendar_bytes_sha256": sha256(calendar_raw),
        "contract": "exact-four-fold-train-purge-test-geometry-v1",
        "folds": dated_geometry,
        "purge_sessions": 7,
        "test_sessions": 30,
        "train_sessions": 289,
        "within_fold_zero_overlap_required": True,
    })
    artifacts = dict(v4.artifacts)
    artifacts.update({
        "candidate_enumeration.json": enumeration_raw,
        "fold_geometry.json": geometry_raw,
        "frozen_session_calendar.json": calendar_raw,
        "universe_lineage.json": p.universe_lineage_bytes,
    })
    hashes = {name: sha256(raw) for name, raw in sorted(artifacts.items())}
    core_raw = canonical_json_bytes({
        "artifact_sha256": hashes,
        "approval_state": STATUS,
        "contract": CONTRACT_ID,
        "derivation_cutoff_utc": p.derivation_cutoff_utc,
        "frozen_readback_at_utc": p.frozen_readback_at_utc,
        "readback_max_age_seconds_at_future_execution": 300,
        "selections": 0,
        "snapshot_id": p.snapshot_id,
        "snapshot_sha256": p.snapshot_sha256,
        "universe_lineage_bytes_sha256": sha256(p.universe_lineage_bytes),
    })
    core_sha = sha256(core_raw)
    manifest_sha = sha256(canonical_json_bytes(hashes))
    wording = (
        "I, Avi, approve only S08 training-fold selection evaluation bound exactly "
        f"to proposal-core SHA-256 {core_sha}, artifact manifest SHA-256 {manifest_sha}, "
        f"and snapshot SHA-256 {p.snapshot_sha256}. This does not authorize predictions, "
        "recommendations, orders, trading, ETF priors, promotion, or weakened safeguards."
    )
    approval_raw = canonical_json_bytes({
        "approval_record_contract": "avi-exact-s08-approval-record-proposal-v2",
        "artifact_manifest_sha256": manifest_sha,
        "proposal_core_sha256": core_sha,
        "required_exact_wording": wording,
        "signer": "AVI",
        "snapshot_sha256": p.snapshot_sha256,
        "status": "UNSIGNED_PROPOSAL_NOT_AUTHORITY",
    })
    return ApprovalProposal(STATUS, (), core_raw, core_sha, approval_raw,
                            sha256(approval_raw), MappingProxyType(artifacts),
                            MappingProxyType(hashes))


def preflight(proposal: ApprovalProposal, **_untrusted: object) -> PreflightResult:
    if PINNED_APPROVAL_RECORD_BYTES is not None or PINNED_APPROVAL_RECORD_SHA256 is not None:
        raise RuntimeError("v5 invariant violated: trust root must remain unpinned")
    if sha256(proposal.proposal_core_bytes) != proposal.proposal_core_sha256:
        raise ProposalError("proposal core is not self-consistent")
    return PreflightResult(STATUS, (), proposal.proposal_core_sha256, None,
                           "no approval trust root is pinned in v5")

