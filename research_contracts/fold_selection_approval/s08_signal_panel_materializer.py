"""Pure read-only split-adjusted signal-panel materializer.

All rows and trust metadata are injected.  The module performs no I/O, network,
database, process, model, selection, or persistence operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import math
import re
import struct

from oracle_research_dataset_serializers import (  # type: ignore[import-not-found]
    MARKET_DAILY_FEATURE_COLUMNS,
    MarketDatasetStreamingDigester,
)


CONTRACT_ID = "codex-oracle-selector-v7-split-adjusted-panel-v1"
PANEL_MAGIC = b"V7PANEL\0"
AUTHENTICITY_STATUS = "CLAIMED_UNVERIFIED_EXTERNAL_APPROVAL_ENVELOPE_REQUIRED"
EXPECTED_TICKERS = 474
EXPECTED_MODEL_SESSIONS = 416
FLOAT_CONTRACT = "IEEE754_BINARY64_LITTLE_ENDIAN_TICKER_MAJOR"
SIGNAL_CONTRACT = (
    "return[t]=adjusted_close[t]/adjusted_close[immediately_previous_full_nyse_session]-1;"
    "no missing duplicate nonfinite nonpositive or imputed values"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SignalPanelError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def canonical_session_dates_sha256(values: tuple[str, ...]) -> str:
    return _canonical_sha256(list(values))


def canonical_ticker_list_sha256(values: tuple[str, ...]) -> str:
    return _canonical_sha256(list(values))


@dataclass(frozen=True)
class FrozenMarketBinding:
    dataset_version: str
    snapshot_id: str
    content_sha256: str
    ticker_universe_sha256: str
    row_count: int
    ticker_count: int
    full_session_dates: tuple[str, ...]
    full_session_calendar_sha256: str
    upstream_imputation_count: int
    binding_artifact_sha256: str


@dataclass(frozen=True)
class S07SignalBinding:
    s07_raw_sha256: str
    frozen_content_sha256: str
    model_session_dates: tuple[str, ...]
    model_session_dates_sha256: str
    tickers: tuple[str, ...]
    ticker_list_sha256: str
    signal_contract: str = SIGNAL_CONTRACT
    float_contract: str = FLOAT_CONTRACT


@dataclass(frozen=True)
class TrustedReadbackBinding:
    dataset_version: str
    snapshot_id: str
    frozen_content_sha256: str
    readback_evidence_sha256: str


@dataclass(frozen=True)
class ImportedSerializerBinding:
    serializer_identity: str
    serializer_release_sha256: str
    serializer_source_sha256: str
    feature_columns_sha256: str


@dataclass(frozen=True)
class ImmutableSignalPanel:
    contract_id: str
    dataset_version: str
    snapshot_id: str
    s07_raw_sha256: str
    frozen_content_sha256: str
    ticker_universe_sha256: str
    full_session_calendar_sha256: str
    model_session_dates_sha256: str
    ticker_list_sha256: str
    tickers: tuple[str, ...]
    model_session_dates: tuple[str, ...]
    shape: tuple[int, int]
    ticker_major_f64le: bytes
    canonical_panel_bytes: bytes
    panel_sha256: str
    claimed_readback_evidence_sha256: str
    claimed_serializer_identity: str
    claimed_serializer_release_sha256: str
    claimed_serializer_source_sha256: str
    claimed_serializer_feature_columns_sha256: str
    claimed_zero_imputation_evidence_sha256: str
    claimed_s07_evidence_sha256: str
    claimed_full_calendar_evidence_sha256: str
    authenticity_status: str = AUTHENTICITY_STATUS
    execution_authorized: bool = False
    signal_contract: str = SIGNAL_CONTRACT
    float_contract: str = FLOAT_CONTRACT
    immutable: bool = True
    database_accessed: bool = False
    database_writes: int = 0
    downstream_outputs: int = 0


def binding_artifact_sha256(binding: FrozenMarketBinding) -> str:
    payload = {
        "dataset_version": binding.dataset_version,
        "snapshot_id": binding.snapshot_id,
        "content_sha256": binding.content_sha256,
        "ticker_universe_sha256": binding.ticker_universe_sha256,
        "row_count": binding.row_count,
        "ticker_count": binding.ticker_count,
        "full_session_dates": list(binding.full_session_dates),
        "full_session_calendar_sha256": binding.full_session_calendar_sha256,
        "upstream_imputation_count": binding.upstream_imputation_count,
    }
    return _canonical_sha256(payload)


def trusted_readback_artifact_sha256(binding: TrustedReadbackBinding) -> str:
    return _canonical_sha256({
        "dataset_version": binding.dataset_version,
        "snapshot_id": binding.snapshot_id,
        "frozen_content_sha256": binding.frozen_content_sha256,
    })


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def selector_v7_panel_bytes(tickers: tuple[str, ...], dates: tuple[str, ...],
                            ticker_major_f64le: bytes) -> bytes:
    ticker_json = _canonical_json_bytes(list(tickers))
    date_json = _canonical_json_bytes(list(dates))
    return (PANEL_MAGIC + struct.pack("<I", len(ticker_json)) + ticker_json
            + struct.pack("<I", len(date_json)) + date_json
            + ticker_major_f64le)


def _sha(value: object, label: str) -> str:
    if type(value) is not str or not SHA256.fullmatch(value):
        raise SignalPanelError(f"{label} must be a lowercase SHA-256")
    return value


def _date_text(value: object) -> str:
    if isinstance(value, datetime):
        raise SignalPanelError("market session must be a date, not timestamp")
    if isinstance(value, date):
        return value.isoformat()
    if type(value) is str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise SignalPanelError("market session is not canonical ISO date") from exc
        if parsed.isoformat() == value:
            return value
    raise SignalPanelError("market session is not canonical ISO date")


def _validate_calendar(values: tuple[str, ...], label: str) -> None:
    if type(values) is not tuple or not values:
        raise SignalPanelError(f"{label} is absent")
    parsed = tuple(_date_text(value) for value in values)
    if parsed != values or tuple(sorted(set(values))) != values:
        raise SignalPanelError(f"{label} is duplicated, unordered, or noncanonical")


def materialize_signal_panel(
    *,
    canonical_rows: tuple[tuple[object, ...], ...],
    market_binding: FrozenMarketBinding,
    s07_binding: S07SignalBinding,
    trusted_readback: TrustedReadbackBinding,
    serializer_binding: ImportedSerializerBinding,
) -> ImmutableSignalPanel:
    if type(canonical_rows) is not tuple or not canonical_rows:
        raise SignalPanelError("full canonical row stream is absent or mutable")
    if any(type(row) is not tuple for row in canonical_rows):
        raise SignalPanelError("canonical rows must be immutable positional tuples")
    if (type(market_binding) is not FrozenMarketBinding or type(s07_binding) is not S07SignalBinding
            or type(trusted_readback) is not TrustedReadbackBinding
            or type(serializer_binding) is not ImportedSerializerBinding):
        raise SignalPanelError("binding evidence type differs")
    for value, label in (
        (market_binding.dataset_version, "claimed market dataset_version"),
        (trusted_readback.dataset_version, "claimed readback dataset_version"),
        (market_binding.snapshot_id, "claimed market snapshot_id"),
        (trusted_readback.snapshot_id, "claimed readback snapshot_id"),
        (serializer_binding.serializer_identity, "claimed serializer identity"),
    ):
        if type(value) is not str or not value:
            raise SignalPanelError(f"{label} must be an exact nonempty str")
    for value, label in (
        (market_binding.content_sha256, "market content"),
        (market_binding.ticker_universe_sha256, "market ticker universe"),
        (market_binding.full_session_calendar_sha256, "full calendar"),
        (market_binding.binding_artifact_sha256, "market binding artifact"),
        (s07_binding.s07_raw_sha256, "S07 raw evidence"),
        (s07_binding.frozen_content_sha256, "S07 frozen content"),
        (s07_binding.model_session_dates_sha256, "S07 model calendar"),
        (s07_binding.ticker_list_sha256, "S07 ticker list"),
        (trusted_readback.frozen_content_sha256, "trusted readback content"),
        (trusted_readback.readback_evidence_sha256, "trusted readback evidence"),
        (serializer_binding.serializer_release_sha256, "serializer release"),
        (serializer_binding.serializer_source_sha256, "serializer source"),
        (serializer_binding.feature_columns_sha256, "serializer columns"),
    ):
        _sha(value, label)
    if binding_artifact_sha256(market_binding) != market_binding.binding_artifact_sha256:
        raise SignalPanelError("market binding artifact digest differs")
    if trusted_readback_artifact_sha256(trusted_readback) != trusted_readback.readback_evidence_sha256:
        raise SignalPanelError("trusted readback evidence digest differs")
    if (market_binding.dataset_version != trusted_readback.dataset_version
            or market_binding.snapshot_id != trusted_readback.snapshot_id
            or market_binding.content_sha256 != trusted_readback.frozen_content_sha256):
        raise SignalPanelError("dataset version/snapshot/content differs from trusted readback")
    if serializer_binding.feature_columns_sha256 != _canonical_sha256(list(MARKET_DAILY_FEATURE_COLUMNS)):
        raise SignalPanelError("imported serializer feature-column identity differs")
    if market_binding.upstream_imputation_count != 0:
        raise SignalPanelError("upstream binding reports imputed market rows")
    if s07_binding.signal_contract != SIGNAL_CONTRACT or s07_binding.float_contract != FLOAT_CONTRACT:
        raise SignalPanelError("S07 signal/float contract differs from selector v5")
    if market_binding.content_sha256 != s07_binding.frozen_content_sha256:
        raise SignalPanelError("market content differs from exact S07 frozen content")

    _validate_calendar(market_binding.full_session_dates, "full NYSE calendar")
    _validate_calendar(s07_binding.model_session_dates, "S07 model calendar")
    if len(s07_binding.model_session_dates) != EXPECTED_MODEL_SESSIONS:
        raise SignalPanelError("S07 model calendar does not contain exactly 416 sessions")
    if canonical_session_dates_sha256(market_binding.full_session_dates) != market_binding.full_session_calendar_sha256:
        raise SignalPanelError("full NYSE calendar digest differs")
    if canonical_session_dates_sha256(s07_binding.model_session_dates) != s07_binding.model_session_dates_sha256:
        raise SignalPanelError("S07 model calendar digest differs")
    tickers = s07_binding.tickers
    if (type(tickers) is not tuple or len(tickers) != EXPECTED_TICKERS
            or tuple(sorted(set(tickers))) != tickers):
        raise SignalPanelError("S07 ticker universe is not exact sorted 474")
    if canonical_ticker_list_sha256(tickers) != s07_binding.ticker_list_sha256:
        raise SignalPanelError("S07 ticker-list digest differs")

    digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
    try:
        digester.update_rows(canonical_rows)
        digests = digester.finalize()
    except Exception as exc:
        raise SignalPanelError("canonical row streaming digest rejected input") from exc
    if (
        digests.content_sha256 != market_binding.content_sha256
        or digests.ticker_universe_sha256 != market_binding.ticker_universe_sha256
        or digests.row_count != market_binding.row_count
        or digests.ticker_count != market_binding.ticker_count
        or digests.snapshot_id != market_binding.snapshot_id
        or digests.first_session_date.isoformat() != market_binding.full_session_dates[0]
        or digests.last_session_date.isoformat() != market_binding.full_session_dates[-1]
    ):
        raise SignalPanelError("canonical row content/ticker/count/snapshot readback differs")
    if market_binding.ticker_count != EXPECTED_TICKERS:
        raise SignalPanelError("canonical market ticker count differs from 474")
    adjusted_index = MARKET_DAILY_FEATURE_COLUMNS.index("adjusted_close")
    full_sessions = set(market_binding.full_session_dates)
    ticker_set = set(tickers)
    observed_tickers: set[str] = set()
    required_dates: set[str]
    full_index = {session: index for index, session in enumerate(market_binding.full_session_dates)}
    try:
        model_indices = tuple(full_index[session] for session in s07_binding.model_session_dates)
    except KeyError as exc:
        raise SignalPanelError("S07 model date is absent from the full NYSE calendar") from exc
    if model_indices[0] == 0:
        raise SignalPanelError("first S07 model date lacks an immediately preceding full NYSE session")
    if any(right != left + 1 for left, right in zip(model_indices, model_indices[1:])):
        raise SignalPanelError("S07 model dates are not consecutive full NYSE sessions")
    required_dates = {
        market_binding.full_session_dates[model_indices[0] - 1],
        *s07_binding.model_session_dates,
    }
    adjusted: dict[tuple[str, str], float] = {}
    for row in canonical_rows:
        ticker = row[1]
        session = _date_text(row[2])
        if ticker not in ticker_set:
            raise SignalPanelError("canonical row ticker differs from exact S07 universe")
        if session not in full_sessions:
            raise SignalPanelError("canonical row date is outside the frozen full NYSE calendar")
        observed_tickers.add(ticker)
        if session not in required_dates:
            continue
        value = row[adjusted_index]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SignalPanelError("adjusted_close is missing or nonnumeric; no imputation allowed")
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise SignalPanelError("adjusted_close must be finite and positive; no imputation allowed")
        key = (ticker, session)
        if key in adjusted:
            raise SignalPanelError("required signal subset contains a duplicate ticker/date")
        adjusted[key] = number
    if observed_tickers != ticker_set:
        raise SignalPanelError("canonical row ticker coverage differs from exact S07 universe")
    expected_required_count = EXPECTED_TICKERS * (EXPECTED_MODEL_SESSIONS + 1)
    if len(adjusted) != expected_required_count:
        raise SignalPanelError("required 474-by-417 signal subset is incomplete")

    raw = bytearray()
    for ticker in tickers:
        for index in model_indices:
            current = adjusted[(ticker, market_binding.full_session_dates[index])]
            previous = adjusted[(ticker, market_binding.full_session_dates[index - 1])]
            value = current / previous - 1.0
            if not math.isfinite(value):
                raise SignalPanelError("derived split-adjusted return is nonfinite")
            raw.extend(struct.pack("<d", value))
    immutable_raw = bytes(raw)
    if len(immutable_raw) != EXPECTED_TICKERS * EXPECTED_MODEL_SESSIONS * 8:
        raise SignalPanelError("float64-le panel byte geometry differs")
    canonical_panel = selector_v7_panel_bytes(tickers, s07_binding.model_session_dates,
                                              immutable_raw)
    return ImmutableSignalPanel(
        contract_id=CONTRACT_ID,
        dataset_version=market_binding.dataset_version,
        snapshot_id=market_binding.snapshot_id,
        s07_raw_sha256=s07_binding.s07_raw_sha256,
        frozen_content_sha256=market_binding.content_sha256,
        ticker_universe_sha256=market_binding.ticker_universe_sha256,
        full_session_calendar_sha256=market_binding.full_session_calendar_sha256,
        model_session_dates_sha256=s07_binding.model_session_dates_sha256,
        ticker_list_sha256=s07_binding.ticker_list_sha256,
        tickers=tickers,
        model_session_dates=s07_binding.model_session_dates,
        shape=(EXPECTED_TICKERS, EXPECTED_MODEL_SESSIONS),
        ticker_major_f64le=immutable_raw,
        canonical_panel_bytes=canonical_panel,
        panel_sha256=hashlib.sha256(canonical_panel).hexdigest(),
        claimed_readback_evidence_sha256=trusted_readback.readback_evidence_sha256,
        claimed_serializer_identity=serializer_binding.serializer_identity,
        claimed_serializer_release_sha256=serializer_binding.serializer_release_sha256,
        claimed_serializer_source_sha256=serializer_binding.serializer_source_sha256,
        claimed_serializer_feature_columns_sha256=serializer_binding.feature_columns_sha256,
        claimed_zero_imputation_evidence_sha256=market_binding.binding_artifact_sha256,
        claimed_s07_evidence_sha256=s07_binding.s07_raw_sha256,
        claimed_full_calendar_evidence_sha256=market_binding.full_session_calendar_sha256,
    )
