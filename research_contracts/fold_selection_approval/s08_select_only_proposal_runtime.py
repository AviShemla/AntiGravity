"""Audit-only assembly of the unchanged S08 v5 approval proposal.

The runtime accepts an injected database client, executes only the exact
canonical SELECT statements used by the frozen-dataset and content readers,
and returns an in-memory signal panel plus an unsigned v5 proposal.  It has no
connection, credential, persistence, model, selector, or downstream-output
surface.  The missing independently installed S07 authority record remains a
deliberate execution blocker.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from model_lineage import LineageError
from oracle_research_dataset import load_frozen_oracle_research_dataset
from oracle_research_dataset_content_reader import (
    FIRST_PAGE_SQL, NEXT_PAGE_SQL, PinnedMarketSnapshot,
    stream_pinned_market_content,
)
from oracle_research_dataset_serializers import MARKET_DAILY_FEATURE_COLUMNS

from .s08_signal_panel_materializer import (
    FLOAT_CONTRACT, SIGNAL_CONTRACT, FrozenMarketBinding,
    ImportedSerializerBinding, S07SignalBinding, TrustedReadbackBinding,
    binding_artifact_sha256, canonical_session_dates_sha256,
    canonical_ticker_list_sha256, materialize_signal_panel,
    trusted_readback_artifact_sha256,
)
from .training_fold_selection_approval_v4 import canonical_json_bytes, sha256
from .training_fold_selection_approval_v5 import (
    ApprovalProposal, ProposalInputs, build_proposal,
)


CONTRACT_ID = "codex-oracle-s08-select-only-v5-proposal-assembly-v1"
CANONICAL_GIT_HEAD = "ad7d5853fe0d5f56dfbbf9f7ab3ea573a0e6e198"
CANONICAL_MODEL_SLICE_SHA256 = "ad119e6e33114a241fdd20268d4ca5cfabd1d6c08636f48f58545f4ccad2d66e"
CANONICAL_TICKER_LIST_SHA256 = "aab998d86840441e5a4cf75113a7b2f2c6260229181d2045f1f311de74cdfb9e"
EXPECTED_RAW_SHA256 = {
    "freeze_completion": "52f7cb83d5c3f55c93e1e354f2054e06d96d55687650a3451ede2d23e4f4886a",
    "content_completion": "6aaa2acf378b8833264e5f544acf1332fcd1b1e124229a059cef26a310986df8",
    "content_audit": "a77361be86febdc1ec750a28ba9a989636cb338a1ac52696da4e0ecee426b476",
    "serializer": "c4b7621663de01dc5a4a56abe73992ae89f9502612e614b7200c13ed3239eac7",
    "content_reader": "caf92cd75c7399648b9716b7c5ceba30171856ad243d48275fcb1e93e2b1118c",
    "materializer": "e5b7504c44494bd8245610e9109c5f9e097aad4eccf7b10a04eda4d6ff793a77",
    "proposal_v5": "545536acecfda78e3fa13a6aec825c8c7d4151b683f0d565e874da79b564b6cd",
    "proposal_v4": "45b61c8e325583899c0308017abafc2aac48f66cae722790c59ebbf9ff1d783a",
    "selector_v7": "2942a14627a29f74236d715b7b5f4eb58a9fb1e91b9451d7b4f6a681ad284b3b",
    "preregistration": "66e99535b5a57153b4035b37cbede4f5e141e7fae8910747d70ba6a31058a2e5",
    "preregistration_binding": "09decd7127eaca8f95cd277f84264ea32d5886be022796637ed31bd843e1d164",
}
EXPECTED_S07_RAW_SHA256 = {
    "current_readback": "02f1ed6a7b654c6856d0c1b2c9d2c1288f9756ead6f3909bc9db64877fe632cc",
    "current_readback_source": "f37a11474a10613b398289251cfb488494f428ba74c291f8548a33fcf8a3ab35",
    "preregistration_manifest": "9049c351795a9c80830f9b4153d4bece3b0849ea54d14f58662de3dc912a91dc",
    "independent_verification": "1ba1921b8b4c9f94da89ebae9b404d29475e2434f8844342526f280e5a8bb69d",
}
MAX_S07_READBACK_AGE_SECONDS = 300
_SHA = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|REPLACE|UPSERT|MERGE|"
    r"TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|BEGIN|COMMIT|ROLLBACK)\b", re.I,
)


class SelectOnlyAssemblyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CanonicalArtifactBytes:
    freeze_completion: bytes
    content_completion: bytes
    content_audit: bytes
    serializer: bytes
    content_reader: bytes
    materializer: bytes
    proposal_v5: bytes
    proposal_v4: bytes
    selector_v7: bytes
    preregistration: bytes
    preregistration_binding: bytes


@dataclass(frozen=True)
class AuditPins:
    model_session_dates_sha256: str = CANONICAL_MODEL_SLICE_SHA256
    ticker_list_sha256: str = CANONICAL_TICKER_LIST_SHA256


@dataclass(frozen=True)
class InstalledS07Artifacts:
    current_readback: bytes
    current_readback_source: bytes
    preregistration_manifest: bytes
    independent_verification: bytes
    owner_uid: int
    owner_gid: int
    mode: int
    link_count: int


@dataclass(frozen=True)
class SelectOnlyProposalAssembly:
    contract_id: str
    status: str
    canonical_git_head: str
    frozen_dataset_version: str
    snapshot_id: str
    frozen_content_sha256: str
    fresh_readback_evidence_sha256: str
    s07_reconstruction_sha256: str
    panel_sha256: str
    panel_shape: tuple[int, int]
    proposal: ApprovalProposal
    proposal_core_sha256: str
    query_count: int
    database_writes: int = 0
    selection_runs: int = 0
    model_runs: int = 0
    predictions: int = 0
    recommendations: int = 0
    orders: int = 0
    downstream_outputs: int = 0
    execution_authorized: bool = False
    s07_readback_fresh: bool = False
    s07_readback_age_seconds: float = 0.0
    unresolved_authority_gate: str = (
        "INDEPENDENT_INSTALLED_S07_APPROVAL_RECORD_AND_REPLAY_AUDIT_ABSENT"
    )

def load_canonical_artifacts(root: Path) -> CanonicalArtifactBytes:
    """Read only the exact canonical files needed by this audit runtime."""
    paths = {
        "freeze_completion": root / "docs/evidence/oracle_research_dataset_freeze_completion_20260827.json",
        "content_completion": root / "docs/evidence/oracle_content_audit_completion_20260827.json",
        "content_audit": root / "docs/evidence/oracle_research_content_audit_20260826.json",
        "serializer": root / "oracle_research_dataset_serializers.py",
        "content_reader": root / "oracle_research_dataset_content_reader.py",
        "materializer": root / "research_contracts/fold_selection_approval/s08_signal_panel_materializer.py",
        "proposal_v5": root / "research_contracts/fold_selection_approval/training_fold_selection_approval_v5.py",
        "proposal_v4": root / "research_contracts/fold_selection_approval/training_fold_selection_approval_v4.py",
        "selector_v7": root / "research_contracts/fold_selection_approval/s08_selector_v7.py",
        "preregistration": root / "research_contracts/stock_model_preregistration/stock_model_preregistration.py",
        "preregistration_binding": root / "research_contracts/stock_model_preregistration/stock_model_preregistration_binding.py",
    }
    return CanonicalArtifactBytes(**{name: path.read_bytes() for name, path in paths.items()})


def load_installed_s07_artifacts(
    directory: Path, *, preregistration_manifest_path: Path,
) -> InstalledS07Artifacts:
    """Read one exact root-owned S07 artifact set without mutating it."""
    paths = (
        directory / "current-readback.json",
        directory / "current-readback-source.json",
        preregistration_manifest_path,
        directory / "independent-verification.json",
    )
    infos = tuple(path.stat(follow_symlinks=False) for path in paths)
    identities = {(info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink)
                  for info in infos}
    if len(identities) != 1:
        raise SelectOnlyAssemblyError("installed S07 artifact identities differ")
    uid, gid, mode, links = next(iter(identities))
    if uid != 0 or gid != 0 or mode != 0o600 or links != 1 \
            or any(not stat.S_ISREG(info.st_mode) for info in infos):
        raise SelectOnlyAssemblyError("installed S07 artifacts are not root:root 0600 regular files")
    return InstalledS07Artifacts(
        current_readback=paths[0].read_bytes(),
        current_readback_source=paths[1].read_bytes(),
        preregistration_manifest=paths[2].read_bytes(),
        independent_verification=paths[3].read_bytes(),
        owner_uid=uid, owner_gid=gid, mode=mode, link_count=links,
    )


def _json(raw: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SelectOnlyAssemblyError(f"{label} is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise SelectOnlyAssemblyError(f"{label} is not a JSON object")
    return value


def _verify_artifacts(artifacts: CanonicalArtifactBytes) -> None:
    if type(artifacts) is not CanonicalArtifactBytes:
        raise SelectOnlyAssemblyError("canonical artifact bundle type differs")
    for name, expected in EXPECTED_RAW_SHA256.items():
        raw = getattr(artifacts, name)
        if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != expected:
            raise SelectOnlyAssemblyError(f"canonical artifact bytes differ: {name}")


def _verify_s07_artifacts(
    artifacts: InstalledS07Artifacts, *, observed_at_utc: datetime,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], bool, float]:
    if type(artifacts) is not InstalledS07Artifacts:
        raise SelectOnlyAssemblyError("installed S07 artifact bundle type differs")
    if (artifacts.owner_uid, artifacts.owner_gid, artifacts.mode, artifacts.link_count) != (0, 0, 0o600, 1):
        raise SelectOnlyAssemblyError("installed S07 artifact ownership/mode/link identity differs")
    for name, expected in EXPECTED_S07_RAW_SHA256.items():
        raw = getattr(artifacts, name)
        if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != expected:
            raise SelectOnlyAssemblyError(f"installed S07 artifact bytes differ: {name}")
    readback = _json(artifacts.current_readback, "S07 current readback")
    source = _json(artifacts.current_readback_source, "S07 current readback source")
    manifest = _json(artifacts.preregistration_manifest, "S07 preregistration manifest")
    verification = _json(artifacts.independent_verification, "S07 independent verification")
    try:
        boundary = readback["boundary"]
        evidence = readback["evidence"]
        source_lineage = source["immutable_lineage"]
        mapping = source["lineage_mapping"]
        manifest_lineage = manifest["lineage"]
        observed = datetime.fromisoformat(str(readback["observed_at_utc"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SelectOnlyAssemblyError("installed S07 artifact schema differs") from exc
    if observed.tzinfo is None:
        raise SelectOnlyAssemblyError("S07 readback observation lacks timezone")
    now = observed_at_utc.astimezone(timezone.utc)
    age = (now - observed.astimezone(timezone.utc)).total_seconds()
    if age < 0:
        raise SelectOnlyAssemblyError("S07 readback is future-dated")
    expected_boundary = {
        "database_writes": 0, "evaluator_performed_io": False,
        "fixture_only": True, "model_fit_authorized": False,
        "model_fit_performed": False, "ready_state_available": False,
    }
    dates = readback.get("model_session_dates")
    full_dates = readback.get("full_session_calendar_dates")
    tickers = mapping.get("ticker_universe") if type(mapping) is dict else None
    if (readback.get("contract_id") != "codex-oracle-current-baseline-readback-v1"
            or readback.get("status") != "VERIFIED_SELECT_ONLY"
            or boundary != expected_boundary
            or source.get("contract_id") != "codex-oracle-current-baseline-source-evidence-v1"
            or source.get("status") != "VERIFIED_SELECT_ONLY"
            or source.get("database_writes") != 0
            or source.get("model_fit_authorized") is not False
            or manifest.get("contract_id") != "codex-oracle-hierarchical-stock-preregistration-v2"
            or manifest.get("execution", {}).get("model_fit_started") is not False
            or manifest.get("preflight", {}).get("fixture_only") is not True
            or manifest.get("preflight", {}).get("model_fit_authorized") is not False
            or verification != {
                "artifact_file_sha256": EXPECTED_S07_RAW_SHA256["current_readback"],
                "artifact_id": readback.get("artifact_id"),
                "database_writes": 0,
                "model_fit_authorized": False,
                "request_sha256": readback.get("request_sha256"),
                "select_query_ids": [
                    "SELECT_DOWNSTREAM_COUNTS", "SELECT_DOWNSTREAM_SCHEMA",
                    "SELECT_SCREENING_RUNS", "SELECT_SESSION_CALENDAR",
                    "SELECT_TICKER_UNIVERSE",
                ],
                "source_embedded_evidence_sha256": evidence.get(
                    "source_readback_embedded_evidence_sha256"
                ),
                "source_file_sha256": EXPECTED_S07_RAW_SHA256["current_readback_source"],
                "status": "VERIFIED_SELECT_ONLY",
            }
            or evidence.get("source_readback_artifact_sha256")
               != EXPECTED_S07_RAW_SHA256["current_readback_source"]
            or source.get("model_session_dates") != dates
            or manifest.get("model_session_dates") != dates
            or source.get("full_session_calendar_dates") != full_dates
            or manifest.get("full_session_calendar_dates") != full_dates
            or len(dates or []) != 416 or len(full_dates or []) < 417
            or len(tickers or []) != 474
            or evidence.get("snapshot_id") != source_lineage.get("snapshot_id")
            or evidence.get("snapshot_id") != manifest_lineage.get("snapshot_id")
            or evidence.get("model_session_dates_sha256")
               != source_lineage.get("model_session_dates_sha256")
            or evidence.get("model_session_dates_sha256")
               != manifest_lineage.get("model_session_dates_sha256")
            or evidence.get("full_session_calendar_sha256")
               != source_lineage.get("full_session_calendar_sha256")
            or evidence.get("full_session_calendar_sha256")
               != manifest_lineage.get("full_session_calendar_sha256")
            or evidence.get("universe_sha256") != source_lineage.get("universe_sha256")
            or evidence.get("universe_sha256") != manifest_lineage.get("universe_sha256")
            or evidence.get("model_session_dates_sha256")
               != canonical_session_dates_sha256(tuple(dates))
            or evidence.get("full_session_calendar_sha256")
               != canonical_session_dates_sha256(tuple(full_dates))
            or evidence.get("universe_sha256")
               != canonical_ticker_list_sha256(tuple(tickers))):
        raise SelectOnlyAssemblyError("installed S07 artifacts contradict each other")
    return readback, source, manifest, age <= MAX_S07_READBACK_AGE_SECONDS, age


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


_VERSION_SQL = _normalize("""
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
""")
_EVENT_SQL = _normalize("""
SELECT event_id,event_type,market_snapshot_checksum_sha256,
       content_sha256,ticker_universe_sha256,provider_lineage_sha256,
       actor,decided_at_utc,evidence_sha256
