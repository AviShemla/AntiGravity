from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import pytest

from oracle_research_dataset_serializers import (  # noqa: E402
    MARKET_DAILY_FEATURE_COLUMNS, MarketDatasetStreamingDigester,
)
try:
    from .normalized_edge_input_contract import (
        NormalizedEdge, PreregistrationProof, canonical_sha256,
        verify_normalized_edge_bundle,
    )
except ImportError:
    from normalized_edge_input_contract import (
        NormalizedEdge, PreregistrationProof, canonical_sha256,
        verify_normalized_edge_bundle,
    )
try:
    from .injected_source_materializer import (
        FoldEdgeSelection, FrozenContentBinding, MaterializationError,
        materialize_normalized_edge_inputs,
    )
except ImportError:
    from injected_source_materializer import (
        FoldEdgeSelection, FrozenContentBinding, MaterializationError,
        materialize_normalized_edge_inputs,
    )


NOW = datetime.now(timezone.utc)
TICKERS = tuple(f"T{index:03d}" for index in range(474))
FULL_DATES = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(423))
MODEL_DATES = FULL_DATES[-416:]
RETURN_INDEX = MARKET_DAILY_FEATURE_COLUMNS.index("daily_return_pct")
CLOSE_INDEX = MARKET_DAILY_FEATURE_COLUMNS.index("close_price")


def row(ticker: str, session: date, ticker_index: int, date_index: int) -> tuple[object, ...]:
    values: list[object] = [None] * len(MARKET_DAILY_FEATURE_COLUMNS)
    values[0] = "market-features-fixture"
    values[1] = ticker
    values[2] = session.isoformat()
    values[CLOSE_INDEX] = 100.0 + ticker_index / 1000.0 + date_index / 10000.0
    values[RETURN_INDEX] = ((ticker_index + date_index) % 17 - 8) / 100.0
    return tuple(values)


@pytest.fixture(scope="module")
def sources():
    rows = tuple(
        row(ticker, session, ticker_index, date_index)
        for ticker_index, ticker in enumerate(TICKERS)
        for date_index, session in enumerate(FULL_DATES)
    )
    digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
    digester.update_rows(rows)
    digests = digester.finalize()
    model_sha = canonical_sha256([item.isoformat() for item in MODEL_DATES])
    proof = PreregistrationProof(
        contract_id="codex-oracle-hierarchical-stock-preregistration-v2",
        run_id="stock-prereg-fixture", raw_sha256="1" * 64,
        checkpoint_identity_sha256="2" * 64,
        independent_audit_raw_sha256="3" * 64,
        independent_audit_status="VERIFIED_FIXTURE_ONLY",
        independent_audit_observed_at_utc=NOW - timedelta(minutes=4),
        current_readback_raw_sha256="4" * 64,
        current_readback_status="VERIFIED_SELECT_ONLY",
        current_readback_observed_at_utc=NOW - timedelta(minutes=2),
        snapshot_id=digests.snapshot_id, snapshot_sha256="5" * 64,
        universe_id="approved-universe-fixture",
        universe_sha256=canonical_sha256(list(TICKERS)),
        full_session_calendar_sha256=canonical_sha256(
            [item.isoformat() for item in FULL_DATES]
        ),
        model_session_dates_sha256=model_sha,
        model_code_git_commit="b" * 40,
        model_config_sha256="9" * 64, sampler_sha256="c" * 64,
        candidate_lags=tuple(range(1, 8)), candidate_depths=tuple(range(1, 6)),
        target_count=474, fold_count=4, model_calendar_sessions=416,
        training_only_selection=True,
        multiple_testing_control="BH_FDR_PREREGISTERED",
        zero_temporal_overlap=True, fixture_only=True,
        model_fit_authorized=False, model_fit_started=False,
        downstream_counts={"predictions": 0, "recommendations": 0,
                           "orders": 0, "etf_outputs": 0},
    )
    frozen = FrozenContentBinding(
        dataset_version_id="oracle-research-fixture",
        dataset_status="FROZEN", freeze_event_count=1,
        market_snapshot_id=digests.snapshot_id,
        market_snapshot_sha256=proof.snapshot_sha256,
        content_sha256=digests.content_sha256,
        content_ticker_universe_sha256=digests.ticker_universe_sha256,
        expected_row_count=digests.row_count,
        expected_ticker_count=digests.ticker_count,
        first_session_date=digests.first_session_date,
        last_session_date=digests.last_session_date,
    )
    selections = tuple(
        FoldEdgeSelection(
            target_ticker=ticker,
            fold_number=fold,
            selection_end_ordinal=(288, 318, 348, 378)[fold - 1],
            selection_artifact_sha256=canonical_sha256(
                {"target": ticker, "fold": fold, "source": TICKERS[(index + fold) % 474],
                 "lag": fold + 1}
            ),
            edges=(NormalizedEdge(TICKERS[(index + fold) % 474], fold + 1),),
        )
        for index, ticker in enumerate(TICKERS)
        for fold in range(1, 5)
    )
    return rows, proof, frozen, selections


