"""Fail-closed 472-ticker S08 fold-selection proposal successor.

The proposal derives one complete-case universe from a canonical 474 by 417
presence mask.  It creates content-addressed proposal artifacts only: approval,
selection, model execution, persistence, and downstream activity remain absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from types import MappingProxyType
from typing import Mapping

from .training_fold_selection_approval_v5 import (
    FOLD_GEOMETRY, ProposalError, canonical_json_bytes, sha256,
)


CONTRACT_ID = "codex-oracle-s08-approval-proposal-v6-472-complete-case"
PRESENCE_MASK_CONTRACT = "s08-474-ticker-417-date-presence-mask-v1"
PINNED_APPROVAL_RECORD_BYTES: bytes | None = None
PINNED_APPROVAL_RECORD_SHA256: str | None = None
STATUS = "APPROVAL_REQUIRED"
UPSTREAM_TICKER_COUNT = 474
SESSION_COUNT = 417
ELIGIBLE_TICKER_COUNT = 472
LAGS = tuple(range(1, 8))
FOLD_COUNT = 4
EXPECTED_CANDIDATES_PER_FOLD = 1_556_184
EXPECTED_TOTAL_HYPOTHESES = 6_224_736
EXPECTED_TARGET_FOLD_GROUPS = 1_888
EXPECTED_OOS_OBSERVATIONS = 56_640
EXCLUSION_PRESENCE_COUNTS = MappingProxyType({"FISV": 416, "SNDK": 358})
ENUMERATION_ORDER = "TARGET_ASC_SOURCE_ASC_LAG_ASC"
_SHA = re.compile(r"[0-9a-f]{64}")
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,14}")


@dataclass(frozen=True)
class ProposalInputs:
    upstream_tickers: tuple[str, ...]
    presence_mask_bytes: bytes
    upstream_universe_sha256: str
    presence_mask_sha256: str
    eligible_universe_sha256: str
    prior_preregistration_sha256: str


@dataclass(frozen=True)
class ApprovalProposal:
    status: str
    selections: tuple[()]
    proposal_core_bytes: bytes
    proposal_core_sha256: str
    artifacts: Mapping[str, bytes]
    artifact_sha256: Mapping[str, str]


@dataclass(frozen=True)
class PreflightResult:
    status: str
    selections: tuple[()]
    proposal_core_sha256: str
    pinned_approval_record_sha256: None
    reason: str


def _require_sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ProposalError(f"{label} must be exact lowercase SHA-256")


def _parse_presence_mask(raw: bytes) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], Mapping[str, int]]:
    if type(raw) is not bytes or not raw:
        raise ProposalError("presence mask bytes are absent")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalError("presence mask is not strict UTF-8 JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProposalError("presence mask must be one canonical JSON object")
    if set(value) != {"contract", "session_dates", "ticker_order", "presence_rows"}:
        raise ProposalError("presence mask fields differ")
    if value["contract"] != PRESENCE_MASK_CONTRACT:
        raise ProposalError("presence mask contract differs")
    dates = value["session_dates"]
    tickers = value["ticker_order"]
    rows = value["presence_rows"]
    if type(dates) is not list or len(dates) != SESSION_COUNT or dates != sorted(set(dates)):
        raise ProposalError("presence mask must bind 417 distinct sorted dates")
    try:
        parsed_dates = tuple(date.fromisoformat(value) for value in dates)
    except (TypeError, ValueError) as exc:
        raise ProposalError("presence mask contains a non-canonical date") from exc
    if any(value.isoformat() != raw for value, raw in zip(parsed_dates, dates)):
        raise ProposalError("presence mask contains a non-canonical date")
    if type(tickers) is not list or len(tickers) != UPSTREAM_TICKER_COUNT or tickers != sorted(set(tickers)):
        raise ProposalError("presence mask must bind 474 distinct sorted tickers")
    if type(rows) is not list or len(rows) != UPSTREAM_TICKER_COUNT:
        raise ProposalError("presence mask row count differs")
    counts: dict[str, int] = {}
    eligible: list[str] = []
    for ticker, row in zip(tickers, rows):
        if not isinstance(ticker, str) or not _TICKER.fullmatch(ticker):
            raise ProposalError("presence mask ticker is unsafe")
        if type(row) is not str or len(row) != SESSION_COUNT or set(row) - {"0", "1"}:
            raise ProposalError("presence row must contain exactly 417 binary observations")
        count = row.count("1")
        counts[ticker] = count
        if count == SESSION_COUNT:
            eligible.append(ticker)
    return tuple(tickers), tuple(dates), tuple(eligible), MappingProxyType(counts)


def candidate_ordinal(target_rank: int, source_rank: int, lag: int) -> int:
    """Zero-based ordinal for a complete 472-ticker directed edge family."""
    if (not isinstance(target_rank, int) or isinstance(target_rank, bool)
            or not isinstance(source_rank, int) or isinstance(source_rank, bool)
            or not (0 <= target_rank < ELIGIBLE_TICKER_COUNT and 0 <= source_rank < ELIGIBLE_TICKER_COUNT)):
        raise ProposalError("eligible ticker rank outside 0..471")
    if target_rank == source_rank:
        raise ProposalError("self edge is excluded")
    if not isinstance(lag, int) or isinstance(lag, bool) or lag not in LAGS:
        raise ProposalError("lag outside 1..7")
    compact_source = source_rank if source_rank < target_rank else source_rank - 1
    return target_rank * (471 * 7) + compact_source * 7 + lag - 1


def reconstruct_candidate(ordinal: int) -> tuple[int, int, int]:
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or not (0 <= ordinal < EXPECTED_CANDIDATES_PER_FOLD):
        raise ProposalError("candidate ordinal outside complete family")
    target, remainder = divmod(ordinal, 471 * 7)
    compact_source, lag0 = divmod(remainder, 7)
    source = compact_source if compact_source < target else compact_source + 1
    return target, source, lag0 + 1


def _validate_fold_geometry() -> None:
    if len(FOLD_GEOMETRY) != FOLD_COUNT:
        raise ProposalError("fold count differs")
    for fold in FOLD_GEOMETRY:
        if fold["train_end_index"] + 1 != fold["purge_start_index"]:
            raise ProposalError("train/purge geometry differs")
        if fold["purge_end_index"] + 1 != fold["test_start_index"]:
            raise ProposalError("purge/test geometry differs")
        if fold["purge_end_index"] - fold["purge_start_index"] + 1 != 7:
            raise ProposalError("purge geometry differs")
        if fold["test_end_index"] - fold["test_start_index"] + 1 != 30:
            raise ProposalError("test geometry differs")
        if fold["train_end_index"] - fold["train_start_index"] + 1 != 289:
            raise ProposalError("training geometry differs")


def build_proposal(p: ProposalInputs) -> ApprovalProposal:
    if type(p) is not ProposalInputs:
        raise ProposalError("proposal input type differs")
    for label in ("upstream_universe_sha256", "presence_mask_sha256",
                  "eligible_universe_sha256", "prior_preregistration_sha256"):
        _require_sha(getattr(p, label), label)
    if len(p.upstream_tickers) != UPSTREAM_TICKER_COUNT or tuple(sorted(set(p.upstream_tickers))) != p.upstream_tickers:
        raise ProposalError("upstream universe must contain exactly 474 sorted distinct tickers")
    upstream_raw = canonical_json_bytes(list(p.upstream_tickers))
    if sha256(upstream_raw) != p.upstream_universe_sha256:
        raise ProposalError("upstream universe hash differs")
    if sha256(p.presence_mask_bytes) != p.presence_mask_sha256:
        raise ProposalError("presence mask hash differs")
    mask_tickers, dates, eligible, counts = _parse_presence_mask(p.presence_mask_bytes)
    if mask_tickers != p.upstream_tickers:
        raise ProposalError("presence mask ticker order differs from upstream universe")
    if eligible != tuple(sorted(eligible)) or len(eligible) != ELIGIBLE_TICKER_COUNT:
        raise ProposalError("complete-case eligible universe must contain exactly 472 sorted tickers")
    if set(p.upstream_tickers) - set(eligible) != set(EXCLUSION_PRESENCE_COUNTS):
        raise ProposalError("symmetric target/source exclusion set differs")
    for ticker, expected in EXCLUSION_PRESENCE_COUNTS.items():
        if counts.get(ticker) != expected:
            raise ProposalError(f"{ticker} presence count differs")
    if any(counts[ticker] != SESSION_COUNT for ticker in eligible):
        raise ProposalError("eligible universe contains an incomplete ticker")
    eligible_raw = canonical_json_bytes(list(eligible))
    if sha256(eligible_raw) != p.eligible_universe_sha256:
        raise ProposalError("eligible universe hash differs")
    _validate_fold_geometry()
    if EXPECTED_CANDIDATES_PER_FOLD != ELIGIBLE_TICKER_COUNT * (ELIGIBLE_TICKER_COUNT - 1) * len(LAGS):
        raise AssertionError("candidate family constant differs")
    if EXPECTED_TOTAL_HYPOTHESES != FOLD_COUNT * EXPECTED_CANDIDATES_PER_FOLD:
        raise AssertionError("total hypothesis constant differs")
    if EXPECTED_TARGET_FOLD_GROUPS != FOLD_COUNT * ELIGIBLE_TICKER_COUNT:
        raise AssertionError("target-fold group constant differs")
    if EXPECTED_OOS_OBSERVATIONS != FOLD_COUNT * ELIGIBLE_TICKER_COUNT * 30:
        raise AssertionError("OOS observation constant differs")

    exclusions_raw = canonical_json_bytes({
        "contract": "s08-symmetric-complete-case-exclusions-v1",
        "excluded_from_source": dict(EXCLUSION_PRESENCE_COUNTS),
        "excluded_from_target": dict(EXCLUSION_PRESENCE_COUNTS),
        "rule": "PRESENCE_COUNT_MUST_EQUAL_417_ZERO_IMPUTATION",
    })
    enumeration_raw = canonical_json_bytes({
        "candidates_per_fold": EXPECTED_CANDIDATES_PER_FOLD,
        "eligible_ticker_count": ELIGIBLE_TICKER_COUNT,
        "lags": list(LAGS),
        "order": ENUMERATION_ORDER,
        "ordinal_formula": "target_rank*3297+(source_rank-(source_rank>target_rank))*7+(lag-1)",
        "symmetric_self_edge_exclusion": True,
        "total_hypotheses": EXPECTED_TOTAL_HYPOTHESES,
    })
    fold_raw = canonical_json_bytes({
        "contract": "s08-unchanged-four-fold-geometry-v6",
        "folds": list(FOLD_GEOMETRY),
        "oos_observations": EXPECTED_OOS_OBSERVATIONS,
        "target_fold_groups": EXPECTED_TARGET_FOLD_GROUPS,
    })
    lineage_raw = canonical_json_bytes({
        "eligible_universe_sha256": p.eligible_universe_sha256,
        "presence_mask_sha256": p.presence_mask_sha256,
        "prior_preregistration_sha256": p.prior_preregistration_sha256,
        "session_count": len(dates),
        "upstream_universe_sha256": p.upstream_universe_sha256,
        "zero_imputation": True,
    })
    artifacts = MappingProxyType({
        "eligible_universe.json": eligible_raw,
        "exclusions.json": exclusions_raw,
        "fold_geometry.json": fold_raw,
        "lineage.json": lineage_raw,
        "candidate_enumeration.json": enumeration_raw,
    })
    hashes = MappingProxyType({name: sha256(raw) for name, raw in sorted(artifacts.items())})
    core_raw = canonical_json_bytes({
        "approval_state": STATUS,
        "artifact_sha256": dict(hashes),
        "candidates_per_fold": EXPECTED_CANDIDATES_PER_FOLD,
        "contract": CONTRACT_ID,
        "eligible_ticker_count": ELIGIBLE_TICKER_COUNT,
        "execution_authorized": False,
        "fold_count": FOLD_COUNT,
        "oos_observations": EXPECTED_OOS_OBSERVATIONS,
        "selections": 0,
        "target_fold_groups": EXPECTED_TARGET_FOLD_GROUPS,
        "total_hypotheses": EXPECTED_TOTAL_HYPOTHESES,
    })
    return ApprovalProposal(STATUS, (), core_raw, sha256(core_raw), artifacts, hashes)


def preflight(proposal: ApprovalProposal, **_untrusted: object) -> PreflightResult:
    if PINNED_APPROVAL_RECORD_BYTES is not None or PINNED_APPROVAL_RECORD_SHA256 is not None:
        raise RuntimeError("v6 invariant violated: approval trust root must remain absent")
    if type(proposal) is not ApprovalProposal:
        raise ProposalError("proposal type differs")
    if sha256(proposal.proposal_core_bytes) != proposal.proposal_core_sha256:
        raise ProposalError("proposal core is not self-consistent")
    if proposal.status != STATUS or proposal.selections != ():
        raise ProposalError("proposal crosses approval boundary")
    return PreflightResult(STATUS, (), proposal.proposal_core_sha256, None,
                           "no approval trust root is pinned in v6")