FROM oracle_research_dataset_events
WHERE dataset_version_id=?
ORDER BY decided_at_utc DESC,event_id DESC LIMIT 1
""")
_COVERAGE_SQL = _normalize("""
SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,
       COUNT(DISTINCT date) AS session_count,
       MIN(date) AS first_session_date,MAX(date) AS last_session_date
FROM market_daily_features WHERE snapshot_id=?
""")
_BOUND_PROVIDER_SQL = _normalize("""
SELECT ticker,provider,requested_source_session_date,first_available_date,
       last_available_date,source_row_count,source_checksum_sha256
FROM oracle_research_dataset_provider_lineage
WHERE dataset_version_id=? ORDER BY ticker
""")
_ACTUAL_PROVIDER_SQL = _normalize("""
SELECT ticker,provider,requested_source_session_date,first_available_date,
       last_available_date,source_row_count,source_checksum_sha256
FROM market_data_provider_lineage
WHERE snapshot_id=? ORDER BY ticker
""")


class _GuardedCaptureClient:
    def __init__(self, client: object, *, dataset_version: str, snapshot_id: str,
                 page_size: int):
        if not callable(getattr(client, "execute", None)):
            raise SelectOnlyAssemblyError("injected client lacks execute")
        self._client = client
        self._dataset = dataset_version
        self._snapshot = snapshot_id
        self._page_size = page_size
        self._last_cursor: tuple[str, str] | None = None
        self._pagination_started = False
        self.rows: list[tuple[object, ...]] = []
        self.query_count = 0
        self.database_writes = 0

    def execute(self, sql: str, args: list[object]):
        if type(sql) is not str or type(args) is not list:
            raise SelectOnlyAssemblyError("SQL/argument boundary differs")
        normalized = _normalize(sql)
        if not normalized.startswith("SELECT ") or ";" in normalized or _FORBIDDEN.search(normalized):
            raise SelectOnlyAssemblyError("non-SELECT statement rejected")
        expected_args: list[object]
        if normalized in {_VERSION_SQL, _EVENT_SQL, _BOUND_PROVIDER_SQL}:
            expected_args = [self._dataset]
        elif normalized in {_COVERAGE_SQL, _ACTUAL_PROVIDER_SQL}:
            expected_args = [self._snapshot]
        elif sql == FIRST_PAGE_SQL:
            if self._pagination_started:
                raise SelectOnlyAssemblyError("duplicate first page rejected")
            expected_args = [self._snapshot, self._page_size]
            self._pagination_started = True
        elif sql == NEXT_PAGE_SQL:
            if not self._pagination_started or self._last_cursor is None:
                raise SelectOnlyAssemblyError("next page lacks exact cursor lineage")
            expected_args = [self._snapshot, self._last_cursor[0], self._last_cursor[0],
                             self._last_cursor[1], self._page_size]
        else:
            raise SelectOnlyAssemblyError("query outside exact SELECT allowlist")
        if args != expected_args:
            raise SelectOnlyAssemblyError("query arguments differ from exact lineage")
        result = self._client.execute(sql, args)
        self.query_count += 1
        if sql in {FIRST_PAGE_SQL, NEXT_PAGE_SQL}:
            columns = tuple(getattr(result, "columns", ()) or ())
            page = getattr(result, "rows", None)
            if columns != MARKET_DAILY_FEATURE_COLUMNS or not isinstance(page, (list, tuple)):
                raise SelectOnlyAssemblyError("market page schema differs")
            previous = self._last_cursor
            for raw in page:
                row = tuple(raw)
                if len(row) != len(MARKET_DAILY_FEATURE_COLUMNS) or row[0] != self._snapshot:
                    raise SelectOnlyAssemblyError("market page row identity differs")
                key = (str(row[1]), str(row[2]))
                if previous is not None and key <= previous:
                    raise SelectOnlyAssemblyError("market cursor is not strictly monotonic")
                previous = key
                self.rows.append(row)
            if page:
                self._last_cursor = (str(page[-1][1]), str(page[-1][2]))
        return result


def _strict_utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SelectOnlyAssemblyError("observation time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_evidence(value: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(dict(value))


def assemble_v5_proposal(
    client: object,
    *,
    artifacts: CanonicalArtifactBytes,
    s07_artifacts: InstalledS07Artifacts,
    observed_at_utc: datetime,
    pins: AuditPins = AuditPins(),
    page_size: int = 4000,
) -> SelectOnlyProposalAssembly:
    """Assemble an unsigned v5 proposal from fresh SELECT-only readback."""
    _verify_artifacts(artifacts)
    if type(pins) is not AuditPins or not _SHA.fullmatch(pins.model_session_dates_sha256) \
            or not _SHA.fullmatch(pins.ticker_list_sha256):
        raise SelectOnlyAssemblyError("audit pin format differs")
    if type(page_size) is not int or not 1 <= page_size <= 10_000:
        raise SelectOnlyAssemblyError("page size differs")
    observed_text = _strict_utc(observed_at_utc)
    s07_readback, s07_source, s07_manifest, s07_fresh, s07_age = _verify_s07_artifacts(
        s07_artifacts, observed_at_utc=observed_at_utc,
    )
    freeze = _json(artifacts.freeze_completion, "freeze completion")
    completion = _json(artifacts.content_completion, "content completion")
    audit = _json(artifacts.content_audit, "content audit")
    try:
        dataset = str(freeze["dataset_version_id"])
        snapshot = str(completion["fresh_readback"]["snapshot_id"])  # type: ignore[index]
        logical = audit["logical_evidence"]  # type: ignore[index]
        canonical = logical["canonical_content"]  # type: ignore[index]
        snapshot_meta = logical["snapshot"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise SelectOnlyAssemblyError("canonical evidence schema differs") from exc
    if (freeze.get("status") != "VERIFIED"
            or freeze.get("independent_readback") != {
                "freeze_event_count": 1, "provider_lineage_count": 476, "status": "FROZEN"
            }
            or completion.get("status") != "VERIFIED_SELECT_ONLY"
            or logical.get("read_only") is not True
            or audit.get("independent_readback", {}).get("matches") is not True):
        raise SelectOnlyAssemblyError("freeze/content evidence is not independently verified")
    logical_core = dict(logical)
    logical_claim = logical_core.pop("evidence_sha256", None)
    if logical_claim != hashlib.sha256(_canonical_evidence(logical_core)).hexdigest():
        raise SelectOnlyAssemblyError("content audit embedded evidence digest differs")
    fresh = completion["fresh_readback"]
    for key in ("content_sha256", "ticker_universe_sha256", "row_count", "ticker_count",
                "first_session_date", "last_session_date", "snapshot_id"):
        if fresh.get(key) != canonical.get(key):
            raise SelectOnlyAssemblyError(f"fresh content completion differs: {key}")
    if (fresh.get("evidence_sha256") != logical_claim or fresh.get("read_only") is not True
            or fresh.get("retained_row_count") != 0):
        raise SelectOnlyAssemblyError("fresh readback identity/read-only boundary differs")
    guarded = _GuardedCaptureClient(
        client, dataset_version=dataset, snapshot_id=snapshot, page_size=page_size,
    )
    try:
        frozen = load_frozen_oracle_research_dataset(
            guarded, dataset_version_id=dataset,
            expected_market_snapshot_id=snapshot,
            expected_market_snapshot_checksum_sha256=str(snapshot_meta["source_checksum_sha256"]),
            expected_source_session_date=datetime.fromisoformat(
                str(snapshot_meta["source_session_date"])
            ).date(), cutoff_utc=observed_at_utc,
        )
        stream = stream_pinned_market_content(
            guarded,
            pin=PinnedMarketSnapshot(
                snapshot_id=snapshot,
                source_checksum_sha256=str(snapshot_meta["source_checksum_sha256"]),
                source_session_date=frozen.source_session_date,
                expected_row_count=frozen.expected_row_count,
                expected_ticker_count=frozen.expected_ticker_count,
            ), page_size=page_size,
        )
    except (LineageError, KeyError, ValueError) as exc:
        raise SelectOnlyAssemblyError("fresh frozen SELECT readback rejected") from exc
    if guarded.database_writes != 0 or len(guarded.rows) != frozen.expected_row_count:
        raise SelectOnlyAssemblyError("SELECT-only capture count differs")
    if frozen.expected_provider_lineage_count != freeze["independent_readback"]["provider_lineage_count"]:
        raise SelectOnlyAssemblyError("fresh provider-lineage count differs from freeze completion")
    if (stream.digests.content_sha256 != canonical["content_sha256"]
            or stream.digests.ticker_universe_sha256 != canonical["ticker_universe_sha256"]
            or stream.digests.row_count != canonical["row_count"]
            or stream.digests.ticker_count != canonical["ticker_count"]):
        raise SelectOnlyAssemblyError("fresh row content differs from canonical evidence")
    rows = tuple(guarded.rows)
    full_dates = tuple(sorted({str(row[2]) for row in rows}))
    tickers = tuple(sorted({str(row[1]) for row in rows}))
    model_dates = tuple(s07_readback["model_session_dates"])
    s07_full_dates = tuple(s07_readback["full_session_calendar_dates"])
    tickers_from_s07 = tuple(s07_source["lineage_mapping"]["ticker_universe"])
    if (len(full_dates) != frozen.expected_session_count
            or full_dates != s07_full_dates
            or tickers != tickers_from_s07
            or canonical_session_dates_sha256(model_dates) != pins.model_session_dates_sha256
            or canonical_ticker_list_sha256(tickers) != pins.ticker_list_sha256):
        raise SelectOnlyAssemblyError("S07 calendar/ticker authority pins differ")
    full_calendar_sha = canonical_session_dates_sha256(full_dates)
    temporary_market = FrozenMarketBinding(
        dataset_version=dataset, snapshot_id=snapshot,
        content_sha256=stream.digests.content_sha256,
        ticker_universe_sha256=stream.digests.ticker_universe_sha256,
        row_count=stream.digests.row_count, ticker_count=stream.digests.ticker_count,
        full_session_dates=full_dates, full_session_calendar_sha256=full_calendar_sha,
        upstream_imputation_count=0, binding_artifact_sha256="0" * 64,
    )
    market = replace(temporary_market,
                     binding_artifact_sha256=binding_artifact_sha256(temporary_market))
    s07_sha = EXPECTED_S07_RAW_SHA256["current_readback"]
    s07 = S07SignalBinding(
        s07_raw_sha256=s07_sha, frozen_content_sha256=frozen.content_sha256,
        model_session_dates=model_dates,
        model_session_dates_sha256=pins.model_session_dates_sha256,
        tickers=tickers, ticker_list_sha256=pins.ticker_list_sha256,
    )
    temporary_readback = TrustedReadbackBinding(
        dataset_version=dataset, snapshot_id=snapshot,
        frozen_content_sha256=frozen.content_sha256,
        readback_evidence_sha256="0" * 64,
    )
    readback = replace(temporary_readback,
                       readback_evidence_sha256=trusted_readback_artifact_sha256(temporary_readback))
    columns_sha = hashlib.sha256(_canonical_evidence({
        "columns": list(MARKET_DAILY_FEATURE_COLUMNS)
    })).hexdigest()
    serializer_release = _canonical_evidence({
        "canonical_git_head": CANONICAL_GIT_HEAD,
        "serializer_source_sha256": EXPECTED_RAW_SHA256["serializer"],
        "materializer_source_sha256": EXPECTED_RAW_SHA256["materializer"],
        "feature_columns_sha256": columns_sha,
        "execution_authorized": False,
    })
    serializer = ImportedSerializerBinding(
        serializer_identity="oracle-market-daily-features-jsonl-v1@ad7d5853",
        serializer_release_sha256=hashlib.sha256(serializer_release).hexdigest(),
        serializer_source_sha256=EXPECTED_RAW_SHA256["serializer"],
        feature_columns_sha256=canonical_ticker_list_sha256(tuple(MARKET_DAILY_FEATURE_COLUMNS)),
    )
    panel = materialize_signal_panel(
        canonical_rows=rows, market_binding=market, s07_binding=s07,
        trusted_readback=readback, serializer_binding=serializer,
    )
    dependency_lock = _canonical_evidence({
        "canonical_git_head": CANONICAL_GIT_HEAD,
        "artifacts": EXPECTED_RAW_SHA256,
        "execution_authorized": False,
    })
    selector_release = _canonical_evidence({
        "canonical_git_head": CANONICAL_GIT_HEAD,
        "selector_source_sha256": EXPECTED_RAW_SHA256["selector_v7"],
        "dependency_lock_sha256": hashlib.sha256(dependency_lock).hexdigest(),
        "execution_authorized": False,
    })
    universe_lineage = _canonical_evidence({
        "contract": "exact-frozen-ticker-universe-lineage-v1",
        "frozen_dataset_version": dataset,
        "snapshot_id": snapshot,
        "snapshot_sha256": str(snapshot_meta["source_checksum_sha256"]),
        "ticker_count": 474,
        "ticker_universe_bytes_sha256": sha256(canonical_json_bytes(list(tickers))),
    })
    proposal = build_proposal(ProposalInputs(
        tickers=tickers, frozen_session_dates=model_dates,
        universe_lineage_bytes=universe_lineage,
        derivation_cutoff_utc=str(snapshot_meta["available_at_utc"]).replace("+00:00", "Z"),
        frozen_dataset_version=dataset,
        frozen_content_sha256=frozen.content_sha256,
        frozen_readback_sha256=str(logical_claim),
        frozen_readback_at_utc=observed_text,
        snapshot_id=snapshot,
        snapshot_sha256=str(snapshot_meta["source_checksum_sha256"]),
        preregistration_sha256=EXPECTED_S07_RAW_SHA256["preregistration_manifest"],
        selector_source_bytes=artifacts.selector_v7,
        selector_git_commit=CANONICAL_GIT_HEAD,
        selector_release_bytes=selector_release,
        dependency_lock_bytes=dependency_lock,
        verifier_source_bytes=artifacts.selector_v7,
    ))
    if proposal.status != "APPROVAL_REQUIRED" or proposal.selections != () \
            or panel.execution_authorized is not False or panel.database_writes != 0 \
            or panel.downstream_outputs != 0:
        raise SelectOnlyAssemblyError("inert proposal/materializer boundary changed")
    return SelectOnlyProposalAssembly(
        contract_id=CONTRACT_ID,
        status="AUDIT_ONLY_PROPOSAL_ASSEMBLED_AUTHORITY_PENDING",
        canonical_git_head=CANONICAL_GIT_HEAD,
        frozen_dataset_version=dataset, snapshot_id=snapshot,
        frozen_content_sha256=frozen.content_sha256,
        fresh_readback_evidence_sha256=str(logical_claim),
        s07_reconstruction_sha256=s07_sha,
        panel_sha256=panel.panel_sha256, panel_shape=panel.shape,
        proposal=proposal, proposal_core_sha256=proposal.proposal_core_sha256,
        query_count=guarded.query_count,
        s07_readback_fresh=s07_fresh, s07_readback_age_seconds=s07_age,
        unresolved_authority_gate=(
            "INDEPENDENT_S07_REPLAY_APPROVAL_ABSENT" if s07_fresh else
            "FRESH_ROOT_OWNED_S07_READBACK_AND_INDEPENDENT_REPLAY_APPROVAL_ABSENT"
        ),
    )
