"""Fail-closed recovery for one created but never identity-bound Turso branch.

There is deliberately no command-line entrypoint.  The caller must inject the
CLI runner and production reader, pin every source artifact and identity, and
explicitly invoke the recovery function.  No CLI response body is persisted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Callable

from model_lineage import LineageError
from oracle_research_branch_cleanup_verifier import (
    BranchCleanupEvidence,
    read_production_fingerprint,
    verify_and_cleanup_bound_branch,
)
from scripts.oracle_research_dataset_isolated_matrix import EXPECTED_PRODUCTION_NAME
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    CLI,
    CliRunner,
    derive_branch_identity_from_cli,
    exact_cleanup_command,
    load_pre_branch_intent,
)
from scripts.oracle_research_dataset_isolated_matrix_lifecycle import (
    atomic_write_redacted_json,
)
from scripts.run_oracle_research_dataset_isolated_matrix_lifecycle import (
    ephemeral_turso_home,
)


MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
TERMINAL_KEYS = {
    "artifact_source_commit",
    "branch_id",
    "cleanup",
    "cleanup_failure_type",
    "cleanup_identity_state",
    "cleanup_reconciliation_diagnostic",
    "create",
    "evidence_contract",
    "execution_evidence_path",
    "executor_git_commit",
    "failure_evidence_file_sha256",
    "intent_evidence_sha256",
    "intent_id",
    "matrix_evidence_file_sha256",
    "primary_failure_type",
}


@dataclass(frozen=True)
class UnboundBranchRecoveryEvidence:
    contract: str
    observed_at_utc: str
    approval_id: str
    intent_file_sha256: str
    terminal_file_sha256: str
    pre_cleanup_file_sha256: str
    fresh_identity_proof_sha256: str
    cleanup: BranchCleanupEvidence


def _sha256_file(path: Path, expected: str, label: str) -> tuple[bytes, str]:
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise LineageError(f"Expected {label} SHA-256 is invalid.")
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise LineageError(f"{label} evidence could not be read.") from exc
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise LineageError(f"{label} evidence is empty or oversized.")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise LineageError(f"{label} evidence SHA-256 differs.")
    return raw, actual


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LineageError("Terminal evidence contains a duplicate key.")
        result[key] = value
    return result


def _load_failed_terminal(raw: bytes, *, intent, intent_file_sha256: str):
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LineageError("Terminal evidence JSON is invalid.") from exc
    if not isinstance(payload, dict) or set(payload) != TERMINAL_KEYS:
        raise LineageError("Terminal evidence contract shape differs.")
    if payload["evidence_contract"] != "oracle-isolated-matrix-lifecycle-terminal-v1":
        raise LineageError("Terminal evidence contract is unsupported.")
    exact = {
        "intent_id": intent.intent_id,
        "artifact_source_commit": intent.source_commit,
        "intent_evidence_sha256": intent_file_sha256,
        "branch_id": None,
        "cleanup": None,
        "execution_evidence_path": None,
        "failure_evidence_file_sha256": None,
        "matrix_evidence_file_sha256": None,
        "primary_failure_type": "IdentityContradiction",
        "cleanup_failure_type": "CleanupError",
        "cleanup_identity_state": "UNRESOLVED_EXHAUSTED",
    }
    for key, expected in exact.items():
        if payload.get(key) != expected:
            raise LineageError(f"Terminal evidence {key} differs from recovery contract.")
    if not GIT_COMMIT.fullmatch(str(payload.get("executor_git_commit", ""))):
        raise LineageError("Terminal executor Git identity is invalid.")
    create = payload.get("create")
    expected_argv = [CLI, "db", "branch", EXPECTED_PRODUCTION_NAME, intent.branch_name]
    if not isinstance(create, dict) or set(create) != {
        "ambiguous", "argv", "returncode", "stderr_sha256", "stdout_sha256"
    }:
        raise LineageError("Terminal create evidence shape differs.")
    if (
        create["ambiguous"] is not False
        or create["argv"] != expected_argv
        or create["returncode"] != 0
        or not SHA256.fullmatch(str(create["stdout_sha256"]))
        or not SHA256.fullmatch(str(create["stderr_sha256"]))
    ):
        raise LineageError("Terminal create evidence does not prove one exact creation.")
    diagnostic = payload.get("cleanup_reconciliation_diagnostic")
    if not isinstance(diagnostic, dict) or diagnostic.get("outcome") != "UNRESOLVED_EXHAUSTED":
        raise LineageError("Terminal cleanup exhaustion evidence is invalid.")
    return payload


def _canonical_sha(payload: object) -> str:
    try:
        raw = json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LineageError("Recovery evidence is not canonically serializable.") from exc
    return hashlib.sha256(raw).hexdigest()


def _timestamp(observed_at: datetime) -> str:
    if observed_at.tzinfo is None:
        raise LineageError("Recovery observation timestamp must be timezone-aware.")
    return observed_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_once(path: Path, payload: dict[str, object], label: str) -> str:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise LineageError(f"{label} evidence target already exists.")
    atomic_write_redacted_json(path, payload)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LineageError(f"{label} evidence readback failed.") from exc
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise LineageError(f"{label} evidence readback is empty or oversized.")
    return hashlib.sha256(raw).hexdigest()


def recover_created_unbound_branch(
    *,
    intent_path: Path,
    expected_intent_file_sha256: str,
    terminal_path: Path,
    expected_terminal_file_sha256: str,
    expected_approval_id: str,
    expected_branch_name: str,
    expected_branch_id: str,
    expected_production_fingerprint: str,
    expected_production_object_count: int,
    pre_cleanup_evidence_path: Path,
    final_evidence_path: Path,
    runner: CliRunner,
    production_reader,
    observed_at: datetime,
) -> UnboundBranchRecoveryEvidence:
    """Persist pre-cleanup proof, destroy once, and persist exact final proof."""

    if runner is None or production_reader is None:
        raise LineageError("Recovery requires injected CLI and production readers.")
    if not IDENTIFIER.fullmatch(str(expected_approval_id)):
        raise LineageError("Expected recovery approval ID is invalid.")
    if not IDENTIFIER.fullmatch(str(expected_branch_id)):
        raise LineageError("Expected branch ID is invalid.")
    if not SHA256.fullmatch(str(expected_production_fingerprint)):
        raise LineageError("Expected production fingerprint is invalid.")
    if (
        isinstance(expected_production_object_count, bool)
        or not isinstance(expected_production_object_count, int)
        or expected_production_object_count < 0
    ):
        raise LineageError("Expected production object count is invalid.")
    observed_at_utc = _timestamp(observed_at)
    intent_raw, intent_sha = _sha256_file(
        intent_path, expected_intent_file_sha256, "Pre-branch intent"
    )
    del intent_raw
    intent = load_pre_branch_intent(intent_path)
    if intent.approval.approval_id != expected_approval_id:
        raise LineageError("Pre-branch approval ID differs from recovery authority.")
    if not intent.approval.destroy_branch_after_evidence:
        raise LineageError("Pre-branch approval does not authorize exact cleanup.")
    if intent.branch_name != expected_branch_name:
        raise LineageError("Pre-branch target differs from the pinned recovery branch.")
    terminal_raw, terminal_sha = _sha256_file(
        terminal_path, expected_terminal_file_sha256, "Terminal"
    )
    _load_failed_terminal(terminal_raw, intent=intent, intent_file_sha256=intent_sha)

    proof = derive_branch_identity_from_cli(intent, runner, observed_at=observed_at)
    if proof.branch_id != expected_branch_id:
        raise LineageError("Fresh branch ID differs from the pinned recovery identity.")
    production_fingerprint, production_count = read_production_fingerprint(
        production_reader, label="Recovery pre-evidence"
    )
    if (production_fingerprint, production_count) != (
        expected_production_fingerprint,
        expected_production_object_count,
    ):
        raise LineageError("Recovery production fingerprint or object count differs.")

    pre_payload = {
        "contract": "oracle-unbound-branch-pre-cleanup-v1",
        "observed_at_utc": observed_at_utc,
        "approval_id": expected_approval_id,
        "intent_id": intent.intent_id,
        "artifact_source_commit": intent.source_commit,
        "intent_file_sha256": intent_sha,
        "terminal_file_sha256": terminal_sha,
        "branch_identity": asdict(proof),
        "production_fingerprint_sha256": production_fingerprint,
        "production_oracle_object_count": production_count,
        "destroy_argv_sha256": _canonical_sha(list(exact_cleanup_command(proof))),
        "redaction": {
            "credentials_included": False,
            "response_bodies_included": False,
            "urls_included": False,
        },
    }
    pre_sha = _write_once(pre_cleanup_evidence_path, pre_payload, "Pre-cleanup")

    cleanup = verify_and_cleanup_bound_branch(
        intent_path=intent_path,
        identity_proof=proof,
        durable_evidence_path=pre_cleanup_evidence_path,
        expected_durable_evidence_sha256=pre_sha,
        expected_production_fingerprint=production_fingerprint,
        expected_production_object_count=production_count,
        runner=runner,
        production_reader=production_reader,
        observed_at=observed_at,
    )
    final = UnboundBranchRecoveryEvidence(
        contract="oracle-unbound-branch-recovery-final-v1",
        observed_at_utc=observed_at_utc,
        approval_id=expected_approval_id,
        intent_file_sha256=intent_sha,
        terminal_file_sha256=terminal_sha,
        pre_cleanup_file_sha256=pre_sha,
        fresh_identity_proof_sha256=_canonical_sha(asdict(proof)),
        cleanup=cleanup,
    )
    _write_once(final_evidence_path, asdict(final), "Final cleanup")
    return final


def recover_with_ephemeral_turso_home(
    *,
    turso_settings_path: Path,
    turso_settings_owner_uid: int,
    runner_factory: Callable[[], CliRunner],
    production_reader,
    temp_root: Path = Path("/tmp"),
    **recovery_arguments,
) -> UnboundBranchRecoveryEvidence:
    """Run the injected recovery inside the hardened private Turso HOME."""

    if not callable(runner_factory):
        raise LineageError("Recovery CLI runner factory is not callable.")
    with ephemeral_turso_home(
        turso_settings_path,
        expected_owner_uid=turso_settings_owner_uid,
        temp_root=temp_root,
    ):
        runner = runner_factory()
        return recover_created_unbound_branch(
            runner=runner,
            production_reader=production_reader,
            **recovery_arguments,
        )


__all__ = [
    "UnboundBranchRecoveryEvidence",
    "recover_created_unbound_branch",
    "recover_with_ephemeral_turso_home",
]
