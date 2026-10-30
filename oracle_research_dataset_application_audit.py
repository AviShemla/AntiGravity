"""Pure read-only runner for the Oracle research-dataset application audits."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from model_lineage import LineageError


_ALLOWED_PHASES = frozenset({"pre_schema", "post_schema", "pre_freeze", "post_freeze"})
_PLACEHOLDER = re.compile(r"^EXPECTED_[A-Z0-9_]+$")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|ANALYZE)\b",
    re.IGNORECASE,
)
_SELECT_START = re.compile(r"^SELECT\b", re.IGNORECASE)


class ReadOnlyAuditClient(Protocol):
    def execute(self, sql: str, args: list[object]): ...


@dataclass(frozen=True)
class ArtifactHashEvidence:
    artifact_name: str
    path: str
    expected_sha256: str
    actual_sha256: str


@dataclass(frozen=True)
class QueryAuditEvidence:
    audit_id: str
    sql_sha256: str
    binding_sha256: str
    result_sha256: str
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    row_count: int
    expected_interpretation: str


@dataclass(frozen=True)
class ApplicationAuditEvidence:
    contract_id: str
    contract_sha256: str
    contract_status: str
    target_database_id: str
    source_git_commit: str
    phase: str
    artifacts: tuple[ArtifactHashEvidence, ...]
    queries: tuple[QueryAuditEvidence, ...]
    evidence_sha256: str


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LineageError(f"{label} is required.")
    return value


def _sha256_digest(value: object, label: str) -> str:
    digest = _required_text(value, label)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise LineageError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LineageError("Audit evidence is not canonically JSON serializable.") from exc


def _artifact_evidence(root: Path, artifacts: object) -> tuple[ArtifactHashEvidence, ...]:
    if not isinstance(artifacts, dict) or not artifacts:
        raise LineageError("Contract artifacts must be a non-empty object.")
    root = root.resolve()
    evidence: list[ArtifactHashEvidence] = []
    for name in sorted(artifacts):
        artifact = artifacts[name]
        if not isinstance(artifact, dict):
            raise LineageError(f"Artifact {name} is malformed.")
        relative = Path(_required_text(artifact.get("path"), f"artifact {name} path"))
        if relative.is_absolute():
            raise LineageError(f"Artifact {name} path must be repository-relative.")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise LineageError(f"Artifact {name} escapes the repository root.") from exc
        if not resolved.is_file():
            raise LineageError(f"Artifact {name} is missing.")
        expected = _sha256_digest(artifact.get("sha256"), f"artifact {name} sha256")
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if actual != expected:
            raise LineageError(f"Artifact {name} hash does not match the contract.")
        evidence.append(ArtifactHashEvidence(str(name), relative.as_posix(), expected, actual))
    return tuple(evidence)


def _validate_select(sql: object, audit_id: str) -> str:
    statement = _required_text(sql, f"audit {audit_id} SQL").strip()
    if not _SELECT_START.match(statement):
        raise LineageError(f"Audit {audit_id} is not a SELECT statement.")
    if ";" in statement or "--" in statement or "/*" in statement or "*/" in statement:
        raise LineageError(f"Audit {audit_id} contains disallowed multi-statement/comment syntax.")
    if _FORBIDDEN_SQL.search(statement):
        raise LineageError(f"Audit {audit_id} contains a forbidden SQL operation.")
    return statement


def _binding_value(value: object, label: str) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise LineageError(f"{label} cannot be non-finite.")
        return value
    raise LineageError(f"{label} must be a scalar query binding.")


def _resolve_bindings(
    declared: object,
    explicit: Mapping[str, object],
    *,
    audit_id: str,
) -> tuple[list[object], set[str]]:
    if declared is None:
        declared = []
    if not isinstance(declared, list):
        raise LineageError(f"Audit {audit_id} bindings must be a list.")
    resolved: list[object] = []
    used: set[str] = set()
    for index, value in enumerate(declared):
        if isinstance(value, str) and _PLACEHOLDER.fullmatch(value):
            if value not in explicit:
                raise LineageError(f"Audit {audit_id} is missing explicit binding {value}.")
            resolved.append(_binding_value(explicit[value], f"binding {value}"))
            used.add(value)
        else:
            resolved.append(_binding_value(value, f"audit {audit_id} literal binding {index}"))
    return resolved, used


def _normalized_result(result: object, audit_id: str) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
    columns_raw = getattr(result, "columns", None)
    rows_raw = getattr(result, "rows", None)
    if not isinstance(columns_raw, (list, tuple)) or not isinstance(rows_raw, (list, tuple)):
        raise LineageError(f"Audit {audit_id} returned an invalid read-only result.")
    columns = tuple(_required_text(column, f"audit {audit_id} result column") for column in columns_raw)
    if len(set(columns)) != len(columns):
        raise LineageError(f"Audit {audit_id} returned duplicate result columns.")
    rows: list[tuple[object, ...]] = []
    for raw_row in rows_raw:
        if not isinstance(raw_row, (list, tuple)) or len(raw_row) != len(columns):
            raise LineageError(f"Audit {audit_id} returned a malformed row.")
        row = tuple(_binding_value(value, f"audit {audit_id} result value") for value in raw_row)
        rows.append(row)
    _canonical_json([list(row) for row in rows])
    return columns, tuple(rows)


def run_application_audit(
    *,
    repository_root: Path,
    contract_path: Path,
    expected_contract_sha256: str,
    phase: str,
    explicit_bindings: Mapping[str, object],
    client: ReadOnlyAuditClient,
) -> ApplicationAuditEvidence:
    """Validate and execute one hash-locked application audit phase read-only."""
    if phase not in _ALLOWED_PHASES:
        raise LineageError("Unknown application audit phase.")
    expected_contract_sha256 = _sha256_digest(
        expected_contract_sha256, "expected_contract_sha256"
    )
    contract_bytes = contract_path.read_bytes()
    actual_contract_sha256 = hashlib.sha256(contract_bytes).hexdigest()
    if actual_contract_sha256 != expected_contract_sha256:
        raise LineageError("Application contract hash does not match the approved digest.")
    try:
        contract = json.loads(contract_bytes)
    except (TypeError, ValueError) as exc:
        raise LineageError("Application contract is not valid JSON.") from exc
    if not isinstance(contract, dict):
        raise LineageError("Application contract must be a JSON object.")
    artifacts = _artifact_evidence(repository_root, contract.get("artifacts"))
    audits = contract.get("read_only_audits")
    if not isinstance(audits, dict) or not isinstance(audits.get(phase), list) or not audits[phase]:
        raise LineageError(f"Application contract has no audits for {phase}.")
    if not isinstance(explicit_bindings, Mapping):
        raise LineageError("explicit_bindings must be a mapping.")

    prepared: list[tuple[str, str, list[object], str]] = []
    required_bindings: set[str] = set()
    audit_ids: set[str] = set()
    for audit in audits[phase]:
        if not isinstance(audit, dict):
            raise LineageError(f"Application contract has a malformed {phase} audit.")
        audit_id = _required_text(audit.get("id"), "audit id")
        if audit_id in audit_ids:
            raise LineageError(f"Duplicate audit id {audit_id}.")
        audit_ids.add(audit_id)
        sql = _validate_select(audit.get("sql"), audit_id)
        bindings, used = _resolve_bindings(
            audit.get("bindings"), explicit_bindings, audit_id=audit_id
        )
        if sql.count("?") != len(bindings):
            raise LineageError(f"Audit {audit_id} placeholder count does not match bindings.")
        required_bindings.update(used)
        prepared.append(
            (audit_id, sql, bindings, _required_text(audit.get("expected"), f"audit {audit_id} expected"))
        )
    extra_bindings = set(explicit_bindings) - required_bindings
    if extra_bindings:
        raise LineageError("Undeclared explicit bindings were supplied: " + ",".join(sorted(extra_bindings)))

    query_evidence: list[QueryAuditEvidence] = []
    for audit_id, sql, bindings, expected in prepared:
        result = client.execute(sql, list(bindings))
        columns, rows = _normalized_result(result, audit_id)
        query_evidence.append(
            QueryAuditEvidence(
                audit_id=audit_id,
                sql_sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                binding_sha256=hashlib.sha256(_canonical_json(bindings)).hexdigest(),
                result_sha256=hashlib.sha256(
                    _canonical_json({"columns": columns, "rows": rows})
                ).hexdigest(),
                columns=columns,
                rows=rows,
                row_count=len(rows),
                expected_interpretation=expected,
            )
        )

    identity = {
        "contract_id": _required_text(contract.get("contract_id"), "contract_id"),
        "contract_sha256": actual_contract_sha256,
        "contract_status": _required_text(contract.get("contract_status"), "contract_status"),
        "target_database_id": _required_text(contract.get("target_database_id"), "target_database_id"),
        "source_git_commit": _required_text(contract.get("source_git_commit"), "source_git_commit"),
        "phase": phase,
        "artifacts": [item.__dict__ for item in artifacts],
        "queries": [
            {
                "audit_id": item.audit_id,
                "sql_sha256": item.sql_sha256,
                "binding_sha256": item.binding_sha256,
                "result_sha256": item.result_sha256,
                "row_count": item.row_count,
                "expected_interpretation": item.expected_interpretation,
            }
            for item in query_evidence
        ],
    }
    evidence_sha256 = hashlib.sha256(_canonical_json(identity)).hexdigest()
    return ApplicationAuditEvidence(
        contract_id=identity["contract_id"],
        contract_sha256=actual_contract_sha256,
        contract_status=identity["contract_status"],
        target_database_id=identity["target_database_id"],
        source_git_commit=identity["source_git_commit"],
        phase=phase,
        artifacts=artifacts,
        queries=tuple(query_evidence),
        evidence_sha256=evidence_sha256,
    )
