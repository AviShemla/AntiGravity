#!/usr/bin/env python3
"""Read-only canonical-content audit for the pinned Oracle market snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from oracle_research_dataset_content_reader import (
    PinnedMarketSnapshot,
    stream_pinned_market_content,
)
from turso_read_pipeline import TursoReadPipeline


EVIDENCE_CONTRACT = "oracle-research-content-audit-v1"
METADATA_COLUMNS = (
    "snapshot_id",
    "dataset_type",
    "source_session_date",
    "available_at_utc",
    "provider",
    "code_version",
    "source_checksum_sha256",
    "expected_row_count",
    "expected_ticker_count",
    "status",
)
COVERAGE_COLUMNS = (
    "row_count",
    "ticker_count",
    "first_session_date",
    "last_session_date",
)
METADATA_SQL = (
    "SELECT snapshot_id,dataset_type,source_session_date,available_at_utc,provider,"
    "code_version,source_checksum_sha256,expected_row_count,expected_ticker_count,status "
    "FROM model_input_snapshots WHERE snapshot_id=?"
)
COVERAGE_SQL = (
    "SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,"
    "MIN(date) AS first_session_date,MAX(date) AS last_session_date "
    "FROM market_daily_features WHERE snapshot_id=?"
)
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class PinnedContentAuditContract:
    snapshot: PinnedMarketSnapshot
    dataset_type: str
    provider: str
    code_version: str
    first_session_date: date


PINNED_CONTENT = PinnedContentAuditContract(
    snapshot=PinnedMarketSnapshot(
        snapshot_id="market_features_2026-08-25_5b1044ee45605a3d",
        source_checksum_sha256=(
            "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011"
        ),
        source_session_date=date(2026, 8, 25),
        expected_row_count=586_710,
        expected_ticker_count=474,
    ),
    dataset_type="MARKET_FEATURES",
    provider="TIINGO_EOD+YAHOO_FINANCE",
    code_version="1e28786832b633c8b63163e7954e3297b0b9ec0e",
    first_session_date=date(2021, 9, 8),
)


def _load_local_secret_env(path: Path) -> None:
    """Load an ignored env file without logging keys or values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _one(result: object, *, columns: tuple[str, ...], label: str) -> dict[str, object]:
    actual_columns = getattr(result, "columns", None)
    rows = getattr(result, "rows", None)
    if not isinstance(actual_columns, (list, tuple)) or tuple(actual_columns) != columns:
        raise LineageError(f"{label} returned an invalid column contract.")
    if not isinstance(rows, (list, tuple)) or len(rows) != 1:
        raise LineageError(f"{label} must return exactly one row.")
    if not isinstance(rows[0], (list, tuple)) or len(rows[0]) != len(columns):
        raise LineageError(f"{label} returned a malformed row.")
    return dict(zip(columns, rows[0]))


