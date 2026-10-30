"""SELECT-only injected-client adapter for S08 materializer source evidence.

The adapter never opens a connection and contains no credentials.  It reads
only exact allowlisted queries through an injected client.  Legacy screening
fold rows are accepted only if one explicitly named VALIDATED run already has
complete 474 x 4 durable coverage; incomplete evidence is dependency-blocked,
never inferred, backfilled, or recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re
from typing import Protocol, Sequence

try:
    from .injected_source_materializer import FoldEdgeSelection
    from .normalized_edge_input_contract import NormalizedEdge, canonical_sha256
except ImportError:  # isolated test execution
    from injected_source_materializer import FoldEdgeSelection
    from research_contracts.pymc_stock_model_backend.normalized_edge_input_contract import (
        NormalizedEdge, canonical_sha256,
    )

from oracle_research_dataset_serializers import MARKET_DAILY_FEATURE_COLUMNS


EXPECTED_TARGETS = 474
EXPECTED_FOLDS = 4
EXPECTED_SELECTION_ROWS = EXPECTED_TARGETS * EXPECTED_FOLDS
EXPECTED_MODEL_DATES = 416
EXPECTED_FOLD_GEOMETRY = (
    (1, 0, 288, 296, 325),
    (2, 30, 318, 326, 355),
    (3, 60, 348, 356, 385),
    (4, 90, 378, 386, 415),
)
_SHA = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|REPLACE|UPSERT|MERGE|"
    r"TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)

_MARKET_COLUMNS_SQL = ",".join(MARKET_DAILY_FEATURE_COLUMNS)
MARKET_FIRST_SQL = (
    f"SELECT {_MARKET_COLUMNS_SQL} FROM market_daily_features "
    "WHERE snapshot_id=? ORDER BY ticker,date LIMIT ?"
)
MARKET_NEXT_SQL = (
    f"SELECT {_MARKET_COLUMNS_SQL} FROM market_daily_features "
    "WHERE snapshot_id=? AND (ticker>? OR (ticker=? AND date>?)) "
    "ORDER BY ticker,date LIMIT ?"
)
CALENDAR_SQL = (
    "SELECT DISTINCT date FROM market_daily_features "
    "WHERE snapshot_id=? ORDER BY date"
)
SELECTION_COVERAGE_SQL = """SELECT r.status,r.market_snapshot_id,
       COUNT(f.ticker) AS selection_row_count,
       COUNT(DISTINCT f.ticker) AS target_count,
       MIN(f.fold_number) AS min_fold,MAX(f.fold_number) AS max_fold,
       SUM(CASE WHEN f.ticker IS NOT NULL AND f.purge_sessions<>7 THEN 1 ELSE 0 END)
           AS bad_purge_count
FROM predictive_screening_runs r
LEFT JOIN predictive_screening_fold_metrics f
  ON f.screening_run_id=r.screening_run_id
WHERE r.screening_run_id=?
GROUP BY r.status,r.market_snapshot_id"""
SELECTION_ROWS_SQL = """SELECT f.ticker,f.fold_number,f.train_start_date,
       f.train_end_date,f.test_start_date,f.test_end_date,f.purge_sessions,
       f.selected_depth,f.feature_spec_json
