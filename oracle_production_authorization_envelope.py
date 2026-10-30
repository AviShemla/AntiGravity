"""Non-circular production-authorization envelope for Oracle dataset writes.

Trust graph (strictly one-way):

    reviewed application contract bytes ----\
                                              > authorization envelope hash
    immutable adapter release manifest ------/             |
                                                            v
                                        explicit scoped approval / launcher pin

Neither the application contract nor adapter code pins a concrete envelope
hash. The contract names only this envelope *protocol*. The adapter validates
an envelope against an expected SHA-256 supplied by a separate trusted approval
or immutable launcher. This breaks the prior contract<->adapter hash cycle.

This module has no transport, database, credential, environment, subprocess,
or production-write surface.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping


ENVELOPE_CONTRACT_ID = "oracle-production-authorization-envelope-v1"
AUTHORIZATION_CONTRACT_ID = "oracle-production-explicit-authorization-v1"
LEGACY_APPLICATION_CONTRACT_ID = "oracle-research-dataset-application-freeze-v1"
APPLICATION_CONTRACT_ID = "oracle-research-dataset-application-freeze-v2"
RELEASE_CONTRACT_ID = "codex-oracle-immutable-release-v1"
RELEASE_KIND = "oracle-research-dataset-production-adapter"
TARGET_DATABASE_ID = "theoracle-avishe"
ADAPTER_ENTRYPOINT = "oracle_research_dataset_turso_adapter_v2.py"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,191}$")

ALLOWED_OPERATIONS = (
    "STAGE_RESEARCH_DATASET",
    "FREEZE_RESEARCH_DATASET",
)
ZERO_OUTPUT_FIELDS = (
    "model_run_count",
    "model_scorecard_count",
    "etf_prior_count",
    "recommendation_count",
    "order_count",
)
AUTHORIZATION_BINDING = {
    "protocol_contract_id": ENVELOPE_CONTRACT_ID,
    "concrete_adapter_hash_in_application_contract": False,
    "expected_envelope_sha256_source": "EXPLICIT_SCOPED_APPROVAL_OR_IMMUTABLE_LAUNCHER",
}
ADAPTER_SELECTION = {
    "selection": "AUTHORIZATION_ENVELOPE",
    "execution_status": "NOT_APPROVED_FOR_EXECUTION",
    "production_use_status": "NEVER_USED",
    "owns_endpoint_token_session_or_environment": False,
    "required_release_contract_id": RELEASE_CONTRACT_ID,
    "required_release_kind": RELEASE_KIND,
}


class AuthorizationEnvelopeError(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact(raw: Mapping[str, object], keys: set[str], label: str) -> None:
    if set(raw) != keys:
        raise AuthorizationEnvelopeError(f"{label} keys are not exact")


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AuthorizationEnvelopeError(f"{label} is not lowercase SHA-256")
    return value


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise AuthorizationEnvelopeError(f"{label} is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AuthorizationEnvelopeError(f"{label} is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AuthorizationEnvelopeError(f"{label} is invalid") from exc
    if parsed.tzinfo != timezone.utc or parsed.isoformat().replace("+00:00", "Z") != value:
        raise AuthorizationEnvelopeError(f"{label} is not canonical UTC")
    return parsed


def _relative(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise AuthorizationEnvelopeError(f"{label} is missing")
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise AuthorizationEnvelopeError(f"{label} is not normalized and relative")
    return path


def _secure_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise AuthorizationEnvelopeError(f"artifact is missing or a symlink: {path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AuthorizationEnvelopeError(f"artifact is not a single-link regular file: {path}")


def load_canonical(path: Path, expected_sha256: str | None = None) -> Mapping[str, object]:
    _secure_file(path)
    encoded = path.read_bytes()
    try:
        raw = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorizationEnvelopeError("artifact is not canonical JSON") from exc
    if not isinstance(raw, Mapping) or encoded != canonical_bytes(raw):
        raise AuthorizationEnvelopeError("artifact is not canonical JSON")
    if expected_sha256 is not None and hashlib.sha256(encoded).hexdigest() != _sha(
        expected_sha256, "expected artifact identity"
    ):
        raise AuthorizationEnvelopeError("artifact identity mismatch")
    return raw


def validate_non_circular_application_contract(raw: Mapping[str, object]) -> None:
    """Require a protocol pin, while forbidding a concrete adapter byte pin."""

    if raw.get("contract_id") != APPLICATION_CONTRACT_ID:
        raise AuthorizationEnvelopeError("application contract identity mismatch")
    if raw.get("target_database_id") != TARGET_DATABASE_ID:
        raise AuthorizationEnvelopeError("application target database mismatch")
    if raw.get("authorization_binding") != AUTHORIZATION_BINDING:
        raise AuthorizationEnvelopeError("non-circular authorization binding is absent")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise AuthorizationEnvelopeError("application artifact inventory is absent")
    if "injected_turso_atomic_adapter" in artifacts:
        raise AuthorizationEnvelopeError(
            "application concrete artifact inventory must not contain the selected adapter"
        )
    if raw.get("adapter_selection") != ADAPTER_SELECTION:
        raise AuthorizationEnvelopeError("adapter selection is not exactly envelope-bound")


def verify_adapter_release(
    release_root: Path, release_manifest_sha256: str
) -> tuple[Mapping[str, object], Mapping[str, Mapping[str, str]]]:
    release_id = _sha(release_manifest_sha256, "adapter release identity")
    directory = release_root / f"{RELEASE_KIND}-{release_id}"
    if directory.is_symlink() or not directory.is_dir():
        raise AuthorizationEnvelopeError("adapter release directory is missing")
    manifest = load_canonical(directory / "release-manifest.json", release_id)
    _exact(manifest, {"contract_id", "release_kind", "files"}, "release manifest")
    if (
        manifest["contract_id"] != RELEASE_CONTRACT_ID
        or manifest["release_kind"] != RELEASE_KIND
    ):
        raise AuthorizationEnvelopeError("adapter release contract/kind mismatch")
    rows = manifest["files"]
    if not isinstance(rows, list) or not rows:
        raise AuthorizationEnvelopeError("adapter release is empty")
    inventory: dict[str, Mapping[str, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise AuthorizationEnvelopeError("adapter release row is invalid")
        _exact(row, {"path", "sha256", "mode"}, "adapter release row")
        relative = _relative(row["path"], "adapter release path").as_posix()
        if relative in inventory:
            raise AuthorizationEnvelopeError("adapter release path is duplicated")
        digest = _sha(row["sha256"], "adapter artifact identity")
        mode = row["mode"]
        if mode not in {"0600", "0700"}:
            raise AuthorizationEnvelopeError("adapter artifact mode is outside allowlist")
        artifact = directory.joinpath(*PurePosixPath(relative).parts)
        _secure_file(artifact)
        if sha256_file(artifact) != digest:
            raise AuthorizationEnvelopeError("adapter artifact hash mismatch")
        inventory[relative] = {"sha256": digest, "mode": str(mode)}
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != set(inventory) | {"release-manifest.json"}:
        raise AuthorizationEnvelopeError("adapter release contains unmanifested files")
    if ADAPTER_ENTRYPOINT not in inventory or inventory[ADAPTER_ENTRYPOINT]["mode"] != "0600":
        raise AuthorizationEnvelopeError("adapter entrypoint identity/mode is absent")
    return manifest, inventory


def _leaf_strings(value: object):
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _leaf_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _leaf_strings(child)
    elif isinstance(value, str):
        yield value


def _assert_non_circular_leaves(
    application: Mapping[str, object],
    application_sha256: str,
    adapter_release_root: Path,
    adapter_release_id: str,
    inventory: Mapping[str, Mapping[str, str]],
) -> None:
    """Reject either leaf directly pinning the concrete identity of the other."""

    adapter_identities = {adapter_release_id} | {
        str(row["sha256"]) for row in inventory.values()
    }
    if adapter_identities & set(_leaf_strings(application)):
        raise AuthorizationEnvelopeError(
            "application contract directly pins a concrete adapter identity"
        )
    directory = adapter_release_root / f"{RELEASE_KIND}-{adapter_release_id}"
    assignment = re.compile(
        rb"(?i)[A-Za-z0-9_]*contract_sha256\s*=\s*['\"][0-9a-f]{64}['\"]"
    )
    for relative in inventory:
        encoded = directory.joinpath(*PurePosixPath(relative).parts).read_bytes()
        if application_sha256.encode("ascii") in encoded or assignment.search(encoded):
            raise AuthorizationEnvelopeError(
                "adapter release directly pins a concrete application-contract hash"
            )


def build_envelope(
    *,
    application_contract_path: Path,
    adapter_release_root: Path,
    adapter_release_manifest_sha256: str,
    content_audit_evidence_sha256: str,
) -> dict[str, object]:
    application = load_canonical(application_contract_path)
    validate_non_circular_application_contract(application)
    application_sha = sha256_file(application_contract_path)
    _, inventory = verify_adapter_release(
        adapter_release_root, adapter_release_manifest_sha256
    )
    _assert_non_circular_leaves(
        application,
        application_sha,
        adapter_release_root,
        adapter_release_manifest_sha256,
        inventory,
    )
    envelope = {
        "contract_id": ENVELOPE_CONTRACT_ID,
        "application_contract": {
            "contract_id": APPLICATION_CONTRACT_ID,
            "sha256": application_sha,
        },
        "adapter_release": {
            "contract_id": RELEASE_CONTRACT_ID,
            "release_kind": RELEASE_KIND,
            "manifest_sha256": adapter_release_manifest_sha256,
            "entrypoint": ADAPTER_ENTRYPOINT,
            "entrypoint_sha256": inventory[ADAPTER_ENTRYPOINT]["sha256"],
        },
        "target_database_id": TARGET_DATABASE_ID,
        "content_audit_evidence_sha256": _sha(
            content_audit_evidence_sha256, "content audit identity"
        ),
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "forbidden_output_counts": {key: 0 for key in ZERO_OUTPUT_FIELDS},
        "trust_anchor": "EXPECTED_ENVELOPE_SHA256_MUST_BE_SUPPLIED_OUT_OF_BAND",
    }
    validate_envelope_structure(envelope)
    return envelope


def validate_envelope_structure(raw: Mapping[str, object]) -> None:
    _exact(
        raw,
        {
            "contract_id",
            "application_contract",
            "adapter_release",
            "target_database_id",
            "content_audit_evidence_sha256",
            "allowed_operations",
            "forbidden_output_counts",
            "trust_anchor",
        },
        "authorization envelope",
    )
    if raw["contract_id"] != ENVELOPE_CONTRACT_ID:
        raise AuthorizationEnvelopeError("authorization envelope identity mismatch")
    application = raw["application_contract"]
    release = raw["adapter_release"]
    if not isinstance(application, Mapping) or not isinstance(release, Mapping):
        raise AuthorizationEnvelopeError("authorization envelope leaves are invalid")
    _exact(application, {"contract_id", "sha256"}, "application leaf")
    _exact(
        release,
        {
            "contract_id",
            "release_kind",
            "manifest_sha256",
            "entrypoint",
            "entrypoint_sha256",
        },
        "adapter release leaf",
    )
    if application["contract_id"] != APPLICATION_CONTRACT_ID:
        raise AuthorizationEnvelopeError("application leaf identity mismatch")
    _sha(application["sha256"], "application leaf hash")
    if (
        release["contract_id"] != RELEASE_CONTRACT_ID
        or release["release_kind"] != RELEASE_KIND
        or release["entrypoint"] != ADAPTER_ENTRYPOINT
    ):
        raise AuthorizationEnvelopeError("adapter release leaf identity mismatch")
    _sha(release["manifest_sha256"], "adapter release manifest hash")
    _sha(release["entrypoint_sha256"], "adapter entrypoint hash")
    if raw["target_database_id"] != TARGET_DATABASE_ID:
        raise AuthorizationEnvelopeError("authorization target database mismatch")
    _sha(raw["content_audit_evidence_sha256"], "content audit hash")
    if raw["allowed_operations"] != list(ALLOWED_OPERATIONS):
        raise AuthorizationEnvelopeError("authorization operation set differs")
    if raw["forbidden_output_counts"] != {key: 0 for key in ZERO_OUTPUT_FIELDS}:
        raise AuthorizationEnvelopeError("authorization output boundary differs")
    if raw["trust_anchor"] != "EXPECTED_ENVELOPE_SHA256_MUST_BE_SUPPLIED_OUT_OF_BAND":
        raise AuthorizationEnvelopeError("out-of-band trust anchor is absent")


def verify_envelope_artifacts(
    envelope: Mapping[str, object],
    *,
    expected_envelope_sha256: str,
    application_contract_path: Path,
    adapter_release_root: Path,
) -> str:
    """Independently bind envelope bytes to both leaves and external trust."""

    validate_envelope_structure(envelope)
    envelope_sha = canonical_sha256(envelope)
    if envelope_sha != _sha(expected_envelope_sha256, "trusted envelope identity"):
        raise AuthorizationEnvelopeError("authorization envelope is not externally trusted")
    application_leaf = envelope["application_contract"]
    release_leaf = envelope["adapter_release"]
    assert isinstance(application_leaf, Mapping) and isinstance(release_leaf, Mapping)
    application = load_canonical(
        application_contract_path, str(application_leaf["sha256"])
    )
    validate_non_circular_application_contract(application)
    _, inventory = verify_adapter_release(
        adapter_release_root, str(release_leaf["manifest_sha256"])
    )
    _assert_non_circular_leaves(
        application,
        str(application_leaf["sha256"]),
        adapter_release_root,
        str(release_leaf["manifest_sha256"]),
        inventory,
    )
    if inventory[ADAPTER_ENTRYPOINT]["sha256"] != release_leaf["entrypoint_sha256"]:
        raise AuthorizationEnvelopeError("adapter entrypoint/release identity mismatch")
    return envelope_sha


def validate_runtime_authorization(
    envelope: Mapping[str, object],
    authorization: Mapping[str, object],
    *,
    expected_envelope_sha256: str,
    application_contract_path: Path,
    adapter_release_root: Path,
    operation_id: str,
    observed_at_utc: datetime,
) -> str:
    """Return the trusted envelope hash or fail before any adapter transport use."""

    envelope_sha = verify_envelope_artifacts(
        envelope,
        expected_envelope_sha256=expected_envelope_sha256,
        application_contract_path=application_contract_path,
        adapter_release_root=adapter_release_root,
    )
    _exact(
        authorization,
        {
            "contract_id",
            "authorization_id",
            "envelope_sha256",
            "authorized_by",
            "authorized_at_utc",
            "expires_at_utc",
            "schema_application_gate_satisfied",
            "schema_application_approval_id",
            "dataset_freeze_gate_satisfied",
            "dataset_freeze_approval_id",
            "authorized_dataset_version_id",
            "authorized_freeze_event_id",
            *ZERO_OUTPUT_FIELDS,
        },
        "runtime authorization",
    )
    if authorization["contract_id"] != AUTHORIZATION_CONTRACT_ID:
        raise AuthorizationEnvelopeError("runtime authorization identity mismatch")
    _safe_id(authorization["authorization_id"], "authorization ID")
    if authorization["envelope_sha256"] != envelope_sha:
        raise AuthorizationEnvelopeError("runtime authorization references another envelope")
    _safe_id(authorization["authorized_by"], "authorizer")
    authorized = _utc(authorization["authorized_at_utc"], "authorization time")
    expires = _utc(authorization["expires_at_utc"], "authorization expiry")
    if observed_at_utc.tzinfo != timezone.utc or not authorized <= observed_at_utc < expires:
        raise AuthorizationEnvelopeError("runtime authorization is not currently valid")
    if authorization["schema_application_gate_satisfied"] is not True:
        raise AuthorizationEnvelopeError("schema application gate is not satisfied")
    if authorization["dataset_freeze_gate_satisfied"] is not True:
        raise AuthorizationEnvelopeError("dataset freeze gate is not satisfied")
    schema_approval = _safe_id(
        authorization["schema_application_approval_id"], "schema approval"
    )
    freeze_approval = _safe_id(
        authorization["dataset_freeze_approval_id"], "freeze approval"
    )
    if schema_approval == freeze_approval:
        raise AuthorizationEnvelopeError("schema and freeze approvals are not distinct")
    dataset_id = _safe_id(
        authorization["authorized_dataset_version_id"], "dataset version"
    )
    event_id = _safe_id(
        authorization["authorized_freeze_event_id"], "freeze event"
    )
    if freeze_approval != event_id:
        raise AuthorizationEnvelopeError("freeze approval does not bind freeze event")
    if operation_id not in {
        f"stage:{dataset_id}",
        f"freeze:{dataset_id}:{event_id}",
    }:
        raise AuthorizationEnvelopeError("operation is outside exact authorization")
    for key in ZERO_OUTPUT_FIELDS:
        value = authorization[key]
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            raise AuthorizationEnvelopeError("runtime authorization permits downstream output")
    return envelope_sha
