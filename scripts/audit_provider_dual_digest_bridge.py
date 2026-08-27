"""Deterministic, SELECT-only provider-lineage dual-digest bridge.

The bridge proves that the legacy compact-JSON-array digest and the Oracle
research JSONL digest were computed from the same already-canonical scalar
tuples.  Evidence intentionally contains hashes and aggregate counts only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Protocol, Sequence
from urllib.parse import urlsplit


CONTRACT_ID = "codex-oracle-provider-dual-digest-bridge-v1"
LEGACY_ENCODING_ID = "legacy-provider-lineage-compact-json-array-v1"
CANONICAL_ENCODING_ID = "oracle-provider-lineage-jsonl-v1"
EXPECTED_ROW_COUNT = 476
APPROVED_LEGACY_SHA256 = (
    "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a"
)
PROVIDERS = frozenset({"TIINGO_EOD", "YAHOO_FINANCE"})
COLUMNS = (
    "ticker",
    "provider",
    "requested_source_session_date",
    "first_available_date",
    "last_available_date",
    "source_row_count",
    "source_checksum_sha256",
)
SELECT_SQL = (
    "SELECT ticker,provider,requested_source_session_date,first_available_date,"
    "last_available_date,source_row_count,source_checksum_sha256 "
    "FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,31}$")
_SAFE_SNAPSHOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,191}$")


class BridgeError(RuntimeError):
    """A fail-closed bridge contract violation."""


class Reader(Protocol):
    def execute(self, query: str, args: list[object]): ...


@dataclass(frozen=True)
class QueryResult:
    columns: Sequence[str]
    rows: Sequence[Sequence[object]]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _canonical_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise BridgeError(f"{field} is not an exact text scalar")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BridgeError(f"{field} is not an ISO date") from exc
    if parsed.isoformat() != value:
        raise BridgeError(f"{field} changes under canonicalization")
    return value


def _canonical_row(raw: Sequence[object]) -> list[object]:
    if len(raw) != len(COLUMNS):
        raise BridgeError("provider row width differs from the exact contract")
    ticker, provider, requested, first, last, count, checksum = raw
    if not isinstance(ticker, str) or not _TICKER.fullmatch(ticker):
        raise BridgeError("ticker is not already canonical")
    if ticker.strip().upper() != ticker:
        raise BridgeError("ticker changes under canonicalization")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise BridgeError("provider is not already canonical")
    if provider.strip().upper() != provider:
        raise BridgeError("provider changes under canonicalization")
    requested_text = _canonical_date(requested, "requested source session")
    first_text = _canonical_date(first, "first available date")
    last_text = _canonical_date(last, "last available date")
    if first_text > last_text or requested_text != last_text:
        raise BridgeError("provider date bounds differ from the research contract")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise BridgeError("source row count is not an exact positive integer")
    if not isinstance(checksum, str) or not _SHA256.fullmatch(checksum):
        raise BridgeError("source checksum is not already canonical lowercase SHA-256")
    canonical = [ticker, provider, requested_text, first_text, last_text, count, checksum]
    if list(raw) != canonical:
        raise BridgeError("provider scalar tuple changes under canonicalization")
    return canonical


def legacy_bytes(rows: Sequence[Sequence[object]]) -> bytes:
    """Legacy form: one compact outer JSON array and no terminal LF."""
    return _compact([list(row) for row in rows]).encode("utf-8")


def canonical_jsonl_bytes(rows: Sequence[Sequence[object]]) -> bytes:
    """Research form: compact row arrays with exactly one LF per row."""
    return ("\n".join(_compact(list(row)) for row in rows) + "\n").encode("utf-8")


def _canonical_evidence(evidence: dict[str, object]) -> dict[str, object]:
    payload = _compact(evidence).encode("utf-8")
    return {**evidence, "evidence_sha256": _sha256(payload)}


def audit_provider_dual_digest(
    reader: Reader,
    *,
    snapshot_id: str,
    expected_row_count: int = EXPECTED_ROW_COUNT,
    expected_legacy_sha256: str = APPROVED_LEGACY_SHA256,
) -> dict[str, object]:
    """Execute one exact SELECT and return sanitized deterministic evidence."""
    if not _SAFE_SNAPSHOT.fullmatch(snapshot_id):
        raise BridgeError("snapshot identity is unsafe")
    if expected_row_count != EXPECTED_ROW_COUNT:
        raise BridgeError("expected provider row count must remain exactly 476")
    if not _SHA256.fullmatch(expected_legacy_sha256):
        raise BridgeError("approved legacy digest is invalid")
    if not SELECT_SQL.lstrip().upper().startswith("SELECT"):
        raise BridgeError("internal query is not SELECT-only")

    try:
        result = reader.execute(SELECT_SQL, [snapshot_id])
    except Exception as exc:
        raise BridgeError("SELECT-only provider read failed") from exc
    if tuple(result.columns) != COLUMNS:
        raise BridgeError("provider query columns differ from the exact contract")
    if len(result.rows) != EXPECTED_ROW_COUNT:
        raise BridgeError("provider query did not return exactly 476 rows")

    rows = [_canonical_row(row) for row in result.rows]
    tickers = [str(row[0]) for row in rows]
    if tickers != sorted(tickers) or len(set(tickers)) != EXPECTED_ROW_COUNT:
        raise BridgeError("provider rows are not uniquely ticker-ordered")

    legacy_sha = _sha256(legacy_bytes(rows))
    if legacy_sha != expected_legacy_sha256:
        raise BridgeError("legacy compact-array digest differs from approval")
    canonical_sha = _sha256(canonical_jsonl_bytes(rows))
    if canonical_sha == legacy_sha:
        raise BridgeError("distinct provider encodings unexpectedly share a digest")

    evidence: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "status": "VERIFIED",
        "snapshot_id_sha256": _sha256(snapshot_id.encode("utf-8")),
        "query_sha256": _sha256(SELECT_SQL.encode("utf-8")),
        "query_count": 1,
        "select_statement_count": 1,
        "write_statement_count": 0,
        "row_count": EXPECTED_ROW_COUNT,
        "scalar_count": EXPECTED_ROW_COUNT * len(COLUMNS),
        "canonicalization_equivalent": True,
        "legacy": {"encoding_id": LEGACY_ENCODING_ID, "sha256": legacy_sha},
        "canonical": {
            "encoding_id": CANONICAL_ENCODING_ID,
            "sha256": canonical_sha,
        },
    }
    return _canonical_evidence(evidence)


def _endpoint(database_url: str) -> str:
    normalized = (
        database_url.replace("libsql://", "https://", 1)
        if database_url.startswith("libsql://")
        else database_url
    )
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise BridgeError("Turso URL shape is invalid")
    return normalized.rstrip("/") + "/v2/pipeline"


def _load_reader(repo_root: Path):
    root = repo_root.resolve()
    if not root.is_dir():
        raise BridgeError("repository root does not exist")
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("turso_read_pipeline")
        cls = module.TursoReadPipeline
    except (ImportError, AttributeError) as exc:
        raise BridgeError("verified Turso read pipeline is unavailable") from exc
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not url or not token:
        raise BridgeError("Turso read credentials are missing")
    return cls(_endpoint(url), token)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--expected-legacy-sha256", default=APPROVED_LEGACY_SHA256
    )
    args = parser.parse_args(argv)
    try:
        if args.env_file is not None:
            from dotenv import load_dotenv
            load_dotenv(args.env_file)
        evidence = audit_provider_dual_digest(
            _load_reader(args.repo_root),
            snapshot_id=args.snapshot_id,
            expected_legacy_sha256=args.expected_legacy_sha256,
        )
    except BridgeError as exc:
        print(_compact({"contract_id": CONTRACT_ID, "status": "BLOCKED", "reason": str(exc)}))
        return 2
    print(_compact(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
