"""Pure materializer for the immutable S08 normalized-edge input bundle.

All source evidence is injected.  The module has no database, network,
filesystem, process, persistence, model-fit, prediction, or trading capability.
It binds full canonical market rows to a verified frozen-content digest, binds
the exact 416-session slice to S07, and materializes fold-local independent
ticker/lag payloads without interpreting edge tuple position as lag depth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping, Sequence
import hashlib
import re

import numpy as np

try:
    from .normalized_edge_input_contract import (
        CLAIM_SCOPE, EXPECTED_DEPTHS, EXPECTED_FOLD_GEOMETRY, EXPECTED_FOLDS,
        EXPECTED_LAGS, EXPECTED_PAYLOADS, EXPECTED_TARGETS, INPUT_CONTRACT_ID,
        NORMALIZED_EDGE_SOURCE_CONTRACT_ID, PREREGISTRATION_CONTRACT_ID,
        RETURN_UNIT, TOPOLOGY, FoldPayloadDescriptor, NormalizedEdge,
        NormalizedInputError, build_manifest, canonical_sha256,
        encode_fold_payload, serialize_manifest,
    )
except ImportError:  # direct isolated execution against canonical package
    from research_contracts.pymc_stock_model_backend.normalized_edge_input_contract import (
        CLAIM_SCOPE, EXPECTED_DEPTHS, EXPECTED_FOLD_GEOMETRY, EXPECTED_FOLDS,
        EXPECTED_LAGS, EXPECTED_PAYLOADS, EXPECTED_TARGETS, INPUT_CONTRACT_ID,
        NORMALIZED_EDGE_SOURCE_CONTRACT_ID, PREREGISTRATION_CONTRACT_ID,
        RETURN_UNIT, TOPOLOGY, FoldPayloadDescriptor, NormalizedEdge,
        NormalizedInputError, build_manifest, canonical_sha256,
        encode_fold_payload, serialize_manifest,
    )

from oracle_research_dataset_serializers import (
    MARKET_DAILY_FEATURE_COLUMNS, MarketDatasetStreamingDigester,
)


MATERIALIZER_CONTRACT_ID = "codex-oracle-s08-injected-source-materializer-v1"
EXPECTED_CALENDAR_SESSIONS = 416
EXPECTED_PURGE = 7
_SHA = re.compile(r"[0-9a-f]{64}")
_GIT = re.compile(r"[0-9a-f]{40}")
_ZERO_DOWNSTREAM = {
    "predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0,
}


class MaterializationError(NormalizedInputError):
    """Raised before returning any bundle when injected evidence differs."""


@dataclass(frozen=True)
class FrozenContentBinding:
    dataset_version_id: str
    dataset_status: str
    freeze_event_count: int
    market_snapshot_id: str
    market_snapshot_sha256: str
    content_sha256: str
    content_ticker_universe_sha256: str
    expected_row_count: int
    expected_ticker_count: int
    first_session_date: date
    last_session_date: date


@dataclass(frozen=True)
class FoldEdgeSelection:
    target_ticker: str
    fold_number: int
    selection_end_ordinal: int
    selection_artifact_sha256: str
    edges: tuple[NormalizedEdge, ...]
    training_only: bool = True
    lag_semantics: str = "TARGET_RELATIVE_TRADING_SESSIONS"


@dataclass(frozen=True)
class MaterializedNormalizedEdgeInputs:
    contract_id: str
    dataset_version_id: str
    frozen_content_sha256: str
    edge_selection_sha256: str
    normalized_edge_source_sha256: str
    manifest_raw: bytes
    manifest_raw_sha256: str
    payloads: Mapping[str, bytes]
    payload_count: int
    payload_bytes: int
    target_count: int
    fold_count: int
    database_reads: int = 0
    database_writes: int = 0
    network_calls: int = 0
    model_fits: int = 0
    downstream_outputs: int = 0


def _fail(message: str) -> None:
    raise MaterializationError(message)


def _validate_binding(binding: FrozenContentBinding, preregistration: object) -> None:
    if type(binding) is not FrozenContentBinding:
        _fail("frozen content binding must use the exact injected type")
    if not binding.dataset_version_id or binding.dataset_status != "FROZEN":
        _fail("dataset binding is not an exact FROZEN version")
    if type(binding.freeze_event_count) is not int or binding.freeze_event_count != 1:
        _fail("dataset binding must have exactly one freeze event")
    for value, label in (
        (binding.market_snapshot_sha256, "market snapshot"),
        (binding.content_sha256, "frozen content"),
        (binding.content_ticker_universe_sha256, "content ticker universe"),
    ):
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            _fail(f"{label} identity is not lowercase SHA-256")
    if (
        type(binding.expected_row_count) is not int
        or type(binding.expected_ticker_count) is not int
        or binding.expected_row_count <= 0
        or binding.expected_ticker_count != EXPECTED_TARGETS
    ):
        _fail("frozen row/ticker coverage differs")
    if type(binding.first_session_date) is not date or type(binding.last_session_date) is not date:
        _fail("frozen session boundary type differs")
    if binding.first_session_date >= binding.last_session_date:
        _fail("frozen session boundary is invalid")
    if (
        getattr(preregistration, "contract_id", None) != PREREGISTRATION_CONTRACT_ID
        or getattr(preregistration, "snapshot_id", None) != binding.market_snapshot_id
        or getattr(preregistration, "snapshot_sha256", None) != binding.market_snapshot_sha256
        or getattr(preregistration, "target_count", None) != EXPECTED_TARGETS
        or getattr(preregistration, "fold_count", None) != EXPECTED_FOLDS
        or getattr(preregistration, "model_calendar_sessions", None) != EXPECTED_CALENDAR_SESSIONS
        or getattr(preregistration, "candidate_lags", None) != EXPECTED_LAGS
        or getattr(preregistration, "candidate_depths", None) != EXPECTED_DEPTHS
        or getattr(preregistration, "training_only_selection", None) is not True
        or getattr(preregistration, "zero_temporal_overlap", None) is not True
        or getattr(preregistration, "fixture_only", None) is not True
        or getattr(preregistration, "model_fit_authorized", None) is not False
        or getattr(preregistration, "model_fit_started", None) is not False
        or dict(getattr(preregistration, "downstream_counts", {})) != _ZERO_DOWNSTREAM
    ):
        _fail("S07 preregistration geometry, lineage, or fixture boundary differs")
    for field in (
        "raw_sha256", "checkpoint_identity_sha256", "universe_sha256",
        "full_session_calendar_sha256", "model_session_dates_sha256",
        "model_config_sha256", "sampler_sha256",
    ):
        if not _SHA.fullmatch(str(getattr(preregistration, field, ""))):
            _fail(f"S07 {field} identity differs")
    if not _GIT.fullmatch(str(getattr(preregistration, "model_code_git_commit", ""))):
        _fail("S07 model code identity differs")


def _calendar(model_session_dates: Sequence[date], preregistration: object) -> tuple[date, ...]:
    dates = tuple(model_session_dates)
    if (
        len(dates) != EXPECTED_CALENDAR_SESSIONS
        or any(type(item) is not date for item in dates)
        or tuple(sorted(set(dates))) != dates
    ):
        _fail("model session calendar differs from 416 increasing unique dates")
    if canonical_sha256([item.isoformat() for item in dates]) != preregistration.model_session_dates_sha256:
        _fail("model session calendar digest differs from S07")
    return dates


def _digest_and_panel(
    rows: Sequence[Sequence[object]],
    *,
    binding: FrozenContentBinding,
    model_dates: tuple[date, ...],
    preregistration: object,
) -> tuple[tuple[str, ...], tuple[date, ...], Mapping[tuple[str, date], float]]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        _fail("canonical market rows must be an injected positional sequence")
    if len(rows) != binding.expected_row_count:
        _fail("injected market row count differs from frozen binding")
    digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
    try:
        digester.update_rows(rows)
        digests = digester.finalize()
    except Exception as exc:
        raise MaterializationError("canonical market row serialization failed") from exc
    if (
        digests.content_sha256 != binding.content_sha256
        or digests.ticker_universe_sha256 != binding.content_ticker_universe_sha256
        or digests.row_count != binding.expected_row_count
        or digests.ticker_count != binding.expected_ticker_count
        or digests.snapshot_id != binding.market_snapshot_id
        or digests.first_session_date != binding.first_session_date
        or digests.last_session_date != binding.last_session_date
    ):
        _fail("injected canonical market content differs from frozen binding")

    return_index = MARKET_DAILY_FEATURE_COLUMNS.index("daily_return_pct")
    tickers: list[str] = []
    full_dates: set[date] = set()
    returns: dict[tuple[str, date], float] = {}
    last_ticker: str | None = None
    for row in rows:
        ticker = str(row[1])
        session = row[2] if type(row[2]) is date else date.fromisoformat(str(row[2]))
        value = row[return_index]
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            _fail("daily_return_pct is absent, nonnumeric, or non-finite")
        if ticker != last_ticker:
            tickers.append(ticker)
            last_ticker = ticker
        full_dates.add(session)
        returns[(ticker, session)] = float(value)
    ordered_dates = tuple(sorted(full_dates))
    if canonical_sha256([item.isoformat() for item in ordered_dates]) != preregistration.full_session_calendar_sha256:
        _fail("full frozen session calendar digest differs from S07")
    if any(item not in full_dates for item in model_dates):
        _fail("S07 model calendar contains a session absent from frozen content")
    if len(returns) != len(rows):
        _fail("canonical market content has duplicated ticker/session keys")
    ticker_tuple = tuple(tickers)
    if canonical_sha256(list(ticker_tuple)) != preregistration.universe_sha256:
        _fail("materialized target universe differs from S07")
    first_model_index = ordered_dates.index(model_dates[0])
    if first_model_index < max(EXPECTED_LAGS):
        _fail("frozen content lacks seven pre-model sessions for lag alignment")
    if tuple(ordered_dates[ordered_dates.index(item)] for item in model_dates) != model_dates:
        _fail("model calendar ordering differs from frozen content")
    required_sessions = set(model_dates)
    for session in model_dates:
        ordinal = ordered_dates.index(session)
        required_sessions.update(
            ordered_dates[ordinal - lag] for lag in EXPECTED_LAGS
        )
    if any((ticker, session) not in returns for ticker in ticker_tuple for session in required_sessions):
        _fail("frozen content is incomplete for a required target or lagged source session")
    return ticker_tuple, ordered_dates, MappingProxyType(returns)


def _selection_source(
    selections: Sequence[FoldEdgeSelection], *, tickers: tuple[str, ...]
) -> tuple[tuple[FoldEdgeSelection, ...], str]:
    if isinstance(selections, (str, bytes)) or not isinstance(selections, Sequence):
        _fail("fold-local selections must be an injected sequence")
    ordered = tuple(selections)
    if len(ordered) != EXPECTED_PAYLOADS or any(type(item) is not FoldEdgeSelection for item in ordered):
        _fail("fold-local selection coverage differs from 474 x 4")
    expected_keys = tuple((ticker, fold) for ticker in tickers for fold in range(1, 5))
    keys = tuple((item.target_ticker, item.fold_number) for item in ordered)
    if keys != expected_keys:
        _fail("fold-local selections are missing, duplicated, or noncanonical")
    ticker_set = set(tickers)
    source_payload: list[object] = []
    for item in ordered:
        _, _start, train_end, _test_start, _test_end = EXPECTED_FOLD_GEOMETRY[item.fold_number - 1]
        if (
            item.selection_end_ordinal != train_end
            or item.training_only is not True
            or item.lag_semantics != "TARGET_RELATIVE_TRADING_SESSIONS"
            or not _SHA.fullmatch(item.selection_artifact_sha256)
            or not 1 <= len(item.edges) <= max(EXPECTED_DEPTHS)
        ):
            _fail("fold selection cutoff, lineage, depth, or semantics differs")
        identities: list[tuple[str, int]] = []
        for edge in item.edges:
            if type(edge) is not NormalizedEdge:
                _fail("edge must use exact normalized identity; positional fields are prohibited")
            identity = (edge.source_ticker, edge.lag_sessions)
            if (
                edge.source_ticker not in ticker_set
                or edge.lag_sessions not in EXPECTED_LAGS
                or edge.lag_semantics != item.lag_semantics
            ):
                _fail("edge source, lag 1-7, or target-relative semantics differs")
            identities.append(identity)
        if len(set(identities)) != len(identities) or identities != sorted(identities):
            _fail("fold edges are duplicated or not canonical independent identities")
        source_payload.append({
            "target_ticker": item.target_ticker,
            "fold_number": item.fold_number,
            "selection_end_ordinal": item.selection_end_ordinal,
            "selection_artifact_sha256": item.selection_artifact_sha256,
            "edges": [
                {"source_ticker": edge.source_ticker, "lag_sessions": edge.lag_sessions,
                 "lag_semantics": edge.lag_semantics}
                for edge in item.edges
            ],
        })
    return ordered, canonical_sha256(source_payload)


def materialize_normalized_edge_inputs(
    *,
    frozen: FrozenContentBinding,
    canonical_market_rows: Sequence[Sequence[object]],
    model_session_dates: Sequence[date],
    preregistration: object,
    fold_edge_selections: Sequence[FoldEdgeSelection],
) -> MaterializedNormalizedEdgeInputs:
    """Materialize a deterministic 474x4 bundle from injected evidence only."""
    _validate_binding(frozen, preregistration)
    model_dates = _calendar(model_session_dates, preregistration)
    tickers, full_dates, returns = _digest_and_panel(
        canonical_market_rows, binding=frozen, model_dates=model_dates,
        preregistration=preregistration,
    )
    selections, edge_selection_sha = _selection_source(fold_edge_selections, tickers=tickers)
    source_sha = canonical_sha256({
        "contract_id": MATERIALIZER_CONTRACT_ID,
        "dataset_version_id": frozen.dataset_version_id,
        "market_snapshot_id": frozen.market_snapshot_id,
        "market_snapshot_sha256": frozen.market_snapshot_sha256,
        "frozen_content_sha256": frozen.content_sha256,
        "content_ticker_universe_sha256": frozen.content_ticker_universe_sha256,
        "model_session_dates_sha256": preregistration.model_session_dates_sha256,
        "edge_selection_sha256": edge_selection_sha,
    })
    full_ordinal = {session: index for index, session in enumerate(full_dates)}

    payloads: dict[str, bytes] = {}
    records: list[FoldPayloadDescriptor] = []
    for selection in selections:
        _, train_start, train_end, test_start, test_end = EXPECTED_FOLD_GEOMETRY[
            selection.fold_number - 1
        ]
        train_ordinals = tuple(range(train_start, train_end + 1))
        test_ordinals = tuple(range(test_start, test_end + 1))
        edges = selection.edges

        def matrix(ordinals: tuple[int, ...]) -> np.ndarray:
            return np.asarray([
                [
                    returns[(edge.source_ticker, full_dates[full_ordinal[model_dates[ordinal]] - edge.lag_sessions])]
                    for edge in edges
                ]
                for ordinal in ordinals
            ], dtype=float)

        y_train = np.asarray(
            [returns[(selection.target_ticker, model_dates[item])] for item in train_ordinals],
            dtype=float,
        )
        y_test = np.asarray(
            [returns[(selection.target_ticker, model_dates[item])] for item in test_ordinals],
            dtype=float,
        )
        temporary = FoldPayloadDescriptor(
            target_ticker=selection.target_ticker,
            fold_number=selection.fold_number,
            payload_key=f"folds/{selection.target_ticker}/fold-{selection.fold_number}.bin",
            payload_sha256="0" * 64,
            payload_size_bytes=9,
            train_start_ordinal=train_start,
            train_end_ordinal=train_end,
            selection_end_ordinal=selection.selection_end_ordinal,
            test_start_ordinal=test_start,
            test_end_ordinal=test_end,
            train_observations=len(train_ordinals),
            test_observations=len(test_ordinals),
            purge_sessions=test_start - train_end - 1,
            selection_artifact_sha256=selection.selection_artifact_sha256,
            edges=edges,
        )
        raw = encode_fold_payload(
            temporary,
            x_train=matrix(train_ordinals),
            y_train_direction=(y_train > 0.0).astype(np.uint8),
            y_train_return_pct=y_train,
            x_test=matrix(test_ordinals),
            y_test_direction=(y_test > 0.0).astype(np.uint8),
            y_test_return_pct=y_test,
        )
        record = FoldPayloadDescriptor(
            **{
                **temporary.__dict__,
                "payload_sha256": hashlib.sha256(raw).hexdigest(),
                "payload_size_bytes": len(raw),
            }
        )
        payloads[record.payload_key] = raw
        records.append(record)

    manifest = build_manifest(
        contract_id=INPUT_CONTRACT_ID,
        preregistration_contract_id=PREREGISTRATION_CONTRACT_ID,
        preregistration_raw_sha256=preregistration.raw_sha256,
        checkpoint_identity_sha256=preregistration.checkpoint_identity_sha256,
        snapshot_id=preregistration.snapshot_id,
        snapshot_sha256=preregistration.snapshot_sha256,
        universe_id=preregistration.universe_id,
        universe_sha256=preregistration.universe_sha256,
        full_session_calendar_sha256=preregistration.full_session_calendar_sha256,
        model_session_dates_sha256=preregistration.model_session_dates_sha256,
        model_code_git_commit=preregistration.model_code_git_commit,
        model_config_sha256=preregistration.model_config_sha256,
        sampler_sha256=preregistration.sampler_sha256,
        normalized_edge_source_contract_id=NORMALIZED_EDGE_SOURCE_CONTRACT_ID,
        normalized_edge_source_sha256=source_sha,
        multiple_testing_control=preregistration.multiple_testing_control,
        topology=TOPOLOGY,
        claim_scope=CLAIM_SCOPE,
        return_unit=RETURN_UNIT,
        candidate_lags=EXPECTED_LAGS,
        candidate_depths=EXPECTED_DEPTHS,
        calendar_sessions=EXPECTED_CALENDAR_SESSIONS,
        target_count=EXPECTED_TARGETS,
        fold_count=EXPECTED_FOLDS,
        payload_count=EXPECTED_PAYLOADS,
        training_only_selection=True,
        zero_temporal_overlap=True,
        database_write_scope="NONE",
        downstream_counts=_ZERO_DOWNSTREAM,
        records=tuple(records),
    )
    manifest_raw = serialize_manifest(manifest)
    return MaterializedNormalizedEdgeInputs(
        contract_id=MATERIALIZER_CONTRACT_ID,
        dataset_version_id=frozen.dataset_version_id,
        frozen_content_sha256=frozen.content_sha256,
        edge_selection_sha256=edge_selection_sha,
        normalized_edge_source_sha256=source_sha,
        manifest_raw=manifest_raw,
        manifest_raw_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        payloads=MappingProxyType(payloads),
        payload_count=len(payloads),
        payload_bytes=sum(len(value) for value in payloads.values()),
        target_count=len(tickers),
        fold_count=EXPECTED_FOLDS,
    )
