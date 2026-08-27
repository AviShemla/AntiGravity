"""Independent fail-closed verifier for a postflight handoff artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
CONTRACT_ID = "codex-market-ingestion-postflight-handoff-v1"


class HandoffVerificationError(ValueError):
    """The handoff artifact is stale, malformed, tampered, or unsafe."""


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def verify_handoff(
    artifact: Mapping[str, object],
    *,
    source_session: str,
    now: datetime,
    max_age_seconds: int,
) -> dict[str, object]:
    if max_age_seconds <= 0:
        raise HandoffVerificationError("maximum age must be positive")
    if artifact.get("contract_id") != CONTRACT_ID:
        raise HandoffVerificationError("handoff contract identity is wrong")
    if artifact.get("successor_authorized") is not True:
        raise HandoffVerificationError("successor is not authorized")
    if artifact.get("snapshot_lifecycle_unchanged") is not True:
        raise HandoffVerificationError("snapshot lifecycle assertion is absent")
    evidence = artifact.get("evidence")
    if not isinstance(evidence, Mapping):
        raise HandoffVerificationError("handoff evidence is not an object")
    embedded_hash = artifact.get("evidence_sha256")
    actual_hash = hashlib.sha256(_canonical_bytes(evidence)).hexdigest()
    if embedded_hash != actual_hash:
        raise HandoffVerificationError("handoff evidence hash does not match")
    if evidence.get("source_session") != source_session:
        raise HandoffVerificationError("handoff source session is wrong")
    if evidence.get("status") != "STAGING":
        raise HandoffVerificationError("handoff snapshot is not STAGING")
    if evidence.get("last_date") != source_session:
        raise HandoffVerificationError("handoff latest date is wrong")
    if not isinstance(evidence.get("snapshot_id"), str) or not evidence["snapshot_id"]:
        raise HandoffVerificationError("handoff snapshot identity is absent")
    if not HEX64_RE.fullmatch(str(evidence.get("checksum", ""))):
        raise HandoffVerificationError("handoff checksum is invalid")
    if not HEX64_RE.fullmatch(str(evidence.get("code_version", ""))):
        raise HandoffVerificationError("handoff code identity is invalid")
    rows = evidence.get("rows")
    feature_tickers = evidence.get("feature_tickers")
    lineage_rows = evidence.get("provider_lineage_rows")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (rows, feature_tickers, lineage_rows)):
        raise HandoffVerificationError("handoff counts are invalid")
    if rows <= 0 or feature_tickers <= 0 or lineage_rows != feature_tickers + 2:
        raise HandoffVerificationError("handoff counts do not reconcile")
    if evidence.get("approval_events") != 0 or evidence.get("screening_runs") != 0:
        raise HandoffVerificationError("handoff contains unauthorized downstream output")
    try:
        observed = datetime.fromisoformat(str(artifact.get("observed_at")))
    except ValueError as exc:
        raise HandoffVerificationError("handoff observation timestamp is invalid") from exc
    if observed.tzinfo is None or now.tzinfo is None:
        raise HandoffVerificationError("handoff timestamps must be timezone-aware")
    age = (now - observed).total_seconds()
    if age < 0:
        raise HandoffVerificationError("handoff observation is in the future")
    if age > max_age_seconds:
        raise HandoffVerificationError("handoff observation is stale")
    return {
        "snapshot_id": evidence["snapshot_id"],
        "source_session": source_session,
        "status": "STAGING",
        "evidence_sha256": actual_hash,
        "age_seconds": age,
    }


def read_and_verify(
    path: Path,
    *,
    source_session: str,
    now: datetime,
    max_age_seconds: int,
    require_root_posix: bool = True,
) -> dict[str, object]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise HandoffVerificationError("handoff path is not a single-link regular file")
    if os.name != "nt" and require_root_posix:
        if info.st_uid != 0 or info.st_gid != 0:
            raise HandoffVerificationError("handoff is not root-owned")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise HandoffVerificationError("handoff mode is not 0600")
    raw = path.read_bytes()
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffVerificationError("handoff JSON is invalid") from exc
    if not isinstance(artifact, Mapping):
        raise HandoffVerificationError("handoff root is not an object")
    if raw != _canonical_bytes(artifact):
        raise HandoffVerificationError("handoff JSON is not canonical")
    result = verify_handoff(
        artifact,
        source_session=source_session,
        now=now,
        max_age_seconds=max_age_seconds,
    )
    result["artifact_raw_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--max-age-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        if not SESSION_RE.fullmatch(args.source_session):
            raise HandoffVerificationError("source session must be YYYY-MM-DD")
        result = read_and_verify(
            args.artifact,
            source_session=args.source_session,
            now=datetime.now(timezone.utc),
            max_age_seconds=args.max_age_seconds,
        )
    except (OSError, ValueError) as exc:
        print(f"HANDOFF_VERIFY_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(
        "HANDOFF_VERIFIED "
        f"snapshot_id={result['snapshot_id']} source_session={result['source_session']} "
        f"status=STAGING artifact_raw_sha256={result['artifact_raw_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTRACT_ID",
    "HandoffVerificationError",
    "main",
    "read_and_verify",
    "verify_handoff",
]
