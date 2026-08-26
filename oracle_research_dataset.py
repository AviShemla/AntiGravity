"""Fail-closed reader for immutable, Turso-backed Oracle research datasets.

This module is read-only.  Dataset creation, freezing, revocation, and schema
application are deliberately outside this interface and require explicit
production approval.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from model_lineage import LineageError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVIDERS = {"YAHOO_FINANCE", "TIINGO_EOD"}


def _sha256(value: object, *, field: str) -> str:
    digest = str(value or "")
    if not _SHA256.fullmatch(digest):
        raise LineageError(f"{field} must be a lowercase SHA-256 digest.")
    return digest


def _utc(value: object, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{field} is invalid.") from exc
    if parsed.tzinfo is None:
        raise LineageError(f"{field} must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _one(result, *, label: str) -> dict[str, object]:
    if len(result.rows) != 1:
        raise LineageError(f"{label} must return exactly one row.")
    return dict(zip(result.columns, result.rows[0]))


@dataclass(frozen=True)
class OracleProviderLineage:
    ticker: str
    provider: str
    requested_source_session_date: date
    first_available_date: date
    last_available_date: date
    source_row_count: int
    source_checksum_sha256: str


@dataclass(frozen=True)
class OracleResearchDatasetVersion:
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
    freeze_approval_id: str
    frozen_by: str
    frozen_at_utc: datetime
    provider_lineage: tuple[OracleProviderLineage, ...]


def canonical_provider_lineage_bytes(
    lineage: tuple[OracleProviderLineage, ...],
) -> bytes:
    """Serialize provider lineage for its independently reproducible digest.

    Canonical form is UTF-8 JSON Lines, sorted by ticker. Each compact JSON
    array contains, in order: ticker, provider, requested source session,
    first available date, last available date, source row count, and lowercase
    source SHA-256. The document ends with exactly one LF byte.
    """
    if not lineage:
        raise LineageError("Research provider lineage cannot be empty.")
    ordered = sorted(lineage, key=lambda item: item.ticker)
    if len({item.ticker for item in ordered}) != len(ordered):
        raise LineageError("Research provider lineage contains duplicate tickers.")
    records = [
        [
            item.ticker,
            item.provider,
            item.requested_source_session_date.isoformat(),
            item.first_available_date.isoformat(),
            item.last_available_date.isoformat(),
            item.source_row_count,
            item.source_checksum_sha256,
        ]
        for item in ordered
    ]
    return (
        "\n".join(
            json.dumps(record, ensure_ascii=True, separators=(",", ":"))
            for record in records
        )
        + "\n"
    ).encode("utf-8")


def compute_provider_lineage_sha256(
    lineage: tuple[OracleProviderLineage, ...],
) -> str:
    """Return the SHA-256 of ``canonical_provider_lineage_bytes``."""
    return hashlib.sha256(canonical_provider_lineage_bytes(lineage)).hexdigest()


def _lineage_rows(result, *, source_session_date: date) -> tuple[OracleProviderLineage, ...]:
    rows: list[OracleProviderLineage] = []
    seen: set[str] = set()
    for raw in result.rows:
        row = dict(zip(result.columns, raw))
        ticker = str(row["ticker"] or "").strip().upper()
        provider = str(row["provider"] or "").strip().upper()
        if not ticker or ticker in seen:
            raise LineageError("Research provider lineage contains a blank or duplicate ticker.")
        if provider not in _PROVIDERS:
            raise LineageError(f"Unsupported research provider lineage: {provider!r}.")
        requested = date.fromisoformat(str(row["requested_source_session_date"]))
        first = date.fromisoformat(str(row["first_available_date"]))
        last = date.fromisoformat(str(row["last_available_date"]))
        count = int(row["source_row_count"])
        if requested != source_session_date or last != source_session_date:
            raise LineageError("Research provider lineage does not end at the source session.")
        if first > last or count <= 0:
            raise LineageError("Research provider lineage has an invalid date or row range.")
        seen.add(ticker)
        rows.append(
            OracleProviderLineage(
                ticker=ticker,
                provider=provider,
                requested_source_session_date=requested,
                first_available_date=first,
                last_available_date=last,
                source_row_count=count,
                source_checksum_sha256=_sha256(
                    row["source_checksum_sha256"], field="Provider source checksum"
                ),
            )
        )
    return tuple(rows)


def load_frozen_oracle_research_dataset(
    db,
    *,
    dataset_version_id: str,
    expected_market_snapshot_id: str,
    expected_market_snapshot_checksum_sha256: str,
    expected_source_session_date: date,
    cutoff_utc: datetime,
) -> OracleResearchDatasetVersion:
    """Read and reconcile one exact frozen research dataset version.

    The caller must supply the expected snapshot identity, checksum, source
    session, and point-in-time cutoff. Any mismatch, revocation, missing freeze
    evidence, count drift, or provider-lineage drift raises ``LineageError``.
    """
    if not dataset_version_id.strip() or not expected_market_snapshot_id.strip():
        raise LineageError("Research dataset and market snapshot IDs are required.")
    expected_checksum = _sha256(
        expected_market_snapshot_checksum_sha256,
        field="Expected market snapshot checksum",
    )
    if cutoff_utc.tzinfo is None:
        raise LineageError("Research dataset cutoff must be timezone-aware.")
    cutoff = cutoff_utc.astimezone(timezone.utc)

    version = _one(
        db.execute(
            """
            SELECT d.dataset_version_id,d.market_snapshot_id,
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
            WHERE d.dataset_version_id=?
            """,
            [dataset_version_id],
        ),
        label="Research dataset version",
    )
    if str(version["status"]) != "FROZEN":
        raise LineageError("Research dataset version is not FROZEN.")
    if str(version["snapshot_status"]) != "VALIDATED":
        raise LineageError("Research dataset market snapshot is not VALIDATED.")
    if str(version["snapshot_dataset_type"]) != "MARKET_FEATURES":
        raise LineageError("Research dataset must bind a MARKET_FEATURES snapshot.")

    snapshot_id = str(version["market_snapshot_id"])
    snapshot_checksum = _sha256(
        version["market_snapshot_checksum_sha256"],
        field="Bound market snapshot checksum",
    )
    metadata_checksum = _sha256(
        version["snapshot_checksum_sha256"], field="Market snapshot metadata checksum"
    )
    source_session = date.fromisoformat(str(version["source_session_date"]))
    if snapshot_id != expected_market_snapshot_id:
        raise LineageError("Research dataset binds a different market snapshot ID.")
    if snapshot_checksum != expected_checksum or metadata_checksum != expected_checksum:
        raise LineageError("Research dataset market checksum does not match the expected snapshot.")
    if source_session != expected_source_session_date:
        raise LineageError("Research dataset source session does not match the expected session.")
    if str(version["snapshot_source_session_date"]) != source_session.isoformat():
        raise LineageError("Research dataset and market metadata source sessions disagree.")

    evidence_cutoff = _utc(version["evidence_cutoff_utc"], field="Evidence cutoff")
    available_at = _utc(
        version["snapshot_available_at_utc"], field="Market snapshot availability"
    )
    frozen_at = _utc(version["frozen_at_utc"], field="Dataset freeze timestamp")
    if available_at > evidence_cutoff or evidence_cutoff > frozen_at or frozen_at > cutoff:
        raise LineageError("Research dataset point-in-time chronology is invalid.")

    row_count = int(version["expected_row_count"])
    ticker_count = int(version["expected_ticker_count"])
    session_count = int(version["expected_session_count"])
    provider_count = int(version["expected_provider_lineage_count"])
    if min(row_count, ticker_count, session_count, provider_count) <= 0:
        raise LineageError("Frozen research dataset counts must all be positive.")
    if row_count != int(version["snapshot_expected_row_count"]):
        raise LineageError("Research row count differs from market snapshot metadata.")
    if ticker_count != int(version["snapshot_expected_ticker_count"]):
        raise LineageError("Research ticker count differs from market snapshot metadata.")

    for field in ("freeze_approval_id", "frozen_by", "schema_version", "code_version"):
        if not str(version[field] or "").strip():
            raise LineageError(f"Frozen research dataset is missing {field}.")
    content_sha = _sha256(version["content_sha256"], field="Research content checksum")
    ticker_sha = _sha256(
        version["ticker_universe_sha256"], field="Research ticker-universe checksum"
    )
    provider_sha = _sha256(
        version["provider_lineage_sha256"], field="Research provider-lineage checksum"
    )

    event = _one(
        db.execute(
            """
            SELECT event_id,event_type,market_snapshot_checksum_sha256,
                   content_sha256,ticker_universe_sha256,provider_lineage_sha256,
                   actor,decided_at_utc,evidence_sha256
            FROM oracle_research_dataset_events
            WHERE dataset_version_id=?
            ORDER BY decided_at_utc DESC,event_id DESC LIMIT 1
            """,
            [dataset_version_id],
        ),
        label="Latest research dataset event",
    )
    if str(event["event_type"]) != "FREEZE":
        raise LineageError("Latest research dataset event is not FREEZE.")
    if str(event["event_id"]) != str(version["freeze_approval_id"]):
        raise LineageError("Research freeze event does not match the dataset version.")
    if str(event["actor"] or "").strip() != str(version["frozen_by"]).strip():
        raise LineageError("Research freeze actor does not match the dataset version.")
    if _utc(event["decided_at_utc"], field="Freeze decision timestamp") != frozen_at:
        raise LineageError("Research freeze timestamp does not match its event.")
    event_hashes = (
        _sha256(event["market_snapshot_checksum_sha256"], field="Event market checksum"),
        _sha256(event["content_sha256"], field="Event content checksum"),
        _sha256(event["ticker_universe_sha256"], field="Event ticker checksum"),
        _sha256(event["provider_lineage_sha256"], field="Event provider checksum"),
    )
    if event_hashes != (snapshot_checksum, content_sha, ticker_sha, provider_sha):
        raise LineageError("Research freeze event checksums do not match the dataset version.")
    _sha256(event["evidence_sha256"], field="Freeze evidence checksum")

    counts = _one(
        db.execute(
            """
            SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,
                   COUNT(DISTINCT date) AS session_count,
                   MIN(date) AS first_session_date,MAX(date) AS last_session_date
            FROM market_daily_features WHERE snapshot_id=?
            """,
            [snapshot_id],
        ),
        label="Research market coverage",
    )
    first_session = date.fromisoformat(str(version["first_session_date"]))
    last_session = date.fromisoformat(str(version["last_session_date"]))
    if (
        int(counts["row_count"]) != row_count
        or int(counts["ticker_count"]) != ticker_count
        or int(counts["session_count"]) != session_count
        or str(counts["first_session_date"]) != first_session.isoformat()
        or str(counts["last_session_date"]) != last_session.isoformat()
        or last_session != source_session
    ):
        raise LineageError("Frozen research dataset market coverage has drifted.")

    columns = (
        "ticker", "provider", "requested_source_session_date", "first_available_date",
        "last_available_date", "source_row_count", "source_checksum_sha256",
    )
    bound_result = db.execute(
        """
        SELECT ticker,provider,requested_source_session_date,first_available_date,
               last_available_date,source_row_count,source_checksum_sha256
        FROM oracle_research_dataset_provider_lineage
        WHERE dataset_version_id=? ORDER BY ticker
        """,
        [dataset_version_id],
    )
    actual_result = db.execute(
        """
        SELECT ticker,provider,requested_source_session_date,first_available_date,
               last_available_date,source_row_count,source_checksum_sha256
        FROM market_data_provider_lineage
        WHERE snapshot_id=? ORDER BY ticker
        """,
        [snapshot_id],
    )
    if tuple(bound_result.columns) != columns or tuple(actual_result.columns) != columns:
        raise LineageError("Research provider lineage query returned an invalid contract.")
    bound = _lineage_rows(bound_result, source_session_date=source_session)
    actual = _lineage_rows(actual_result, source_session_date=source_session)
    if len(bound) != provider_count or bound != actual:
        raise LineageError("Frozen research dataset provider lineage has drifted.")
    if compute_provider_lineage_sha256(bound) != provider_sha:
        raise LineageError("Frozen research dataset provider-lineage digest does not match.")

    return OracleResearchDatasetVersion(
        dataset_version_id=dataset_version_id,
        market_snapshot_id=snapshot_id,
        market_snapshot_checksum_sha256=snapshot_checksum,
        source_session_date=source_session,
        evidence_cutoff_utc=evidence_cutoff,
        first_session_date=first_session,
        last_session_date=last_session,
        expected_row_count=row_count,
        expected_ticker_count=ticker_count,
        expected_session_count=session_count,
        expected_provider_lineage_count=provider_count,
        content_sha256=content_sha,
        ticker_universe_sha256=ticker_sha,
        provider_lineage_sha256=provider_sha,
        schema_version=str(version["schema_version"]),
        code_version=str(version["code_version"]),
        freeze_approval_id=str(version["freeze_approval_id"]),
        frozen_by=str(version["frozen_by"]),
        frozen_at_utc=frozen_at,
        provider_lineage=bound,
    )