FROM predictive_screening_fold_metrics f
WHERE f.screening_run_id=?
ORDER BY f.ticker,f.fold_number"""
ALLOWLIST = frozenset({
    MARKET_FIRST_SQL, MARKET_NEXT_SQL, CALENDAR_SQL,
    SELECTION_COVERAGE_SQL, SELECTION_ROWS_SQL,
})


class InjectedSelectClient(Protocol):
    def execute(self, sql: str, args: list[object]): ...


class SourceAdapterError(RuntimeError):
    pass


class SelectionDependencyBlocked(SourceAdapterError):
    def __init__(self, evidence: "SelectionCoverageEvidence") -> None:
        super().__init__(
            "durable fold-local normalized edge selections do not cover 474 x 4"
        )
        self.evidence = evidence


@dataclass(frozen=True)
class SelectionCoverageEvidence:
    screening_run_id: str
    requested_market_snapshot_id: str
    observed_market_snapshot_id: str | None
    run_status: str
    observed_rows: int
    required_rows: int
    observed_targets: int
    required_targets: int
    observed_min_fold: int | None
    observed_max_fold: int | None
    bad_purge_count: int
    status: str
    database_writes: int = 0
    screening_reruns: int = 0


@dataclass(frozen=True)
class SelectOnlyMaterializerSources:
    market_rows: tuple[tuple[object, ...], ...]
    full_session_dates: tuple[date, ...]
    model_session_dates: tuple[date, ...]
    fold_edge_selections: tuple[FoldEdgeSelection, ...]
    selection_source_sha256: str
    query_count: int
    database_writes: int = 0
    screening_reruns: int = 0


def _execute(client: InjectedSelectClient, sql: str, args: list[object]):
    if sql not in ALLOWLIST or not sql.lstrip().upper().startswith("SELECT "):
        raise SourceAdapterError("query is outside the exact SELECT-only allowlist")
    if ";" in sql or _FORBIDDEN.search(sql):
        raise SourceAdapterError("query contains prohibited SQL")
    return client.execute(sql, args)


def _rows(result: object, columns: tuple[str, ...], label: str) -> tuple[tuple[object, ...], ...]:
    actual_columns = getattr(result, "columns", None)
    actual_rows = getattr(result, "rows", None)
    if tuple(actual_columns or ()) != columns or not isinstance(actual_rows, (list, tuple)):
        raise SourceAdapterError(f"{label} result schema differs")
    output = tuple(tuple(item) for item in actual_rows)
    if any(len(item) != len(columns) for item in output):
        raise SourceAdapterError(f"{label} row width differs")
    return output


def preflight_fold_selection_source(
    client: InjectedSelectClient, *, screening_run_id: str, market_snapshot_id: str,
) -> SelectionCoverageEvidence:
    if not screening_run_id or not market_snapshot_id:
        raise SourceAdapterError("screening run and snapshot IDs are required")
    result = _execute(client, SELECTION_COVERAGE_SQL, [screening_run_id])
    rows = _rows(
        result,
        ("status", "market_snapshot_id", "selection_row_count", "target_count",
         "min_fold", "max_fold", "bad_purge_count"),
        "selection coverage",
    )
    if len(rows) > 1:
        raise SourceAdapterError("selection coverage returned multiple run identities")
    if not rows:
        values = ("ABSENT", None, 0, 0, None, None, 0)
    else:
        values = rows[0]
    status, observed_snapshot, row_count, targets, min_fold, max_fold, bad_purge = values
    evidence = SelectionCoverageEvidence(
        screening_run_id=screening_run_id,
        requested_market_snapshot_id=market_snapshot_id,
        observed_market_snapshot_id=(
            None if observed_snapshot is None else str(observed_snapshot)
        ),
        run_status=str(status),
        observed_rows=int(row_count), required_rows=EXPECTED_SELECTION_ROWS,
        observed_targets=int(targets), required_targets=EXPECTED_TARGETS,
        observed_min_fold=None if min_fold is None else int(min_fold),
        observed_max_fold=None if max_fold is None else int(max_fold),
        bad_purge_count=int(bad_purge),
        status="READY" if (
            status == "VALIDATED" and observed_snapshot == market_snapshot_id
            and int(row_count) == EXPECTED_SELECTION_ROWS
            and int(targets) == EXPECTED_TARGETS
            and min_fold == 1 and max_fold == EXPECTED_FOLDS
            and int(bad_purge) == 0
        ) else "DEPENDENCY_BLOCKED",
    )
    if evidence.status != "READY":
        raise SelectionDependencyBlocked(evidence)
    return evidence


def read_model_calendar(
    client: InjectedSelectClient, *, snapshot_id: str, model_session_dates_sha256: str,
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    if not _SHA.fullmatch(model_session_dates_sha256):
        raise SourceAdapterError("S07 model calendar SHA differs")
    result = _execute(client, CALENDAR_SQL, [snapshot_id])
    raw = _rows(result, ("date",), "session calendar")
    try:
        full = tuple(date.fromisoformat(str(item[0])) for item in raw)
    except ValueError as exc:
        raise SourceAdapterError("session calendar contains invalid dates") from exc
    if not full or tuple(sorted(set(full))) != full or len(full) < EXPECTED_MODEL_DATES:
        raise SourceAdapterError("full session calendar is incomplete or unordered")
    model = full[-EXPECTED_MODEL_DATES:]
    if canonical_sha256([item.isoformat() for item in model]) != model_session_dates_sha256:
        raise SourceAdapterError("last 416 sessions differ from exact S07 calendar")
    return full, model


def read_canonical_market_rows(
    client: InjectedSelectClient, *, snapshot_id: str, expected_row_count: int,
    page_size: int = 4000,
) -> tuple[tuple[object, ...], ...]:
    if type(expected_row_count) is not int or expected_row_count <= 0:
        raise SourceAdapterError("expected market row count must be positive")
    if type(page_size) is not int or not 1 <= page_size <= 10_000:
        raise SourceAdapterError("page size is outside 1..10000")
    output: list[tuple[object, ...]] = []
    last_key: tuple[str, str] | None = None
    while True:
        if last_key is None:
            sql, args = MARKET_FIRST_SQL, [snapshot_id, page_size]
        else:
            sql = MARKET_NEXT_SQL
            args = [snapshot_id, last_key[0], last_key[0], last_key[1], page_size]
        result = _execute(client, sql, args)
        page = _rows(result, MARKET_DAILY_FEATURE_COLUMNS, "canonical market page")
        if len(page) > page_size:
            raise SourceAdapterError("canonical market page exceeds requested bound")
        if not page:
            break
        if len(output) + len(page) > expected_row_count:
            raise SourceAdapterError("canonical market stream exceeds frozen row count")
        first_key = (str(page[0][1]), str(page[0][2]))
        next_key = (str(page[-1][1]), str(page[-1][2]))
        if last_key is not None and first_key <= last_key:
            raise SourceAdapterError("canonical market cursor did not advance")
        if any(str(item[0]) != snapshot_id for item in page):
            raise SourceAdapterError("canonical market page crossed snapshot identity")
        output.extend(page)
        last_key = next_key
    if len(output) != expected_row_count:
        raise SourceAdapterError("canonical market stream differs from frozen row count")
    return tuple(output)


def read_fold_edge_selections(
    client: InjectedSelectClient, *, screening_run_id: str,
    market_snapshot_id: str, model_session_dates: Sequence[date],
) -> tuple[FoldEdgeSelection, ...]:
    preflight_fold_selection_source(
        client, screening_run_id=screening_run_id,
        market_snapshot_id=market_snapshot_id,
    )
    dates = tuple(model_session_dates)
    if len(dates) != EXPECTED_MODEL_DATES:
        raise SourceAdapterError("exact 416-session model calendar is required")
    result = _execute(client, SELECTION_ROWS_SQL, [screening_run_id])
    columns = (
        "ticker", "fold_number", "train_start_date", "train_end_date",
        "test_start_date", "test_end_date", "purge_sessions",
        "selected_depth", "feature_spec_json",
    )
    raw_rows = _rows(result, columns, "fold selections")
    if len(raw_rows) != EXPECTED_SELECTION_ROWS:
        raise SourceAdapterError("fold selection readback changed after coverage preflight")
    selections: list[FoldEdgeSelection] = []
    for raw in raw_rows:
        ticker, fold, train_start, train_end, test_start, test_end, purge, depth, spec_raw = raw
        if type(fold) is not int or not 1 <= fold <= 4:
            raise SourceAdapterError("fold number differs")
        _, train_start_i, train_end_i, test_start_i, test_end_i = EXPECTED_FOLD_GEOMETRY[fold - 1]
        if (
            str(train_start) != dates[train_start_i].isoformat()
            or str(train_end) != dates[train_end_i].isoformat()
            or str(test_start) != dates[test_start_i].isoformat()
            or str(test_end) != dates[test_end_i].isoformat()
            or purge != 7
        ):
            raise SourceAdapterError("fold dates or purge differ from governed geometry")
        try:
            spec = json.loads(str(spec_raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SourceAdapterError("fold feature specification is invalid JSON") from exc
        if set(spec) != {"depth", "lag_tickers", "lag_sessions", "lag_semantics", "technical_features"}:
            raise SourceAdapterError("fold feature specification schema differs")
        lag_tickers = tuple(spec["lag_tickers"])
        lag_sessions = tuple(spec["lag_sessions"])
        if (
            spec["depth"] != depth or depth != len(lag_tickers)
            or len(lag_tickers) != len(lag_sessions) or not 1 <= depth <= 5
            or spec["lag_semantics"] != "target_relative_sessions"
            or spec["technical_features"] != []
        ):
            raise SourceAdapterError("fold specification cannot map exactly to normalized edges")
        edges = tuple(sorted(
            (NormalizedEdge(str(source), int(lag))
             for source, lag in zip(lag_tickers, lag_sessions, strict=True)),
            key=lambda item: (item.source_ticker, item.lag_sessions),
        ))
        artifact_payload = {
            "source_contract": "predictive_screening_fold_metrics.feature_spec_json",
            "screening_run_id": screening_run_id,
            "target_ticker": ticker,
            "fold_number": fold,
            "train_start_date": train_start,
            "train_end_date": train_end,
            "test_start_date": test_start,
            "test_end_date": test_end,
            "purge_sessions": purge,
            "feature_spec": spec,
        }
        selections.append(FoldEdgeSelection(
            target_ticker=str(ticker), fold_number=fold,
            selection_end_ordinal=train_end_i,
            selection_artifact_sha256=canonical_sha256(artifact_payload),
            edges=edges,
        ))
    ordered = tuple(selections)
    expected_keys = tuple(
        (ticker, fold) for ticker in sorted({item.target_ticker for item in ordered})
        for fold in range(1, 5)
    )
    if tuple((item.target_ticker, item.fold_number) for item in ordered) != expected_keys:
        raise SourceAdapterError("fold selections are not canonical 474 x 4 coverage")
    return ordered
