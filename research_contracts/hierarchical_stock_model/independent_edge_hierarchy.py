"""Leakage-safe independent-edge selection and hierarchical fitter boundary.

The module is pure: it has no filesystem, network, database, process, PyMC,
recommendation, order, ETF, or trading operation.  It prepares exact
percentage-unit matrices and validates an injected hierarchical posterior
backend.  The backend is mandatory and cannot be selected implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import atanh, erfc, isfinite, sqrt
from typing import Callable, Mapping, Sequence
import hashlib
import json
import re

import numpy as np


TOPOLOGY = "INDEPENDENT_TICKER_LAG_EDGES_PARTIAL_POOLING"
CLAIM_SCOPE = "OBSERVATIONAL_PREDICTIVE_ASSOCIATION_NOT_CAUSAL"
RETURN_UNIT = "PERCENT"
EXPECTED_LAGS = tuple(range(1, 8))
EXPECTED_DEPTHS = tuple(range(1, 6))
MINIMUM_FIT_OBSERVATIONS = 126
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class HierarchicalContractError(RuntimeError):
    """Raised before a backend call when selection or fit evidence is unsafe."""


def _canonical(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {name: _canonical(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def canonical_sha256(value: object) -> str:
    try:
        raw = json.dumps(
            _canonical(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise HierarchicalContractError("evidence is non-canonical or non-finite") from exc
    return hashlib.sha256(raw).hexdigest()


def _safe_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise HierarchicalContractError(f"{label} is missing or unsafe")


@dataclass(frozen=True)
class HistoricalReturnPanel:
    snapshot_id: str
    snapshot_sha256: str
    tickers: tuple[str, ...]
    session_dates: tuple[date, ...]
    returns_pct: np.ndarray


@dataclass(frozen=True)
class EdgeSelectionPolicy:
    candidate_lags: tuple[int, ...] = EXPECTED_LAGS
    candidate_depths: tuple[int, ...] = EXPECTED_DEPTHS
    minimum_fit_observations: int = MINIMUM_FIT_OBSERVATIONS
    fdr_alpha: float = 0.05
    association_test: str = "FISHER_Z_TWO_SIDED_APPROXIMATION"
    multiple_testing_method: str = "BENJAMINI_HOCHBERG_GLOBAL_FAMILY"
    topology: str = TOPOLOGY
    claim_scope: str = CLAIM_SCOPE


@dataclass(frozen=True)
class EdgeHypothesis:
    target_ticker: str
    source_ticker: str
    lag: int
    aligned_observations: int
    correlation: float
    p_value: float
    q_value: float


@dataclass(frozen=True)
class TargetEdgeSet:
    target_ticker: str
    selected_depth: int
    edges: tuple[EdgeHypothesis, ...]


@dataclass(frozen=True)
class EdgeSelectionArtifact:
    selection_id: str
    panel_snapshot_id: str
    panel_snapshot_sha256: str
    selection_end_ordinal: int
    selection_end_date: date
    policy: EdgeSelectionPolicy
    hypothesis_count: int
    target_edge_sets: tuple[TargetEdgeSet, ...]
    all_hypotheses: tuple[EdgeHypothesis, ...]
    training_only: bool = True
    forced_chain: bool = False
    return_unit: str = RETURN_UNIT


@dataclass(frozen=True)
class TargetDesignMatrix:
    ticker: str
    feature_names: tuple[str, ...]
    edge_identities: tuple[tuple[str, int], ...]
    training_dates: tuple[date, ...]
    x_train: np.ndarray
    y_direction: np.ndarray
    y_return_pct: np.ndarray
    x_predict: np.ndarray
    train_mean: np.ndarray
    train_scale: np.ndarray


@dataclass(frozen=True)
class HierarchicalFitRequest:
    model_run_id: str
    selection_id: str
    panel_snapshot_id: str
    panel_snapshot_sha256: str
    source_session_date: date
    prediction_date: date
    model_topology: str
    hierarchy: str
    graph_contract_sha256: str
    preregistered_model_config_sha256: str
    preregistered_sampler_sha256: str
    candidate_lags: tuple[int, ...]
    candidate_depths: tuple[int, ...]
    target_matrices: tuple[TargetDesignMatrix, ...]
    return_unit: str = RETURN_UNIT
    training_only_selection: bool = True
    research_only: bool = True
    persist_predictions: bool = False
    create_recommendations: bool = False
    create_orders: bool = False
    create_etf_outputs: bool = False
    activate_trading: bool = False


@dataclass(frozen=True)
class SamplerDiagnosticsEvidence:
    chains: int
    draws: int
    tune: int
    max_rhat: float
    min_bulk_ess: float
    min_tail_ess: float
    bfmi_min: float
    divergences: int
    max_treedepth_fraction: float


@dataclass(frozen=True)
class CanonicalPercentPosterior:
    ticker: str
    probability_up_mean: float
    probability_up_std: float
    probability_up_q05: float
    probability_up_q95: float
    expected_return_pct_mean: float
    expected_return_pct_std: float
    predictive_risk_pct: float
    diagnostics: SamplerDiagnosticsEvidence


@dataclass(frozen=True)
class HierarchicalBackendResult:
    model_run_id: str
    selection_id: str
    model_topology: str
    hierarchy: str
    graph_contract_sha256: str
    preregistered_model_config_sha256: str
    preregistered_sampler_sha256: str
    posterior_by_ticker: Mapping[str, CanonicalPercentPosterior]
    database_writes: int = 0
    predictions_persisted: int = 0
    recommendations_created: int = 0
    orders_created: int = 0
    etf_outputs_created: int = 0
    trading_activated: bool = False


@dataclass(frozen=True)
class ValidatedHierarchicalResult:
    model_run_id: str
    selection_id: str
    result_sha256: str
    posterior_by_ticker: tuple[CanonicalPercentPosterior, ...]
    research_only: bool = True
    operationally_eligible: bool = False


HierarchicalPosteriorBackend = Callable[[HierarchicalFitRequest], HierarchicalBackendResult]


def _validate_panel(panel: HistoricalReturnPanel) -> None:
    _safe_id(panel.snapshot_id, "snapshot_id")
    if not isinstance(panel.snapshot_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", panel.snapshot_sha256):
        raise HierarchicalContractError("snapshot identity must be a lowercase SHA-256")
    if type(panel.tickers) is not tuple or not panel.tickers or len(set(panel.tickers)) != len(panel.tickers):
        raise HierarchicalContractError("panel tickers must be a unique nonempty tuple")
    if any(not isinstance(ticker, str) or ticker != ticker.strip().upper() or not ticker for ticker in panel.tickers):
        raise HierarchicalContractError("panel ticker identifiers must be normalized")
    if type(panel.session_dates) is not tuple or len(panel.session_dates) < MINIMUM_FIT_OBSERVATIONS + max(EXPECTED_LAGS):
        raise HierarchicalContractError("panel history is shorter than the governed minimum")
    if any(type(item) is not date for item in panel.session_dates):
        raise HierarchicalContractError("panel session dates must be dates")
    if tuple(sorted(set(panel.session_dates))) != panel.session_dates:
        raise HierarchicalContractError("panel session dates must be increasing and unique")
    if type(panel.returns_pct) is not np.ndarray or panel.returns_pct.shape != (
        len(panel.session_dates), len(panel.tickers)
    ):
        raise HierarchicalContractError("percentage return panel shape differs")
    if not np.issubdtype(panel.returns_pct.dtype, np.number) or not np.isfinite(panel.returns_pct).all():
        raise HierarchicalContractError("percentage return panel is nonnumeric or non-finite")


def _validate_policy(policy: EdgeSelectionPolicy) -> None:
    if type(policy) is not EdgeSelectionPolicy:
        raise HierarchicalContractError("selection policy must use the governed type")
    if policy.candidate_lags != EXPECTED_LAGS or policy.candidate_depths != EXPECTED_DEPTHS:
        raise HierarchicalContractError("candidate lag/depth geometry differs")
    if type(policy.minimum_fit_observations) is not int or policy.minimum_fit_observations != MINIMUM_FIT_OBSERVATIONS:
        raise HierarchicalContractError("minimum fit observations differ")
    if type(policy.fdr_alpha) is not float or not math_is_finite(policy.fdr_alpha) or not 0.0 < policy.fdr_alpha <= 0.05:
        raise HierarchicalContractError("FDR alpha is invalid or weakened")
    if policy.association_test != "FISHER_Z_TWO_SIDED_APPROXIMATION":
        raise HierarchicalContractError("association test differs")
    if policy.multiple_testing_method != "BENJAMINI_HOCHBERG_GLOBAL_FAMILY":
        raise HierarchicalContractError("multiple-testing method differs")
    if policy.topology != TOPOLOGY or policy.claim_scope != CLAIM_SCOPE:
        raise HierarchicalContractError("model topology or claim scope differs")


def math_is_finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _pearson_and_p(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if len(x) != len(y) or len(x) < 4:
        raise HierarchicalContractError("edge alignment is invalid")
    x_centered = x - float(np.mean(x))
    y_centered = y - float(np.mean(y))
    denominator = float(np.linalg.norm(x_centered) * np.linalg.norm(y_centered))
    if denominator <= 1e-15:
        return 0.0, 1.0
    correlation = float(np.dot(x_centered, y_centered) / denominator)
    correlation = max(-1.0, min(1.0, correlation))
    if abs(correlation) >= 1.0:
        return correlation, 0.0
    fisher_z = atanh(correlation) * sqrt(len(x) - 3)
    p_value = erfc(abs(fisher_z) / sqrt(2.0))
    return correlation, max(0.0, min(1.0, p_value))


def _bh_q_values(p_values: Sequence[float]) -> tuple[float, ...]:
    """Return deterministic BH adjusted q-values over the full family."""
    values = tuple(p_values)
    if not values or any(not math_is_finite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise HierarchicalContractError("BH-FDR p-values are absent or invalid")
    ordered = sorted(range(len(values)), key=lambda index: (values[index], index))
    adjusted = [1.0] * len(values)
    running = 1.0
    family_size = len(values)
    for reverse_rank, index in enumerate(reversed(ordered), 1):
        rank = family_size - reverse_rank + 1
        running = min(running, values[index] * family_size / rank)
        adjusted[index] = min(1.0, running)
    return tuple(adjusted)


def select_independent_edges(
    panel: HistoricalReturnPanel,
    *,
    target_sources: Mapping[str, Sequence[str]],
    selection_end_ordinal: int,
    policy: EdgeSelectionPolicy = EdgeSelectionPolicy(),
) -> EdgeSelectionArtifact:
    """Select each ticker/lag edge independently using training rows only."""
    _validate_panel(panel)
    _validate_policy(policy)
    if type(selection_end_ordinal) is not int or not 0 <= selection_end_ordinal < len(panel.session_dates):
        raise HierarchicalContractError("selection cutoff is outside the panel")
    if not isinstance(target_sources, Mapping) or not target_sources:
        raise HierarchicalContractError("target/source candidate mapping is required")
    ticker_index = {ticker: index for index, ticker in enumerate(panel.tickers)}
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for target, raw_sources in target_sources.items():
        if target not in ticker_index:
            raise HierarchicalContractError("target ticker is absent from the panel")
        sources = tuple(raw_sources)
        if not sources or len(set(sources)) != len(sources) or any(source not in ticker_index for source in sources):
            raise HierarchicalContractError("source candidates are empty, duplicated, or absent")
        normalized.append((target, tuple(sorted(sources))))
    normalized.sort(key=lambda item: item[0])

    provisional: list[tuple[str, str, int, int, float, float]] = []
    for target, sources in normalized:
        target_column = ticker_index[target]
        for source in sources:
            source_column = ticker_index[source]
            for lag in policy.candidate_lags:
                start = lag
                stop = selection_end_ordinal + 1
                aligned = stop - start
                if aligned < policy.minimum_fit_observations:
                    raise HierarchicalContractError("selection fold has insufficient aligned observations")
                x = panel.returns_pct[: stop - lag, source_column]
                y = panel.returns_pct[lag:stop, target_column]
                correlation, p_value = _pearson_and_p(x, y)
                provisional.append((target, source, lag, aligned, correlation, p_value))
    q_values = _bh_q_values(tuple(row[5] for row in provisional))
    hypotheses = tuple(
        EdgeHypothesis(
            target_ticker=row[0], source_ticker=row[1], lag=row[2],
            aligned_observations=row[3], correlation=row[4],
            p_value=row[5], q_value=q_value,
        )
        for row, q_value in zip(provisional, q_values, strict=True)
    )
    target_sets: list[TargetEdgeSet] = []
    for target, _sources in normalized:
        accepted = [
            item for item in hypotheses
            if item.target_ticker == target and item.q_value <= policy.fdr_alpha
        ]
        accepted.sort(key=lambda item: (item.q_value, -abs(item.correlation), item.source_ticker, item.lag))
        selected = tuple(accepted[: max(policy.candidate_depths)])
        target_sets.append(TargetEdgeSet(target, len(selected), selected))
    payload = {
        "panel_snapshot_id": panel.snapshot_id,
        "panel_snapshot_sha256": panel.snapshot_sha256,
        "selection_end_ordinal": selection_end_ordinal,
        "selection_end_date": panel.session_dates[selection_end_ordinal],
        "policy": policy,
        "hypothesis_count": len(hypotheses),
        "target_edge_sets": tuple(target_sets),
        "all_hypotheses": hypotheses,
        "training_only": True,
        "forced_chain": False,
        "return_unit": RETURN_UNIT,
    }
    return EdgeSelectionArtifact(
        selection_id=f"edge-selection-{canonical_sha256(payload)}",
        **payload,
    )


def build_hierarchical_fit_request(
    panel: HistoricalReturnPanel,
    selection: EdgeSelectionArtifact,
    *,
    model_run_id: str,
    prediction_date: date,
    preregistered_model_config_sha256: str,
    preregistered_sampler_sha256: str,
) -> HierarchicalFitRequest:
    """Build frozen percent-unit matrices for an injected hierarchical backend."""
    _validate_panel(panel)
    _safe_id(model_run_id, "model_run_id")
    for value, label in (
        (preregistered_model_config_sha256, "preregistered model configuration"),
        (preregistered_sampler_sha256, "preregistered sampler"),
    ):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise HierarchicalContractError(f"{label} identity must be a lowercase SHA-256")
    if selection.panel_snapshot_id != panel.snapshot_id or selection.panel_snapshot_sha256 != panel.snapshot_sha256:
        raise HierarchicalContractError("edge selection uses a different panel")
    if selection.policy.candidate_lags != EXPECTED_LAGS or selection.policy.candidate_depths != EXPECTED_DEPTHS:
        raise HierarchicalContractError("edge selection geometry differs")
    if selection.training_only is not True or selection.forced_chain is not False or selection.return_unit != RETURN_UNIT:
        raise HierarchicalContractError("edge selection boundary differs")
    expected_selection_id = f"edge-selection-{canonical_sha256({
        'panel_snapshot_id': selection.panel_snapshot_id,
        'panel_snapshot_sha256': selection.panel_snapshot_sha256,
        'selection_end_ordinal': selection.selection_end_ordinal,
        'selection_end_date': selection.selection_end_date,
        'policy': selection.policy,
        'hypothesis_count': selection.hypothesis_count,
        'target_edge_sets': selection.target_edge_sets,
        'all_hypotheses': selection.all_hypotheses,
        'training_only': selection.training_only,
        'forced_chain': selection.forced_chain,
        'return_unit': selection.return_unit,
    })}"
    if selection.selection_id != expected_selection_id:
        raise HierarchicalContractError("edge selection identity mismatch")
    source_date = panel.session_dates[selection.selection_end_ordinal]
    if type(prediction_date) is not date or prediction_date <= source_date:
        raise HierarchicalContractError("prediction date must follow the source session")
    ticker_index = {ticker: index for index, ticker in enumerate(panel.tickers)}
    matrices: list[TargetDesignMatrix] = []
    for target_set in selection.target_edge_sets:
        if target_set.selected_depth != len(target_set.edges) or not 1 <= target_set.selected_depth <= 5:
            raise HierarchicalContractError("target has no qualifying governed edge set")
        edge_ids = tuple((edge.source_ticker, edge.lag) for edge in target_set.edges)
        if len(set(edge_ids)) != len(edge_ids):
            raise HierarchicalContractError("selected edge identity is duplicated")
        maximum_lag = max(edge.lag for edge in target_set.edges)
        rows = np.arange(maximum_lag, selection.selection_end_ordinal + 1)
        if len(rows) < selection.policy.minimum_fit_observations:
            raise HierarchicalContractError("fit matrix has insufficient observations")
        columns = tuple(
            panel.returns_pct[rows - edge.lag, ticker_index[edge.source_ticker]]
            for edge in target_set.edges
        )
        raw_x = np.column_stack(columns)
        mean = raw_x.mean(axis=0)
        scale = raw_x.std(axis=0)
        scale[scale < 1e-12] = 1.0
        x_train = (raw_x - mean) / scale
        target_returns = panel.returns_pct[rows, ticker_index[target_set.target_ticker]].copy()
        y_direction = (target_returns > 0.0).astype(int)
        prediction_ordinal = selection.selection_end_ordinal + 1
        prediction_raw = np.asarray([
            panel.returns_pct[prediction_ordinal - edge.lag, ticker_index[edge.source_ticker]]
            for edge in target_set.edges
        ], dtype=float)
        x_predict = ((prediction_raw - mean) / scale).reshape(1, -1)
        matrices.append(TargetDesignMatrix(
            ticker=target_set.target_ticker,
            feature_names=tuple(
                f"{edge.source_ticker}_return_pct_lag{edge.lag}"
                for edge in target_set.edges
            ),
            edge_identities=edge_ids,
            training_dates=tuple(panel.session_dates[index] for index in rows),
            x_train=x_train,
            y_direction=y_direction,
            y_return_pct=target_returns,
            x_predict=x_predict,
            train_mean=mean,
            train_scale=scale,
        ))
    hierarchy = "PARTIAL_POOLING_GLOBAL_EDGE_SCALE_AND_TARGET_INTERCEPTS"
    graph_contract_sha256 = canonical_sha256({
        "model_topology": TOPOLOGY,
        "hierarchy": hierarchy,
        "direction_likelihood": "BERNOULLI_LOGIT",
        "return_likelihood": "STUDENT_T_PERCENT",
        "edge_coefficients": "INDEPENDENT_EXCHANGEABLE_NO_POSITIONAL_CHAIN",
        "standardization": "TRAINING_ONLY_PER_TARGET_EDGE",
        "preregistered_model_config_sha256": preregistered_model_config_sha256,
        "preregistered_sampler_sha256": preregistered_sampler_sha256,
    })
    return HierarchicalFitRequest(
        model_run_id=model_run_id,
        selection_id=selection.selection_id,
        panel_snapshot_id=panel.snapshot_id,
        panel_snapshot_sha256=panel.snapshot_sha256,
        source_session_date=source_date,
        prediction_date=prediction_date,
        model_topology=TOPOLOGY,
        hierarchy=hierarchy,
        graph_contract_sha256=graph_contract_sha256,
        preregistered_model_config_sha256=preregistered_model_config_sha256,
        preregistered_sampler_sha256=preregistered_sampler_sha256,
        candidate_lags=EXPECTED_LAGS,
        candidate_depths=EXPECTED_DEPTHS,
        target_matrices=tuple(matrices),
    )


def _validate_fit_request(request: HierarchicalFitRequest) -> None:
    if type(request) is not HierarchicalFitRequest:
        raise HierarchicalContractError("fit request must use the exact governed type")
    _safe_id(request.model_run_id, "model_run_id")
    _safe_id(request.selection_id, "selection_id")
    if request.model_topology != TOPOLOGY or request.hierarchy != "PARTIAL_POOLING_GLOBAL_EDGE_SCALE_AND_TARGET_INTERCEPTS":
        raise HierarchicalContractError("hierarchical graph differs")
    for value, label in (
        (request.graph_contract_sha256, "graph contract"),
        (request.preregistered_model_config_sha256, "model configuration"),
        (request.preregistered_sampler_sha256, "sampler"),
    ):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise HierarchicalContractError(f"{label} identity differs")
    expected_graph = canonical_sha256({
        "model_topology": request.model_topology,
        "hierarchy": request.hierarchy,
        "direction_likelihood": "BERNOULLI_LOGIT",
        "return_likelihood": "STUDENT_T_PERCENT",
        "edge_coefficients": "INDEPENDENT_EXCHANGEABLE_NO_POSITIONAL_CHAIN",
        "standardization": "TRAINING_ONLY_PER_TARGET_EDGE",
        "preregistered_model_config_sha256": request.preregistered_model_config_sha256,
        "preregistered_sampler_sha256": request.preregistered_sampler_sha256,
    })
    if request.graph_contract_sha256 != expected_graph:
        raise HierarchicalContractError("hierarchical graph identity mismatch")
    if request.candidate_lags != EXPECTED_LAGS or request.candidate_depths != EXPECTED_DEPTHS:
        raise HierarchicalContractError("fit request geometry differs")
    if request.return_unit != RETURN_UNIT or request.training_only_selection is not True or request.research_only is not True:
        raise HierarchicalContractError("fit request evidence boundary differs")
    if any((request.persist_predictions, request.create_recommendations, request.create_orders, request.create_etf_outputs, request.activate_trading)):
        raise HierarchicalContractError("fit request enables downstream behavior")
    if not request.target_matrices or len({item.ticker for item in request.target_matrices}) != len(request.target_matrices):
        raise HierarchicalContractError("fit request targets are absent or duplicated")
    for matrix in request.target_matrices:
        arrays = (
            matrix.x_train, matrix.y_direction, matrix.y_return_pct,
            matrix.x_predict, matrix.train_mean, matrix.train_scale,
        )
        if any(type(value) is not np.ndarray or not np.isfinite(value).all() for value in arrays):
            raise HierarchicalContractError("fit matrix contains non-finite or non-array evidence")
        observations, features = matrix.x_train.shape
        if observations < MINIMUM_FIT_OBSERVATIONS or not 1 <= features <= 5:
            raise HierarchicalContractError("fit matrix shape differs")
        if matrix.x_predict.shape != (1, features) or len(matrix.y_direction) != observations or len(matrix.y_return_pct) != observations:
            raise HierarchicalContractError("fit matrix arrays do not align")
        if len(matrix.feature_names) != features or len(matrix.edge_identities) != features or len(matrix.training_dates) != observations:
            raise HierarchicalContractError("fit matrix metadata does not align")
        if any(not name.endswith(tuple(f"lag{lag}" for lag in EXPECTED_LAGS)) or "_return_pct_" not in name for name in matrix.feature_names):
            raise HierarchicalContractError("fit feature names do not use canonical percentage units")
        if not set(np.unique(matrix.y_direction)).issubset({0, 1}):
            raise HierarchicalContractError("direction outcome is not binary")


def _validate_diagnostics(value: SamplerDiagnosticsEvidence) -> None:
    if type(value) is not SamplerDiagnosticsEvidence:
        raise HierarchicalContractError("sampler diagnostics use an ungoverned type")
    if value.chains < 4 or value.draws < 1000 or value.tune < 1000:
        raise HierarchicalContractError("sampler counts are below the frozen minimum")
    numeric = (value.max_rhat, value.min_bulk_ess, value.min_tail_ess, value.bfmi_min, value.max_treedepth_fraction)
    if any(not math_is_finite(item) for item in numeric):
        raise HierarchicalContractError("sampler diagnostics are non-finite")
    if value.max_rhat > 1.01 or value.min_bulk_ess < 400 or value.min_tail_ess < 400 or value.bfmi_min < 0.3:
        raise HierarchicalContractError("sampler diagnostics fail convergence gates")
    if type(value.divergences) is not int or value.divergences != 0 or not 0.0 <= value.max_treedepth_fraction <= 0.01:
        raise HierarchicalContractError("sampler divergences or tree-depth saturation fail")


def _validate_posterior(value: CanonicalPercentPosterior, ticker: str) -> None:
    if type(value) is not CanonicalPercentPosterior or value.ticker != ticker:
        raise HierarchicalContractError("posterior type or ticker differs")
    numbers = (
        value.probability_up_mean, value.probability_up_std,
        value.probability_up_q05, value.probability_up_q95,
        value.expected_return_pct_mean, value.expected_return_pct_std,
        value.predictive_risk_pct,
    )
    if any(not math_is_finite(item) for item in numbers):
        raise HierarchicalContractError("posterior contains non-finite evidence")
    if not 0.0 <= value.probability_up_q05 <= value.probability_up_mean <= value.probability_up_q95 <= 1.0:
        raise HierarchicalContractError("posterior probability ordering differs")
    if value.probability_up_std <= 0.0 or value.expected_return_pct_std <= 0.0 or value.predictive_risk_pct <= 0.0:
        raise HierarchicalContractError("posterior uncertainty is missing")
    _validate_diagnostics(value.diagnostics)


def run_hierarchical_backend(
    request: HierarchicalFitRequest,
    *,
    backend: HierarchicalPosteriorBackend,
) -> ValidatedHierarchicalResult:
    """Call one explicit backend and validate research-only percent outputs."""
    _validate_fit_request(request)
    if not callable(backend):
        raise HierarchicalContractError("an explicit hierarchical backend is required")
    result = backend(request)
    if type(result) is not HierarchicalBackendResult:
        raise HierarchicalContractError("backend result uses an ungoverned type")
    if result.model_run_id != request.model_run_id or result.selection_id != request.selection_id:
        raise HierarchicalContractError("backend run/selection lineage differs")
    if result.model_topology != request.model_topology or result.hierarchy != request.hierarchy:
        raise HierarchicalContractError("backend hierarchical graph differs")
    if (
        result.graph_contract_sha256 != request.graph_contract_sha256
        or result.preregistered_model_config_sha256 != request.preregistered_model_config_sha256
        or result.preregistered_sampler_sha256 != request.preregistered_sampler_sha256
    ):
        raise HierarchicalContractError("backend preregistered graph identity differs")
    expected = {item.ticker for item in request.target_matrices}
    if not isinstance(result.posterior_by_ticker, Mapping) or set(result.posterior_by_ticker) != expected:
        raise HierarchicalContractError("backend posterior ticker coverage differs")
    if any(
        type(value) is not int or value != 0
        for value in (
            result.database_writes, result.predictions_persisted,
            result.recommendations_created, result.orders_created,
            result.etf_outputs_created,
        )
    ) or result.trading_activated is not False:
        raise HierarchicalContractError("backend crossed the research-only boundary")
    ordered_tickers = tuple(sorted(expected))
    posteriors = tuple(result.posterior_by_ticker[ticker] for ticker in ordered_tickers)
    for ticker, posterior in zip(ordered_tickers, posteriors, strict=True):
        _validate_posterior(posterior, ticker)
    result_sha = canonical_sha256({
        "model_run_id": result.model_run_id,
        "selection_id": result.selection_id,
        "model_topology": result.model_topology,
        "hierarchy": result.hierarchy,
        "graph_contract_sha256": result.graph_contract_sha256,
        "preregistered_model_config_sha256": result.preregistered_model_config_sha256,
        "preregistered_sampler_sha256": result.preregistered_sampler_sha256,
        "posteriors": posteriors,
        "database_writes": 0,
        "predictions_persisted": 0,
        "recommendations_created": 0,
        "orders_created": 0,
        "etf_outputs_created": 0,
        "trading_activated": False,
    })
    return ValidatedHierarchicalResult(
        model_run_id=result.model_run_id,
        selection_id=result.selection_id,
        result_sha256=result_sha,
        posterior_by_ticker=posteriors,
    )
