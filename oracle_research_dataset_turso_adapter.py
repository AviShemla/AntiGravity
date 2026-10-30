"""Injected atomic Turso boundary for the Oracle research-dataset writer.

This module owns no endpoint, token, session, environment lookup, or retry
policy.  A separately authorized transport is injected after all contract
gates are satisfied.  Only the exact SQL literals used by the pure writer and
its frozen-dataset readback are accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

from model_lineage import LineageError
from scripts.apply_atomic_migration import (
    AtomicMigrationError,
    _require_baton,
    verify_pipeline_results,
)
from turso_read_pipeline import PipelineResult, _decode_value, _encode_arg


T = TypeVar("T")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT_ID = "oracle-research-dataset-application-freeze-v1"
_TARGET_DATABASE_ID = "theoracle-avishe"
_CONTRACT_SHA256 = "854a4d17e66a4f00a7192646feb2274d517ad731026740796ba2a52aa61cc447"
_CONTENT_AUDIT_SHA256 = "b0b775d6aa4ff37faacb3987a65019724b358cdc86d5aa5967aea927c1401df3"


def _sql(value: str) -> str:
    return " ".join(value.split())


_SELECT_SQL = frozenset(
    map(
        _sql,
        (
            """SELECT ticker,provider,requested_source_session_date,first_available_date,
            last_available_date,source_row_count,source_checksum_sha256
            FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker""",
            """SELECT dataset_type,source_session_date,available_at_utc,
            source_checksum_sha256,expected_row_count,expected_ticker_count,status
            FROM model_input_snapshots WHERE snapshot_id=?""",
            """SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,
            COUNT(DISTINCT date) AS session_count,MIN(date) AS first_session_date,
            MAX(date) AS last_session_date FROM market_daily_features
            WHERE snapshot_id=?""",
            """SELECT dataset_version_id,market_snapshot_id,
            market_snapshot_checksum_sha256,source_session_date,evidence_cutoff_utc,
            first_session_date,last_session_date,expected_row_count,
            expected_ticker_count,expected_session_count,
            expected_provider_lineage_count,content_sha256,ticker_universe_sha256,
            provider_lineage_sha256,schema_version,code_version,status,
            freeze_approval_id,frozen_by,frozen_at_utc,created_at_utc
            FROM oracle_research_dataset_versions WHERE dataset_version_id=?""",
            """SELECT COUNT(*) AS event_count FROM oracle_research_dataset_events
            WHERE dataset_version_id=?""",
            """SELECT ticker,provider,requested_source_session_date,first_available_date,
            last_available_date,source_row_count,source_checksum_sha256
            FROM oracle_research_dataset_provider_lineage
            WHERE dataset_version_id=? ORDER BY ticker""",
            """SELECT d.dataset_version_id,d.market_snapshot_id,
            d.market_snapshot_checksum_sha256,d.source_session_date,
            d.evidence_cutoff_utc,d.first_session_date,d.last_session_date,
            d.expected_row_count,d.expected_ticker_count,
            d.expected_session_count,d.expected_provider_lineage_count,
            d.content_sha256,d.ticker_universe_sha256,
            d.provider_lineage_sha256,d.schema_version,d.code_version,
            d.status,d.freeze_approval_id,d.frozen_by,d.frozen_at_utc,
            s.dataset_type AS snapshot_dataset_type,
            s.source_session_date AS snapshot_source_session_date,
            s.available_at_utc AS snapshot_available_at_utc,
            s.source_checksum_sha256 AS snapshot_checksum_sha256,
            s.expected_row_count AS snapshot_expected_row_count,
            s.expected_ticker_count AS snapshot_expected_ticker_count,
            s.status AS snapshot_status
            FROM oracle_research_dataset_versions d
            JOIN model_input_snapshots s ON s.snapshot_id=d.market_snapshot_id
            WHERE d.dataset_version_id=?""",
            """SELECT event_id,event_type,market_snapshot_checksum_sha256,
            content_sha256,ticker_universe_sha256,provider_lineage_sha256,
            actor,decided_at_utc,evidence_sha256
            FROM oracle_research_dataset_events
            WHERE dataset_version_id=?
            ORDER BY decided_at_utc DESC,event_id DESC LIMIT 1""",
            """SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,
            COUNT(DISTINCT date) AS session_count,
            MIN(date) AS first_session_date,MAX(date) AS last_session_date
            FROM market_daily_features WHERE snapshot_id=?""",
            """SELECT ticker,provider,requested_source_session_date,first_available_date,
            last_available_date,source_row_count,source_checksum_sha256
            FROM market_data_provider_lineage
            WHERE snapshot_id=? ORDER BY ticker""",
        ),
    )
)

_STAGE_VERSION_SQL = _sql(
    """INSERT INTO oracle_research_dataset_versions
    (dataset_version_id,market_snapshot_id,
     market_snapshot_checksum_sha256,source_session_date,
     evidence_cutoff_utc,first_session_date,last_session_date,
     expected_row_count,expected_ticker_count,expected_session_count,
     expected_provider_lineage_count,content_sha256,
     ticker_universe_sha256,provider_lineage_sha256,schema_version,
     code_version,status,created_at_utc)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
)
_STAGE_PROVIDER_SQL = _sql(
    """INSERT INTO oracle_research_dataset_provider_lineage
    (dataset_version_id,ticker,provider,
     requested_source_session_date,first_available_date,
     last_available_date,source_row_count,source_checksum_sha256,
     created_at_utc)
    SELECT ?,ticker,provider,requested_source_session_date,
           first_available_date,last_available_date,source_row_count,
           source_checksum_sha256,?
    FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker"""
)
_FREEZE_EVENT_SQL = _sql(
    """INSERT INTO oracle_research_dataset_events
    (event_id,dataset_version_id,event_type,
     market_snapshot_checksum_sha256,content_sha256,
     ticker_universe_sha256,provider_lineage_sha256,actor,
     decided_at_utc,evidence_sha256,created_at_utc)
    VALUES (?,?,'FREEZE',?,?,?,?,?,?,?,?)"""
)
_FREEZE_VERSION_SQL = _sql(
    """UPDATE oracle_research_dataset_versions
    SET status='FROZEN',freeze_approval_id=?,frozen_by=?,frozen_at_utc=?
    WHERE dataset_version_id=? AND status='STAGING'
      AND market_snapshot_id=?
      AND market_snapshot_checksum_sha256=?
      AND content_sha256=? AND ticker_universe_sha256=?
      AND provider_lineage_sha256=?
      AND EXISTS (
        SELECT 1 FROM oracle_research_dataset_events e
        WHERE e.event_id=? AND e.dataset_version_id=?
          AND e.event_type='FREEZE'
      )"""
)
_STAGE_MUTATIONS = (_STAGE_VERSION_SQL, _STAGE_PROVIDER_SQL)
_FREEZE_MUTATIONS = (_FREEZE_EVENT_SQL, _FREEZE_VERSION_SQL)


