"""Pure complete-case materializer for the versioned S08 472-ticker panel."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

from oracle_research_dataset_serializers import (
    MARKET_DAILY_FEATURE_COLUMNS, MarketDatasetStreamingDigester,
)

from .s08_complete_case_universe import (
    CompleteCaseUniverseAudit, audit_complete_case_universe,
)
from .s08_selector_v8 import SignalPanel, build_signal_panel
from .s08_signal_panel_materializer import (
    FLOAT_CONTRACT, SIGNAL_CONTRACT,
    FrozenMarketBinding, ImportedSerializerBinding, S07SignalBinding,
    TrustedReadbackBinding, binding_artifact_sha256,
    canonical_session_dates_sha256, canonical_ticker_list_sha256,
    trusted_readback_artifact_sha256,
)


CONTRACT_ID = "codex-oracle-selector-v8-complete-case-panel-v2"
EXPECTED_UPSTREAM_TICKERS = 474
EXPECTED_ELIGIBLE_TICKERS = 472
EXPECTED_MODEL_SESSIONS = 416


class CompleteCasePanelError(ValueError):
    pass


@dataclass(frozen=True)
class CompleteCaseSignalPanelEvidence:
    contract_id: str
    dataset_version: str
    snapshot_id: str
    frozen_content_sha256: str
    upstream_universe_sha256: str
    required_dates_sha256: str
    presence_mask_sha256: str
    eligible_universe_sha256: str
    exclusion_evidence_sha256: str
    eligible_tickers: tuple[str, ...]
    model_session_dates: tuple[str, ...]
    shape: tuple[int, int]
    panel: SignalPanel
    panel_sha256: str
    complete_case_audit: CompleteCaseUniverseAudit
    imputation_count: int = 0
    database_writes: int = 0
    selections: int = 0
    model_runs: int = 0
    predictions: int = 0
    downstream_outputs: int = 0
    execution_authorized: bool = False


def _sha_json(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_bindings(
    market: FrozenMarketBinding,
    s07: S07SignalBinding,
    readback: TrustedReadbackBinding,
    serializer: ImportedSerializerBinding,
) -> None:
    if (type(market) is not FrozenMarketBinding or type(s07) is not S07SignalBinding
            or type(readback) is not TrustedReadbackBinding
            or type(serializer) is not ImportedSerializerBinding):
        raise CompleteCasePanelError("binding evidence type differs")
    if (binding_artifact_sha256(market) != market.binding_artifact_sha256
            or trusted_readback_artifact_sha256(readback) != readback.readback_evidence_sha256):
        raise CompleteCasePanelError("market/readback binding identity differs")
    if (market.dataset_version != readback.dataset_version
            or market.snapshot_id != readback.snapshot_id
            or market.content_sha256 != readback.frozen_content_sha256
            or market.content_sha256 != s07.frozen_content_sha256):
        raise CompleteCasePanelError("dataset/snapshot/content lineage differs")
    if market.upstream_imputation_count != 0:
        raise CompleteCasePanelError("upstream imputation is prohibited")
    if s07.signal_contract != SIGNAL_CONTRACT or s07.float_contract != FLOAT_CONTRACT:
        raise CompleteCasePanelError("S07 signal/float contract differs")
    if serializer.feature_columns_sha256 != _sha_json(list(MARKET_DAILY_FEATURE_COLUMNS)):
        raise CompleteCasePanelError("serializer feature-column identity differs")
    if (len(s07.tickers) != EXPECTED_UPSTREAM_TICKERS
            or tuple(sorted(set(s07.tickers))) != s07.tickers
            or canonical_ticker_list_sha256(s07.tickers) != s07.ticker_list_sha256):
        raise CompleteCasePanelError("S07 upstream universe differs from sorted 474")
    if (len(s07.model_session_dates) != EXPECTED_MODEL_SESSIONS
            or tuple(sorted(set(s07.model_session_dates))) != s07.model_session_dates
            or canonical_session_dates_sha256(s07.model_session_dates)
            != s07.model_session_dates_sha256):
        raise CompleteCasePanelError("S07 model calendar differs from exact 416")
    if (tuple(sorted(set(market.full_session_dates))) != market.full_session_dates
            or canonical_session_dates_sha256(market.full_session_dates)
            != market.full_session_calendar_sha256):
        raise CompleteCasePanelError("full-session calendar identity differs")


def materialize_complete_case_signal_panel(
    *, canonical_rows: tuple[tuple[object, ...], ...],
    market_binding: FrozenMarketBinding,
    s07_binding: S07SignalBinding,
    trusted_readback: TrustedReadbackBinding,
    serializer_binding: ImportedSerializerBinding,
) -> CompleteCaseSignalPanelEvidence:
    """Audit the immutable 474 upstream rows and derive the 472 complete panel."""
    _validate_bindings(market_binding, s07_binding, trusted_readback, serializer_binding)
    if type(canonical_rows) is not tuple or any(type(row) is not tuple for row in canonical_rows):
        raise CompleteCasePanelError("canonical rows must be an immutable tuple of tuples")
    digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
    try:
        digester.update_rows(canonical_rows)
        digest = digester.finalize()
    except Exception as exc:
        raise CompleteCasePanelError("canonical frozen row digest rejected") from exc
    if (digest.content_sha256 != market_binding.content_sha256
            or digest.ticker_universe_sha256 != market_binding.ticker_universe_sha256
            or digest.row_count != market_binding.row_count
            or digest.ticker_count != market_binding.ticker_count
            or digest.snapshot_id != market_binding.snapshot_id):
        raise CompleteCasePanelError("canonical frozen content identity differs")

    full_index = {session: index for index, session in enumerate(market_binding.full_session_dates)}
    try:
        model_indices = tuple(full_index[session] for session in s07_binding.model_session_dates)
    except KeyError as exc:
        raise CompleteCasePanelError("model session is absent from full calendar") from exc
    if (not model_indices or model_indices[0] == 0
            or any(right != left + 1 for left, right in zip(model_indices, model_indices[1:]))):
        raise CompleteCasePanelError("model calendar lacks one prior seed or is nonconsecutive")
    required_dates = (
        market_binding.full_session_dates[model_indices[0] - 1],
        *s07_binding.model_session_dates,
    )
    required_set = set(required_dates)
    adjusted_index = MARKET_DAILY_FEATURE_COLUMNS.index("adjusted_close")
    presence_rows: list[tuple[object, object, object]] = []
    prices: dict[tuple[str, str], float] = {}
    for row in canonical_rows:
        if len(row) != len(MARKET_DAILY_FEATURE_COLUMNS):
            raise CompleteCasePanelError("canonical row width differs")
        ticker, session = row[1], row[2]
        if session not in required_set:
            continue
        value = row[adjusted_index]
        presence_rows.append((ticker, session, value))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CompleteCasePanelError("required adjusted_close is nonnumeric")
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise CompleteCasePanelError("required adjusted_close is nonfinite/nonpositive")
        prices[(str(ticker), str(session))] = number
    audit = audit_complete_case_universe(
        upstream_tickers=s07_binding.tickers,
        required_session_dates=required_dates,
        canonical_presence_rows=tuple(presence_rows),
    )
    if len(audit.eligible_tickers) != EXPECTED_ELIGIBLE_TICKERS:
        raise CompleteCasePanelError("complete-case eligible universe differs from 472")
    returns: dict[str, tuple[float, ...]] = {}
    for ticker in audit.eligible_tickers:
        values = tuple(
            prices[(ticker, required_dates[index])]
            / prices[(ticker, required_dates[index - 1])] - 1.0
            for index in range(1, len(required_dates))
        )
        if len(values) != EXPECTED_MODEL_SESSIONS or any(not math.isfinite(x) for x in values):
            raise CompleteCasePanelError("derived complete-case return geometry differs")
        returns[ticker] = values
    panel = build_signal_panel(
        audit.eligible_tickers, s07_binding.model_session_dates, returns,
    )
    return CompleteCaseSignalPanelEvidence(
        contract_id=CONTRACT_ID,
        dataset_version=market_binding.dataset_version,
        snapshot_id=market_binding.snapshot_id,
        frozen_content_sha256=market_binding.content_sha256,
        upstream_universe_sha256=audit.upstream_universe_sha256,
        required_dates_sha256=audit.required_dates_sha256,
        presence_mask_sha256=audit.presence_mask_sha256,
        eligible_universe_sha256=audit.eligible_universe_sha256,
        exclusion_evidence_sha256=audit.exclusion_evidence_sha256,
        eligible_tickers=audit.eligible_tickers,
        model_session_dates=s07_binding.model_session_dates,
        shape=(EXPECTED_ELIGIBLE_TICKERS, EXPECTED_MODEL_SESSIONS),
        panel=panel,
        panel_sha256=panel.sha256,
        complete_case_audit=audit,
    )
