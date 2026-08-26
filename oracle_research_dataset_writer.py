"""Pure transaction contract for staging and freezing Oracle research datasets.

The writer owns no database connection, credentials, schema application, or
network transport. A production adapter would need separate approval and must
implement ``ImmediateTransactionRunner`` exactly: begin an immediate isolated
transaction, run the callback, commit only on success, and roll back on every
exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Protocol, TypeVar

from model_lineage import LineageError
from oracle_research_dataset import (
    OracleProviderLineage,
    _lineage_rows,
    _one,
    _sha256,
    _utc,
    compute_provider_lineage_sha256,
    load_frozen_oracle_research_dataset,
)


T = TypeVar("T")


class OracleResearchTransaction(Protocol):
    """Narrow SQL surface available only inside one isolated transaction."""

    def execute(self, query: str, args: list[object]): ...

    def execute_mutation(self, query: str, args: list[object]) -> int: ...


class ImmediateTransactionRunner(Protocol):
    """Injectable atomicity boundary; adapters must commit or roll back wholly."""

    def run_immediate(
        self,
        operation_id: str,
        callback: Callable[[OracleResearchTransaction], T],
    ) -> T: ...


@dataclass(frozen=True)
class OracleResearchDatasetStageIntent:
    dataset_version_id: str
    market_snapshot_id: str
    market_snapshot_checksum_sha256: str
    source_session_date: date
    evidence_cutoff_utc: datetime
    first_session_date: date
    last_session_date: date
    expected_row_count: int
    expected_ticker_count: int
    expected_session_count: int
    expected_provider_lineage_count: int
    content_sha256: str
    ticker_universe_sha256: str
    provider_lineage_sha256: str
    schema_version: str
    code_version: str
    created_at_utc: datetime


@dataclass(frozen=True)
class OracleResearchDatasetFreezeEvidence:
    event_id: str
    actor: str
    decided_at_utc: datetime
    evidence_sha256: str
    market_snapshot_checksum_sha256: str
    content_sha256: str
    ticker_universe_sha256: str
    provider_lineage_sha256: str


@dataclass(frozen=True)
class OracleResearchDatasetWriteReceipt:
    operation_id: str
    dataset_version_id: str
    status: str
    market_snapshot_id: str
    provider_lineage_count: int
    created: bool
    event_id: str | None = None


def _validate_stage_intent(intent: OracleResearchDatasetStageIntent) -> None:
    for field in (
        "dataset_version_id", "market_snapshot_id", "schema_version", "code_version"
    ):
        value = str(getattr(intent, field))
        if not value.strip():
            raise LineageError(f"Research stage intent requires {field}.")
        if value != value.strip():
            raise LineageError(
                f"Research stage intent {field} cannot contain surrounding whitespace."
            )
    for value, field in (
        (intent.market_snapshot_checksum_sha256, "Market snapshot checksum"),
        (intent.content_sha256, "Research content checksum"),
        (intent.ticker_universe_sha256, "Ticker-universe checksum"),
        (intent.provider_lineage_sha256, "Provider-lineage checksum"),
    ):
        _sha256(value, field=field)
    if intent.evidence_cutoff_utc.tzinfo is None or intent.created_at_utc.tzinfo is None:
        raise LineageError("Research stage timestamps must be timezone-aware.")
    cutoff = intent.evidence_cutoff_utc.astimezone(timezone.utc)
    created = intent.created_at_utc.astimezone(timezone.utc)
    if created < cutoff:
        raise LineageError("Research dataset cannot be created before its evidence cutoff.")
    if intent.first_session_date > intent.last_session_date:
        raise LineageError("Research dataset session range is invalid.")
    if intent.last_session_date != intent.source_session_date:
        raise LineageError("Research dataset must end at its source session.")
    counts = (
        intent.expected_row_count,
        intent.expected_ticker_count,
        intent.expected_session_count,
        intent.expected_provider_lineage_count,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in counts):
        raise LineageError("Research dataset expected counts must be positive integers.")


def _validate_freeze_evidence(
    intent: OracleResearchDatasetStageIntent,
    evidence: OracleResearchDatasetFreezeEvidence,
) -> None:
    if not evidence.event_id.strip() or not evidence.actor.strip():
        raise LineageError("Research freeze requires an event ID and accountable actor.")
    if (
        evidence.event_id != evidence.event_id.strip()
        or evidence.actor != evidence.actor.strip()
    ):
        raise LineageError(
            "Research freeze event ID and actor cannot contain surrounding whitespace."
        )
    if evidence.decided_at_utc.tzinfo is None:
        raise LineageError("Research freeze decision timestamp must be timezone-aware.")
    decided = evidence.decided_at_utc.astimezone(timezone.utc)
    if decided < intent.created_at_utc.astimezone(timezone.utc):
        raise LineageError("Research freeze cannot precede dataset staging.")
    _sha256(evidence.evidence_sha256, field="Freeze evidence checksum")
    expected = (
        intent.market_snapshot_checksum_sha256,
        intent.content_sha256,
        intent.ticker_universe_sha256,
        intent.provider_lineage_sha256,
    )
    observed = (
        _sha256(evidence.market_snapshot_checksum_sha256, field="Freeze market checksum"),
        _sha256(evidence.content_sha256, field="Freeze content checksum"),
        _sha256(evidence.ticker_universe_sha256, field="Freeze ticker checksum"),
        _sha256(evidence.provider_lineage_sha256, field="Freeze provider checksum"),
    )
    if observed != expected:
        raise LineageError("Freeze event evidence does not match the staged dataset identity.")


def _source_provider_lineage(
    db,
    intent: OracleResearchDatasetStageIntent,
) -> tuple[OracleProviderLineage, ...]:
    columns = (
        "ticker", "provider", "requested_source_session_date", "first_available_date",
        "last_available_date", "source_row_count", "source_checksum_sha256",
    )
    result = db.execute(
        """SELECT ticker,provider,requested_source_session_date,first_available_date,
        last_available_date,source_row_count,source_checksum_sha256
        FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker""",
        [intent.market_snapshot_id],
    )
    if tuple(result.columns) != columns:
        raise LineageError("Source provider lineage query returned an invalid contract.")
    lineage = _lineage_rows(result, source_session_date=intent.source_session_date)
    if len(lineage) != intent.expected_provider_lineage_count:
        raise LineageError("Source provider-lineage count differs from stage intent.")
    if compute_provider_lineage_sha256(lineage) != intent.provider_lineage_sha256:
        raise LineageError("Source provider-lineage digest differs from stage intent.")
    return lineage


def _verify_source(
    db,
    intent: OracleResearchDatasetStageIntent,
) -> tuple[OracleProviderLineage, ...]:
    snapshot = _one(
        db.execute(
            """SELECT dataset_type,source_session_date,available_at_utc,
            source_checksum_sha256,expected_row_count,expected_ticker_count,status
            FROM model_input_snapshots WHERE snapshot_id=?""",
            [intent.market_snapshot_id],
        ),
        label="Research source snapshot",
    )
    if str(snapshot["dataset_type"]) != "MARKET_FEATURES":
        raise LineageError("Research source must be a MARKET_FEATURES snapshot.")
    if str(snapshot["status"]) != "VALIDATED":
        raise LineageError("Research source snapshot is not VALIDATED.")
    if str(snapshot["source_session_date"]) != intent.source_session_date.isoformat():
        raise LineageError("Research source session differs from stage intent.")
    if _sha256(snapshot["source_checksum_sha256"], field="Source snapshot checksum") != (
        intent.market_snapshot_checksum_sha256
    ):
        raise LineageError("Research source checksum differs from stage intent.")
    if int(snapshot["expected_row_count"]) != intent.expected_row_count:
        raise LineageError("Research source row metadata differs from stage intent.")
    if int(snapshot["expected_ticker_count"]) != intent.expected_ticker_count:
        raise LineageError("Research source ticker metadata differs from stage intent.")
    available = _utc(snapshot["available_at_utc"], field="Source availability")
    if available > intent.evidence_cutoff_utc.astimezone(timezone.utc):
        raise LineageError("Research source became available after the evidence cutoff.")

    coverage = _one(
        db.execute(
            """SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,
            COUNT(DISTINCT date) AS session_count,MIN(date) AS first_session_date,
            MAX(date) AS last_session_date FROM market_daily_features
            WHERE snapshot_id=?""",
            [intent.market_snapshot_id],
        ),
        label="Research source coverage",
    )
    expected = (
        intent.expected_row_count,
        intent.expected_ticker_count,
        intent.expected_session_count,
        intent.first_session_date.isoformat(),
        intent.last_session_date.isoformat(),
    )
    observed = (
        int(coverage["row_count"]),
        int(coverage["ticker_count"]),
        int(coverage["session_count"]),
        str(coverage["first_session_date"]),
        str(coverage["last_session_date"]),
    )
    if observed != expected:
        raise LineageError("Research source coverage differs from stage intent.")
    return _source_provider_lineage(db, intent)


def _version_row(db, dataset_version_id: str) -> dict[str, object] | None:
    result = db.execute(
        """SELECT dataset_version_id,market_snapshot_id,
        market_snapshot_checksum_sha256,source_session_date,evidence_cutoff_utc,
        first_session_date,last_session_date,expected_row_count,
        expected_ticker_count,expected_session_count,
        expected_provider_lineage_count,content_sha256,ticker_universe_sha256,
        provider_lineage_sha256,schema_version,code_version,status,
        freeze_approval_id,frozen_by,frozen_at_utc,created_at_utc
        FROM oracle_research_dataset_versions WHERE dataset_version_id=?""",
        [dataset_version_id],
    )
    if not result.rows:
        return None
    return _one(result, label="Research dataset version")


def _assert_exact_staging(
    db,
    intent: OracleResearchDatasetStageIntent,
    source_lineage: tuple[OracleProviderLineage, ...],
) -> None:
    row = _version_row(db, intent.dataset_version_id)
    if row is None:
        raise LineageError("Staged research dataset is missing.")
    expected = {
        "market_snapshot_id": intent.market_snapshot_id,
        "market_snapshot_checksum_sha256": intent.market_snapshot_checksum_sha256,
        "source_session_date": intent.source_session_date.isoformat(),
        "evidence_cutoff_utc": intent.evidence_cutoff_utc.astimezone(timezone.utc).isoformat(),
        "first_session_date": intent.first_session_date.isoformat(),
        "last_session_date": intent.last_session_date.isoformat(),
        "expected_row_count": intent.expected_row_count,
        "expected_ticker_count": intent.expected_ticker_count,
        "expected_session_count": intent.expected_session_count,
        "expected_provider_lineage_count": intent.expected_provider_lineage_count,
        "content_sha256": intent.content_sha256,
        "ticker_universe_sha256": intent.ticker_universe_sha256,
        "provider_lineage_sha256": intent.provider_lineage_sha256,
        "schema_version": intent.schema_version,
        "code_version": intent.code_version,
        "status": "STAGING",
        "created_at_utc": intent.created_at_utc.astimezone(timezone.utc).isoformat(),
    }
    if any(str(row[key]) != str(value) for key, value in expected.items()):
        raise LineageError("Existing staged research dataset differs from retry intent.")
    if any(row[field] is not None for field in ("freeze_approval_id", "frozen_by", "frozen_at_utc")):
        raise LineageError("Staged research dataset unexpectedly contains freeze evidence.")
    events = _one(
        db.execute(
            "SELECT COUNT(*) AS event_count FROM oracle_research_dataset_events "
            "WHERE dataset_version_id=?",
            [intent.dataset_version_id],
        ),
        label="Staged research event count",
    )
    if int(events["event_count"]) != 0:
        raise LineageError("Staged research dataset already has lifecycle events.")
    bindings = db.execute(
        """SELECT ticker,provider,requested_source_session_date,first_available_date,
        last_available_date,source_row_count,source_checksum_sha256
        FROM oracle_research_dataset_provider_lineage
        WHERE dataset_version_id=? ORDER BY ticker""",
        [intent.dataset_version_id],
    )
    bound = _lineage_rows(bindings, source_session_date=intent.source_session_date)
    if bound != source_lineage:
        raise LineageError("Staged provider binding differs from its source snapshot.")


class OracleResearchDatasetWriter:
    """Idempotent stage/freeze orchestration over an injected transaction runner."""

    def __init__(self, reader, transaction_runner: ImmediateTransactionRunner):
        if reader is None or transaction_runner is None:
            raise LineageError("Research dataset writer requires reader and transaction runner.")
        self.reader = reader
        self.transaction_runner = transaction_runner

    @staticmethod
    def _stage_receipt(intent, *, created: bool) -> OracleResearchDatasetWriteReceipt:
        return OracleResearchDatasetWriteReceipt(
            operation_id=f"stage:{intent.dataset_version_id}",
            dataset_version_id=intent.dataset_version_id,
            status="STAGING",
            market_snapshot_id=intent.market_snapshot_id,
            provider_lineage_count=intent.expected_provider_lineage_count,
            created=created,
        )

    def _reconcile_staging(self, intent) -> OracleResearchDatasetWriteReceipt:
        source = _verify_source(self.reader, intent)
        _assert_exact_staging(self.reader, intent, source)
        return self._stage_receipt(intent, created=False)

    def stage(
        self, intent: OracleResearchDatasetStageIntent
    ) -> OracleResearchDatasetWriteReceipt:
        """Atomically stage exact metadata and a copied provider binding."""
        _validate_stage_intent(intent)
        operation_id = f"stage:{intent.dataset_version_id}"

        def callback(tx: OracleResearchTransaction):
            source = _verify_source(tx, intent)
            existing = _version_row(tx, intent.dataset_version_id)
            if existing is not None:
                _assert_exact_staging(tx, intent, source)
                return self._stage_receipt(intent, created=False)
            affected = tx.execute_mutation(
                """INSERT INTO oracle_research_dataset_versions
                (dataset_version_id,market_snapshot_id,
                 market_snapshot_checksum_sha256,source_session_date,
                 evidence_cutoff_utc,first_session_date,last_session_date,
                 expected_row_count,expected_ticker_count,expected_session_count,
                 expected_provider_lineage_count,content_sha256,
                 ticker_universe_sha256,provider_lineage_sha256,schema_version,
                 code_version,status,created_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    intent.dataset_version_id,
                    intent.market_snapshot_id,
                    intent.market_snapshot_checksum_sha256,
                    intent.source_session_date.isoformat(),
                    intent.evidence_cutoff_utc.astimezone(timezone.utc).isoformat(),
                    intent.first_session_date.isoformat(),
                    intent.last_session_date.isoformat(),
                    intent.expected_row_count,
                    intent.expected_ticker_count,
                    intent.expected_session_count,
                    intent.expected_provider_lineage_count,
                    intent.content_sha256,
                    intent.ticker_universe_sha256,
                    intent.provider_lineage_sha256,
                    intent.schema_version,
                    intent.code_version,
                    "STAGING",
                    intent.created_at_utc.astimezone(timezone.utc).isoformat(),
                ],
            )
            if affected != 1:
                raise LineageError("Research stage did not insert exactly one version row.")
            affected = tx.execute_mutation(
                """INSERT INTO oracle_research_dataset_provider_lineage
                (dataset_version_id,ticker,provider,
                 requested_source_session_date,first_available_date,
                 last_available_date,source_row_count,source_checksum_sha256,
                 created_at_utc)
                SELECT ?,ticker,provider,requested_source_session_date,
                       first_available_date,last_available_date,source_row_count,
                       source_checksum_sha256,?
                FROM market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker""",
                [
                    intent.dataset_version_id,
                    intent.created_at_utc.astimezone(timezone.utc).isoformat(),
                    intent.market_snapshot_id,
                ],
            )
            if affected != intent.expected_provider_lineage_count:
                raise LineageError("Research stage provider binding count is not exact.")
            _assert_exact_staging(tx, intent, source)
            return self._stage_receipt(intent, created=True)

        try:
            return self.transaction_runner.run_immediate(operation_id, callback)
        except Exception as exc:
            try:
                return self._reconcile_staging(intent)
            except Exception as reconciliation_error:
                raise LineageError(
                    "Research stage transaction failed without exact idempotent readback."
                ) from exc

    @staticmethod
    def _frozen_receipt(intent, evidence, *, created: bool):
        return OracleResearchDatasetWriteReceipt(
            operation_id=f"freeze:{intent.dataset_version_id}:{evidence.event_id}",
            dataset_version_id=intent.dataset_version_id,
            status="FROZEN",
            market_snapshot_id=intent.market_snapshot_id,
            provider_lineage_count=intent.expected_provider_lineage_count,
            created=created,
            event_id=evidence.event_id,
        )

    def _reconcile_frozen(self, intent, evidence, *, created: bool, db=None):
        read_db = self.reader if db is None else db
        frozen = load_frozen_oracle_research_dataset(
            read_db,
            dataset_version_id=intent.dataset_version_id,
            expected_market_snapshot_id=intent.market_snapshot_id,
            expected_market_snapshot_checksum_sha256=(
                intent.market_snapshot_checksum_sha256
            ),
            expected_source_session_date=intent.source_session_date,
            cutoff_utc=evidence.decided_at_utc,
        )
        if (
            frozen.freeze_approval_id != evidence.event_id
            or frozen.frozen_by != evidence.actor
            or frozen.content_sha256 != evidence.content_sha256
            or frozen.ticker_universe_sha256 != evidence.ticker_universe_sha256
            or frozen.provider_lineage_sha256 != evidence.provider_lineage_sha256
        ):
            raise LineageError("Frozen research readback differs from freeze evidence.")
        return self._frozen_receipt(intent, evidence, created=created)

    def freeze(
        self,
        intent: OracleResearchDatasetStageIntent,
        evidence: OracleResearchDatasetFreezeEvidence,
    ) -> OracleResearchDatasetWriteReceipt:
        """Atomically append explicit freeze evidence and freeze one staged version."""
        _validate_stage_intent(intent)
        _validate_freeze_evidence(intent, evidence)
        operation_id = f"freeze:{intent.dataset_version_id}:{evidence.event_id}"

        def callback(tx: OracleResearchTransaction):
            source = _verify_source(tx, intent)
            existing = _version_row(tx, intent.dataset_version_id)
            if existing is None:
                raise LineageError("Research dataset must be staged before freezing.")
            if str(existing["status"]) == "FROZEN":
                return self._reconcile_frozen(
                    intent, evidence, created=False, db=tx
                )
            _assert_exact_staging(tx, intent, source)
            decided = evidence.decided_at_utc.astimezone(timezone.utc).isoformat()
            affected = tx.execute_mutation(
                """INSERT INTO oracle_research_dataset_events
                (event_id,dataset_version_id,event_type,
                 market_snapshot_checksum_sha256,content_sha256,
                 ticker_universe_sha256,provider_lineage_sha256,actor,
                 decided_at_utc,evidence_sha256,created_at_utc)
                VALUES (?,?,'FREEZE',?,?,?,?,?,?,?,?)""",
                [
                    evidence.event_id,
                    intent.dataset_version_id,
                    evidence.market_snapshot_checksum_sha256,
                    evidence.content_sha256,
                    evidence.ticker_universe_sha256,
                    evidence.provider_lineage_sha256,
                    evidence.actor.strip(),
                    decided,
                    evidence.evidence_sha256,
                    decided,
                ],
            )
            if affected != 1:
                raise LineageError("Research freeze did not append exactly one event.")
            affected = tx.execute_mutation(
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
                  )""",
                [
                    evidence.event_id,
                    evidence.actor.strip(),
                    decided,
                    intent.dataset_version_id,
                    intent.market_snapshot_id,
                    intent.market_snapshot_checksum_sha256,
                    intent.content_sha256,
                    intent.ticker_universe_sha256,
                    intent.provider_lineage_sha256,
                    evidence.event_id,
                    intent.dataset_version_id,
                ],
            )
            if affected != 1:
                raise LineageError("Research freeze did not transition exactly one staged version.")
            return self._reconcile_frozen(intent, evidence, created=True, db=tx)

        try:
            return self.transaction_runner.run_immediate(operation_id, callback)
        except Exception as exc:
            try:
                return self._reconcile_frozen(intent, evidence, created=False)
            except Exception:
                raise LineageError(
                    "Research freeze transaction failed without exact idempotent readback."
                ) from exc
