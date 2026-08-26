"""Fail-closed cleanup verifier for one approved disposable Oracle branch.

The module has no automatic entrypoint. CLI execution and production reads are
injected; tests never execute Turso, create credentials, or access a network.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from model_lineage import LineageError
from scripts.oracle_research_dataset_isolated_matrix import (
    EXPECTED_PRODUCTION_NAME,
    IsolatedBranchIdentity,
)
from scripts.oracle_research_dataset_isolated_matrix_execute import (
    CLI,
    BranchIdentityProof,
    CliResult,
    CliRunner,
    SubprocessCliRunner,
    _fingerprint,
    derive_branch_identity_from_cli,
    exact_cleanup_command,
    load_pre_branch_intent,
)


MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_CLI_BYTES = 64 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BRANCH_TABLE_HEADER = ("NAME", "TYPE", "GROUP", "URL")


@dataclass(frozen=True)
class BranchCleanupEvidence:
    contract: str
    intent_sha256: str
    persisted_evidence_file_sha256: str
    persisted_evidence_payload_sha256: str
    fresh_identity_proof_sha256: str
    destroy_argv_sha256: str
    destroy_result: str
    branch_show_readback: str
    parent_branch_list_readback: str
    production_fingerprint_sha256: str
    production_oracle_object_count: int


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LineageError("Cleanup evidence is not canonically serializable.") from exc


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise LineageError("Persisted matrix evidence contains a duplicate key.")
        value[key] = item
    return value


def _load_bound_evidence(path: Path, expected_file_sha256: str, intent):
    if not SHA256.fullmatch(str(expected_file_sha256)):
        raise LineageError("Expected persisted evidence SHA-256 is invalid.")
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise LineageError("Persisted matrix evidence could not be read.") from exc
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise LineageError("Persisted matrix evidence is empty or oversized.")
    actual_file_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_file_sha256 != expected_file_sha256:
        raise LineageError("Persisted matrix evidence file SHA-256 differs.")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LineageError("Persisted matrix evidence JSON is invalid.") from exc
    if not isinstance(payload, dict):
        raise LineageError("Persisted matrix evidence must be an object.")
    claimed = payload.get("evidence_sha256")
    if not isinstance(claimed, str) or not SHA256.fullmatch(claimed):
        raise LineageError("Persisted matrix evidence payload SHA-256 is invalid.")
    unsigned = dict(payload)
    unsigned.pop("evidence_sha256")
    if _sha(unsigned) != claimed:
        raise LineageError("Persisted matrix evidence payload SHA-256 differs.")
    required = {
        "evidence_contract", "plan_id", "source_commit", "created_at_utc",
        "branch_identity", "approval_id",
        "migration", "readback", "redaction", "pre_branch_intent",
        "branch_identity_proof", "evidence_sha256",
    }
    if set(payload) != required:
        raise LineageError("Persisted matrix evidence top-level contract differs.")
    if payload["evidence_contract"] != "oracle-research-isolated-matrix-execution-v1":
        raise LineageError("Persisted matrix evidence contract is unsupported.")
    if payload["source_commit"] != intent.source_commit:
        raise LineageError("Persisted matrix source commit differs from intent.")
    if payload["created_at_utc"] != intent.created_at_utc:
        raise LineageError("Persisted matrix creation time differs from intent.")
    if payload["approval_id"] != intent.approval.approval_id:
        raise LineageError("Persisted matrix approval differs from intent.")
    if payload["redaction"] != {
        "branch_url_included": False,
        "production_url_included": False,
        "response_bodies_included": False,
        "token_included": False,
    }:
        raise LineageError("Persisted matrix evidence is not exactly redacted.")
    if payload["pre_branch_intent"] != {
        "intent_id": intent.intent_id,
        "created_at_utc": intent.created_at_utc,
        "approval_id": intent.approval.approval_id,
        "source_commit": intent.source_commit,
    }:
        raise LineageError("Persisted matrix evidence differs from pre-branch intent.")
    migration = payload["migration"]
    if migration != {
        "id": intent.migration_id,
        "sha256": intent.migration_sha256,
        "schema_version": intent.schema_version,
        "statement_count": intent.statement_count,
    }:
        raise LineageError("Persisted matrix migration differs from intent.")
    try:
        proof = BranchIdentityProof(**payload["branch_identity_proof"])
    except (TypeError, ValueError) as exc:
        raise LineageError("Persisted branch identity proof is invalid.") from exc
    identity = IsolatedBranchIdentity(
        proof.branch_name, proof.branch_id, proof.parent_name, proof.parent_id
    )
    proof.validate(identity, intent_created_at_utc=intent.created_at_utc)
    if payload["branch_identity"] != asdict(identity):
        raise LineageError("Persisted branch identity differs from its proof.")
    readback = payload["readback"]
    if not isinstance(readback, dict):
        raise LineageError("Persisted matrix readback is invalid.")
    if (readback.get("branch_name"), readback.get("branch_id")) != (
        identity.branch_name,
        identity.branch_id,
    ):
        raise LineageError("Persisted matrix readback branch identity differs.")
    before = readback.get("production_fingerprint_before")
    after = readback.get("production_fingerprint_after")
    before_count = readback.get("production_oracle_object_count_before")
    after_count = readback.get("production_oracle_object_count_after")
    if not isinstance(before, str) or not SHA256.fullmatch(before) or before != after:
        raise LineageError("Persisted matrix production fingerprint is not exact.")
    if (
        isinstance(before_count, bool)
        or not isinstance(before_count, int)
        or before_count < 0
        or before_count != after_count
    ):
        raise LineageError("Persisted matrix production object count is not exact.")
    return payload, proof, identity, actual_file_sha256, claimed, before, before_count


def _exact_result(result: CliResult, argv: tuple[str, ...], label: str) -> CliResult:
    if not isinstance(result, CliResult) or result.argv != argv:
        raise LineageError(f"{label} command identity is not exact.")
    for value in (result.stdout, result.stderr):
        raw = value.encode("utf-8")
        if len(raw) > MAX_CLI_BYTES or "\x00" in value or "\x1b" in value:
            raise LineageError(f"{label} output is oversized or contains controls.")
    return result


def _run_cli(runner: CliRunner, argv: tuple[str, ...], label: str) -> CliResult:
    try:
        result = runner.run(argv)
    except subprocess.TimeoutExpired:
        raise
    except Exception as exc:
        raise LineageError(f"{label} runner failed without exact CLI evidence.") from exc
    return _exact_result(result, argv, label)


def _read_fingerprint(reader, label: str) -> tuple[str, int]:
    try:
        return _fingerprint(reader)
    except Exception as exc:
        raise LineageError(f"{label} production fingerprint read failed.") from exc


def _prove_exact_missing(result: CliResult, argv: tuple[str, ...], branch_name: str):
    result = _exact_result(result, argv, "Missing-branch readback")
    expected = (
        f"Error: database {branch_name} not found. "
        "List known databases using turso db list\n"
    )
    if result.returncode != 1 or result.stdout != "" or result.stderr != expected:
        raise LineageError("Missing-branch readback does not match the observed CLI contract.")


def _prove_parent_listing_absence(
    result: CliResult, argv: tuple[str, ...], branch_name: str
):
    result = _exact_result(result, argv, "Parent branch-list readback")
    if result.returncode != 0 or result.stderr != "":
        raise LineageError("Parent branch-list readback did not succeed cleanly.")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines or tuple(lines[0].split()) != BRANCH_TABLE_HEADER:
        raise LineageError("Parent branch-list header is malformed or missing.")
    seen = set()
    for line in lines[1:]:
        fields = tuple(line.split())
        if len(fields) != 4:
            raise LineageError("Parent branch-list row is malformed.")
        name, row_type, group, url = fields
        if name in seen or not row_type or not group or not url.startswith("libsql://"):
            raise LineageError("Parent branch-list row identity is malformed.")
        seen.add(name)
    if branch_name in seen:
        raise LineageError("Disposable branch remains in the parent branch listing.")


def verify_and_cleanup_isolated_branch(
    *,
    intent_path: Path,
    persisted_evidence_path: Path,
    expected_persisted_evidence_sha256: str,
    runner: CliRunner,
    production_reader,
    observed_at: datetime,
) -> BranchCleanupEvidence:
    """Execute one exact destroy and prove absence without exposing raw identity."""
    if runner is None or production_reader is None:
        raise LineageError("Cleanup requires injected CLI and production readers.")
    intent = load_pre_branch_intent(intent_path)
    loaded = _load_bound_evidence(
        persisted_evidence_path, expected_persisted_evidence_sha256, intent
    )
    _, persisted_proof, identity, file_sha, payload_sha, expected_fp, expected_count = loaded
    try:
        fresh = derive_branch_identity_from_cli(intent, runner, observed_at=observed_at)
    except LineageError:
        raise
    except Exception as exc:
        raise LineageError("Fresh branch identity read failed.") from exc
    fresh_identity = IsolatedBranchIdentity(
        fresh.branch_name, fresh.branch_id, fresh.parent_name, fresh.parent_id
    )
    fresh.validate(
        fresh_identity,
        intent_created_at_utc=intent.created_at_utc,
        verified_at=observed_at,
    )
    if fresh_identity != identity or (
        fresh.branch_id != persisted_proof.branch_id
        or fresh.parent_id != persisted_proof.parent_id
    ):
        raise LineageError("Fresh branch identity differs from persisted matrix evidence.")
    production_before, count_before = _read_fingerprint(
        production_reader, "Pre-destroy"
    )
    if (production_before, count_before) != (expected_fp, expected_count):
        raise LineageError("Pre-destroy production fingerprint or object count differs.")

    destroy_argv = exact_cleanup_command(fresh)
    try:
        destroy = _run_cli(runner, destroy_argv, "Destroy")
    except subprocess.TimeoutExpired:
        destroy = None
        destroy_result = "AMBIGUOUS_TIMEOUT_PROVEN_BY_READBACK"
    else:
        if destroy.returncode == 0 and destroy.stderr == "":
            destroy_result = "ZERO_EXIT_PROVEN_BY_READBACK"
        elif destroy.returncode != 0 and destroy.stdout == "" and destroy.stderr == "":
            destroy_result = "AMBIGUOUS_EMPTY_RESULT_PROVEN_BY_READBACK"
        else:
            raise LineageError("Destroy returned a permission, network, parse, or CLI error.")

    show_argv = (CLI, "db", "show", identity.branch_name)
    _prove_exact_missing(
        _run_cli(runner, show_argv, "Missing-branch readback"),
        show_argv,
        identity.branch_name,
    )
    list_argv = (CLI, "db", "show", EXPECTED_PRODUCTION_NAME, "--branches")
    _prove_parent_listing_absence(
        _run_cli(runner, list_argv, "Parent branch-list readback"),
        list_argv,
        identity.branch_name,
    )
    production_after, count_after = _read_fingerprint(
        production_reader, "Post-destroy"
    )
    if (production_after, count_after) != (production_before, count_before):
        raise LineageError("Post-destroy production fingerprint or object count differs.")

    return BranchCleanupEvidence(
        contract="oracle-research-isolated-branch-cleanup-v1",
        intent_sha256=_sha(asdict(intent)),
        persisted_evidence_file_sha256=file_sha,
        persisted_evidence_payload_sha256=payload_sha,
        fresh_identity_proof_sha256=_sha(asdict(fresh)),
        destroy_argv_sha256=_sha(list(destroy_argv)),
        destroy_result=destroy_result,
        branch_show_readback="EXACT_OBSERVED_NOT_FOUND",
        parent_branch_list_readback="EXACT_NAME_ABSENCE",
        production_fingerprint_sha256=production_after,
        production_oracle_object_count=count_after,
    )


__all__ = [
    "BranchCleanupEvidence",
    "CliRunner",
    "CliResult",
    "SubprocessCliRunner",
    "verify_and_cleanup_isolated_branch",
]
