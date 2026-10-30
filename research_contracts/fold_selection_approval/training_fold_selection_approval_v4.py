"""Non-authorizing proposal generator for the S08 fold-selection contract.

This isolated module deliberately has no approved trust root.  It cannot turn
approval-shaped caller data into authority and cannot execute statistics.  A
future, separately reviewed canonical commit must pin Avi's exact approval
record bytes and SHA-256 before an execution gate can exist.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping


CONTRACT_ID = "codex-oracle-s08-approval-proposal-v4"
PINNED_APPROVAL_RECORD_BYTES: bytes | None = None
PINNED_APPROVAL_RECORD_SHA256: str | None = None
STATUS = "APPROVAL_REQUIRED"
EXPECTED_TICKERS = 474
LAGS = tuple(range(1, 8))
DEPTHS = tuple(range(1, 6))
FOLDS = 4
EXPECTED_CANDIDATES_PER_FOLD = 474 * 473 * 7
EXPECTED_TOTAL_HYPOTHESES = EXPECTED_CANDIDATES_PER_FOLD * FOLDS
_SHA = re.compile(r"[0-9a-f]{64}")
_GIT = re.compile(r"[0-9a-f]{40}")
_TICKER = re.compile(r"[A-Z0-9.^-]{1,24}")


class ProposalError(ValueError):
    pass


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProposalError("proposal value is not canonical JSON") from exc


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: str, label: str) -> None:
    if not _SHA.fullmatch(value):
        raise ProposalError(f"{label} must be lowercase SHA-256")


@dataclass(frozen=True)
class ProposalInputs:
    tickers: tuple[str, ...]
    derivation_cutoff_utc: str
    frozen_dataset_version: str
    frozen_content_sha256: str
    frozen_readback_sha256: str
    frozen_readback_at_utc: str
    snapshot_id: str
    universe_lineage_sha256: str
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


def _validate_inputs(p: ProposalInputs) -> None:
    if len(p.tickers) != EXPECTED_TICKERS or len(set(p.tickers)) != EXPECTED_TICKERS:
        raise ProposalError("exactly 474 unique tickers are required")
    if tuple(sorted(p.tickers)) != p.tickers or any(not _TICKER.fullmatch(x) for x in p.tickers):
        raise ProposalError("tickers must be valid and canonically sorted")
    for name in ("frozen_content_sha256", "frozen_readback_sha256",
                 "universe_lineage_sha256", "preregistration_sha256"):
        _require_sha(getattr(p, name), name)
    if not _GIT.fullmatch(p.selector_git_commit):
        raise ProposalError("selector_git_commit must be a full lowercase Git identity")
    for name in ("selector_source_bytes", "selector_release_bytes",
                 "dependency_lock_bytes", "verifier_source_bytes"):
        value = getattr(p, name)
        if type(value) is not bytes or not value:
            raise ProposalError(f"{name} must contain exact non-empty bytes")
    if not p.derivation_cutoff_utc.endswith("Z") or not p.frozen_readback_at_utc.endswith("Z"):
        raise ProposalError("derivation cutoff and frozen readback time must be canonical UTC")


def build_proposal(p: ProposalInputs) -> ApprovalProposal:
    """Build a deterministic, reviewable package; never grant authority."""
    _validate_inputs(p)
    ticker_raw = canonical_json_bytes(list(p.tickers))
    candidate_raw = canonical_json_bytes({
        "contract": "complete-source-target-lag-family-v4",
        "candidate_count_per_fold": EXPECTED_CANDIDATES_PER_FOLD,
        "derivation_cutoff_utc": p.derivation_cutoff_utc,
        "derivation_window": "NONE_COMPLETE_UNIVERSE",
        "exclusions": ["SOURCE_EQUALS_TARGET"],
        "forbid_future_or_test_informed_preselection": True,
        "frozen_content_sha256": p.frozen_content_sha256,
        "frozen_dataset_version": p.frozen_dataset_version,
        "frozen_readback_sha256": p.frozen_readback_sha256,
        "frozen_readback_at_utc": p.frozen_readback_at_utc,
        "lags": list(LAGS),
        "snapshot_id": p.snapshot_id,
        "sources": "ALL_474_TICKERS",
        "targets": "ALL_474_TICKERS",
        "ticker_universe_bytes_sha256": sha256(ticker_raw),
        "universe_lineage_sha256": p.universe_lineage_sha256,
        "preregistration_sha256": p.preregistration_sha256,
    })
    selector_raw = canonical_json_bytes({
        "contract": "immutable-selector-code-closure-v4",
        "dependency_lock_bytes_sha256": sha256(p.dependency_lock_bytes),
        "git_commit": p.selector_git_commit,
        "immutable_reviewed_release_required": True,
        "release_bytes_sha256": sha256(p.selector_release_bytes),
        "source_bytes_sha256": sha256(p.selector_source_bytes),
    })
    verifier_raw = canonical_json_bytes({
        "contract": "independent-verifier-closure-v4",
        "independent_execution_required": True,
        "independent_reviewer_identity_and_signature_required": True,
        "review_event_must_predate_evaluation": True,
        "source_bytes_sha256": sha256(p.verifier_source_bytes),
    })
    policy_raw = canonical_json_bytes({
        "association": "CENTERED_PEARSON_FISHER_Z",
        "candidate_family_bytes_sha256": sha256(candidate_raw),
        "claim": "OBSERVATIONAL_PREDICTIVE_ASSOCIATION_NOT_CAUSAL_PROOF",
        "depths": list(DEPTHS),
        "folds": 4,
        "fdr": {"method": "GLOBAL_BH_COMPLETE_FAMILY", "q": 0.05},
        "lags": list(LAGS),
        "minimum_training_observations": 126,
        "purge_sessions": 7,
        "selector_closure_bytes_sha256": sha256(selector_raw),
        "threshold_changes_forbidden": True,
        "topology": "INDEPENDENT_SOURCE_TARGET_LAG_EDGES",
        "training_only": True,
    })
    evidence_raw = canonical_json_bytes({
        "encoding": "CANONICAL_JSONL_UTF8_V1",
        "fold_chunk_count": FOLDS,
        "hypotheses_per_fold": EXPECTED_CANDIDATES_PER_FOLD,
        "required_fields": ["candidate_ordinal", "fold", "source", "target", "lag",
                            "train_start", "train_end", "purge_start", "purge_end",
                            "n", "association", "fisher_z", "p_value", "bh_q_value"],
        "raw_chunk_bytes_and_sha256_required": True,
        "total_hypotheses": EXPECTED_TOTAL_HYPOTHESES,
        "opaque_per_row_hash_only_forbidden": True,
    })
    resources_raw = canonical_json_bytes({
        "estimate_only_not_authority": True,
        "candidate_evaluations": EXPECTED_TOTAL_HYPOTHESES,
        "estimated_runtime_seconds": "UNKNOWN_PENDING_IMMUTABLE_RELEASE_BENCHMARK",
        "estimated_peak_memory_bytes": "UNKNOWN_PENDING_IMMUTABLE_RELEASE_BENCHMARK",
        "peak_memory_must_be_measured_in_preflight": True,
        "runtime_must_be_benchmarked_before_execution": True,
        "checkpointing_required": True,
        "zero_downstream_predictions_recommendations_orders": True,
    })
    artifacts = {
        "candidate_family.json": candidate_raw,
        "dependency.lock": p.dependency_lock_bytes,
        "evidence_contract.json": evidence_raw,
        "policy.json": policy_raw,
        "resource_estimate.json": resources_raw,
        "selector.release": p.selector_release_bytes,
        "selector.source": p.selector_source_bytes,
        "selector_closure.json": selector_raw,
        "tickers.json": ticker_raw,
        "verifier.source": p.verifier_source_bytes,
        "verifier_closure.json": verifier_raw,
    }
    hashes = {name: sha256(raw) for name, raw in sorted(artifacts.items())}
    core_raw = canonical_json_bytes({
        "contract": CONTRACT_ID,
        "artifact_sha256": hashes,
        "approval_state": STATUS,
        "freeze_readback": {"max_age_seconds_at_execution": 300,
                            "proposal_readback_at_utc": p.frozen_readback_at_utc,
                            "fresh_independent_readback_required": True,
                            "exact_frozen_content_recomputation_required": True},
        "independent_review": {"candidate_policy_code_verifier_review_required": True,
                               "reviewer_authority_and_signature_required": True,
                               "review_artifact_bytes_must_be_pinned_by_future_commit": True},
        "selections": 0,
    })
    core_sha = sha256(core_raw)
    wording = (
        "I, Avi, approve only S08 training-fold selection evaluation bound exactly "
        f"to proposal-core SHA-256 {core_sha} and artifact manifest SHA-256 "
        f"{sha256(canonical_json_bytes(hashes))}. This approval does not authorize "
        "predictions, recommendations, orders, trading, email, snapshot validation "
        "or promotion, ETF priors, destructive changes, or weakened safeguards."
    )
    approval_raw = canonical_json_bytes({
        "approval_record_contract": "avi-exact-s08-approval-record-proposal-v1",
        "artifact_manifest_sha256": sha256(canonical_json_bytes(hashes)),
        "proposal_core_sha256": core_sha,
        "required_exact_wording": wording,
        "signer": "AVI",
        "status": "UNSIGNED_PROPOSAL_NOT_AUTHORITY",
    })
    return ApprovalProposal(STATUS, (), core_raw, core_sha, approval_raw,
                            sha256(approval_raw), MappingProxyType(artifacts),
                            MappingProxyType(hashes))


def preflight(proposal: ApprovalProposal, **_untrusted_caller_artifacts: object) -> PreflightResult:
    """Return the compile-time closed state; caller artifacts are never authority."""
    if PINNED_APPROVAL_RECORD_BYTES is not None or PINNED_APPROVAL_RECORD_SHA256 is not None:
        raise RuntimeError("v4 invariant violated: trust root must remain unpinned")
    if sha256(proposal.proposal_core_bytes) != proposal.proposal_core_sha256:
        raise ProposalError("proposal core is not self-consistent")
    return PreflightResult(STATUS, (), proposal.proposal_core_sha256, None,
                           "no approval trust root is pinned in this module")

