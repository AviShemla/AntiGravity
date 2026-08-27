"""Immutable normalized-edge input reader for the governed S08 stock fit.

The reader is pure apart from an injected byte loader. It never contacts Turso,
selects edges, changes model/sampler semantics, or launches a fit. It requires
exact S07 lineage plus 474 targets x four leakage-free folds and verifies every
binary payload before returning a preflight artifact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import struct
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

import numpy as np

try:
    from model_fit_contract_impl.execution_contract import PreregistrationProof
except ImportError:
    from research_contracts.stock_model_fit_execution.execution_contract import PreregistrationProof


INPUT_CONTRACT_ID = "codex-oracle-s08-normalized-edge-input-v1"
PAYLOAD_CONTRACT_ID = "codex-oracle-s08-normalized-edge-fold-binary-v1"
NORMALIZED_EDGE_SOURCE_CONTRACT_ID = "codex-oracle-normalized-independent-edge-source-v1"
PREREGISTRATION_CONTRACT_ID = "codex-oracle-hierarchical-stock-preregistration-v2"
TOPOLOGY = "INDEPENDENT_TICKER_LAG_EDGES_PARTIAL_POOLING"
CLAIM_SCOPE = "OBSERVATIONAL_PREDICTIVE_ASSOCIATION_NOT_CAUSAL"
RETURN_UNIT = "PERCENT"
EXPECTED_TARGETS = 474
EXPECTED_FOLDS = 4
EXPECTED_PAYLOADS = EXPECTED_TARGETS * EXPECTED_FOLDS
EXPECTED_CALENDAR_SESSIONS = 416
EXPECTED_LAGS = tuple(range(1, 8))
EXPECTED_DEPTHS = tuple(range(1, 6))
EXPECTED_PURGE = 7
EXPECTED_TRAIN = 289
EXPECTED_TEST = 30
EXPECTED_FOLD_GEOMETRY = (
    (1, 0, 288, 296, 325),
    (2, 30, 318, 326, 355),
    (3, 60, 348, 356, 385),
    (4, 90, 378, 386, 415),
)
_SHA = re.compile(r"[0-9a-f]{64}")
_GIT = re.compile(r"[0-9a-f]{40}")
_TICKER = re.compile(r"[A-Z0-9.^-]{1,24}")
_PAYLOAD_KEY = re.compile(r"folds/[A-Z0-9.^-]{1,24}/fold-[1-4]\.bin")
_HEADER_LENGTH = struct.Struct(">Q")
_ZERO_DOWNSTREAM = {
    "predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0,
}


class NormalizedInputError(RuntimeError):
    """Raised before backend access when immutable input evidence differs."""


@dataclass(frozen=True)
class NormalizedEdge:
    source_ticker: str
    lag_sessions: int
    lag_semantics: str = "TARGET_RELATIVE_TRADING_SESSIONS"


@dataclass(frozen=True)
class FoldPayloadDescriptor:
    target_ticker: str
    fold_number: int
    payload_key: str
    payload_sha256: str
    payload_size_bytes: int
    train_start_ordinal: int
    train_end_ordinal: int
    selection_end_ordinal: int
    test_start_ordinal: int
    test_end_ordinal: int
    train_observations: int
    test_observations: int
    purge_sessions: int
    selection_artifact_sha256: str
    edges: tuple[NormalizedEdge, ...]


@dataclass(frozen=True)
class NormalizedEdgeManifest:
    contract_id: str
    preregistration_contract_id: str
    preregistration_raw_sha256: str
    checkpoint_identity_sha256: str
    snapshot_id: str
    snapshot_sha256: str
    universe_id: str
    universe_sha256: str
    full_session_calendar_sha256: str
    model_session_dates_sha256: str
    model_code_git_commit: str
    model_config_sha256: str
    sampler_sha256: str
    normalized_edge_source_contract_id: str
    normalized_edge_source_sha256: str
    multiple_testing_control: str
    topology: str
    claim_scope: str
    return_unit: str
    candidate_lags: tuple[int, ...]
    candidate_depths: tuple[int, ...]
    calendar_sessions: int
    target_count: int
    fold_count: int
    payload_count: int
    training_only_selection: bool
    zero_temporal_overlap: bool
    database_write_scope: str
    downstream_counts: Mapping[str, int]
    records: tuple[FoldPayloadDescriptor, ...]
    deterministic_bundle_sha256: str


@dataclass(frozen=True)
class DecodedFoldPayload:
    target_ticker: str
    fold_number: int
    edges: tuple[NormalizedEdge, ...]
    train_session_ordinals: tuple[int, ...]
    test_session_ordinals: tuple[int, ...]
    x_train: np.ndarray
    y_train_direction: np.ndarray
    y_train_return_pct: np.ndarray
    x_test: np.ndarray
    y_test_direction: np.ndarray
    y_test_return_pct: np.ndarray


@dataclass(frozen=True)
class VerifiedNormalizedEdgeBundle:
    manifest_raw_sha256: str
    deterministic_bundle_sha256: str
    preregistration_raw_sha256: str
    checkpoint_identity_sha256: str
    snapshot_sha256: str
    universe_sha256: str
    model_session_dates_sha256: str
    model_code_git_commit: str
    model_config_sha256: str
    sampler_sha256: str
    target_count: int
    fold_count: int
    payload_count: int
    verified_payload_count: int
    target_fold_set_sha256: str
    records: tuple[FoldPayloadDescriptor, ...]
    database_writes: int = 0
    downstream_outputs: int = 0


PayloadLoader = Callable[[str], bytes]


def _primitive(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {field.name: _primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    return value


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _primitive(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise NormalizedInputError("input evidence is not canonical") from exc


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise NormalizedInputError(f"{label} must be a lowercase SHA-256")
    return value


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise NormalizedInputError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _validate_preregistration(proof: PreregistrationProof, observed_at_utc: datetime) -> None:
    if type(proof) is not PreregistrationProof or proof.contract_id != PREREGISTRATION_CONTRACT_ID:
        raise NormalizedInputError("S07 preregistration type or contract differs")
    now = _utc(observed_at_utc, "input observation")
    for value, label in (
        (proof.raw_sha256, "S07 raw identity"),
        (proof.checkpoint_identity_sha256, "S07 checkpoint identity"),
        (proof.snapshot_sha256, "S07 snapshot identity"),
        (proof.universe_sha256, "S07 universe identity"),
        (proof.full_session_calendar_sha256, "S07 full calendar identity"),
        (proof.model_session_dates_sha256, "S07 model dates identity"),
        (proof.model_config_sha256, "S07 model configuration"),
        (proof.sampler_sha256, "S07 sampler"),
    ):
        _sha(value, label)
    if not _GIT.fullmatch(proof.model_code_git_commit):
        raise NormalizedInputError("S07 code identity differs")
    for timestamp, label in (
        (proof.independent_audit_observed_at_utc, "S07 independent audit"),
        (proof.current_readback_observed_at_utc, "S07 current readback"),
    ):
        value = _utc(timestamp, label)
        if value > now or now - value > timedelta(hours=1):
            raise NormalizedInputError(f"{label} is stale or future-dated")
    if proof.independent_audit_status != "VERIFIED_FIXTURE_ONLY" or proof.current_readback_status != "VERIFIED_SELECT_ONLY":
        raise NormalizedInputError("S07 independent audit or current readback is not verified")
    expected = (
        proof.candidate_lags == EXPECTED_LAGS,
        proof.candidate_depths == EXPECTED_DEPTHS,
        proof.target_count == EXPECTED_TARGETS,
        proof.fold_count == EXPECTED_FOLDS,
        proof.model_calendar_sessions == EXPECTED_CALENDAR_SESSIONS,
        proof.training_only_selection is True,
        proof.zero_temporal_overlap is True,
        proof.fixture_only is True,
        proof.model_fit_authorized is False,
        proof.model_fit_started is False,
        dict(proof.downstream_counts) == _ZERO_DOWNSTREAM,
    )
    if not all(expected):
        raise NormalizedInputError("S07 governed geometry or side-effect boundary differs")


def _validate_edge(edge: NormalizedEdge) -> None:
    if type(edge) is not NormalizedEdge or not _TICKER.fullmatch(edge.source_ticker):
        raise NormalizedInputError("normalized edge source differs")
    if type(edge.lag_sessions) is not int or edge.lag_sessions not in EXPECTED_LAGS:
        raise NormalizedInputError("normalized edge lag differs")
    if edge.lag_semantics != "TARGET_RELATIVE_TRADING_SESSIONS":
        raise NormalizedInputError("normalized edge lag semantics differ")


def _validate_descriptor(record: FoldPayloadDescriptor) -> None:
    if type(record) is not FoldPayloadDescriptor or not _TICKER.fullmatch(record.target_ticker):
        raise NormalizedInputError("target/fold descriptor type or ticker differs")
    if type(record.fold_number) is not int or not 1 <= record.fold_number <= EXPECTED_FOLDS:
        raise NormalizedInputError("fold number differs")
    if record.payload_key != f"folds/{record.target_ticker}/fold-{record.fold_number}.bin" or not _PAYLOAD_KEY.fullmatch(record.payload_key):
        raise NormalizedInputError("payload key differs or is unsafe")
    _sha(record.payload_sha256, "fold payload identity")
    _sha(record.selection_artifact_sha256, "fold selection artifact identity")
    integer_fields = (
        record.payload_size_bytes, record.train_start_ordinal,
        record.train_end_ordinal, record.selection_end_ordinal,
        record.test_start_ordinal, record.test_end_ordinal,
        record.train_observations, record.test_observations,
        record.purge_sessions,
    )
    if any(type(value) is not int for value in integer_fields):
        raise NormalizedInputError("fold descriptor integer type differs")
    expected = EXPECTED_FOLD_GEOMETRY[record.fold_number - 1]
    observed = (
        record.fold_number, record.train_start_ordinal, record.train_end_ordinal,
        record.test_start_ordinal, record.test_end_ordinal,
    )
    if observed != expected:
        raise NormalizedInputError("fold walk-forward geometry differs")
    if (
        record.selection_end_ordinal > record.train_end_ordinal
        or record.selection_end_ordinal < record.train_start_ordinal
        or record.test_start_ordinal - record.train_end_ordinal - 1 != EXPECTED_PURGE
        or record.train_observations != EXPECTED_TRAIN
        or record.test_observations != EXPECTED_TEST
        or record.purge_sessions != EXPECTED_PURGE
        or record.payload_size_bytes <= _HEADER_LENGTH.size
    ):
        raise NormalizedInputError("fold selection, purge, or observation contract differs")
    if not 1 <= len(record.edges) <= max(EXPECTED_DEPTHS):
        raise NormalizedInputError("normalized edge depth differs")
    identities = set()
    for edge in record.edges:
        _validate_edge(edge)
        identity = (edge.source_ticker, edge.lag_sessions)
        if identity in identities:
            raise NormalizedInputError("normalized edges are duplicated")
        identities.add(identity)
    if record.edges != tuple(sorted(record.edges, key=lambda item: (item.source_ticker, item.lag_sessions))):
        raise NormalizedInputError("normalized edges are not in canonical identity order")


def _deterministic_manifest_payload(manifest: NormalizedEdgeManifest) -> dict[str, object]:
    payload = _primitive(manifest)
    if not isinstance(payload, dict):
        raise NormalizedInputError("normalized manifest primitive differs")
    payload.pop("deterministic_bundle_sha256")
    return payload


def build_manifest(**kwargs: object) -> NormalizedEdgeManifest:
    """Build a content-addressed manifest; validation occurs during readback."""
    temporary = NormalizedEdgeManifest(**kwargs, deterministic_bundle_sha256="0" * 64)
    return replace(
        temporary,
        deterministic_bundle_sha256=canonical_sha256(_deterministic_manifest_payload(temporary)),
    )


def serialize_manifest(manifest: NormalizedEdgeManifest) -> bytes:
    return canonical_bytes(manifest) + b"\n"


def parse_manifest(raw: bytes) -> NormalizedEdgeManifest:
    if not isinstance(raw, bytes) or not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise NormalizedInputError("manifest framing differs")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizedInputError("manifest is not JSON") from exc
    if canonical_bytes(value) + b"\n" != raw:
        raise NormalizedInputError("manifest bytes are not canonical")
    try:
        records = tuple(
            FoldPayloadDescriptor(
                **{**item, "edges": tuple(NormalizedEdge(**edge) for edge in item["edges"])}
            )
            for item in value["records"]
        )
        return NormalizedEdgeManifest(
            **{
                **value,
                "candidate_lags": tuple(value["candidate_lags"]),
                "candidate_depths": tuple(value["candidate_depths"]),
                "records": records,
                "downstream_counts": MappingProxyType(dict(value["downstream_counts"])),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NormalizedInputError("manifest schema differs") from exc


def _payload_header(record: FoldPayloadDescriptor) -> dict[str, object]:
    return {
        "contract_id": PAYLOAD_CONTRACT_ID,
        "target_ticker": record.target_ticker,
        "fold_number": record.fold_number,
        "selection_artifact_sha256": record.selection_artifact_sha256,
        "edges": [asdict(edge) for edge in record.edges],
        "train_session_ordinals": list(range(record.train_start_ordinal, record.train_end_ordinal + 1)),
        "test_session_ordinals": list(range(record.test_start_ordinal, record.test_end_ordinal + 1)),
        "train_observations": record.train_observations,
        "test_observations": record.test_observations,
        "depth": len(record.edges),
        "layout": [
            ["x_train", "<f8", [record.train_observations, len(record.edges)]],
            ["y_train_direction", "u1", [record.train_observations]],
            ["y_train_return_pct", "<f8", [record.train_observations]],
            ["x_test", "<f8", [record.test_observations, len(record.edges)]],
            ["y_test_direction", "u1", [record.test_observations]],
            ["y_test_return_pct", "<f8", [record.test_observations]],
        ],
        "return_unit": RETURN_UNIT,
        "training_only_selection": True,
    }


def encode_fold_payload(
    record: FoldPayloadDescriptor,
    *,
    x_train: np.ndarray,
    y_train_direction: np.ndarray,
    y_train_return_pct: np.ndarray,
    x_test: np.ndarray,
    y_test_direction: np.ndarray,
    y_test_return_pct: np.ndarray,
) -> bytes:
    """Deterministically encode one already-normalized fold for immutable storage."""
    _validate_descriptor(record)
    arrays = (
        np.asarray(x_train, dtype="<f8", order="C"),
        np.asarray(y_train_direction, dtype="u1", order="C"),
        np.asarray(y_train_return_pct, dtype="<f8", order="C"),
        np.asarray(x_test, dtype="<f8", order="C"),
        np.asarray(y_test_direction, dtype="u1", order="C"),
        np.asarray(y_test_return_pct, dtype="<f8", order="C"),
    )
    expected_shapes = (
        (record.train_observations, len(record.edges)),
        (record.train_observations,), (record.train_observations,),
        (record.test_observations, len(record.edges)),
        (record.test_observations,), (record.test_observations,),
    )
    if tuple(array.shape for array in arrays) != expected_shapes:
        raise NormalizedInputError("fold payload array shape differs")
    if any(not np.isfinite(array).all() for index, array in enumerate(arrays) if index not in {1, 4}):
        raise NormalizedInputError("fold payload contains non-finite numeric evidence")
    if any(not set(np.unique(arrays[index])).issubset({0, 1}) for index in (1, 4)):
        raise NormalizedInputError("fold payload direction evidence is not binary")
    header = canonical_bytes(_payload_header(record))
    return _HEADER_LENGTH.pack(len(header)) + header + b"".join(array.tobytes(order="C") for array in arrays)


def decode_fold_payload(record: FoldPayloadDescriptor, raw: bytes) -> DecodedFoldPayload:
    if not isinstance(raw, bytes) or len(raw) != record.payload_size_bytes:
        raise NormalizedInputError("fold payload size differs")
    if hashlib.sha256(raw).hexdigest() != record.payload_sha256:
        raise NormalizedInputError("fold payload SHA-256 differs")
    if len(raw) < _HEADER_LENGTH.size:
        raise NormalizedInputError("fold payload is truncated")
    header_length = _HEADER_LENGTH.unpack_from(raw, 0)[0]
    header_end = _HEADER_LENGTH.size + header_length
    if header_end > len(raw):
        raise NormalizedInputError("fold payload header is truncated")
    try:
        header = json.loads(raw[_HEADER_LENGTH.size:header_end])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizedInputError("fold payload header is not JSON") from exc
    if canonical_bytes(header) != raw[_HEADER_LENGTH.size:header_end] or header != _payload_header(record):
        raise NormalizedInputError("fold payload header differs")
    depth = len(record.edges)
    shapes = (
        (record.train_observations, depth), (record.train_observations,),
        (record.train_observations,), (record.test_observations, depth),
        (record.test_observations,), (record.test_observations,),
    )
    dtypes = ("<f8", "u1", "<f8", "<f8", "u1", "<f8")
    arrays: list[np.ndarray] = []
    offset = header_end
    for dtype, shape in zip(dtypes, shapes, strict=True):
        count = math.prod(shape)
        size = count * np.dtype(dtype).itemsize
        if offset + size > len(raw):
            raise NormalizedInputError("fold payload data is truncated")
        array = np.frombuffer(raw, dtype=dtype, count=count, offset=offset).reshape(shape).copy()
        arrays.append(array)
        offset += size
    if offset != len(raw):
        raise NormalizedInputError("fold payload has trailing bytes")
    if any(not np.isfinite(array).all() for index, array in enumerate(arrays) if index not in {1, 4}):
        raise NormalizedInputError("fold payload contains non-finite numeric evidence")
    if any(not set(np.unique(arrays[index])).issubset({0, 1}) for index in (1, 4)):
        raise NormalizedInputError("fold payload direction evidence is not binary")
    return DecodedFoldPayload(
        target_ticker=record.target_ticker,
        fold_number=record.fold_number,
        edges=record.edges,
        train_session_ordinals=tuple(range(record.train_start_ordinal, record.train_end_ordinal + 1)),
        test_session_ordinals=tuple(range(record.test_start_ordinal, record.test_end_ordinal + 1)),
        x_train=arrays[0], y_train_direction=arrays[1],
        y_train_return_pct=arrays[2], x_test=arrays[3],
        y_test_direction=arrays[4], y_test_return_pct=arrays[5],
    )


def verify_normalized_edge_bundle(
    manifest_raw: bytes,
    *,
    payload_loader: PayloadLoader,
    preregistration: PreregistrationProof,
    observed_at_utc: datetime,
) -> VerifiedNormalizedEdgeBundle:
    """Verify exact S07 binding, 474x4 geometry, and every payload hash/body."""
    _validate_preregistration(preregistration, observed_at_utc)
    if not callable(payload_loader):
        raise NormalizedInputError("an explicit payload loader is required")
    manifest = parse_manifest(manifest_raw)
    if manifest.contract_id != INPUT_CONTRACT_ID or manifest.preregistration_contract_id != PREREGISTRATION_CONTRACT_ID:
        raise NormalizedInputError("normalized input contract identity differs")
    binding_pairs = (
        (manifest.preregistration_raw_sha256, preregistration.raw_sha256),
        (manifest.checkpoint_identity_sha256, preregistration.checkpoint_identity_sha256),
        (manifest.snapshot_id, preregistration.snapshot_id),
        (manifest.snapshot_sha256, preregistration.snapshot_sha256),
        (manifest.universe_id, preregistration.universe_id),
        (manifest.universe_sha256, preregistration.universe_sha256),
        (manifest.full_session_calendar_sha256, preregistration.full_session_calendar_sha256),
        (manifest.model_session_dates_sha256, preregistration.model_session_dates_sha256),
        (manifest.model_code_git_commit, preregistration.model_code_git_commit),
        (manifest.model_config_sha256, preregistration.model_config_sha256),
        (manifest.sampler_sha256, preregistration.sampler_sha256),
        (manifest.multiple_testing_control, preregistration.multiple_testing_control),
    )
    if any(left != right for left, right in binding_pairs):
        raise NormalizedInputError("normalized input differs from exact S07 lineage")
    if (
        manifest.topology != TOPOLOGY or manifest.claim_scope != CLAIM_SCOPE
        or manifest.normalized_edge_source_contract_id != NORMALIZED_EDGE_SOURCE_CONTRACT_ID
        or not _SHA.fullmatch(manifest.normalized_edge_source_sha256)
        or manifest.return_unit != RETURN_UNIT
        or manifest.candidate_lags != EXPECTED_LAGS
        or manifest.candidate_depths != EXPECTED_DEPTHS
        or (manifest.calendar_sessions, manifest.target_count, manifest.fold_count, manifest.payload_count)
        != (EXPECTED_CALENDAR_SESSIONS, EXPECTED_TARGETS, EXPECTED_FOLDS, EXPECTED_PAYLOADS)
        or manifest.training_only_selection is not True
        or manifest.zero_temporal_overlap is not True
        or manifest.database_write_scope != "NONE"
        or dict(manifest.downstream_counts) != _ZERO_DOWNSTREAM
    ):
        raise NormalizedInputError("normalized input geometry or safety boundary differs")
    deterministic = canonical_sha256(_deterministic_manifest_payload(manifest))
    if manifest.deterministic_bundle_sha256 != deterministic:
        raise NormalizedInputError("normalized input deterministic identity differs")
    if len(manifest.records) != EXPECTED_PAYLOADS:
        raise NormalizedInputError("normalized input record coverage is incomplete")
    keys = []
    targets: dict[str, set[int]] = {}
    verified = 0
    prior_record_key: tuple[str, int] | None = None
    for record in manifest.records:
        _validate_descriptor(record)
        record_key = (record.target_ticker, record.fold_number)
        if prior_record_key is not None and record_key <= prior_record_key:
            raise NormalizedInputError("normalized input records are duplicated or unsorted")
        prior_record_key = record_key
        targets.setdefault(record.target_ticker, set()).add(record.fold_number)
        keys.append(record.payload_key)
        try:
            raw = payload_loader(record.payload_key)
        except Exception as exc:
            raise NormalizedInputError("normalized fold payload is unavailable") from exc
        decode_fold_payload(record, raw)
        verified += 1
    if len(set(keys)) != EXPECTED_PAYLOADS:
        raise NormalizedInputError("normalized payload keys are duplicated")
    if len(targets) != EXPECTED_TARGETS or any(folds != set(range(1, 5)) for folds in targets.values()):
        raise NormalizedInputError("normalized target x fold coverage differs from 474 x 4")
    sorted_targets = tuple(sorted(targets))
    universe_set = set(sorted_targets)
    if any(edge.source_ticker not in universe_set for record in manifest.records for edge in record.edges):
        raise NormalizedInputError("normalized edge source is outside the S07 universe")
    if canonical_sha256(list(sorted_targets)) != preregistration.universe_sha256:
        raise NormalizedInputError("normalized target universe identity differs from S07")
    target_fold_set = [[target, fold] for target in sorted_targets for fold in range(1, 5)]
    return VerifiedNormalizedEdgeBundle(
        manifest_raw_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        deterministic_bundle_sha256=deterministic,
        preregistration_raw_sha256=preregistration.raw_sha256,
        checkpoint_identity_sha256=preregistration.checkpoint_identity_sha256,
        snapshot_sha256=preregistration.snapshot_sha256,
        universe_sha256=preregistration.universe_sha256,
        model_session_dates_sha256=preregistration.model_session_dates_sha256,
        model_code_git_commit=preregistration.model_code_git_commit,
        model_config_sha256=preregistration.model_config_sha256,
        sampler_sha256=preregistration.sampler_sha256,
        target_count=len(targets), fold_count=EXPECTED_FOLDS,
        payload_count=len(manifest.records), verified_payload_count=verified,
        target_fold_set_sha256=canonical_sha256(target_fold_set),
        records=manifest.records,
    )


def load_verified_fold(
    bundle: VerifiedNormalizedEdgeBundle,
    *,
    target_ticker: str,
    fold_number: int,
    payload_loader: PayloadLoader,
) -> DecodedFoldPayload:
    """Re-read and rehash one fold; prior bundle verification is never trusted blindly."""
    if type(bundle) is not VerifiedNormalizedEdgeBundle or bundle.verified_payload_count != EXPECTED_PAYLOADS:
        raise NormalizedInputError("verified bundle evidence differs")
    matches = tuple(
        record for record in bundle.records
        if record.target_ticker == target_ticker and record.fold_number == fold_number
    )
    if len(matches) != 1:
        raise NormalizedInputError("requested normalized fold is absent or duplicated")
    try:
        raw = payload_loader(matches[0].payload_key)
    except Exception as exc:
        raise NormalizedInputError("requested normalized fold payload is unavailable") from exc
    return decode_fold_payload(matches[0], raw)