class InjectedAtomicPipelineTransport(Protocol):
    def send(self, requests: list[dict[str, object]], *, baton: str | None = None) -> dict: ...


@dataclass(frozen=True)
class OracleResearchProductionAuthorization:
    contract_id: str
    contract_sha256: str
    target_database_id: str
    schema_application_gate_satisfied: bool
    schema_application_approval_id: str
    schema_post_audit_evidence_sha256: str
    dataset_freeze_gate_satisfied: bool
    dataset_freeze_approval_id: str
    content_audit_evidence_sha256: str
    authorized_dataset_version_id: str
    authorized_freeze_event_id: str
    model_run_count: int = 0
    model_scorecard_count: int = 0
    etf_prior_count: int = 0
    recommendation_count: int = 0
    order_count: int = 0


def _required(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise LineageError(f"{label} is required without surrounding whitespace.")
    return value


def _digest(value: object, label: str) -> str:
    digest = _required(value, label)
    if not _SHA256.fullmatch(digest):
        raise LineageError(f"{label} must be lowercase SHA-256.")
    return digest


def _validate_authorization(auth: OracleResearchProductionAuthorization) -> None:
    if not isinstance(auth, OracleResearchProductionAuthorization):
        raise LineageError("Oracle research production authorization is required.")
    if auth.contract_id != _CONTRACT_ID:
        raise LineageError("Oracle research application contract ID is not exact.")
    if _digest(auth.contract_sha256, "Application contract checksum") != _CONTRACT_SHA256:
        raise LineageError("Application contract checksum is not the pinned reviewed artifact.")
    if auth.target_database_id != _TARGET_DATABASE_ID:
        raise LineageError("Oracle research target database ID is not exact.")
    schema_approval = _required(
        auth.schema_application_approval_id, "Schema application approval ID"
    )
    freeze_approval = _required(
        auth.dataset_freeze_approval_id, "Dataset freeze approval ID"
    )
    if not auth.schema_application_gate_satisfied or not auth.dataset_freeze_gate_satisfied:
        raise LineageError("Oracle research production approval gates are not satisfied.")
    if schema_approval == freeze_approval:
        raise LineageError("Schema and dataset-freeze approvals must be distinct.")
    if freeze_approval != _required(
        auth.authorized_freeze_event_id, "Authorized freeze event ID"
    ):
        raise LineageError("Dataset-freeze approval must bind the authorized freeze event.")
    _required(auth.authorized_dataset_version_id, "Authorized dataset version ID")
    _digest(auth.schema_post_audit_evidence_sha256, "Schema post-audit checksum")
    if (
        _digest(auth.content_audit_evidence_sha256, "Content audit checksum")
        != _CONTENT_AUDIT_SHA256
    ):
        raise LineageError("Content audit checksum is not the pinned reviewed evidence.")
    counts = (
        auth.model_run_count,
        auth.model_scorecard_count,
        auth.etf_prior_count,
        auth.recommendation_count,
        auth.order_count,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value != 0 for value in counts):
        raise LineageError("Research dataset application requires zero model/trading outputs.")


def _verify_exact_results(payload: object, expected: int = 1) -> dict:
    verify_pipeline_results(payload, expected)
    if not isinstance(payload, dict) or len(payload["results"]) != expected:
        raise AtomicMigrationError("Turso returned an ambiguous result cardinality.")
    return payload


def _execute_result(payload: dict) -> dict:
    try:
        response = payload["results"][0]["response"]
        result = response["result"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AtomicMigrationError("Turso returned malformed execute evidence.") from exc
    if not isinstance(result, dict):
        raise AtomicMigrationError("Turso returned malformed execute evidence.")
    return result


class _OracleResearchTransaction:
    def __init__(self, transport, baton: str, expected_mutations: tuple[str, ...]):
        self.transport = transport
        self.baton = baton
        self.expected_mutations = expected_mutations
        self.mutations: list[str] = []
        self.ended = False

    def _send(self, sql: str, args: list[object]) -> dict:
        if self.ended:
            raise AtomicMigrationError("Oracle research transaction is already terminal.")
        if not isinstance(args, list) or sql.count("?") != len(args):
            raise LineageError("Oracle research SQL bindings are not exact.")
        request = {
            "type": "execute",
            "stmt": {"sql": sql, "args": [_encode_arg(value) for value in args]},
        }
        payload = _verify_exact_results(
            self.transport.send([request], baton=self.baton), 1
        )
        self.baton = _require_baton(payload)
        return _execute_result(payload)

    def execute(self, query: str, args: list[object]) -> PipelineResult:
        normalized = _sql(query)
        if normalized not in _SELECT_SQL:
            raise LineageError("Oracle research adapter rejected an undeclared SELECT.")
        result = self._send(query, args)
        try:
            columns = tuple(column["name"] for column in result["cols"])
            rows = tuple(
                tuple(_decode_value(value) for value in row) for row in result["rows"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AtomicMigrationError("Turso returned malformed SELECT evidence.") from exc
        if any(len(row) != len(columns) for row in rows):
            raise AtomicMigrationError("Turso returned a malformed SELECT row.")
        return PipelineResult(columns=columns, rows=rows)

    def execute_mutation(self, query: str, args: list[object]) -> int:
        normalized = _sql(query)
        index = len(self.mutations)
        if index >= len(self.expected_mutations) or normalized != self.expected_mutations[index]:
            raise LineageError("Oracle research adapter rejected an undeclared mutation.")
        result = self._send(query, args)
        affected = result.get("affected_row_count")
        if isinstance(affected, bool):
            raise AtomicMigrationError("Turso returned invalid affected-row evidence.")
        try:
            count = int(affected)
        except (TypeError, ValueError) as exc:
            raise AtomicMigrationError("Turso returned invalid affected-row evidence.") from exc
        if str(count) != str(affected) or count < 0:
            raise AtomicMigrationError("Turso returned invalid affected-row evidence.")
        self.mutations.append(normalized)
        return count


class InjectedTursoImmediateTransactionRunner:
    """Production-capable atomic runner over an already-authorized transport."""

    def __init__(self, transport: InjectedAtomicPipelineTransport, authorization):
        if transport is None:
            raise LineageError("Oracle research atomic transport is required.")
        _validate_authorization(authorization)
        self.transport = transport
        self.authorization = authorization

    def _operation_contract(self, operation_id: str) -> tuple[str, ...]:
        dataset_id = self.authorization.authorized_dataset_version_id
        event_id = self.authorization.authorized_freeze_event_id
        if operation_id == f"stage:{dataset_id}":
            return _STAGE_MUTATIONS
        if operation_id == f"freeze:{dataset_id}:{event_id}":
            return _FREEZE_MUTATIONS
        raise LineageError("Oracle research operation is outside the approved identity.")

    def _rollback(self, baton: str) -> None:
        request = {"type": "execute", "stmt": {"sql": "ROLLBACK", "args": []}}
        payload = _verify_exact_results(self.transport.send([request], baton=baton), 1)
        _execute_result(payload)

    def run_immediate(
        self,
        operation_id: str,
        callback: Callable[[_OracleResearchTransaction], T],
    ) -> T:
        expected_mutations = self._operation_contract(operation_id)
        begin = _verify_exact_results(
            self.transport.send(
                [{"type": "execute", "stmt": {"sql": "BEGIN IMMEDIATE", "args": []}}]
            ),
            1,
        )
        _execute_result(begin)
        baton = _require_baton(begin)
        transaction = _OracleResearchTransaction(
            self.transport, baton, expected_mutations
        )
        try:
            result = callback(transaction)
            if transaction.mutations and tuple(transaction.mutations) != expected_mutations:
                raise AtomicMigrationError(
                    "Oracle research callback returned after a partial mutation sequence."
                )
            committed = _verify_exact_results(
                self.transport.send(
                    [{"type": "execute", "stmt": {"sql": "COMMIT", "args": []}}],
                    baton=transaction.baton,
                ),
                1,
            )
            transaction.ended = True
            _execute_result(committed)
            return result
        except Exception as exc:
            transaction.ended = True
            try:
                self._rollback(transaction.baton)
            except Exception as rollback_error:
                raise AtomicMigrationError(
                    "Oracle research transaction outcome is ambiguous; rollback was not verified."
                ) from exc
            raise