def _utc_text(value: object, *, label: str) -> str:
    raw = str(value or "")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LineageError(f"{label} is not an ISO timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LineageError(f"{label} must be timezone-aware.")
    return parsed.astimezone(timezone.utc).isoformat()


def _int(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise LineageError(f"{label} must be an integer.")
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{label} must be an integer.") from exc
    if str(converted) != str(value):
        raise LineageError(f"{label} is not a canonical integer.")
    return converted


def _canonical_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_pinned_content_audit(
    client,
    *,
    contract: PinnedContentAuditContract = PINNED_CONTENT,
    page_size: int = 4000,
) -> dict[str, object]:
    """Reconcile metadata and stream content through an injected read client."""
    pin = contract.snapshot
    metadata = _one(
        client.execute(METADATA_SQL, [pin.snapshot_id]),
        columns=METADATA_COLUMNS,
        label="Pinned snapshot metadata",
    )
    available_at = _utc_text(metadata["available_at_utc"], label="Snapshot availability")
    exact_metadata = (
        metadata["snapshot_id"] == pin.snapshot_id
        and metadata["dataset_type"] == contract.dataset_type
        and metadata["source_session_date"] == pin.source_session_date.isoformat()
        and metadata["provider"] == contract.provider
        and metadata["code_version"] == contract.code_version
        and metadata["source_checksum_sha256"] == pin.source_checksum_sha256
        and _int(metadata["expected_row_count"], label="Snapshot expected row count")
        == pin.expected_row_count
        and _int(metadata["expected_ticker_count"], label="Snapshot expected ticker count")
        == pin.expected_ticker_count
        and metadata["status"] == "VALIDATED"
    )
    if not exact_metadata or not _GIT_SHA.fullmatch(contract.code_version):
        raise LineageError("Current snapshot metadata does not match the pinned identity.")

    coverage = _one(
        client.execute(COVERAGE_SQL, [pin.snapshot_id]),
        columns=COVERAGE_COLUMNS,
        label="Pinned snapshot coverage",
    )
    row_count = _int(coverage["row_count"], label="Current market row count")
    ticker_count = _int(coverage["ticker_count"], label="Current market ticker count")
    if (
        row_count != pin.expected_row_count
        or ticker_count != pin.expected_ticker_count
        or coverage["first_session_date"] != contract.first_session_date.isoformat()
        or coverage["last_session_date"] != pin.source_session_date.isoformat()
    ):
        raise LineageError("Current market coverage does not match the pinned snapshot.")

    streamed = stream_pinned_market_content(client, pin=pin, page_size=page_size)
    payload: dict[str, object] = {
        "evidence_contract": EVIDENCE_CONTRACT,
        "snapshot": {
            "snapshot_id": pin.snapshot_id,
            "dataset_type": contract.dataset_type,
            "source_session_date": pin.source_session_date.isoformat(),
            "available_at_utc": available_at,
            "provider": contract.provider,
            "code_version": contract.code_version,
            "source_checksum_sha256": pin.source_checksum_sha256,
            "status": "VALIDATED",
        },
        "coverage": {
            "row_count": row_count,
            "ticker_count": ticker_count,
            "first_session_date": contract.first_session_date.isoformat(),
            "last_session_date": pin.source_session_date.isoformat(),
        },
        "canonical_content": {
            "content_sha256": streamed.digests.content_sha256,
            "ticker_universe_sha256": streamed.digests.ticker_universe_sha256,
            "content_encoding": streamed.digests.content_encoding,
            "ticker_universe_encoding": streamed.digests.ticker_universe_encoding,
            "row_count": streamed.digests.row_count,
            "ticker_count": streamed.digests.ticker_count,
            "first_session_date": streamed.digests.first_session_date.isoformat(),
            "last_session_date": streamed.digests.last_session_date.isoformat(),
        },
        "pagination": {
            "page_size": streamed.page_size,
            "nonempty_page_count": streamed.nonempty_page_count,
            "query_count": streamed.query_count,
            "maximum_page_rows": streamed.maximum_page_rows,
            "retained_row_count": streamed.retained_row_count,
        },
        "read_only": True,
    }
    payload["evidence_sha256"] = _canonical_sha256(payload)
    return payload


def _client_from_environment(env_file: Path, *, timeout_seconds: float):
    _load_local_secret_env(env_file)
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise LineageError("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    return TursoReadPipeline(endpoint, token, timeout_seconds=timeout_seconds)


def main(
    argv: list[str] | None = None,
    *,
    injected_client=None,
    injected_contract: PinnedContentAuditContract | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=4000)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        raise SystemExit("Timeout must be positive.")
    client = injected_client or _client_from_environment(
        args.env_file, timeout_seconds=args.timeout_seconds
    )
    evidence = build_pinned_content_audit(
        client,
        contract=PINNED_CONTENT if injected_contract is None else injected_contract,
        page_size=args.page_size,
    )
    print(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
