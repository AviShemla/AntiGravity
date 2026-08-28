#!/usr/bin/env python3
"""Fail-closed Linux runtime for the audit-only baseline v2 verifier.

The root-owned release and external pin are inputs.  This program runs as the
unprivileged ``codexops`` account, performs exactly three SELECT statements,
never reruns the baseline producer, and creates one append-only evidence file.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Callable, Mapping, Sequence

sys.dont_write_bytecode = True

try:  # Linux runtime; tests inject an explicit lookup on other platforms.
    import pwd as _pwd
except ImportError:  # pragma: no cover - exercised by the injected Windows tests.
    _pwd = None

CANONICAL_GIT_COMMIT = "8e0bc9e73e0d85bff1d6261f384d8aebb37cac4c"
RUNTIME_CONTRACT_ID = "full-universe-common-simple-baselines-linux-runtime-v1"
EXTERNAL_PIN_CONTRACT_ID = "full-universe-common-simple-baselines-external-pin-v1"
EXPECTED_OS_USER = "codexops"
EXPECTED_TURSO_USER = "avishe"
EXPECTED_DATABASE = "theoracle"
EXPECTED_SELECT_COUNT = 3
DEFAULT_TIMEOUT_SECONDS = 120.0
TURSO_CLI = Path("/home/codexops/.turso/turso")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|"
    r"DETACH|PRAGMA|VACUUM|REINDEX|ANALYZE|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|"
    r"RELEASE)\b",
    re.IGNORECASE,
)

DATASET_SESSION_SQL = """SELECT s.snapshot_id,s.source_session_date,f.date
 FROM model_input_snapshots AS s
 JOIN (SELECT DISTINCT snapshot_id,date FROM market_daily_features) AS f
 ON f.snapshot_id=s.snapshot_id
 WHERE s.snapshot_id=? ORDER BY f.date"""
DOWNSTREAM_TABLES = (
    "model_runs",
    "model_scorecards",
    "etf_prior_lineage",
    "stock_prediction_decision_audits",
    "stock_prediction_criterion_audits",
    "execution_plans",
    "execution_events",
    "execution_plan_approvals",
)
SCHEMA_SQL = """SELECT name,type FROM sqlite_schema
 WHERE name IN (?,?,?,?,?,?,?,?) ORDER BY name"""


class RuntimeBoundaryError(RuntimeError):
    """Raised without including credentials or raw database error text."""


def _os_effective_uid() -> int:
    getter = getattr(os, "geteuid", None)
    if getter is None:
        raise RuntimeBoundaryError("Linux effective-UID API is unavailable")
    return int(getter())


@dataclass(frozen=True)
class RuntimePaths:
    external_pin: Path
    runtime_release: Path
    verifier_release: Path
    verifier_module: Path
    verifier_test: Path
    semantic_auditor: Path
    producer_executor: Path
    producer_manifest: Path
    checkpoint_directory: Path
    credentials_env: Path
    output: Path


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise RuntimeBoundaryError("JSON contains a duplicate member")
        output[key] = value
    return output


def decode_json(raw: bytes, label: str) -> object:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeBoundaryError(f"{label} is not strict UTF-8 JSON") from None


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RuntimeBoundaryError(f"{label} schema differs")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise RuntimeBoundaryError(f"{label} is not an exact SHA-256")
    return value


def _git_sha(value: object, label: str) -> str:
    if type(value) is not str or _GIT_SHA.fullmatch(value) is None:
        raise RuntimeBoundaryError(f"{label} is not an exact Git commit")
    return value


def _read_file(path: Path, label: str, *, root_owned: bool, mode: int) -> bytes:
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeBoundaryError(f"{label} path is not absolute and non-symlinked")
    metadata = os.lstat(path)
    expected_uid = 0 if root_owned else _os_effective_uid()
    if (
        metadata.st_uid != expected_uid
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise RuntimeBoundaryError(f"{label} ownership or mode differs")
    return path.read_bytes()


def _read_checkpoints(directory: Path, expected_names: set[str]) -> dict[str, bytes]:
    if not directory.is_absolute() or directory.is_symlink():
        raise RuntimeBoundaryError("checkpoint directory boundary differs")
    metadata = os.lstat(directory)
    if metadata.st_uid != 0 or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeBoundaryError("checkpoint directory must be root-owned")
    names = {item.name for item in directory.iterdir() if item.is_file()}
    if names != expected_names:
        raise RuntimeBoundaryError("checkpoint file set differs")
    return {
        name: _read_file(directory / name, f"checkpoint {name}", root_owned=True, mode=0o444)
        for name in sorted(names)
    }


def read_codexops_credentials(path: Path) -> tuple[str, str]:
    """Read one systemd credential owned by the runtime user, never root."""
    if not path.is_absolute() or path.is_symlink() or not _O_NOFOLLOW:
        raise RuntimeBoundaryError("credential path boundary differs")
    descriptor = os.open(path, os.O_RDONLY | _O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid != _os_effective_uid()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o400
        ):
            raise RuntimeBoundaryError("credential ownership or mode differs")
        raw = os.read(descriptor, 65_537)
        if len(raw) > 65_536 or os.read(descriptor, 1):
            raise RuntimeBoundaryError("credential file size differs")
    finally:
        os.close(descriptor)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise RuntimeBoundaryError("credential encoding differs") from None
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeBoundaryError("credential schema differs")
        key, value = line.split("=", 1)
        if key not in {"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"} or key in values or not value:
            raise RuntimeBoundaryError("credential schema differs")
        values[key] = value
    if set(values) != {"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"}:
        raise RuntimeBoundaryError("credential schema differs")
    return values["TURSO_DATABASE_URL"], values["TURSO_AUTH_TOKEN"]


def build_runtime_release_manifest(
    *,
    runtime_bytes: bytes,
    runtime_test_bytes: bytes,
    verifier_module_bytes: bytes,
    verifier_test_bytes: bytes,
    semantic_auditor_bytes: bytes,
    verifier_release_manifest_sha256: str,
    runtime_integration_git_commit: str,
) -> bytes:
    """Create deterministic proposal bytes; this never grants runtime authority."""
    _git_sha(runtime_integration_git_commit, "runtime integration commit")
    if runtime_integration_git_commit == CANONICAL_GIT_COMMIT:
        raise RuntimeBoundaryError("runtime integration commit is not yet distinct from its base")
    _digest(verifier_release_manifest_sha256, "verifier release")
    artifacts = {
        "baseline_audit_v2_linux_runtime.py": sha256(runtime_bytes),
        "test_baseline_audit_v2_linux_runtime.py": sha256(runtime_test_bytes),
        "audit_only_baseline_v2.py": sha256(verifier_module_bytes),
        "test_audit_only_baseline_v2.py": sha256(verifier_test_bytes),
        "audit_full_universe_simple_baselines.py": sha256(semantic_auditor_bytes),
    }
    if any(not raw for raw in (
        runtime_bytes, runtime_test_bytes, verifier_module_bytes,
        verifier_test_bytes, semantic_auditor_bytes,
    )):
        raise RuntimeBoundaryError("runtime release contains an empty artifact")
    return canonical_bytes({
        "contract_id": RUNTIME_CONTRACT_ID,
        "source_git_commit": CANONICAL_GIT_COMMIT,
        "runtime_integration_git_commit": runtime_integration_git_commit,
        "verifier_release_manifest_sha256": verifier_release_manifest_sha256,
        "artifacts": artifacts,
        "effective_identity": "os=codexops;turso=avishe",
        "database_name": EXPECTED_DATABASE,
        "select_statement_count": EXPECTED_SELECT_COUNT,
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        "write_scope": "NONE",
        "producer_rerun_authorized": False,
        "model_run_authorized": False,
        "successor_authorized": False,
    })


def _validate_external_closure(
    *,
    pin_bytes: bytes,
    runtime_release_bytes: bytes,
    verifier_release_bytes: bytes,
    artifact_bytes: Mapping[str, bytes],
) -> tuple[str, str]:
    pin = _exact_object(
        decode_json(pin_bytes, "external pin"),
        {
            "contract_id", "canonical_git_commit", "runtime_integration_git_commit",
            "runtime_release_manifest_sha256", "verifier_release_manifest_sha256",
            "scope", "database_write_authorized",
            "producer_rerun_authorized", "model_run_authorized", "successor_authorized",
        },
        "external pin",
    )
    if (
        pin["contract_id"] != EXTERNAL_PIN_CONTRACT_ID
        or pin["canonical_git_commit"] != CANONICAL_GIT_COMMIT
        or _git_sha(pin["runtime_integration_git_commit"], "pinned runtime commit") == CANONICAL_GIT_COMMIT
        or pin["scope"] != "EXACT_THREE_SELECTS_BASELINE_AUDIT_ONLY"
        or pin["database_write_authorized"] is not False
        or pin["producer_rerun_authorized"] is not False
        or pin["model_run_authorized"] is not False
        or pin["successor_authorized"] is not False
    ):
        raise RuntimeBoundaryError("external pin boundary differs")
    runtime_sha = _digest(pin["runtime_release_manifest_sha256"], "runtime release pin")
    verifier_sha = _digest(pin["verifier_release_manifest_sha256"], "verifier release pin")
    if sha256(runtime_release_bytes) != runtime_sha or sha256(verifier_release_bytes) != verifier_sha:
        raise RuntimeBoundaryError("external release pin differs")
    release = _exact_object(
        decode_json(runtime_release_bytes, "runtime release"),
        {
            "contract_id", "source_git_commit", "runtime_integration_git_commit",
            "verifier_release_manifest_sha256",
            "artifacts", "effective_identity", "database_name", "select_statement_count",
            "timeout_seconds", "write_scope", "producer_rerun_authorized", "model_run_authorized",
            "successor_authorized",
        },
        "runtime release",
    )
    if (
        release["contract_id"] != RUNTIME_CONTRACT_ID
        or release["source_git_commit"] != CANONICAL_GIT_COMMIT
        or release["runtime_integration_git_commit"] != pin["runtime_integration_git_commit"]
        or release["verifier_release_manifest_sha256"] != verifier_sha
        or release["effective_identity"] != "os=codexops;turso=avishe"
        or release["database_name"] != EXPECTED_DATABASE
        or release["select_statement_count"] != EXPECTED_SELECT_COUNT
        or release["timeout_seconds"] != DEFAULT_TIMEOUT_SECONDS
        or release["write_scope"] != "NONE"
        or release["producer_rerun_authorized"] is not False
        or release["model_run_authorized"] is not False
        or release["successor_authorized"] is not False
    ):
        raise RuntimeBoundaryError("runtime release boundary differs")
    artifacts = release["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != set(artifact_bytes):
        raise RuntimeBoundaryError("runtime artifact closure differs")
    for name, raw in artifact_bytes.items():
        if _digest(artifacts[name], name) != sha256(raw):
            raise RuntimeBoundaryError("runtime artifact bytes differ")
    return runtime_sha, verifier_sha


def verify_effective_identity(
    *,
    effective_uid: Callable[[], int] = _os_effective_uid,
    user_lookup: Callable[[int], object] | None = None,
    command_runner: Callable[..., object] = subprocess.run,
    timeout_seconds: float = 10.0,
) -> str:
    uid = effective_uid()
    if user_lookup is None:
        if _pwd is None:
            raise RuntimeBoundaryError("Linux identity API is unavailable")
        user_lookup = _pwd.getpwuid
    user = getattr(user_lookup(uid), "pw_name", None)
    if user != EXPECTED_OS_USER:
        raise RuntimeBoundaryError("effective OS identity differs")
    try:
        result = command_runner(
            [str(TURSO_CLI), "auth", "whoami"],
            check=False, capture_output=True, text=True, timeout=timeout_seconds,
            env={"HOME": "/home/codexops", "PATH": "/usr/bin:/bin"},
        )
    except Exception:
        raise RuntimeBoundaryError("Turso identity probe failed") from None
    if (
        getattr(result, "returncode", 1) != 0
        or getattr(result, "stdout", "").strip() != EXPECTED_TURSO_USER
        or getattr(result, "stderr", "").strip()
    ):
        raise RuntimeBoundaryError("Turso identity differs")
    return "os=codexops;turso=avishe"


def _assert_select(sql: str, expected: str) -> None:
    if (
        sql != expected
        or not sql.lstrip().upper().startswith("SELECT")
        or ";" in sql
        or _FORBIDDEN_SQL.search(sql)
    ):
        raise RuntimeBoundaryError("SQL is outside the exact SELECT allowlist")


def _records(result: object, columns: Sequence[str], label: str) -> list[dict[str, object]]:
    if tuple(getattr(result, "columns", ())) != tuple(columns):
        raise RuntimeBoundaryError(f"{label} columns differ")
    rows: list[dict[str, object]] = []
    for row in getattr(result, "rows", ()):
        if not isinstance(row, (list, tuple)) or len(row) != len(columns):
            raise RuntimeBoundaryError(f"{label} row shape differs")
        rows.append(dict(zip(columns, row, strict=True)))
    return rows


def _count_sql(present: set[str]) -> str:
    if not present.issubset(DOWNSTREAM_TABLES):
        raise RuntimeBoundaryError("downstream schema contains an unknown table")
    fragments = [
        (f"(SELECT COUNT(*) FROM {name})" if name in present else "0") + f" AS {name}"
        for name in DOWNSTREAM_TABLES
    ]
    return "SELECT " + ", ".join(fragments)


def execute_three_selects(*, db: object, subject: object, now: Callable[[], datetime]) -> object:
    calls = 0
    try:
        _assert_select(DATASET_SESSION_SQL, DATASET_SESSION_SQL)
        raw = db.execute(DATASET_SESSION_SQL, [subject.SNAPSHOT_ID])
        calls += 1
        rows = _records(raw, ("snapshot_id", "source_session_date", "date"), "dataset/session")
        if len(rows) != subject.EXPECTED_SESSIONS:
            raise RuntimeBoundaryError("dataset/session count differs")
        if any(
            row["snapshot_id"] != subject.SNAPSHOT_ID
            or row["source_session_date"] != subject.SOURCE_SESSION_DATE
            for row in rows
        ):
            raise RuntimeBoundaryError("dataset/session identity differs")
        sessions = tuple(str(row["date"]) for row in rows)

        _assert_select(SCHEMA_SQL, SCHEMA_SQL)
        schema_result = db.execute(SCHEMA_SQL, list(DOWNSTREAM_TABLES))
        calls += 1
        schema = _records(schema_result, ("name", "type"), "downstream schema")
        present: set[str] = set()
        for row in schema:
            name = row["name"]
            if name not in DOWNSTREAM_TABLES or row["type"] != "table" or name in present:
                raise RuntimeBoundaryError("downstream schema differs")
            present.add(str(name))

        count_sql = _count_sql(present)
        _assert_select(count_sql, _count_sql(present))
        count_result = db.execute(count_sql, [])
        calls += 1
        count_rows = _records(count_result, DOWNSTREAM_TABLES, "downstream counts")
        if len(count_rows) != 1:
            raise RuntimeBoundaryError("downstream count row differs")
        counts = count_rows[0]
        if any(type(counts[name]) is not int or counts[name] != 0 for name in DOWNSTREAM_TABLES):
            raise RuntimeBoundaryError("downstream output exists")
    except RuntimeBoundaryError:
        raise
    except Exception:
        raise RuntimeBoundaryError("Turso SELECT failed") from None
    if calls != EXPECTED_SELECT_COUNT:
        raise RuntimeBoundaryError("SELECT statement count differs")
    observed = now().astimezone(timezone.utc)
    return subject.LiveReadback(
        observed_at_utc=observed.isoformat(),
        effective_identity="os=codexops;turso=avishe",
        database_name=EXPECTED_DATABASE,
        snapshot_id=subject.SNAPSHOT_ID,
        source_session_date=subject.SOURCE_SESSION_DATE,
        sessions=sessions,
        session_sha256=subject.sha256(subject.canonical_bytes(list(sessions))),
        downstream_counts=counts,
        select_statement_count=calls,
        database_write_count=0,
    )


def _append_once(path: Path, payload: Mapping[str, object]) -> str:
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeBoundaryError("output path is not absolute and non-symlinked")
    parent = os.lstat(path.parent)
    if parent.st_uid != _os_effective_uid() or not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) != 0o700:
        raise RuntimeBoundaryError("output directory ownership or mode differs")
    raw = canonical_bytes(payload) + b"\n"
    if not _O_NOFOLLOW:
        raise RuntimeBoundaryError("Linux O_NOFOLLOW is unavailable")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha256(raw)


def _load_module(path: Path, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeBoundaryError("verified module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(
    *,
    paths: RuntimePaths,
    client_factory: Callable[[str, str, float], object],
    credentials_loader: Callable[[Path], tuple[str, str]],
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[dict[str, object], str]:
    identity = verify_effective_identity()
    root_files = {
        "external_pin": _read_file(paths.external_pin, "external pin", root_owned=True, mode=0o444),
        "runtime_release": _read_file(paths.runtime_release, "runtime release", root_owned=True, mode=0o444),
        "verifier_release": _read_file(paths.verifier_release, "verifier release", root_owned=True, mode=0o444),
        "audit_only_baseline_v2.py": _read_file(paths.verifier_module, "verifier module", root_owned=True, mode=0o444),
        "test_audit_only_baseline_v2.py": _read_file(paths.verifier_test, "verifier test", root_owned=True, mode=0o444),
        "audit_full_universe_simple_baselines.py": _read_file(paths.semantic_auditor, "semantic auditor", root_owned=True, mode=0o444),
        "baseline_audit_v2_linux_runtime.py": _read_file(Path(__file__).resolve(), "runtime wrapper", root_owned=True, mode=0o755),
    }
    # The runtime test is deployment evidence, not executable runtime input.
    runtime_test_path = paths.runtime_release.parent / "test_baseline_audit_v2_linux_runtime.py"
    root_files["test_baseline_audit_v2_linux_runtime.py"] = _read_file(
        runtime_test_path, "runtime test", root_owned=True, mode=0o444
    )
    artifacts = {key: root_files[key] for key in (
        "baseline_audit_v2_linux_runtime.py", "test_baseline_audit_v2_linux_runtime.py",
        "audit_only_baseline_v2.py", "test_audit_only_baseline_v2.py",
        "audit_full_universe_simple_baselines.py",
    )}
    runtime_sha, verifier_sha = _validate_external_closure(
        pin_bytes=root_files["external_pin"],
        runtime_release_bytes=root_files["runtime_release"],
        verifier_release_bytes=root_files["verifier_release"],
        artifact_bytes=artifacts,
    )
    subject = _load_module(paths.verifier_module, "governed_baseline_audit_v2")
    semantic = _load_module(paths.semantic_auditor, "governed_semantic_baseline_auditor")
    producer_executor = _read_file(paths.producer_executor, "producer executor", root_owned=True, mode=0o444)
    producer_manifest = _read_file(paths.producer_manifest, "producer manifest", root_owned=True, mode=0o444)
    manifest = subject.decode_json(producer_manifest, "producer manifest")
    entries = manifest.get("ticker_checkpoints", []) if isinstance(manifest, dict) else []
    expected_names = {
        f"ticker-{hashlib.sha256(str(item.get('ticker')).encode('utf-8')).hexdigest()[:24]}.json"
        for item in entries if isinstance(item, dict)
    }
    checkpoints = _read_checkpoints(paths.checkpoint_directory, expected_names)
    offline = subject.verify_offline_artifacts(
        producer_executor_bytes=producer_executor,
        producer_manifest_bytes=producer_manifest,
        checkpoint_files=checkpoints,
        verifier_release_manifest_bytes=root_files["verifier_release"],
        expected_verifier_release_manifest_sha256=verifier_sha,
    )
    endpoint, token = credentials_loader(paths.credentials_env)
    db = client_factory(endpoint, token, DEFAULT_TIMEOUT_SECONDS)
    live = execute_three_selects(db=db, subject=subject, now=now)
    finalized_at = now().astimezone(timezone.utc).isoformat()
    evidence = subject.finalize_live_audit(
        offline=offline,
        producer_executor_bytes=producer_executor,
        producer_manifest_bytes=producer_manifest,
        checkpoint_files=checkpoints,
        verifier_release_manifest_bytes=root_files["verifier_release"],
        expected_verifier_release_manifest_sha256=verifier_sha,
        live=live,
        finalized_at_utc=finalized_at,
        semantic_verifier=semantic,
    )
    evidence["runtime_release_manifest_sha256"] = runtime_sha
    evidence["external_pin_sha256"] = sha256(root_files["external_pin"])
    evidence["runtime_identity"] = identity
    evidence["database_write_count"] = 0
    evidence["producer_rerun_performed"] = False
    evidence["model_run_performed"] = False
    evidence["successor_authorized"] = False
    output_sha = _append_once(paths.output, evidence)
    return evidence, output_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "external-pin", "runtime-release", "verifier-release", "verifier-module",
        "verifier-test", "semantic-auditor", "producer-executor", "producer-manifest",
        "checkpoint-directory", "credentials-env", "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from scripts.audit_full_universe_simple_baselines import normalize_turso_pipeline_endpoint
        from turso_read_pipeline import TursoReadPipeline
        _evidence, output_sha = run(
            paths=RuntimePaths(**vars(args)),
            credentials_loader=read_codexops_credentials,
            client_factory=lambda endpoint, token, timeout: TursoReadPipeline(
                normalize_turso_pipeline_endpoint(endpoint), token, timeout_seconds=timeout
            ),
        )
    except Exception:
        print("baseline audit v2 failed; inspect redacted journal", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "VERIFIED", "output_sha256": output_sha,
        "database_writes": 0, "producer_rerun_performed": False,
        "model_run_performed": False, "successor_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
