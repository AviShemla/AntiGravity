"""Pure, audit-only v2 boundary for the completed Oracle baseline artifacts.

This module deliberately separates the immutable producer release from the
release that verifies it.  It performs no I/O, SQL, prediction generation, or
lifecycle mutation.  A future root-owned runner must supply the externally
pinned verifier-release digest and the results of exactly three SELECT-only
readbacks before :func:`finalize_live_audit` can produce terminal evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Mapping, Protocol, Sequence


class AuditV2Error(RuntimeError):
    """Raised when any producer, verifier, or live-evidence gate differs."""


CONTRACT_ID = "full-universe-common-simple-baselines-audit-v2"
PRODUCER_CONTRACT_ID = "full-universe-common-simple-baselines-v1"
PRODUCER_GIT_COMMIT = "7fe3c3ba6ade888b01ee6d78cf9bb7fe72b01458"
PRODUCER_MANIFEST_SHA256 = "d8ad829cac7b540080db75c0174e46cd0dbc8b55f769e37aad80e354386496de"
PRODUCER_EXECUTOR_SHA256 = "218c2f23b5544e18299f1308c3915f4efa6fca3c837d403c4bf662e28d1e1a57"
PRODUCER_DETERMINISTIC_SHA256 = "305686770071fc24a1e43d836dc9fc3ced23a250d79243654e6db4ae842adfef"
PRODUCER_LINEAGE_SHA256 = "6f3b2aad35dee281bf186b7b4f079c6f656e799769cbaf1df67a99e9620a0a98"
SNAPSHOT_ID = "market_features_2026-08-25_5b1044ee45605a3d"
SOURCE_SESSION_DATE = "2026-08-25"
SESSION_SHA256 = "030b17a6d94cfebdd24582b8206357b6905c58e5b3d10796b0c8ee3c87b53eeb"
EXPECTED_TICKERS = 474
EXPECTED_FOLDS = 1_896
EXPECTED_OOS = 56_880
EXPECTED_SESSIONS = 1_246
EXPECTED_SELECTS = 3
EXPECTED_EFFECTIVE_IDENTITY = "os=codexops;turso=avishe"
MODEL_NAMES = ("majority_direction", "constant_training_rate", "lag1_logistic")
ZERO_SIDE_EFFECTS = {
    "database_writes": 0,
    "bayesian_fits": 0,
    "predictions": 0,
    "recommendations": 0,
    "orders": 0,
    "etf_outputs": 0,
}
DOWNSTREAM_NAMES = (
    "model_runs",
    "model_scorecards",
    "etf_prior_lineage",
    "stock_prediction_decision_audits",
    "stock_prediction_criterion_audits",
    "execution_plans",
    "execution_events",
    "execution_plan_approvals",
)
_SHA = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_TICKER = re.compile(r"[A-Z0-9.^-]{1,24}")


@dataclass(frozen=True)
class ProducerPins:
    git_commit: str = PRODUCER_GIT_COMMIT
    manifest_sha256: str = PRODUCER_MANIFEST_SHA256
    executor_sha256: str = PRODUCER_EXECUTOR_SHA256
    deterministic_sha256: str = PRODUCER_DETERMINISTIC_SHA256
    lineage_sha256: str = PRODUCER_LINEAGE_SHA256
    tickers: int = EXPECTED_TICKERS
    folds: int = EXPECTED_FOLDS
    oos_observations: int = EXPECTED_OOS


PRODUCTION_PINS = ProducerPins()


@dataclass(frozen=True)
class OfflineArtifactProof:
    producer_manifest_sha256: str
    producer_executor_sha256: str
    producer_git_commit: str
    producer_deterministic_sha256: str
    producer_lineage_sha256: str
    verifier_release_manifest_sha256: str
    verifier_git_commit: str
    checkpoint_count: int
    checkpoint_set_sha256: str
    coverage_tickers: int
    coverage_folds: int
    coverage_oos_observations: int
    execution_authorized: bool = False
    live_readback_complete: bool = False


@dataclass(frozen=True)
class LiveReadback:
    observed_at_utc: str
    effective_identity: str
    database_name: str
    snapshot_id: str
    source_session_date: str
    sessions: tuple[str, ...]
    session_sha256: str
    downstream_counts: Mapping[str, int]
    select_statement_count: int
    database_write_count: int


class SemanticVerifier(Protocol):
    PRODUCER_CONTRACT_ID: str

    def decode_json(self, raw: bytes) -> object: ...

    def validate_manifest(
        self,
        payload: object,
        checkpoints: Mapping[str, object],
        executor_git_commit: str,
        sessions: Sequence[str],
        *,
        verified_at: datetime,
    ) -> Mapping[str, object]: ...


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_constant(value: str) -> object:
    raise AuditV2Error("JSON contains a non-finite value")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AuditV2Error("JSON contains a duplicate key")
        result[key] = value
    return result


def decode_json(raw: bytes, label: str) -> object:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditV2Error(f"{label} is not strict UTF-8 JSON") from exc


def _exact_dict(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise AuditV2Error(f"{label} schema differs")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise AuditV2Error(f"{label} is not a SHA-256 digest")
    return value


def _checkpoint_name(ticker: str) -> str:
    return f"ticker-{hashlib.sha256(ticker.encode('utf-8')).hexdigest()[:24]}.json"


def build_verifier_release_manifest(
    *,
    verifier_git_commit: str,
    verifier_module_bytes: bytes,
    semantic_auditor_bytes: bytes,
    verifier_test_bytes: bytes,
    pins: ProducerPins = PRODUCTION_PINS,
) -> bytes:
    """Build deterministic proposal bytes for an externally pinned release.

    Building these bytes grants no authority. The integration commit must be
    known and distinct from the historical producer commit, and a separate
    root-owned execution boundary must pin the resulting manifest digest.
    """
    if _COMMIT.fullmatch(verifier_git_commit) is None or verifier_git_commit == pins.git_commit:
        raise AuditV2Error("verifier integration commit differs")
    for raw, label in (
        (verifier_module_bytes, "verifier module"),
        (semantic_auditor_bytes, "semantic auditor"),
        (verifier_test_bytes, "verifier tests"),
    ):
        if not isinstance(raw, bytes) or not raw:
            raise AuditV2Error(f"{label} bytes are absent")
    return canonical_bytes(
        {
            "contract_id": CONTRACT_ID,
            "verifier_git_commit": verifier_git_commit,
            "producer_binding": {
                "git_commit": pins.git_commit,
                "manifest_sha256": pins.manifest_sha256,
                "executor_sha256": pins.executor_sha256,
                "deterministic_sha256": pins.deterministic_sha256,
            },
            "artifacts": {
                "audit_only_baseline_v2.py": sha256(verifier_module_bytes),
                "audit_full_universe_simple_baselines.py": sha256(semantic_auditor_bytes),
                "test_audit_only_baseline_v2.py": sha256(verifier_test_bytes),
            },
            "read_scope": "EXACT_THREE_SELECTS_FINAL_PHASE_ONLY",
            "write_scope": "NONE",
            "execution_authorized": False,
        }
    )


def _validate_release_manifest(
    raw: bytes,
    expected_release_sha256: str,
    pins: ProducerPins,
) -> tuple[str, str]:
    """Validate a separately pinned verifier closure, never producer identity."""
    _digest(expected_release_sha256, "external verifier release pin")
    actual = sha256(raw)
    if actual != expected_release_sha256:
        raise AuditV2Error("verifier release manifest differs from external pin")
    release = _exact_dict(
        decode_json(raw, "verifier release manifest"),
        {
            "contract_id",
            "verifier_git_commit",
            "producer_binding",
            "artifacts",
            "read_scope",
            "write_scope",
            "execution_authorized",
        },
        "verifier release manifest",
    )
    commit = release["verifier_git_commit"]
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise AuditV2Error("verifier Git commit differs")
    if commit == pins.git_commit:
        raise AuditV2Error("producer and verifier identities are conflated")
    binding = _exact_dict(
        release["producer_binding"],
        {"git_commit", "manifest_sha256", "executor_sha256", "deterministic_sha256"},
        "producer binding",
    )
    if binding != {
        "git_commit": pins.git_commit,
        "manifest_sha256": pins.manifest_sha256,
        "executor_sha256": pins.executor_sha256,
        "deterministic_sha256": pins.deterministic_sha256,
    }:
        raise AuditV2Error("verifier release producer binding differs")
    artifacts = release["artifacts"]
    required = {
        "audit_only_baseline_v2.py",
        "audit_full_universe_simple_baselines.py",
        "test_audit_only_baseline_v2.py",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != required:
        raise AuditV2Error("verifier artifact closure differs")
    for path, digest in artifacts.items():
        if not isinstance(path, str) or not path or _digest(digest, path) != digest:
            raise AuditV2Error("verifier artifact identity differs")
    if (
        release["contract_id"] != CONTRACT_ID
        or release["read_scope"] != "EXACT_THREE_SELECTS_FINAL_PHASE_ONLY"
        or release["write_scope"] != "NONE"
        or release["execution_authorized"] is not False
    ):
        raise AuditV2Error("verifier authority boundary differs")
    return actual, commit


def verify_offline_artifacts(
    *,
    producer_executor_bytes: bytes,
    producer_manifest_bytes: bytes,
    checkpoint_files: Mapping[str, bytes],
    verifier_release_manifest_bytes: bytes,
    expected_verifier_release_manifest_sha256: str,
    pins: ProducerPins = PRODUCTION_PINS,
) -> OfflineArtifactProof:
    """Verify immutable artifact identity without reading a database or writing output."""
    if sha256(producer_executor_bytes) != pins.executor_sha256:
        raise AuditV2Error("producer executor bytes differ from immutable pin")
    if sha256(producer_manifest_bytes) != pins.manifest_sha256:
        raise AuditV2Error("producer manifest bytes differ from immutable pin")
    release_sha, verifier_commit = _validate_release_manifest(
        verifier_release_manifest_bytes, expected_verifier_release_manifest_sha256, pins
    )
    executor = _exact_dict(
        decode_json(producer_executor_bytes, "producer executor manifest"),
        {"executor_git_commit", "artifacts"},
        "producer executor manifest",
    )
    if executor["executor_git_commit"] != pins.git_commit:
        raise AuditV2Error("producer executor Git identity differs")
    manifest = _exact_dict(
        decode_json(producer_manifest_bytes, "producer final manifest"),
        {
            "contract_id",
            "lineage_sha256",
            "coverage",
            "aggregate",
            "ticker_checkpoints",
            "side_effects",
            "deterministic_evidence_sha256",
            "runtime",
        },
        "producer final manifest",
    )
    coverage = manifest["coverage"]
    if (
        manifest["contract_id"] != PRODUCER_CONTRACT_ID
        or manifest["lineage_sha256"] != pins.lineage_sha256
        or manifest["deterministic_evidence_sha256"] != pins.deterministic_sha256
        or coverage
        != {
            "tickers": pins.tickers,
            "folds": pins.folds,
            "oos_observations": pins.oos_observations,
        }
        or manifest["side_effects"] != ZERO_SIDE_EFFECTS
    ):
        raise AuditV2Error("producer contract, coverage, or zero-side-effect boundary differs")
    runtime = _exact_dict(
        manifest["runtime"], {"executor_git_commit", "observed_at_utc"}, "producer runtime"
    )
    if runtime["executor_git_commit"] != pins.git_commit:
        raise AuditV2Error("producer runtime and executor identities differ")
    deterministic = dict(manifest)
    deterministic.pop("runtime")
    deterministic.pop("deterministic_evidence_sha256")
    if sha256(canonical_bytes(deterministic)) != pins.deterministic_sha256:
        raise AuditV2Error("producer deterministic evidence does not replay")
    entries = manifest["ticker_checkpoints"]
    if not isinstance(entries, list) or len(entries) != pins.tickers:
        raise AuditV2Error("checkpoint coverage differs")
    expected_names: list[str] = []
    ordered_digests: list[dict[str, str]] = []
    previous = ""
    for raw_entry in entries:
        entry = _exact_dict(raw_entry, {"ticker", "checkpoint_sha256"}, "checkpoint entry")
        ticker = entry["ticker"]
        digest = _digest(entry["checkpoint_sha256"], "checkpoint digest")
        if (
            not isinstance(ticker, str)
            or _TICKER.fullmatch(ticker) is None
            or ticker <= previous
        ):
            raise AuditV2Error("checkpoint ticker order/identity differs")
        previous = ticker
        name = _checkpoint_name(ticker)
        expected_names.append(name)
        raw_checkpoint = checkpoint_files.get(name)
        if raw_checkpoint is None:
            raise AuditV2Error("checkpoint file digest differs")
        checkpoint = decode_json(raw_checkpoint, f"{ticker} checkpoint")
        if not isinstance(checkpoint, dict) or checkpoint.get("ticker") != ticker:
            raise AuditV2Error("checkpoint ticker payload differs")
        if checkpoint.get("checkpoint_sha256") != digest:
            raise AuditV2Error("checkpoint embedded digest differs")
        without_digest = dict(checkpoint)
        without_digest.pop("checkpoint_sha256")
        if sha256(canonical_bytes(without_digest)) != digest:
            raise AuditV2Error("checkpoint canonical digest differs")
        ordered_digests.append({"ticker": ticker, "file_sha256": sha256(raw_checkpoint)})
    if set(checkpoint_files) != set(expected_names):
        raise AuditV2Error("checkpoint file set contains missing or extra files")
    return OfflineArtifactProof(
        producer_manifest_sha256=pins.manifest_sha256,
        producer_executor_sha256=pins.executor_sha256,
        producer_git_commit=pins.git_commit,
        producer_deterministic_sha256=pins.deterministic_sha256,
        producer_lineage_sha256=pins.lineage_sha256,
        verifier_release_manifest_sha256=release_sha,
        verifier_git_commit=verifier_commit,
        checkpoint_count=len(entries),
        checkpoint_set_sha256=sha256(canonical_bytes(ordered_digests)),
        coverage_tickers=pins.tickers,
        coverage_folds=pins.folds,
        coverage_oos_observations=pins.oos_observations,
    )


def finalize_live_audit(
    *,
    offline: OfflineArtifactProof,
    producer_executor_bytes: bytes,
    producer_manifest_bytes: bytes,
    checkpoint_files: Mapping[str, bytes],
    verifier_release_manifest_bytes: bytes,
    expected_verifier_release_manifest_sha256: str,
    live: LiveReadback,
    finalized_at_utc: str,
    semantic_verifier: SemanticVerifier,
    pins: ProducerPins = PRODUCTION_PINS,
) -> dict[str, object]:
    """Finalize only from three externally performed SELECT readbacks.

    This function never owns a database client.  The future runner must enforce
    authenticated identity, exact SQL bytes, timeout, and zero writes.
    """
    recomputed = verify_offline_artifacts(
        producer_executor_bytes=producer_executor_bytes,
        producer_manifest_bytes=producer_manifest_bytes,
        checkpoint_files=checkpoint_files,
        verifier_release_manifest_bytes=verifier_release_manifest_bytes,
        expected_verifier_release_manifest_sha256=expected_verifier_release_manifest_sha256,
        pins=pins,
    )
    if offline != recomputed:
        raise AuditV2Error("offline proof does not replay from bound artifacts")
    if offline.execution_authorized or offline.live_readback_complete:
        raise AuditV2Error("offline proof improperly claims live authority")
    if (
        offline.producer_manifest_sha256 != pins.manifest_sha256
        or offline.producer_executor_sha256 != pins.executor_sha256
        or offline.producer_git_commit != pins.git_commit
    ):
        raise AuditV2Error("offline proof producer identity differs")
    if (
        live.select_statement_count != EXPECTED_SELECTS
        or live.database_write_count != 0
        or live.database_name != "theoracle"
        or live.effective_identity != EXPECTED_EFFECTIVE_IDENTITY
        or live.snapshot_id != SNAPSHOT_ID
        or live.source_session_date != SOURCE_SESSION_DATE
        or len(live.sessions) != EXPECTED_SESSIONS
        or tuple(sorted(set(live.sessions))) != live.sessions
        or live.sessions[-1] != SOURCE_SESSION_DATE
        or live.session_sha256 != SESSION_SHA256
        or sha256(canonical_bytes(list(live.sessions))) != SESSION_SHA256
        or set(live.downstream_counts) != set(DOWNSTREAM_NAMES)
        or any(type(value) is not int or value != 0 for value in live.downstream_counts.values())
    ):
        raise AuditV2Error("live three-SELECT evidence differs")
    try:
        observed = datetime.fromisoformat(live.observed_at_utc)
        finalized = datetime.fromisoformat(finalized_at_utc)
    except (TypeError, ValueError) as exc:
        raise AuditV2Error("live observation timestamp differs") from exc
    if (
        observed.tzinfo is None
        or observed.utcoffset() is None
        or finalized.tzinfo is None
        or finalized.utcoffset() is None
    ):
        raise AuditV2Error("live observation timestamp is not timezone-aware")
    manifest_payload = semantic_verifier.decode_json(producer_manifest_bytes)
    entries = manifest_payload.get("ticker_checkpoints") if isinstance(manifest_payload, dict) else None
    if not isinstance(entries, list):
        raise AuditV2Error("producer checkpoint manifest differs")
    runtime = manifest_payload.get("runtime")
    if not isinstance(runtime, dict) or set(runtime) != {"executor_git_commit", "observed_at_utc"}:
        raise AuditV2Error("producer runtime chronology differs")
    try:
        producer_observed = datetime.fromisoformat(str(runtime["observed_at_utc"]))
    except ValueError as exc:
        raise AuditV2Error("producer runtime chronology differs") from exc
    if producer_observed.tzinfo is None or producer_observed.utcoffset() is None:
        raise AuditV2Error("producer runtime chronology differs")
    producer_observed = producer_observed.astimezone(timezone.utc)
    observed = observed.astimezone(timezone.utc)
    finalized = finalized.astimezone(timezone.utc)
    if not producer_observed <= observed <= finalized <= observed + timedelta(minutes=5):
        raise AuditV2Error("producer/live/finalization chronology or freshness differs")
    checkpoints: dict[str, object] = {}
    for entry in entries:
        ticker = entry["ticker"]
        checkpoints[ticker] = semantic_verifier.decode_json(
            checkpoint_files[_checkpoint_name(ticker)]
        )
    verified = semantic_verifier.validate_manifest(
        manifest_payload,
        checkpoints,
        pins.git_commit,
        live.sessions,
        # V1 couples producer completion to a one-hour audit window. V2 uses
        # that timestamp only for structural replay and independently binds the
        # fresh live observation/finalization chronology above.
        verified_at=producer_observed,
    )
    if verified.get("coverage") != {
        "tickers": pins.tickers,
        "folds": pins.folds,
        "oos_observations": pins.oos_observations,
    }:
        raise AuditV2Error("semantic verifier coverage differs")
    evidence: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "stage": "VERIFIED",
        "producer": {
            "git_commit": pins.git_commit,
            "manifest_sha256": pins.manifest_sha256,
            "executor_sha256": pins.executor_sha256,
            "deterministic_sha256": pins.deterministic_sha256,
            "lineage_sha256": pins.lineage_sha256,
        },
        "verifier": {
            "git_commit": offline.verifier_git_commit,
            "release_manifest_sha256": offline.verifier_release_manifest_sha256,
        },
        "coverage": verified["coverage"],
        "checkpoint_set_sha256": offline.checkpoint_set_sha256,
        "live_readback": {
            "observed_at_utc": observed.isoformat(),
            "finalized_at_utc": finalized.isoformat(),
            "effective_identity": live.effective_identity,
            "database_name": live.database_name,
            "snapshot_id": live.snapshot_id,
            "session_sha256": live.session_sha256,
            "select_statement_count": live.select_statement_count,
            "database_write_count": live.database_write_count,
            "downstream_counts": dict(live.downstream_counts),
        },
        "side_effects": dict(ZERO_SIDE_EFFECTS),
        "producer_semantic_replay_at_utc": producer_observed.isoformat(),
        "execution_authorized": False,
        "successor_authorized": False,
    }
    evidence["audit_evidence_sha256"] = sha256(canonical_bytes(evidence))
    return evidence
