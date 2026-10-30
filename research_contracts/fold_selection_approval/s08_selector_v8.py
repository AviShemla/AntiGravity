"""Pure S08 v8 selection proposal for a frozen 472-ticker complete-case universe.

This module computes and audits research evidence only.  It has no database,
model-fitting, prediction, persistence, authorization, or operational surface.
The upstream 474-ticker dataset remains immutable; this successor binds a
presence-only eligible universe that excludes exactly FISV and SNDK.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
import hashlib
import json
import math
import struct
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

__all__ = (
    "SignalPanel", "Lineage", "Evidence", "CompleteRunResult",
    "SCIENTIFIC_CONTRACT_BYTES", "build_signal_panel", "audit_signal_panel",
    "evaluate_candidate", "audit_evidence", "select_complete_run",
    "audit_complete_run_result",
)

_OUTER = (
    (1, 0, 288, 289, 295, 296, 325),
    (2, 30, 318, 319, 325, 326, 355),
    (3, 60, 348, 349, 355, 356, 385),
    (4, 90, 378, 379, 385, 386, 415),
)
_INNER = (
    (1, 0, 132, 133, 139, 140, 191),
    (2, 0, 184, 185, 191, 192, 243),
    (3, 0, 236, 237, 243, 244, 288),
)
_TICKERS = 472
_SOURCE_CHOICES = 471
_LAGS = 7
_GROUP = _SOURCE_CHOICES * _LAGS
_PER_FOLD = _TICKERS * _GROUP
_TOTAL = 4 * _PER_FOLD
_GROUPS = 4 * _TICKERS
_MAX = 5 * _GROUPS
_OOS_OBSERVATIONS = 4 * _TICKERS * 30
_REQUIRED_PRICE_ROWS = 417
_EXCLUSIONS = (("FISV", 416), ("SNDK", 358))
_PANEL_CONTRACT = "S08_FROZEN_TURSO_COMPLETE_CASE_ADJUSTED_RETURN_PANEL_V2"
_REQUIRED_EXTERNAL_IDENTITIES = (
    "dataset_version", "snapshot_sha256", "frozen_dataset_sha256",
    "frozen_content_sha256", "readback_sha256", "calendar_sha256",
    "signal_panel_sha256", "eligible_universe_sha256",
    "presence_mask_sha256", "exclusion_manifest_sha256",
    "preregistration_sha256", "policy_sha256", "selector_code_sha256",
    "selector_release_sha256", "dependency_closure_sha256",
    "materializer_release_sha256", "materializer_evidence_sha256",
    "independent_review_event_sha256",
)


def _cj(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


_EXCLUSION_MANIFEST_BYTES = _cj({
    "contract": "presence-only-complete-case-exclusion-v1",
    "required_price_rows_per_ticker": _REQUIRED_PRICE_ROWS,
    "upstream_ticker_count": 474,
    "eligible_ticker_count": _TICKERS,
    "exclusions": [
        {"ticker": ticker, "observed_price_rows": rows,
         "reason": "INCOMPLETE_REQUIRED_417_DATE_PRESENCE"}
        for ticker, rows in _EXCLUSIONS
    ],
    "outcome_values_consulted": False,
    "imputation_count": 0,
})

SCIENTIFIC_CONTRACT_BYTES = _cj({
    "contract": "S08_NESTED_PREDICTIVE_SELECTION_V8",
    "scope": "SELECTION_ONLY_FOLD_LOCAL_OOS_RESEARCH",
    "upstream_dataset": "immutable 474-ticker dataset; never rewritten",
    "analysis_universe": {
        "rule": "presence-only symmetric complete case",
        "required_price_rows_per_ticker": _REQUIRED_PRICE_ROWS,
        "eligible_tickers": _TICKERS,
        "excluded": [{"ticker": t, "observed_price_rows": n} for t, n in _EXCLUSIONS],
        "exclusion_manifest_sha256": _sha(_EXCLUSION_MANIFEST_BYTES),
        "outcome_values_consulted": False,
        "imputation_count": 0,
        "roles": "same eligible set used for targets and sources",
    },
    "outer_geometry": [list(value) for value in _OUTER],
    "inner_expanding_geometry": [list(value) for value in _INNER],
    "signal": (
        "exact frozen Turso market-row adjusted_close; binary64 "
        "return[t]=adjusted_close[t]/adjusted_close[t-1]-1; 472 eligible "
        "tickers x 416 unique NYSE model sessions from exact 417-row "
        "presence evidence; reject missing duplicate nonfinite zero previous "
        "or imputation"
    ),
    "numeric_dependency": (
        "CPython 3.14.4; NumPy 2.4.6 and GCC 15.2.0 pinned in external "
        "release closure although this pure implementation uses stdlib; "
        "IEEE754 binary64 little-endian evidence"
    ),
    "materializer": (
        "canonical target-major/source-major/lag-major f64-le replay evidence; "
        "exact materializer release and independent materializer evidence "
        "required externally"
    ),
    "candidate_order": (
        "outer_fold ASC,target_rank ASC,source_rank ASC excluding self,"
        "lag ASC 1..7"
    ),
    "candidate_counts": {
        "per_fold": _PER_FOLD, "total": _TOTAL,
        "target_fold_groups": _GROUPS, "oos_observations": _OOS_OBSERVATIONS,
    },
    "ols": (
        "slope=(sum_xy-sum_x*sum_y/n)/(sum_x2-sum_x^2/n);"
        "intercept=mean_y-slope*mean_x"
    ),
    "direction": (
        "sign(prediction); prediction or actual zero uses training-majority; "
        "majority tie +1"
    ),
    "baselines": (
        "direction=training-majority rule evaluated on validation; "
        "return=training-mean evaluated on validation"
    ),
    "pooling": "row pooled 52+52+45",
    "skills": (
        "direction=model_accuracy-baseline_accuracy;"
        "return=1-model_MSE/baseline_MSE;"
        "baseline_MSE_zero=>return_skill_zero"
    ),
    "score": "(direction_skill+return_skill)/2",
    "gates": (
        "strict direction_skill>0 AND return_skill>0; any degenerate fit "
        "disqualifies"
    ),
    "model_depth": (
        "0..5 selected independent incoming source/lag edges per target/fold; "
        "no chain or layer semantics; no forced minimum; same source different "
        "lags allowed"
    ),
    "ranking": "score DESC then candidate ordinal ASC",
    "multiplicity": "NO_MULTIPLICITY_CONTROL_NO_FDR_CLAIM",
    "outer_evaluation_dependency": (
        "future separately approved single untouched outer evaluation; no "
        "retuning after inspection; excluded here"
    ),
    "required_external_approval_envelope_identities": list(
        _REQUIRED_EXTERNAL_IDENTITIES
    ),
    "downstream": (
        "ZERO selections before global closure; ZERO model fits predictions "
        "recommendations orders ETF priors trading email validation promotion "
        "and database writes"
    ),
    "terminal": "withhold all selected edges until exact 6224736-candidate global closure",
})


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class SignalPanel:
    tickers: tuple[str, ...]
    session_dates: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]
    sha256: str


@dataclass(frozen=True)
class Lineage:
    dataset_version: str
    snapshot_sha256: str
    frozen_dataset_sha256: str
    frozen_content_sha256: str
    readback_sha256: str
    calendar_sha256: str
    signal_panel_sha256: str
    eligible_universe_sha256: str
    presence_mask_sha256: str
    exclusion_manifest_sha256: str
    preregistration_sha256: str
    policy_sha256: str
    selector_code_sha256: str
    selector_release_sha256: str
    dependency_closure_sha256: str
    materializer_release_sha256: str
    materializer_evidence_sha256: str
    independent_review_event_sha256: str

    def fingerprint(self):
        return _sha(_cj(asdict(self)))


@dataclass(frozen=True)
class _Replay:
    inner_fold: int
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    train_dates: tuple[str, ...]
    validation_dates: tuple[str, ...]
    train_x_hex: str
    train_y_hex: str
    validation_x_hex: str
    actual_hex: str
    prediction_hex: str
    baseline_hex: str
    sum_x: float
    sum_y: float
    sum_x2: float
    sum_y2: float
    sum_xy: float
    intercept: float
    slope: float
    majority: int
    model_correct: int
    baseline_correct: int
    model_sse: float
    baseline_sse: float
    degenerate: bool
    chunk_sha256: str


@dataclass(frozen=True)
class Evidence:
    outer_fold: int
    ordinal: int
    source_rank: int
    source: str
    target_rank: int
    target: str
    lag: int
    lineage: Lineage
    lineage_fingerprint: str
    panel_sha256: str
    replay: tuple[_Replay, ...]
    direction_accuracy: float
    baseline_direction_accuracy: float
    direction_skill: float
    return_mse: float
    baseline_return_mse: float
    return_skill: float
    score: float
    qualified: bool
    evidence_sha256: str

    def _payload(self):
        result = asdict(self)
        result.pop("evidence_sha256")
        return result


@dataclass(frozen=True)
class _Selected:
    outer_fold: int
    target_rank: int
    target: str
    model_depth_rank: int
    ordinal: int
    evidence_sha256: str
    panel_sha256: str
    lineage_fingerprint: str


@dataclass(frozen=True)
class _Terminal:
    candidate_count: int
    group_count: int
    selection_count: int
    stream_sha256: str
    selection_manifest_sha256: str
    panel_sha256: str
    lineage_fingerprint: str
    scientific_contract_sha256: str
    terminal_sha256: str


@dataclass(frozen=True)
class CompleteRunResult:
    terminal: _Terminal
    selections: tuple[_Selected, ...]


def _f64(values):
    return b"".join(struct.pack("<d", float(value)) for value in values)


def _panel_raw(tickers, dates, rows):
    ticker_bytes = _cj(list(tickers))
    date_bytes = _cj(list(dates))
    return (
        b"V8PANEL\0" + struct.pack("<I", len(ticker_bytes)) + ticker_bytes
        + struct.pack("<I", len(date_bytes)) + date_bytes
        + b"".join(_f64(row) for row in rows)
    )


def _eligible_universe_sha256(tickers):
    return _sha(_cj({
        "contract": "s08-v8-symmetric-eligible-universe-v1",
        "tickers": list(tickers),
        "excluded": [ticker for ticker, _ in _EXCLUSIONS],
    }))


def build_signal_panel(
    tickers: tuple[str, ...], session_dates: tuple[str, ...],
    returns: Mapping[str, Sequence[float]],
) -> SignalPanel:
    if (
        len(tickers) != _TICKERS or len(set(tickers)) != _TICKERS
        or tuple(sorted(tickers)) != tickers
        or any(ticker in tickers for ticker, _ in _EXCLUSIONS)
    ):
        raise ContractError("exact sorted 472-ticker eligible universe required")
    if (
        len(session_dates) != 416 or len(set(session_dates)) != 416
        or tuple(sorted(session_dates)) != session_dates
    ):
        raise ContractError("exact 416 unique increasing dates required")
    try:
        parsed = tuple(date.fromisoformat(value) for value in session_dates)
    except ValueError as exc:
        raise ContractError("invalid session date") from exc
    if (
        tuple(value.isoformat() for value in parsed) != session_dates
        or set(returns) != set(tickers)
    ):
        raise ContractError("calendar or ticker family mismatch")
    rows = []
    for ticker in tickers:
        source_row = tuple(returns[ticker])
        if any(type(value) is bool for value in source_row):
            raise ContractError("panel row bool invalid")
        row = tuple(float(value) for value in source_row)
        if len(row) != 416 or any(
            not math.isfinite(value) or value <= -1 for value in row
        ):
            raise ContractError("panel row invalid")
        rows.append(row)
    frozen_rows = tuple(rows)
    return SignalPanel(
        tickers, session_dates, frozen_rows,
        _sha(_panel_raw(tickers, session_dates, frozen_rows)),
    )


def audit_signal_panel(panel: SignalPanel) -> None:
    rebuilt = build_signal_panel(
        panel.tickers, panel.session_dates,
        MappingProxyType(dict(zip(panel.tickers, panel.rows))),
    )
    if rebuilt != panel:
        raise ContractError("panel identity mismatch")


def _ord(target_rank: int, source_rank: int, lag: int) -> int:
    if (
        type(target_rank) is not int or type(source_rank) is not int
        or type(lag) is not int or not 0 <= target_rank < _TICKERS
        or not 0 <= source_rank < _TICKERS or target_rank == source_rank
        or not 1 <= lag <= _LAGS
    ):
        raise ContractError("candidate coordinates invalid")
    compressed_source = source_rank if source_rank < target_rank else source_rank - 1
    return target_rank * _GROUP + compressed_source * _LAGS + lag - 1


def _coordinates(ordinal: int) -> tuple[int, int, int]:
    if type(ordinal) is not int or not 0 <= ordinal < _PER_FOLD:
        raise ContractError("candidate ordinal outside complete family")
    target_rank, local = divmod(ordinal, _GROUP)
    compressed_source, lag0 = divmod(local, _LAGS)
    source_rank = (
        compressed_source if compressed_source < target_rank
        else compressed_source + 1
    )
    return target_rank, source_rank, lag0 + 1


def _fit(x_values, y_values):
    count = len(x_values)
    sum_x = math.fsum(x_values)
    sum_y = math.fsum(y_values)
    sum_x2 = math.fsum(value * value for value in x_values)
    sum_y2 = math.fsum(value * value for value in y_values)
    sum_xy = math.fsum(
        x_value * y_value for x_value, y_value in zip(x_values, y_values)
    )
    variance_x = sum_x2 - sum_x * sum_x / count
    mean_y = sum_y / count
    if variance_x <= 0:
        return mean_y, 0.0, sum_x, sum_y, sum_x2, sum_y2, sum_xy, True
    slope = (sum_xy - sum_x * sum_y / count) / variance_x
    return (
        mean_y - slope * sum_x / count, slope, sum_x, sum_y, sum_x2,
        sum_y2, sum_xy, False,
    )


def _direction(value, majority):
    return 1 if value > 0 else -1 if value < 0 else majority


def _lineage_ok(lineage: Lineage, panel: SignalPanel) -> None:
    values = asdict(lineage)
    if (
        type(lineage.dataset_version) is not str or not lineage.dataset_version
        or any(
            len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)
            for key, value in values.items() if key != "dataset_version"
        )
    ):
        raise ContractError("lineage identity invalid")
    if (
        lineage.signal_panel_sha256 != panel.sha256
        or lineage.calendar_sha256 != _sha(_cj(list(panel.session_dates)))
        or lineage.eligible_universe_sha256 != _eligible_universe_sha256(panel.tickers)
        or lineage.exclusion_manifest_sha256 != _sha(_EXCLUSION_MANIFEST_BYTES)
    ):
        raise ContractError("lineage panel/calendar/eligibility mismatch")


def evaluate_candidate(
    *, outer_fold: int, source_rank: int, source: str, target_rank: int,
    target: str, lag: int, panel: SignalPanel, lineage: Lineage,
) -> Evidence:
    audit_signal_panel(panel)
    _lineage_ok(lineage, panel)
    outer = next((value for value in _OUTER if value[0] == outer_fold), None)
    if (
        outer is None or panel.tickers[source_rank] != source
        or panel.tickers[target_rank] != target
    ):
        raise ContractError("fold or ticker mapping invalid")
    ordinal = _ord(target_rank, source_rank, lag)
    outer_train_start, outer_train_end, outer_validation_start = (
        outer[1], outer[2], outer[5]
    )
    source_values = panel.rows[source_rank]
    target_values = panel.rows[target_rank]
    replays = []
    any_degenerate = False
    for inner in _INNER:
        train_start = outer_train_start + inner[1]
        train_end = outer_train_start + inner[2]
        purge_start = outer_train_start + inner[3]
        purge_end = outer_train_start + inner[4]
        validation_start = outer_train_start + inner[5]
        validation_end = outer_train_start + inner[6]
        if not (
            train_start <= train_end < purge_start <= purge_end
            < validation_start <= validation_end <= outer_train_end
            < outer_validation_start
        ):
            raise ContractError("geometry violation")
        train_indices = tuple(range(train_start + lag, train_end + 1))
        validation_indices = tuple(range(validation_start, validation_end + 1))
        train_x = tuple(source_values[index - lag] for index in train_indices)
        train_y = tuple(target_values[index] for index in train_indices)
        validation_x = tuple(
            source_values[index - lag] for index in validation_indices
        )
        actual = tuple(target_values[index] for index in validation_indices)
        if len(train_x) < 126 or any(
            not math.isfinite(value)
            for value in train_x + train_y + validation_x + actual
        ):
            raise ContractError("aligned data violation")
        (
            intercept, slope, sum_x, sum_y, sum_x2, sum_y2, sum_xy,
            degenerate,
        ) = _fit(train_x, train_y)
        any_degenerate |= degenerate
        majority = (
            1 if sum(value > 0 for value in train_y)
            >= sum(value < 0 for value in train_y) else -1
        )
        prediction = tuple(intercept + slope * value for value in validation_x)
        baseline = (sum_y / len(train_y),) * len(actual)
        model_correct = sum(
            _direction(predicted, majority) == _direction(observed, majority)
            for predicted, observed in zip(prediction, actual)
        )
        baseline_correct = sum(
            majority == _direction(observed, majority) for observed in actual
        )
        model_sse = math.fsum(
            (observed - predicted) ** 2
            for observed, predicted in zip(actual, prediction)
        )
        baseline_sse = math.fsum(
            (observed - predicted) ** 2
            for observed, predicted in zip(actual, baseline)
        )
        parts = (
            inner[0], train_indices, validation_indices,
            tuple(panel.session_dates[index] for index in train_indices),
            tuple(panel.session_dates[index] for index in validation_indices),
            _f64(train_x).hex(), _f64(train_y).hex(),
            _f64(validation_x).hex(), _f64(actual).hex(),
            _f64(prediction).hex(), _f64(baseline).hex(), sum_x, sum_y,
            sum_x2, sum_y2, sum_xy, intercept, slope, majority,
            model_correct, baseline_correct, model_sse, baseline_sse,
            degenerate,
        )
        replays.append(_Replay(*parts, _sha(_cj(parts))))
    validation_count = sum(len(item.validation_indices) for item in replays)
    model_accuracy = sum(item.model_correct for item in replays) / validation_count
    baseline_accuracy = (
        sum(item.baseline_correct for item in replays) / validation_count
    )
    model_mse = math.fsum(item.model_sse for item in replays) / validation_count
    baseline_mse = (
        math.fsum(item.baseline_sse for item in replays) / validation_count
    )
    direction_skill = model_accuracy - baseline_accuracy
    return_skill = 0.0 if baseline_mse <= 0 else 1 - model_mse / baseline_mse
    qualified = not any_degenerate and direction_skill > 0 and return_skill > 0
    empty = Evidence(
        outer_fold, ordinal, source_rank, source, target_rank, target, lag,
        lineage, lineage.fingerprint(), panel.sha256, tuple(replays),
        model_accuracy, baseline_accuracy, direction_skill, model_mse,
        baseline_mse, return_skill, (direction_skill + return_skill) / 2,
        qualified, "",
    )
    return replace(empty, evidence_sha256=_sha(_cj(empty._payload())))


def audit_evidence(evidence: Evidence, panel: SignalPanel) -> None:
    audit_signal_panel(panel)
    _lineage_ok(evidence.lineage, panel)
    if (
        evidence.evidence_sha256 != _sha(_cj(evidence._payload()))
        or evidence.lineage_fingerprint != evidence.lineage.fingerprint()
        or evidence.panel_sha256 != panel.sha256
        or evidence.ordinal != _ord(
            evidence.target_rank, evidence.source_rank, evidence.lag
        )
        or panel.tickers[evidence.source_rank] != evidence.source
        or panel.tickers[evidence.target_rank] != evidence.target
    ):
        raise ContractError("evidence identity mismatch")
    rebuilt = evaluate_candidate(
        outer_fold=evidence.outer_fold, source_rank=evidence.source_rank,
        source=evidence.source, target_rank=evidence.target_rank,
        target=evidence.target, lag=evidence.lag, panel=panel,
        lineage=evidence.lineage,
    )
    if rebuilt != evidence:
        raise ContractError("evidence replay mismatch")
    source_values = panel.rows[evidence.source_rank]
    target_values = panel.rows[evidence.target_rank]
    for replay in evidence.replay:
        if (
            replay.train_x_hex != _f64(tuple(
                source_values[index - evidence.lag]
                for index in replay.train_indices
            )).hex()
            or replay.train_y_hex != _f64(tuple(
                target_values[index] for index in replay.train_indices
            )).hex()
            or replay.validation_x_hex != _f64(tuple(
                source_values[index - evidence.lag]
                for index in replay.validation_indices
            )).hex()
            or replay.actual_hex != _f64(tuple(
                target_values[index] for index in replay.validation_indices
            )).hex()
        ):
            raise ContractError("panel disconnect")


def select_complete_run(
    rows: Iterable[Evidence], panel: SignalPanel,
) -> CompleteRunResult:
    audit_signal_panel(panel)
    fold = 1
    ordinal = 0
    count = 0
    groups = 0
    buffer = []
    held = []
    stream = hashlib.sha256()
    lineage_fingerprint = None

    def emit_audited_group():
        if len(buffer) != _GROUP:
            raise ContractError("incomplete group")
        first = buffer[0]
        target_rank = first.target_rank
        seen = bytearray(_GROUP)
        for candidate in buffer:
            if (
                candidate.outer_fold, candidate.target_rank,
                candidate.lineage_fingerprint,
            ) != (
                first.outer_fold, target_rank, first.lineage_fingerprint,
            ):
                raise ContractError("group mixing")
            local = candidate.ordinal - target_rank * _GROUP
            if not 0 <= local < _GROUP or seen[local]:
                raise ContractError("duplicate/out-of-group")
            seen[local] = 1
        if not all(seen):
            raise ContractError("missing group candidate")
        qualified = sorted(
            (candidate for candidate in buffer if candidate.qualified),
            key=lambda value: (-value.score, value.ordinal),
        )[:5]
        return tuple(
            _Selected(
                candidate.outer_fold, candidate.target_rank, candidate.target,
                depth, candidate.ordinal, candidate.evidence_sha256,
                candidate.panel_sha256, candidate.lineage_fingerprint,
            )
            for depth, candidate in enumerate(qualified, 1)
        )

    for evidence in rows:
        if (evidence.outer_fold, evidence.ordinal) != (fold, ordinal):
            raise ContractError("noncanonical missing/duplicate stream")
        audit_evidence(evidence, panel)
        if lineage_fingerprint is None:
            lineage_fingerprint = evidence.lineage_fingerprint
        if evidence.lineage_fingerprint != lineage_fingerprint:
            raise ContractError("global lineage mixing")
        raw = _cj({**evidence._payload(), "evidence_sha256": evidence.evidence_sha256})
        stream.update(struct.pack("<I", len(raw)))
        stream.update(raw)
        buffer.append(evidence)
        count += 1
        ordinal += 1
        if ordinal % _GROUP == 0:
            held.extend(emit_audited_group())
            buffer = []
            groups += 1
        if ordinal == _PER_FOLD:
            fold += 1
            ordinal = 0
    if (
        count != _TOTAL or groups != _GROUPS or fold != 5 or ordinal
        or buffer
    ):
        raise ContractError("incomplete global closure")
    if len(held) > _MAX:
        raise ContractError("depth cardinality violation")
    manifest = _cj([asdict(item) for item in held])
    core = {
        "candidate_count": count,
        "group_count": groups,
        "selection_count": len(held),
        "stream_sha256": stream.hexdigest(),
        "selection_manifest_sha256": _sha(manifest),
        "panel_sha256": panel.sha256,
        "lineage_fingerprint": lineage_fingerprint,
        "scientific_contract_sha256": _sha(SCIENTIFIC_CONTRACT_BYTES),
    }
    terminal = _Terminal(**core, terminal_sha256=_sha(_cj(core)))
    return CompleteRunResult(terminal, tuple(held))


def audit_complete_run_result(
    result: CompleteRunResult, rows: Iterable[Evidence], panel: SignalPanel,
) -> None:
    if (
        type(result) is not CompleteRunResult
        or type(result.terminal) is not _Terminal
        or type(result.selections) is not tuple
    ):
        raise ContractError("complete-run result type invalid")
    audit_signal_panel(panel)
    terminal = result.terminal
    core = asdict(terminal)
    claimed_terminal_sha = core.pop("terminal_sha256")
    if claimed_terminal_sha != _sha(_cj(core)):
        raise ContractError("terminal digest mismatch")
    if (
        terminal.panel_sha256 != panel.sha256
        or terminal.scientific_contract_sha256 != _sha(SCIENTIFIC_CONTRACT_BYTES)
    ):
        raise ContractError("terminal panel/scientific contract mismatch")
    manifest = _cj([asdict(selection) for selection in result.selections])
    if (
        terminal.selection_manifest_sha256 != _sha(manifest)
        or terminal.selection_count != len(result.selections)
    ):
        raise ContractError("selection manifest mismatch")
    seen = set()
    depth_by_group = {}
    for selection in result.selections:
        if (
            type(selection) is not _Selected
            or selection.panel_sha256 != panel.sha256
            or selection.lineage_fingerprint != terminal.lineage_fingerprint
        ):
            raise ContractError("selection identity mismatch")
        key = (selection.outer_fold, selection.target_rank)
        depth_by_group[key] = depth_by_group.get(key, 0) + 1
        if (
            selection.model_depth_rank != depth_by_group[key]
            or selection.model_depth_rank > 5
            or (selection.outer_fold, selection.ordinal) in seen
        ):
            raise ContractError("selection depth/order/uniqueness mismatch")
        seen.add((selection.outer_fold, selection.ordinal))
    rebuilt = select_complete_run(rows, panel)
    if rebuilt != result:
        raise ContractError("complete-run source replay mismatch")
