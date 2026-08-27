"""Deterministically revise the reviewed Oracle application contract from v1 to v2.

The only semantic changes are the authorization architecture and the blockers
that keep it non-executable until an envelope and envelope-bound approval are
separately built and reviewed. No adapter or production operation is executed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping

import oracle_production_authorization_envelope as envelope


V2_REVISION_KIND = "NON_CIRCULAR_AUTHORIZATION_ENVELOPE_ONLY"
ENVELOPE_BLOCKER = "AUTHORIZATION_ENVELOPE_NOT_BUILT_OR_REVIEWED"
APPROVAL_BLOCKER = "ENVELOPE_BOUND_EXPLICIT_APPROVAL_MISSING"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractV2Error(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ContractV2Error(f"{label} is not lowercase SHA-256")
    return value


def load_v1(path: Path, expected_sha256: str) -> Mapping[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContractV2Error("v1 contract is missing or a symlink")
    info = path.stat()
    if info.st_nlink != 1:
        raise ContractV2Error("v1 contract is not a single-link file")
    encoded = path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != _sha(expected_sha256, "v1 identity"):
        raise ContractV2Error("v1 contract identity mismatch")
    try:
        raw = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractV2Error("v1 contract is not valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise ContractV2Error("v1 contract root is not an object")
    if raw.get("contract_id") != envelope.LEGACY_APPLICATION_CONTRACT_ID:
        raise ContractV2Error("v1 contract ID mismatch")
    if raw.get("target_database_id") != envelope.TARGET_DATABASE_ID:
        raise ContractV2Error("v1 target database mismatch")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ContractV2Error("v1 artifact inventory is missing")
    adapter = artifacts.get("injected_turso_atomic_adapter")
    if not isinstance(adapter, Mapping) or "sha256" not in adapter:
        raise ContractV2Error("v1 concrete adapter descriptor is missing")
    _sha(adapter["sha256"], "v1 adapter identity")
    return raw


def build_v2(v1: Mapping[str, object], *, v1_sha256: str) -> dict[str, object]:
    """Return canonicalizable v2 while preserving every unrelated v1 field."""

    if v1.get("contract_id") != envelope.LEGACY_APPLICATION_CONTRACT_ID:
        raise ContractV2Error("v1 contract ID mismatch")
    v1_identity = _sha(v1_sha256, "v1 identity")
    raw = copy.deepcopy(dict(v1))
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ContractV2Error("v1 artifact inventory is not mutable object data")
    old_adapter = artifacts.get("injected_turso_atomic_adapter")
    if not isinstance(old_adapter, Mapping) or "sha256" not in old_adapter:
        raise ContractV2Error("v1 concrete adapter descriptor is missing")
    _sha(old_adapter["sha256"], "v1 adapter identity")

    raw["contract_id"] = envelope.APPLICATION_CONTRACT_ID
    raw["revision"] = {
        "revision": 2,
        "revision_kind": V2_REVISION_KIND,
        "supersedes": {
            "contract_id": envelope.LEGACY_APPLICATION_CONTRACT_ID,
            "sha256": v1_identity,
        },
    }
    raw["authorization_binding"] = dict(envelope.AUTHORIZATION_BINDING)
    del artifacts["injected_turso_atomic_adapter"]
    raw["adapter_selection"] = dict(envelope.ADAPTER_SELECTION)

    readiness = raw.get("execution_readiness")
    if not isinstance(readiness, dict):
        raise ContractV2Error("v1 execution readiness is missing")
    if readiness.get("schema_application_executable") is not False:
        raise ContractV2Error("v1 schema execution was not false")
    if readiness.get("dataset_freeze_executable") is not False:
        raise ContractV2Error("v1 freeze execution was not false")
    for key in ("schema_blockers", "freeze_blockers"):
        blockers = readiness.get(key)
        if not isinstance(blockers, list) or not all(isinstance(x, str) for x in blockers):
            raise ContractV2Error(f"v1 {key} is invalid")
        for blocker in (ENVELOPE_BLOCKER, APPROVAL_BLOCKER):
            if blocker not in blockers:
                blockers.append(blocker)

    validate_v2(raw, expected_v1_sha256=v1_identity)
    return raw


def validate_v2(raw: Mapping[str, object], *, expected_v1_sha256: str) -> None:
    envelope.validate_non_circular_application_contract(raw)
    revision = raw.get("revision")
    if revision != {
        "revision": 2,
        "revision_kind": V2_REVISION_KIND,
        "supersedes": {
            "contract_id": envelope.LEGACY_APPLICATION_CONTRACT_ID,
            "sha256": _sha(expected_v1_sha256, "superseded v1 identity"),
        },
    }:
        raise ContractV2Error("v2 revision/supersedes identity mismatch")
    readiness = raw.get("execution_readiness")
    if not isinstance(readiness, Mapping):
        raise ContractV2Error("v2 execution readiness is missing")
    if (
        readiness.get("schema_application_executable") is not False
        or readiness.get("dataset_freeze_executable") is not False
    ):
        raise ContractV2Error("v2 execution must remain false")
    for key in ("schema_blockers", "freeze_blockers"):
        blockers = readiness.get(key)
        if not isinstance(blockers, list) or any(
            required not in blockers for required in (ENVELOPE_BLOCKER, APPROVAL_BLOCKER)
        ):
            raise ContractV2Error("v2 envelope/approval blockers are missing")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, Mapping) or "injected_turso_atomic_adapter" in artifacts:
        raise ContractV2Error("v2 concrete artifact inventory still contains the adapter")
    if raw.get("adapter_selection") != envelope.ADAPTER_SELECTION:
        raise ContractV2Error("v2 adapter selection descriptor is not exact")


def build_v2_from_path(
    v1_path: Path, *, expected_v1_sha256: str
) -> tuple[dict[str, object], str]:
    v1 = load_v1(v1_path, expected_v1_sha256)
    v2 = build_v2(v1, v1_sha256=expected_v1_sha256)
    return v2, hashlib.sha256(canonical_bytes(v2)).hexdigest()


def audit_v2_derivation(
    v1: Mapping[str, object],
    v2: Mapping[str, object],
    *,
    expected_v1_sha256: str,
) -> str:
    """Independently rebuild v2 and require exact semantic equality."""

    expected = build_v2(v1, v1_sha256=expected_v1_sha256)
    if v2 != expected:
        raise ContractV2Error("v2 differs from deterministic v1 derivation")
    encoded = canonical_bytes(v2)
    return hashlib.sha256(encoded).hexdigest()


def write_v2_once(path: Path, v2: Mapping[str, object], *, expected_v1_sha256: str) -> str:
    validate_v2(v2, expected_v1_sha256=expected_v1_sha256)
    encoded = canonical_bytes(v2)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    return hashlib.sha256(encoded).hexdigest()