@pytest.fixture(scope="module")
def materialized(sources):
    rows, proof, frozen, selections = sources
    return materialize_normalized_edge_inputs(
        frozen=frozen, canonical_market_rows=rows,
        model_session_dates=MODEL_DATES, preregistration=proof,
        fold_edge_selections=selections,
    )


def test_materializes_exact_474_by_4_bundle_and_existing_reader_accepts(materialized, sources):
    _rows, proof, _frozen, _selections = sources
    verified = verify_normalized_edge_bundle(
        materialized.manifest_raw,
        payload_loader=materialized.payloads.__getitem__,
        preregistration=proof,
        observed_at_utc=NOW,
    )
    assert (verified.target_count, verified.fold_count, verified.payload_count) == (474, 4, 1896)
    assert verified.verified_payload_count == 1896
    assert materialized.payload_count == 1896 and materialized.payload_bytes > 0
    assert len(materialized.frozen_content_sha256) == 64
    assert len(materialized.edge_selection_sha256) == 64
    assert len(materialized.normalized_edge_source_sha256) == 64
    assert (materialized.database_reads, materialized.database_writes,
            materialized.network_calls, materialized.model_fits,
            materialized.downstream_outputs) == (0, 0, 0, 0, 0)


def test_lag_alignment_is_target_relative_not_positional(materialized, sources):
    rows, _proof, _frozen, selections = sources
    selection = selections[0]
    raw = materialized.payloads["folds/T000/fold-1.bin"]
    try:
        from .normalized_edge_input_contract import decode_fold_payload, parse_manifest
    except ImportError:
        from normalized_edge_input_contract import decode_fold_payload, parse_manifest
    record = parse_manifest(materialized.manifest_raw).records[0]
    payload = decode_fold_payload(record, raw)
    source = selection.edges[0].source_ticker
    source_index = TICKERS.index(source)
    expected_first = ((source_index + 7 - selection.edges[0].lag_sessions) % 17 - 8) / 100.0
    assert payload.x_train[0, 0] == pytest.approx(expected_first)
    assert record.edges[0].lag_sessions == 2
    assert record.edges[0].lag_semantics == "TARGET_RELATIVE_TRADING_SESSIONS"


def test_frozen_content_hash_drift_fails_closed(sources):
    rows, proof, frozen, selections = sources
    with pytest.raises(MaterializationError, match="frozen binding"):
        materialize_normalized_edge_inputs(
            frozen=replace(frozen, content_sha256="f" * 64),
            canonical_market_rows=rows, model_session_dates=MODEL_DATES,
            preregistration=proof, fold_edge_selections=selections,
        )


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda selections: selections[:-1], "474 x 4"),
        (lambda selections: (replace(selections[0], selection_end_ordinal=287),) + selections[1:], "cutoff"),
        (lambda selections: (replace(selections[0], edges=(NormalizedEdge("T001", 7), NormalizedEdge("T001", 7))),) + selections[1:], "duplicated"),
    ],
)
def test_missing_leaky_or_duplicate_fold_edges_fail_before_payloads(sources, mutation, message):
    rows, proof, frozen, selections = sources
    with pytest.raises(MaterializationError, match=message):
        materialize_normalized_edge_inputs(
            frozen=frozen, canonical_market_rows=rows,
            model_session_dates=MODEL_DATES, preregistration=proof,
            fold_edge_selections=mutation(selections),
        )


def test_calendar_and_fit_authorization_drift_fail_closed_before_materialization(sources):
    rows, proof, frozen, selections = sources
    with pytest.raises(MaterializationError, match="model session calendar"):
        materialize_normalized_edge_inputs(
            frozen=frozen, canonical_market_rows=rows,
            model_session_dates=tuple(reversed(MODEL_DATES)), preregistration=proof,
            fold_edge_selections=selections,
        )
    with pytest.raises(MaterializationError, match="fixture boundary"):
        materialize_normalized_edge_inputs(
            frozen=frozen, canonical_market_rows=rows,
            model_session_dates=MODEL_DATES,
            preregistration=replace(proof, model_fit_authorized=True),
            fold_edge_selections=selections,
        )
    with pytest.raises(MaterializationError, match="full frozen session calendar"):
        materialize_normalized_edge_inputs(
            frozen=frozen,
            canonical_market_rows=rows,
            model_session_dates=MODEL_DATES,
            preregistration=replace(proof, full_session_calendar_sha256="f" * 64),
            fold_edge_selections=selections,
        )


def test_module_has_no_io_runtime_or_model_fit_imports():
    try:
        from . import injected_source_materializer as module
    except ImportError:
        import injected_source_materializer as module

    names = set(vars(module))
    assert names.isdisjoint({"sqlite3", "requests", "urllib", "socket", "subprocess", "os"})
