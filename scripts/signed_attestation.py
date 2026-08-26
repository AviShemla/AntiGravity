"""Ed25519 verification and replay protection for AntiGravity claims."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b"ANTIGRAVITY_CLAIM_ATTESTATION_V1\n"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def claim_subject_digest(manifest: dict[str, Any]) -> str:
    subject = {key: value for key, value in manifest.items() if key != "attestation"}
    return hashlib.sha256(canonical_bytes(subject)).hexdigest()


def signing_payload(attestation: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in attestation.items() if key != "signature"}
    return DOMAIN + canonical_bytes(unsigned)


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("attestation timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("attestation timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _load_authority(registry_path: Path, verifier_id: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"verifier authority registry unavailable: {exc}"
    if registry.get("schema_version") != "1.0" or not isinstance(registry.get("authorities"), list):
        return None, "verifier authority registry is invalid"
    matches = [item for item in registry["authorities"] if isinstance(item, dict) and item.get("id") == verifier_id and item.get("enabled") is True]
    if len(matches) != 1:
        return None, "verifier is not a unique enabled authority"
    return matches[0], None


def _consume_nonce(ledger_path: Path, verifier_id: str, nonce: str, subject_digest: str) -> str | None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
        with ledger_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            used = {json.loads(line)["nonce"] for line in handle if line.strip()}
            if nonce in used:
                return "attestation nonce has already been consumed"
            handle.write(json.dumps({"verifier_id": verifier_id, "nonce": nonce, "subject_digest": subject_digest}, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return None
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        return f"attestation nonce ledger failure: {exc}"


def verify_attestation(
    manifest: dict[str, Any], *, authority_registry: Path | None,
    nonce_ledger: Path | None, now: datetime | None = None,
    consume_nonce: bool = True,
) -> list[str]:
    errors: list[str] = []
    attestation = manifest.get("attestation")
    if not isinstance(attestation, dict):
        return ["VERIFIED requires a signed external attestation"]
    required = {"verifier_id", "command_id", "issued_at", "expires_at", "nonce", "subject_digest", "artifact_digest", "runtime_identity", "signature"}
    missing = sorted(required - attestation.keys())
    if missing:
        return [f"attestation missing field: {field}" for field in missing]
    if authority_registry is None:
        return ["VERIFIED requires a separately configured verifier authority registry"]
    authority, authority_error = _load_authority(authority_registry, attestation["verifier_id"])
    if authority_error:
        return [authority_error]
    if attestation["command_id"] not in authority.get("allowed_command_ids", []):
        errors.append("attestation command is not allowlisted for this verifier")
    expected_subject = claim_subject_digest(manifest)
    if attestation["subject_digest"] != expected_subject:
        errors.append("attestation subject digest does not bind the manifest")
    if attestation["artifact_digest"] != manifest.get("artifact", {}).get("digest"):
        errors.append("attestation does not bind the artifact digest")
    runtime = manifest.get("runtime", {})
    expected_runtime = runtime.get("identity", "") if runtime.get("applicable") else "NOT_APPLICABLE"
    if attestation["runtime_identity"] != expected_runtime:
        errors.append("attestation does not bind the runtime identity")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        issued = _timestamp(attestation["issued_at"])
        expires = _timestamp(attestation["expires_at"])
        if issued > current or expires < current or expires < issued:
            errors.append("attestation is not currently fresh")
    except ValueError as exc:
        errors.append(str(exc))
    nonce = attestation.get("nonce")
    if not isinstance(nonce, str) or len(nonce) < 32:
        errors.append("attestation nonce must contain at least 32 characters")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(authority["public_key_base64"], validate=True))
        signature = base64.b64decode(attestation["signature"], validate=True)
        public_key.verify(signature, signing_payload(attestation))
    except (KeyError, ValueError, InvalidSignature):
        errors.append("attestation signature is invalid")
    if errors:
        return errors
    if nonce_ledger is None:
        return ["VERIFIED requires an external replay-protection nonce ledger"]
    if consume_nonce:
        nonce_error = _consume_nonce(nonce_ledger, attestation["verifier_id"], nonce, expected_subject)
        if nonce_error:
            errors.append(nonce_error)
    return errors
