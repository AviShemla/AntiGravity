"""Hash-bound production Oracle schema/freeze execution.

This launcher is deliberately phase-separated.  It performs only the approved
additive schema application or the approved research-dataset stage/freeze and
their read-only reconciliations.  It contains no promotion, model, ETF,
recommendation, order, trading, email, or service-activation surface.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from oracle_production_authorization_envelope import (
    load_canonical,
    validate_runtime_authorization,
)
from oracle_research_dataset_freeze_manifest import (
    build_oracle_research_dataset_freeze_manifest,
    verified_freeze_manifest_inputs,
)
from oracle_research_dataset import (
    _lineage_rows,
    compute_provider_lineage_sha256,
    load_frozen_oracle_research_dataset,
)
from oracle_research_dataset_turso_adapter_v2 import (
    InjectedTursoImmediateTransactionRunner,
)
from oracle_research_dataset_writer import (
    OracleResearchDatasetFreezeEvidence,
    OracleResearchDatasetStageIntent,
    OracleResearchDatasetWriter,
)
from scripts.apply_atomic_migration import (
    apply_atomic_migration,
    parse_atomic_bundle,
    verify_expected_hash,
)
from turso_read_pipeline import TursoReadPipeline


ENVELOPE_SHA256 = "665fe03c889a96ec095e0b51ff69697b94e84de314d43af6a7c2fcfa880a796e"
SCHEMA_SHA256 = "d21aa91b356666c6509e234a74f3041130fc1e4ae62455086aa86b2b18e6e01e"
FREEZE_MANIFEST_SHA256 = "8e6a6f411803857950a6792b3729abedf41ae5026ec358211079f12004a63350"
SCHEMA_APPROVAL_ID = "avi-schema-oracle-rd-20260827-d21aa91b3566"
FREEZE_APPROVAL_ID = "avi-freeze-oracle-rd-20260827-07735e093c39"
DATASET_VERSION_ID = "oracle-research-20260825-60f2d9d6f68d7d7d9930abce00d4ba41"
SNAPSHOT_ID = "market_features_2026-08-25_5b1044ee45605a3d"
SNAPSHOT_SHA256 = "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011"
CONTENT_SHA256 = "07735e093c39546276082eba82f53a52d43a71cb1cff2d032b58f1315857a834"
TICKER_SHA256 = "267cdd0dba60a55346ba6f8a6e843259eacae924c9ea8740a093ea2cce3d1e26"
PROVIDER_SHA256 = "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a"
CONTENT_EVIDENCE_SHA256 = "b0b775d6aa4ff37faacb3987a65019724b358cdc86d5aa5967aea927c1401df3"
TARGET_DATABASE_ID = "theoracle-avishe"
ADAPTER_RELEASE_ID = "4e278ca52a838551c51b9da3b0afb7bfb3c8c5a0b16459228a53bd4c46899c05"
MIGRATION_ID = "20260826_oracle_research_dataset_versions_additive"


def _canonical_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _endpoint(raw_url: str) -> str:
    if raw_url.startswith("libsql://"):
        normalized = raw_url.replace("libsql://", "https://", 1)
    elif raw_url.startswith("https://"):
        normalized = raw_url
    else:
        raise LineageError("Production Turso URL scheme is missing or invalid.")
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
        raise LineageError("Production Turso URL shape is invalid.")
    return normalized.rstrip("/") + "/v2/pipeline"


class AtomicPipelineTransport:
    """Minimal secret-safe Hrana transport; never logs headers or bodies."""

    def __init__(self, endpoint: str, token: str, session, *, timeout: float = 45.0):
        if not endpoint.startswith("https://") or not endpoint.endswith("/v2/pipeline"):
            raise LineageError("Atomic transport endpoint is invalid.")
        if not token:
            raise LineageError("Atomic transport token is missing.")
        self._endpoint, self._token, self._session, self._timeout = endpoint, token, session, timeout

    def send(self, requests: list[dict[str, object]], *, baton: str | None = None) -> dict:
        body: dict[str, object] = {"requests": requests}
        if baton is not None:
            body["baton"] = baton
        response = self._session.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            json=body,
            timeout=self._timeout,
        )
        if response.status_code != 200:
            raise LineageError(f"Turso atomic transport failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise LineageError("Turso atomic transport returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise LineageError("Turso atomic transport returned an invalid payload.")
        return payload


def _one(reader, sql: str, args: list[object]) -> dict[str, object]:
    result = reader.execute(sql, args)
    if len(result.rows) != 1:
        raise LineageError("Independent readback did not return exactly one row.")
    return dict(zip(result.columns, result.rows[0]))


def verify_schema_readback(reader) -> dict[str, object]:
    objects = reader.execute(
        "SELECT type,name,sql FROM sqlite_schema WHERE name LIKE 'oracle_research_dataset_%' "
        "OR name LIKE 'trg_oracle_research_%' ORDER BY type,name", []
    )
    if len(objects.rows) != 26:
        raise LineageError("Oracle schema readback did not contain exactly 26 objects.")
    ledger = reader.execute(
        "SELECT event_id,migration_id,artifact_sha256,operation,target_database_id,evidence_json,executed_at_utc "
        "FROM schema_migration_events_v2 WHERE migration_id=? ORDER BY executed_at_utc,event_id",
        [MIGRATION_ID],
    )
    if len(ledger.rows) != 1:
        raise LineageError("Oracle schema APPLY ledger readback is not unique.")
    row = dict(zip(ledger.columns, ledger.rows[0]))
    if (row["artifact_sha256"], row["operation"], row["target_database_id"]) != (
        SCHEMA_SHA256, "APPLY", TARGET_DATABASE_ID
    ):
        raise LineageError("Oracle schema APPLY ledger identity differs from approval.")
    boundary = _one(
        reader,
        "SELECT (SELECT COUNT(*) FROM oracle_research_dataset_versions) AS versions,"
        "(SELECT COUNT(*) FROM oracle_research_dataset_provider_lineage) AS provider_rows,"
        "(SELECT COUNT(*) FROM oracle_research_dataset_events) AS events",
        [],
    )
    return {"object_count": 26, "apply_event_count": 1, "empty_boundary": boundary}


def verify_pre_schema(root: Path, reader, authorization_path: Path) -> dict[str, object]:
    """Read-only collision/duplicate check after all immutable approvals validate."""
    verify_envelope_approval(root, authorization_path, _canonical_utc_now())
    objects = reader.execute(
        "SELECT type,name,sql FROM sqlite_schema WHERE name LIKE 'oracle_research_dataset_%' "
        "OR name LIKE 'trg_oracle_research_%' ORDER BY type,name", []
    )
    ledger = reader.execute(
        "SELECT event_id,migration_id,artifact_sha256,operation,target_database_id,executed_at_utc "
        "FROM schema_migration_events_v2 WHERE migration_id=? ORDER BY executed_at_utc,event_id",
        [MIGRATION_ID],
    )
    if objects.rows or ledger.rows:
        raise LineageError("Production pre-schema readback found an existing object or APPLY identity.")
    return {"schema_object_count": 0, "migration_event_count": 0}


def _intent(created_at: datetime) -> OracleResearchDatasetStageIntent:
    return OracleResearchDatasetStageIntent(
        dataset_version_id=DATASET_VERSION_ID,
        market_snapshot_id=SNAPSHOT_ID,
        market_snapshot_checksum_sha256=SNAPSHOT_SHA256,
        source_session_date=date(2026, 8, 25),
        evidence_cutoff_utc=datetime(2026, 8, 26, 15, 8, 28, tzinfo=timezone.utc),
        first_session_date=date(2021, 9, 8),
        last_session_date=date(2026, 8, 25),
        expected_row_count=586710,
        expected_ticker_count=474,
        expected_session_count=1246,
        expected_provider_lineage_count=476,
        content_sha256=CONTENT_SHA256,
        ticker_universe_sha256=TICKER_SHA256,
        provider_lineage_sha256=PROVIDER_SHA256,
        schema_version="1",
        code_version="1e28786832b633c8b63163e7954e3297b0b9ec0e",
        created_at_utc=created_at,
    )


def _authorization_material(root: Path, authorization_path: Path):
    envelope_path = Path("/var/lib/codex-oracle-research/authorizations") / (
        f"oracle-production-envelope-{ENVELOPE_SHA256}/envelope.json"
    )
    envelope = load_canonical(envelope_path, ENVELOPE_SHA256)
    authorization = load_canonical(authorization_path)
    contract_path = root / "governance/oracle_research_dataset_application_contract_v2.json"
    release_root = Path("/var/lib/codex-oracle-research/releases")
    return envelope, authorization, contract_path, release_root


def verify_envelope_approval(root: Path, authorization_path: Path, observed: datetime) -> tuple:
    """Prove both approved operation identities without constructing transport."""
    envelope, authorization, contract_path, release_root = _authorization_material(
        root, authorization_path
    )
    for operation_id in (
        f"stage:{DATASET_VERSION_ID}",
        f"freeze:{DATASET_VERSION_ID}:{FREEZE_APPROVAL_ID}",
    ):
        validate_runtime_authorization(
            envelope,
            authorization,
            expected_envelope_sha256=ENVELOPE_SHA256,
            application_contract_path=contract_path,
            adapter_release_root=release_root,
            operation_id=operation_id,
            observed_at_utc=observed,
        )
    return envelope, authorization, contract_path, release_root


def verify_frozen_readback(reader, decided_at: datetime) -> dict[str, object]:
    frozen = load_frozen_oracle_research_dataset(
        reader,
        dataset_version_id=DATASET_VERSION_ID,
        expected_market_snapshot_id=SNAPSHOT_ID,
        expected_market_snapshot_checksum_sha256=SNAPSHOT_SHA256,
        expected_source_session_date=date(2026, 8, 25),
        cutoff_utc=decided_at,
    )
    if (
        frozen.content_sha256 != CONTENT_SHA256
        or frozen.ticker_universe_sha256 != TICKER_SHA256
        or frozen.provider_lineage_sha256 != PROVIDER_SHA256
        or frozen.freeze_approval_id != FREEZE_APPROVAL_ID
    ):
        raise LineageError("Frozen dataset readback differs from approved identity.")
    bindings = reader.execute(
        "SELECT ticker,provider,requested_source_session_date,first_available_date,last_available_date,"
        "source_row_count,source_checksum_sha256 FROM oracle_research_dataset_provider_lineage "
        "WHERE dataset_version_id=? ORDER BY ticker",
        [DATASET_VERSION_ID],
    )
    lineage = _lineage_rows(bindings, source_session_date=date(2026, 8, 25))
    if len(lineage) != 476 or compute_provider_lineage_sha256(lineage) != PROVIDER_SHA256:
        raise LineageError("Frozen provider-lineage readback differs from approval.")
    event_count = _one(
        reader,
        "SELECT COUNT(*) AS event_count FROM oracle_research_dataset_events WHERE dataset_version_id=?",
        [DATASET_VERSION_ID],
    )["event_count"]
    if int(event_count) != 1:
        raise LineageError("Frozen dataset lifecycle event count is not exactly one.")
    return {"status": "FROZEN", "provider_lineage_count": 476, "freeze_event_count": 1}


def apply_schema(
    root: Path, reader, session, endpoint: str, token: str,
    authorization_path: Path, *, actor: str
) -> dict:
    verify_envelope_approval(root, authorization_path, _canonical_utc_now())
    migration_path = root / "migrations/20260826_oracle_research_dataset_versions_additive.sql"
    migration = parse_atomic_bundle(migration_path.read_bytes())
    verify_expected_hash(migration, SCHEMA_SHA256)
    existing = reader.execute(
        "SELECT event_id FROM schema_migration_events_v2 WHERE migration_id=?", [MIGRATION_ID]
    )
    if existing.rows:
        return verify_schema_readback(reader)
    apply_atomic_migration(
        session, endpoint, token, migration,
        event_id=SCHEMA_APPROVAL_ID,
        actor=actor,
        target_database_id=TARGET_DATABASE_ID,
        evidence={"authorization_envelope_sha256": ENVELOPE_SHA256, "schema_approval_id": SCHEMA_APPROVAL_ID},
        executed_at_utc=_canonical_utc_now().isoformat().replace("+00:00", "Z"),
    )
    return verify_schema_readback(reader)


def freeze_dataset(root: Path, reader, session, endpoint: str, token: str, authorization_path: Path, *, actor: str) -> dict:
    observed = _canonical_utc_now()
    envelope, authorization, contract_path, release_root = verify_envelope_approval(
        root, authorization_path, observed
    )
    manifest = build_oracle_research_dataset_freeze_manifest(
        verified_freeze_manifest_inputs(),
        schema_approval_id=SCHEMA_APPROVAL_ID,
        freeze_approval_id=FREEZE_APPROVAL_ID,
    )
    if (
        manifest.dataset_version_id != DATASET_VERSION_ID
        or manifest.manifest_sha256 != FREEZE_MANIFEST_SHA256
    ):
        raise LineageError("Rebuilt freeze manifest differs from explicit approval.")
    created_raw = authorization.get("dataset_created_at_utc")
    decided_raw = authorization.get("freeze_decided_at_utc")
    # Runtime record keeps operation timestamps in a separate nested object so
    # the exact authorization schema consumed by the envelope remains unchanged.
    if created_raw is not None or decided_raw is not None:
        raise LineageError("Runtime authorization contains undeclared top-level timestamps.")
    created = observed
    decided = observed
    intent = _intent(created)
    evidence = OracleResearchDatasetFreezeEvidence(
        event_id=FREEZE_APPROVAL_ID,
        actor=actor,
        decided_at_utc=decided,
        evidence_sha256=FREEZE_MANIFEST_SHA256,
        market_snapshot_checksum_sha256=SNAPSHOT_SHA256,
        content_sha256=CONTENT_SHA256,
        ticker_universe_sha256=TICKER_SHA256,
        provider_lineage_sha256=PROVIDER_SHA256,
    )
    def runner(operation_id: str):
        return InjectedTursoImmediateTransactionRunner.from_authorization_envelope(
            lambda: AtomicPipelineTransport(endpoint, token, session),
            envelope=envelope,
            authorization=authorization,
            expected_envelope_sha256=ENVELOPE_SHA256,
            application_contract_path=contract_path,
            adapter_release_root=release_root,
            operation_id=operation_id,
            observed_at_utc=observed,
        )
    OracleResearchDatasetWriter(reader, runner(f"stage:{DATASET_VERSION_ID}")).stage(intent)
    OracleResearchDatasetWriter(
        reader, runner(f"freeze:{DATASET_VERSION_ID}:{FREEZE_APPROVAL_ID}")
    ).freeze(intent, evidence)
    return verify_frozen_readback(reader, decided)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "schema", "freeze", "readback"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--actor", default="avi-shemla")
    args = parser.parse_args()
    from dotenv import load_dotenv
    import requests
    load_dotenv(args.env_file if args.env_file is not None else args.root / ".env")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    endpoint = _endpoint(os.environ.get("TURSO_DATABASE_URL", ""))
    if not token:
        raise SystemExit("Production Turso token is missing.")
    session = requests.Session()
    reader = TursoReadPipeline(endpoint, token, session=session)
    if args.phase == "preflight":
        if args.authorization is None:
            raise SystemExit("Preflight phase requires --authorization.")
        result = verify_pre_schema(args.root, reader, args.authorization)
    elif args.phase == "schema":
        if args.authorization is None:
            raise SystemExit("Schema phase requires --authorization.")
        result = apply_schema(
            args.root, reader, session, endpoint, token, args.authorization,
            actor=args.actor,
        )
    elif args.phase == "freeze":
        if args.authorization is None:
            raise SystemExit("Freeze phase requires --authorization.")
        result = freeze_dataset(args.root, reader, session, endpoint, token, args.authorization, actor=args.actor)
    else:
        result = verify_frozen_readback(reader, _canonical_utc_now())
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
