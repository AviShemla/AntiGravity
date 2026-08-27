"""Root-safe SELECT-only Turso idempotency preflight for nightly continuity.

The executable emits the exact ``codex-market-ingestion-idempotency-preflight-v1``
contract consumed by ``research_contracts/nightly_continuity``. It has no SQL
write path and no local database fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


CONTRACT_ID = "codex-market-ingestion-idempotency-preflight-v1"
QUERY_MODE = "SELECT_ONLY"
DATASET_TYPE = "MARKET_FEATURES"
SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SNAPSHOT_SQL = (
    "SELECT snapshot_id,status FROM model_input_snapshots "
    "WHERE dataset_type=? AND source_session_date=? ORDER BY snapshot_id"
)
APPROVAL_SQL = (
    "SELECT COUNT(*) AS approval_count FROM model_input_approval_events a "
    "JOIN model_input_snapshots s ON s.snapshot_id=a.snapshot_id "
    "WHERE s.dataset_type=? AND s.source_session_date=?"
)
SCREENING_SQL = (
    "SELECT COUNT(*) AS screening_count FROM predictive_screening_runs r "
    "JOIN model_input_snapshots s ON s.snapshot_id=r.market_snapshot_id "
    "WHERE s.dataset_type=? AND s.source_session_date=?"
)
STATEMENTS = (SNAPSHOT_SQL, APPROVAL_SQL, SCREENING_SQL)
QUERY_SET_SHA256 = hashlib.sha256(
    ("\n".join(STATEMENTS) + "\n").encode("utf-8")
).hexdigest()


class PreflightContractError(RuntimeError):
    """The preflight or its runtime boundary failed closed."""


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


class Reader(Protocol):
    def execute(self, sql: str, args: Sequence[object]) -> QueryResult: ...


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _validate_source_session(value: str) -> str:
    if not SESSION_RE.fullmatch(value):
        raise PreflightContractError("source session must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PreflightContractError("source session is not a real date") from exc
    if parsed.isoformat() != value:
        raise PreflightContractError("source session is not canonical")
    return value


def _only_select(sql: str) -> str:
    normalized = sql.lstrip().upper()
    if not normalized.startswith("SELECT ") or ";" in sql:
        raise PreflightContractError("read pipeline accepts one SELECT statement only")
    return sql


def normalize_turso_endpoint(value: str) -> str:
    """Return an HTTPS libSQL pipeline endpoint without leaking credentials."""

    if not isinstance(value, str) or not value.strip():
        raise PreflightContractError("Turso database URL is required")
    raw = value.strip()
    if raw.startswith("libsql://"):
        raw = "https://" + raw[len("libsql://") :]
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PreflightContractError("Turso endpoint must be HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PreflightContractError("Turso endpoint may not contain credentials/query/fragment")
    path = parsed.path.rstrip("/")
    if path.endswith("/v2/pipeline"):
        final_path = path
    elif path in {"", "/"}:
        final_path = "/v2/pipeline"
    else:
        raise PreflightContractError("Turso endpoint path is not the pipeline endpoint")
    return urlunsplit(("https", parsed.netloc, final_path, "", ""))


def _encode_arg(value: object) -> dict[str, object]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    raise PreflightContractError("unsupported Turso argument type")


def _decode_value(value: Mapping[str, Any]) -> object:
    kind = value.get("type")
    raw = value.get("value")
    if kind == "null":
        return None
    if kind == "integer":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "text":
        return str(raw)
    raise PreflightContractError("unsupported Turso response value type")


class TursoSelectReader:
    """Minimal HTTPS reader with a deliberately absent SQL write surface."""

    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        timeout_seconds: float = 30.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._endpoint = normalize_turso_endpoint(endpoint)
        if not token:
            raise PreflightContractError("Turso token is required")
        if timeout_seconds <= 0:
            raise PreflightContractError("timeout must be positive")
        self._token = token
        self._timeout = timeout_seconds
        self._opener = opener

    def execute(self, sql: str, args: Sequence[object]) -> QueryResult:
        sql = _only_select(sql)
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {"sql": sql, "args": [_encode_arg(item) for item in args]},
                },
                {"type": "close"},
            ]
        }
        request = Request(
            self._endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                if int(response.status) != 200:
                    raise PreflightContractError(
                        f"Turso SELECT failed with HTTP {int(response.status)}"
                    )
                body = response.read()
        except HTTPError as exc:
            raise PreflightContractError(f"Turso SELECT failed with HTTP {exc.code}") from exc
        except URLError as exc:
            raise PreflightContractError("Turso SELECT connection failed") from exc
        try:
            raw = json.loads(body.decode("utf-8"))
            first = raw["results"][0]
            if first.get("type") == "error":
                raise PreflightContractError("Turso returned a statement error")
            result = first["response"]["result"]
            columns = tuple(str(item["name"]) for item in result["cols"])
            rows = tuple(
                tuple(_decode_value(item) for item in row) for row in result["rows"]
            )
        except PreflightContractError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, UnicodeError) as exc:
            raise PreflightContractError("Turso returned an invalid response") from exc
        return QueryResult(columns, rows)


def _single_count(result: QueryResult, expected_column: str) -> int:
    if result.columns != (expected_column,) or len(result.rows) != 1:
        raise PreflightContractError(f"{expected_column} result shape is invalid")
    value = result.rows[0][0]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PreflightContractError(f"{expected_column} is invalid")
    return value


def build_preflight_evidence(
    reader: Reader,
    *,
    source_session: str,
    observed_at: datetime,
) -> dict[str, object]:
    """Execute the three fixed SELECTs and build canonical consumer evidence."""

    source_session = _validate_source_session(source_session)
    if observed_at.tzinfo is None:
        raise PreflightContractError("observed_at must be timezone-aware")
    args = (DATASET_TYPE, source_session)
    snapshots = reader.execute(_only_select(SNAPSHOT_SQL), args)
    if snapshots.columns != ("snapshot_id", "status"):
        raise PreflightContractError("snapshot result columns are invalid")
    if any(
        len(row) != 2
        or not isinstance(row[0], str)
        or not row[0]
        or not isinstance(row[1], str)
        for row in snapshots.rows
    ):
        raise PreflightContractError("snapshot result rows are invalid")
    approval_count = _single_count(
        reader.execute(_only_select(APPROVAL_SQL), args), "approval_count"
    )
    screening_count = _single_count(
        reader.execute(_only_select(SCREENING_SQL), args), "screening_count"
    )
    unique = snapshots.rows[0] if len(snapshots.rows) == 1 else None
    evidence: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "source_session": source_session,
        "observed_at": observed_at.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "query_mode": QUERY_MODE,
        "database_writes": 0,
        "statements": list(STATEMENTS),
        "query_set_sha256": QUERY_SET_SHA256,
        "snapshot_count": len(snapshots.rows),
        "snapshot_id": unique[0] if unique else None,
        "status": unique[1] if unique else None,
        "approval_count": approval_count,
        "screening_count": screening_count,
    }
    validate_preflight_evidence(evidence, source_session=source_session)
    return evidence


def validate_preflight_evidence(
    raw: Mapping[str, object], *, source_session: str
) -> None:
    source_session = _validate_source_session(source_session)
    if raw.get("contract_id") != CONTRACT_ID:
        raise PreflightContractError("preflight contract identity mismatch")
    if raw.get("source_session") != source_session:
        raise PreflightContractError("preflight source session mismatch")
    if raw.get("query_mode") != QUERY_MODE or raw.get("database_writes") != 0:
        raise PreflightContractError("preflight is not SELECT-only")
    if raw.get("statements") != list(STATEMENTS):
        raise PreflightContractError("preflight statement set mismatch")
    if raw.get("query_set_sha256") != QUERY_SET_SHA256:
        raise PreflightContractError("preflight statement hash mismatch")
    observed = raw.get("observed_at")
    if not isinstance(observed, str):
        raise PreflightContractError("observed_at is missing")
    try:
        timestamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreflightContractError("observed_at is invalid") from exc
    if timestamp.tzinfo is None:
        raise PreflightContractError("observed_at must be timezone-aware")
    count = raw.get("snapshot_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise PreflightContractError("snapshot_count is invalid")
    snapshot_id, status = raw.get("snapshot_id"), raw.get("status")
    if count == 1:
        if not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(status, str):
            raise PreflightContractError("unique snapshot identity is incomplete")
    elif snapshot_id is not None or status is not None:
        raise PreflightContractError("non-unique snapshot has contradictory identity")
    for key in ("approval_count", "screening_count"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PreflightContractError(f"{key} is invalid")


def _secure_root_file(path: Path) -> None:
    if path.is_symlink():
        raise PreflightContractError(f"{path} must not be a symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PreflightContractError(f"{path} must be a single-link regular file")
    if os.name != "nt" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600):
        raise PreflightContractError(f"{path} must be root-owned mode 0600")


def _secure_output_parent(path: Path) -> None:
    parent = path.parent.resolve(strict=True)
    if path.exists() or path.is_symlink():
        raise PreflightContractError("output already exists")
    info = parent.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise PreflightContractError("output parent is not a directory")
    if os.name != "nt" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700):
        raise PreflightContractError("output parent must be root-owned mode 0700")


def _read_environment(path: Path) -> tuple[str, str]:
    _secure_root_file(path)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise PreflightContractError("environment file has a malformed line")
        key, value = stripped.split("=", 1)
        if key in values:
            raise PreflightContractError("environment file repeats a key")
        values[key] = value
    try:
        endpoint = values["TURSO_DATABASE_URL"]
        token = values["TURSO_AUTH_TOKEN"]
    except KeyError as exc:
        raise PreflightContractError("environment file lacks Turso credentials") from exc
    return endpoint, token


def _read_process_environment() -> tuple[str, str]:
    endpoint = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not endpoint or not token:
        raise PreflightContractError("process environment lacks Turso credentials")
    return endpoint, token


def _require_root() -> None:
    if os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise PreflightContractError("preflight executable must run as root")


def _write_once(path: Path, payload: bytes) -> None:
    _secure_output_parent(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    _secure_root_file(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--environment-file",
        type=Path,
        help=(
            "optional root-owned mode-0600 file; when omitted, consume the "
            "protected systemd process environment"
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        _require_root()
        endpoint, token = (
            _read_environment(args.environment_file)
            if args.environment_file is not None
            else _read_process_environment()
        )
        reader = TursoSelectReader(endpoint, token, timeout_seconds=args.timeout_seconds)
        evidence = build_preflight_evidence(
            reader,
            source_session=args.source_session,
            observed_at=datetime.now(timezone.utc),
        )
        _write_once(args.output, canonical_bytes(evidence))
        print(
            "IDEMPOTENCY_PREFLIGHT_WRITTEN "
            f"source_session={args.source_session} sha256="
            f"{hashlib.sha256(canonical_bytes(evidence)).hexdigest()}"
        )
        return 0
    except (PreflightContractError, OSError, UnicodeError, ValueError) as exc:
        print(f"IDEMPOTENCY_PREFLIGHT_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
