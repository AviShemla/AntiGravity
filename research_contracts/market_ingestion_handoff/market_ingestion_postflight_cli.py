"""SELECT-only Turso postflight CLI with bounded visibility retry.

No SQL statement in this module mutates Turso.  The only write is an optional
root-owned, mode-0600, create-once local handoff artifact.  Secrets are loaded
from an environment variable or root-owned environment file and are never
printed or persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

try:
    from .market_ingestion_postflight import (
        FeatureEvidence,
        PostflightError,
        SnapshotEvidence,
        VisibilityPending,
        reconcile_staging_snapshot,
    )
except ImportError:  # pragma: no cover - direct CLI execution
    from market_ingestion_postflight import (  # type: ignore
        FeatureEvidence,
        PostflightError,
        SnapshotEvidence,
        VisibilityPending,
        reconcile_staging_snapshot,
    )


SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

SNAPSHOT_SQL = (
    "SELECT snapshot_id,status,expected_row_count,expected_ticker_count,"
    "source_checksum_sha256,code_version FROM model_input_snapshots "
    "WHERE dataset_type='MARKET_FEATURES' AND source_session_date=?"
)
FEATURE_SUMMARY_SQL = (
    "SELECT COUNT(*),COUNT(DISTINCT ticker),MIN(date),MAX(date) "
    "FROM market_daily_features WHERE snapshot_id=?"
)
FEATURE_TICKERS_SQL = (
    "SELECT DISTINCT ticker FROM market_daily_features "
    "WHERE snapshot_id=? ORDER BY ticker"
)
LINEAGE_SQL = (
    "SELECT ticker,requested_source_session_date "
    "FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker"
)
APPROVAL_COUNT_SQL = (
    "SELECT COUNT(*) FROM model_input_approval_events WHERE snapshot_id=?"
)
SCREENING_COUNT_SQL = (
    "SELECT COUNT(*) FROM predictive_screening_runs WHERE market_snapshot_id=?"
)
ALL_SELECTS = (
    SNAPSHOT_SQL,
    FEATURE_SUMMARY_SQL,
    FEATURE_TICKERS_SQL,
    LINEAGE_SQL,
    APPROVAL_COUNT_SQL,
    SCREENING_COUNT_SQL,
)


class ReadResult(Protocol):
    rows: Sequence[Sequence[object]]


class Reader(Protocol):
    def execute(self, query: str, args: list[object]) -> ReadResult: ...


class PostflightRuntimeError(RuntimeError):
    """The read adapter or local evidence boundary failed closed."""


class PostflightVisibilityTimeout(PostflightRuntimeError):
    """Incomplete Turso visibility did not converge within the bounded policy."""


def normalize_turso_endpoint(value: str) -> str:
    """Normalize libsql/HTTPS database URL to the exact HTTPS pipeline URL."""

    raw = value.strip()
    if raw.startswith("libsql://"):
        raw = "https://" + raw[len("libsql://") :]
    if not raw.startswith("https://"):
        raise PostflightRuntimeError("Turso endpoint must use libsql or HTTPS")
    raw = raw.rstrip("/")
    if raw.endswith("/v2/pipeline"):
        return raw
    return raw + "/v2/pipeline"


def _read_env_file(path: Path, wanted: set[str]) -> dict[str, str]:
    if not path.is_file():
        raise PostflightRuntimeError("environment file is unavailable")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PostflightRuntimeError(
            "environment file must be a single-link regular file"
        )
    if os.name != "nt":
        if info.st_uid != 0 or info.st_gid != 0:
            raise PostflightRuntimeError("environment file must be root-owned")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise PostflightRuntimeError("environment file mode must be 0600")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in wanted:
            values[key] = value.strip().strip('"').strip("'")
    return values


def load_runtime_values(
    *, endpoint_env: str, token_env: str, env_file: Path | None
) -> tuple[str, str]:
    values: Mapping[str, str] = os.environ
    file_values: dict[str, str] = {}
    if env_file is not None:
        file_values = _read_env_file(env_file, {endpoint_env, token_env})
    endpoint = values.get(endpoint_env) or file_values.get(endpoint_env)
    token = values.get(token_env) or file_values.get(token_env)
    if not endpoint or not token:
        raise PostflightRuntimeError("required Turso runtime variables are unavailable")
    return normalize_turso_endpoint(endpoint), token


def _single_row(rows: Sequence[Sequence[object]], *, label: str) -> Sequence[object]:
    if len(rows) != 1:
        raise PostflightRuntimeError(f"{label} did not return exactly one row")
    return rows[0]


def read_and_reconcile_once(
    reader: Reader,
    *,
    source_session: str,
    expected_code_version: str,
    expected_snapshot_id: str | None = None,
) -> dict[str, object]:
    """Perform one complete SELECT-only read and pure reconciliation."""

    snapshot_rows = reader.execute(SNAPSHOT_SQL, [source_session]).rows
    if not snapshot_rows:
        raise VisibilityPending("snapshot is not yet visible")
    if len(snapshot_rows) != 1:
        raise PostflightError("snapshot cardinality is not exactly one")
    row = snapshot_rows[0]
    if len(row) != 6:
        raise PostflightRuntimeError("snapshot query returned an invalid shape")
    snapshot = SnapshotEvidence(
        snapshot_id=str(row[0]),
        status=str(row[1]),
        expected_rows=int(row[2]),
        expected_tickers=int(row[3]),
        checksum=str(row[4]),
        stored_code_version=str(row[5]),
    )
    if expected_snapshot_id is not None and snapshot.snapshot_id != expected_snapshot_id:
        raise PostflightError("snapshot identity does not match the expected handoff")

    summary = _single_row(
        reader.execute(FEATURE_SUMMARY_SQL, [snapshot.snapshot_id]).rows,
        label="feature summary",
    )
    if len(summary) != 4:
        raise PostflightRuntimeError("feature summary returned an invalid shape")
    ticker_rows = reader.execute(FEATURE_TICKERS_SQL, [snapshot.snapshot_id]).rows
    if any(len(item) != 1 for item in ticker_rows):
        raise PostflightRuntimeError("feature ticker query returned an invalid shape")
    features = FeatureEvidence(
        actual_rows=int(summary[0]),
        ticker_rows=tuple(str(item[0]) for item in ticker_rows),
        first_date=str(summary[2]),
        last_date=str(summary[3]),
    )
    lineage_rows = reader.execute(LINEAGE_SQL, [snapshot.snapshot_id]).rows
    approvals = int(
        _single_row(
            reader.execute(APPROVAL_COUNT_SQL, [snapshot.snapshot_id]).rows,
            label="approval count",
        )[0]
    )
    screenings = int(
        _single_row(
            reader.execute(SCREENING_COUNT_SQL, [snapshot.snapshot_id]).rows,
            label="screening count",
        )[0]
    )
    return reconcile_staging_snapshot(
        snapshot=snapshot,
        features=features,
        lineage_rows=lineage_rows,
        source_session=source_session,
        expected_code_version=expected_code_version,
        approval_count=approvals,
        screening_count=screenings,
    )


def reconcile_with_bounded_retry(
    read_once: Callable[[], dict[str, object]],
    *,
    attempts: int,
    retry_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    if attempts < 1:
        raise PostflightRuntimeError("attempts must be at least one")
    if retry_seconds < 0:
        raise PostflightRuntimeError("retry delay cannot be negative")
    last_pending: VisibilityPending | None = None
    for attempt in range(1, attempts + 1):
        try:
            return read_once()
        except VisibilityPending as exc:
            last_pending = exc
            if attempt < attempts:
                sleep(retry_seconds)
    raise PostflightVisibilityTimeout(
        f"Turso visibility remained incomplete after {attempts} attempts"
    ) from last_pending


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def build_handoff(result: Mapping[str, object], *, observed_at: str) -> dict[str, object]:
    evidence = dict(result)
    evidence_bytes = _canonical_bytes(evidence)
    return {
        "contract_id": "codex-market-ingestion-postflight-handoff-v1",
        "evidence": evidence,
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "observed_at": observed_at,
        "successor_authorized": True,
        "snapshot_lifecycle_unchanged": True,
    }


def write_handoff_once(path: Path, artifact: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(_canonical_bytes(artifact))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--expected-code-version", required=True)
    parser.add_argument("--expected-snapshot-id")
    parser.add_argument("--handoff-output", type=Path, required=True)
    parser.add_argument("--endpoint-env", default="TURSO_DATABASE_URL")
    parser.add_argument("--token-env", default="TURSO_AUTH_TOKEN")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--retry-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not SESSION_RE.fullmatch(args.source_session):
            raise PostflightRuntimeError("source session must be YYYY-MM-DD")
        if not HEX64_RE.fullmatch(args.expected_code_version):
            raise PostflightRuntimeError("expected code version must be lowercase SHA-256")
        endpoint, token = load_runtime_values(
            endpoint_env=args.endpoint_env,
            token_env=args.token_env,
            env_file=args.env_file,
        )
        try:
            from turso_read_pipeline import TursoReadPipeline
        except ImportError as exc:
            raise PostflightRuntimeError("SELECT-only Turso adapter is unavailable") from exc
        reader = TursoReadPipeline(
            endpoint, token, timeout_seconds=args.timeout_seconds
        )
        result = reconcile_with_bounded_retry(
            lambda: read_and_reconcile_once(
                reader,
                source_session=args.source_session,
                expected_code_version=args.expected_code_version,
                expected_snapshot_id=args.expected_snapshot_id,
            ),
            attempts=args.attempts,
            retry_seconds=args.retry_seconds,
        )
        artifact = build_handoff(
            result,
            observed_at=datetime.now(timezone.utc).isoformat(),
        )
        write_handoff_once(args.handoff_output, artifact)
        print(
            "POSTFLIGHT_HANDOFF_WRITTEN "
            f"snapshot_id={result['snapshot_id']} status=STAGING "
            f"rows={result['rows']} feature_tickers={result['feature_tickers']} "
            f"provider_lineage_rows={result['provider_lineage_rows']}"
        )
        return 0
    except (PostflightError, PostflightRuntimeError, OSError, ValueError) as exc:
        print(f"POSTFLIGHT_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALL_SELECTS",
    "PostflightRuntimeError",
    "PostflightVisibilityTimeout",
    "build_handoff",
    "load_runtime_values",
    "main",
    "normalize_turso_endpoint",
    "read_and_reconcile_once",
    "reconcile_with_bounded_retry",
    "write_handoff_once",
]
