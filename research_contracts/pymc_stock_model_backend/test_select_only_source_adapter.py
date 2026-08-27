from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import json
import sys

import pytest


WORKSPACE = Path(__file__).resolve().parents[3]
CANONICAL = WORKSPACE / "canonical_ae48357_auth_review"
MATERIALIZER = WORKSPACE / "normalized_edge_materializer_impl/research_contracts/pymc_stock_model_backend"
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(MATERIALIZER), str(CANONICAL)]

from oracle_research_dataset_serializers import MARKET_DAILY_FEATURE_COLUMNS  # noqa: E402
from research_contracts.pymc_stock_model_backend.normalized_edge_input_contract import canonical_sha256  # noqa: E402
from select_only_source_adapter import (  # noqa: E402
    CALENDAR_SQL, MARKET_FIRST_SQL, MARKET_NEXT_SQL, SELECTION_COVERAGE_SQL,
    SELECTION_ROWS_SQL, SelectionDependencyBlocked, SourceAdapterError,
    preflight_fold_selection_source, read_canonical_market_rows,
    read_fold_edge_selections, read_model_calendar,
)


class Result:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = list(rows)


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, args))
        return self.responses.pop(0)


def coverage(rows=1896, targets=474, status="VALIDATED"):
    return Result(
        ("status", "market_snapshot_id", "selection_row_count", "target_count",
         "min_fold", "max_fold", "bad_purge_count"),
        [(status, "snapshot", rows, targets, 1 if rows else None, 4 if rows else None, 0)],
    )


def test_committed_zero_normalized_tables_and_incomplete_legacy_folds_block():
    client = Client([coverage(rows=92, targets=23)])
    with pytest.raises(SelectionDependencyBlocked) as captured:
        preflight_fold_selection_source(
            client, screening_run_id="screening-run", market_snapshot_id="snapshot",
        )
    evidence = captured.value.evidence
    assert evidence.status == "DEPENDENCY_BLOCKED"
    assert (evidence.observed_rows, evidence.required_rows) == (92, 1896)
    assert (evidence.observed_targets, evidence.required_targets) == (23, 474)
    assert evidence.database_writes == evidence.screening_reruns == 0
    assert client.calls == [(SELECTION_COVERAGE_SQL, ["screening-run"])]


def test_absent_selection_run_blocks_without_heavy_market_queries():
    client = Client([Result(
        ("status", "market_snapshot_id", "selection_row_count", "target_count",
         "min_fold", "max_fold", "bad_purge_count"), [],
    )])
    with pytest.raises(SelectionDependencyBlocked) as captured:
        preflight_fold_selection_source(client, screening_run_id="missing", market_snapshot_id="snapshot")
    assert captured.value.evidence.observed_rows == 0
    assert len(client.calls) == 1


def test_calendar_selects_last_416_and_hash_binds_s07():
    dates = tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(423))
    digest = canonical_sha256([item.isoformat() for item in dates[-416:]])
    client = Client([Result(("date",), [(item.isoformat(),) for item in dates])])
    full, model = read_model_calendar(
        client, snapshot_id="snapshot", model_session_dates_sha256=digest,
    )
    assert full == dates and model == dates[-416:]
    assert client.calls == [(CALENDAR_SQL, ["snapshot"])]


def test_market_keyset_pagination_is_exact_and_terminal_empty_page_required():
    def row(ticker, session):
        values = [None] * len(MARKET_DAILY_FEATURE_COLUMNS)
        values[0:3] = ["snapshot", ticker, session]
        values[MARKET_DAILY_FEATURE_COLUMNS.index("close_price")] = 1.0
        return tuple(values)
    first = [row("AAA", "2026-01-01"), row("AAA", "2026-01-02")]
    second = [row("BBB", "2026-01-01")]
    client = Client([
        Result(MARKET_DAILY_FEATURE_COLUMNS, first),
        Result(MARKET_DAILY_FEATURE_COLUMNS, second),
        Result(MARKET_DAILY_FEATURE_COLUMNS, []),
    ])
    result = read_canonical_market_rows(
        client, snapshot_id="snapshot", expected_row_count=3, page_size=2,
    )
    assert result == tuple(first + second)
    assert [call[0] for call in client.calls] == [MARKET_FIRST_SQL, MARKET_NEXT_SQL, MARKET_NEXT_SQL]


def test_complete_existing_fold_specs_map_only_explicit_ticker_lag_identities():
    dates = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(416))
    rows = []
    for target_index in range(474):
        ticker = f"T{target_index:03d}"
        for fold, (_, train_start, train_end, test_start, test_end) in enumerate(
            ((1, 0, 288, 296, 325), (2, 30, 318, 326, 355),
             (3, 60, 348, 356, 385), (4, 90, 378, 386, 415)), 1
        ):
            source = f"T{(target_index + fold) % 474:03d}"
            spec = json.dumps({
                "depth": 1, "lag_tickers": [source], "lag_sessions": [fold + 1],
                "lag_semantics": "target_relative_sessions", "technical_features": [],
            }, sort_keys=True, separators=(",", ":"))
            rows.append((
                ticker, fold, dates[train_start].isoformat(), dates[train_end].isoformat(),
                dates[test_start].isoformat(), dates[test_end].isoformat(), 7, 1, spec,
            ))
    client = Client([
        coverage(),
        Result(("ticker", "fold_number", "train_start_date", "train_end_date",
                "test_start_date", "test_end_date", "purge_sessions",
                "selected_depth", "feature_spec_json"), rows),
    ])
    selections = read_fold_edge_selections(
        client, screening_run_id="screening-run",
        market_snapshot_id="snapshot", model_session_dates=dates,
    )
    assert len(selections) == 1896
    assert selections[0].edges[0].source_ticker == "T001"
    assert selections[0].edges[0].lag_sessions == 2
    assert len(selections[0].selection_artifact_sha256) == 64


def test_technical_or_positional_only_spec_is_not_silently_discarded():
    dates = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(416))
    spec = json.dumps({
        "depth": 1, "lag_tickers": ["BBB"], "lag_sessions": [1],
        "lag_semantics": "target_relative_sessions", "technical_features": ["rsi_14d"],
    })
    one = ("AAA", 1, dates[0].isoformat(), dates[288].isoformat(),
           dates[296].isoformat(), dates[325].isoformat(), 7, 1, spec)
    client = Client([
        coverage(),
        Result(("ticker", "fold_number", "train_start_date", "train_end_date",
                "test_start_date", "test_end_date", "purge_sessions",
                "selected_depth", "feature_spec_json"), [one] * 1896),
    ])
    with pytest.raises(SourceAdapterError, match="cannot map exactly"):
        read_fold_edge_selections(
            client, screening_run_id="screening-run",
            market_snapshot_id="snapshot", model_session_dates=dates,
        )


def test_no_query_surface_can_execute_mutations():
    import select_only_source_adapter as module

    for sql in module.ALLOWLIST:
        assert sql.lstrip().upper().startswith("SELECT ")
        assert ";" not in sql
    assert set(vars(module)).isdisjoint({"sqlite3", "requests", "urllib", "socket", "subprocess"})
