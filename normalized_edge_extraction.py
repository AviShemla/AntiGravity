"""Deterministic SELECT-only audit of legacy screening specifications as normalized edges.

This module performs no database writes and creates no model, recommendation,
order, or ETF-prior output.  It normalizes already-validated observational
screening specifications into evidence records only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from typing import Iterable, Mapping

from model_lineage import LineageError


EVIDENCE_CONTRACT = "normalized-screening-edge-audit-v1"
LAG_SEMANTICS_SOURCE = "target_relative_sessions"
LAG_SEMANTICS_NORMALIZED = "TARGET_RELATIVE_TRADING_SESSIONS"
TERMINAL_DISPOSITION = "NO_ELIGIBLE_NORMALIZED_EDGE_OUTPUT"


@dataclass(frozen=True)
class ExpectedArm:
    run_id: str
    signal_lookback_sessions: int
    expected_ticker_count: int
    expected_evaluated_count: int
    expected_extractable_set_count: int
    expected_edge_count: int


VALIDATED_20260825_ARMS = (
    ExpectedArm("predictive_screening_2026-08-25_w060_2ef4a10", 60, 474, 0, 0, 0),
    ExpectedArm("predictive_screening_2026-08-25_w126_2ef4a10", 126, 474, 3, 2, 5),
    ExpectedArm("predictive_screening_2026-08-25_w252_2ef4a10", 252, 474, 20, 8, 14),
)

RUN_SQL = """SELECT r.screening_run_id,r.market_snapshot_id,r.source_session_date,
       r.cutoff_utc,r.code_version,r.config_json,r.status,
       s.status AS snapshot_status,s.expected_ticker_count
FROM predictive_screening_runs r
JOIN model_input_snapshots s ON s.snapshot_id=r.market_snapshot_id
WHERE r.screening_run_id IN ({placeholders})
ORDER BY r.screening_run_id"""

RESULT_SQL = """SELECT screening_run_id,ticker,eligible,rejection_reason,oos_sessions,
       selected_depth,lag1_ticker,lag2_ticker,lag3_ticker,lag4_ticker,lag5_ticker,
       lag1_sessions,lag2_sessions,lag3_sessions,lag4_sessions,lag5_sessions,
       feature_spec_json
FROM predictive_screening_results
WHERE screening_run_id IN ({placeholders})
ORDER BY screening_run_id,ticker"""

NORMALIZED_COUNT_SQL = """SELECT
 (SELECT COUNT(*) FROM predictive_screening_edge_sets_v2) AS screening_sets,
 (SELECT COUNT(*) FROM predictive_screening_edges_v2) AS screening_edges,
 (SELECT COUNT(*) FROM stock_universe_edge_sets_v2) AS universe_sets,
 (SELECT COUNT(*) FROM stock_universe_edges_v2) AS universe_edges"""

DOWNSTREAM_COUNT_SQL = """SELECT
 (SELECT COUNT(*) FROM model_runs) AS model_runs,
 (SELECT COUNT(*) FROM model_scorecards) AS model_scorecards,
 (SELECT COUNT(*) FROM etf_prior_lineage) AS etf_priors"""

_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LineageError(f"{label} is required.")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LineageError(f"{label} must be an integer >= {minimum}.")
    return value


def _result_rows(result: object, label: str) -> list[dict[str, object]]:
    columns = getattr(result, "columns", None)
    rows = getattr(result, "rows", None)
    if not isinstance(columns, (list, tuple)) or not isinstance(rows, (list, tuple)):
        raise LineageError(f"{label} returned malformed read-only evidence.")
    if len(columns) != len(set(columns)):
        raise LineageError(f"{label} returned duplicate columns.")
    records = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != len(columns):
            raise LineageError(f"{label} returned a malformed row.")
        records.append(dict(zip(columns, row)))
    return records


def _select(db, sql: str, args: list[object], label: str):
    statement = sql.strip()
    if re.match(r"^SELECT\b", statement, re.IGNORECASE) is None or _FORBIDDEN_SQL.search(statement):
        raise LineageError(f"{label} is not a single SELECT-only query.")
    if ";" in statement or "--" in statement or "/*" in statement:
        raise LineageError(f"{label} contains disallowed SQL syntax.")
    return db.execute(statement, args)


def _one_count_row(records: list[dict[str, object]], label: str) -> dict[str, int]:
    if len(records) != 1:
        raise LineageError(f"{label} did not return exactly one row.")
    return {key: _integer(value, f"{label} {key}") for key, value in records[0].items()}


def _validate_lineage_date(value: str, label: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise LineageError(f"{label} is not an ISO calendar date.") from exc
    if parsed.isoformat() != value:
        raise LineageError(f"{label} is not canonical YYYY-MM-DD.")


def _validate_lineage_timestamp(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LineageError(f"{label} is not an ISO timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LineageError(f"{label} must be timezone-aware.")


def _validate_config(raw: object, arm: ExpectedArm) -> str:
    text = _required_text(raw, "screening config_json")
    try:
        config = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise LineageError("screening config_json is invalid.") from exc
    required = {
        "candidate_lags": [1, 2, 3, 4, 5, 6, 7],
        "eligibility_hypotheses": arm.expected_ticker_count,
        "max_depth": 5,
        "min_depth": 1,
        "model_family": "selected_chain",
        "outer_folds": 4,
        "purge_sessions": 7,
        "signal_lookback_governance_status": "ENABLED",
        "signal_lookback_sessions": arm.signal_lookback_sessions,
        "window_semantics_contract_id": "screening-window-separation-v1-20260825",
    }
    integer_fields = (
        "eligibility_hypotheses", "max_depth", "min_depth", "outer_folds",
        "purge_sessions", "signal_lookback_sessions",
    )
    if (
        not isinstance(config, dict)
        or any(config.get(key) != value for key, value in required.items())
        or any(type(config.get(key)) is not int for key in integer_fields)
        or not isinstance(config.get("candidate_lags"), list)
        or any(type(value) is not int for value in config["candidate_lags"])
    ):
        raise LineageError("Screening run configuration differs from the governed edge audit contract.")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized_spec(row: Mapping[str, object]) -> dict[str, object] | None:
    oos = _integer(row.get("oos_sessions"), "oos_sessions")
    depth = row.get("selected_depth")
    raw_spec = row.get("feature_spec_json")
    lag_values = tuple(row.get(f"lag{position}_ticker") for position in range(1, 6))
    session_values = tuple(row.get(f"lag{position}_sessions") for position in range(1, 6))
    if oos == 0:
        if depth is not None or raw_spec is not None or any(
            value is not None for value in lag_values + session_values
        ):
            raise LineageError("Unevaluated screening row contains a fabricated edge specification.")
        return None
    if depth is None and raw_spec is None:
        if any(value is not None for value in lag_values + session_values):
            raise LineageError("Missing final specification has non-null legacy edge columns.")
        reason = _required_text(row.get("rejection_reason"), "evaluated rejection_reason")
        if "NO_FINAL_ADMISSIBLE_SPECIFICATION" not in reason.split(","):
            raise LineageError("Evaluated row without edges lacks the exact terminal reason.")
        return None
    depth = _integer(depth, "selected_depth", minimum=1)
    if depth > 5 or raw_spec is None:
        raise LineageError("Evaluated edge specification has invalid depth or JSON.")
    try:
        spec = json.loads(str(raw_spec))
    except (TypeError, ValueError) as exc:
        raise LineageError("feature_spec_json is invalid.") from exc
    if not isinstance(spec, dict) or set(spec) != {
        "depth", "lag_tickers", "lag_sessions", "lag_semantics", "technical_features"
    }:
        raise LineageError("feature_spec_json keys are not exact.")
    tickers = spec.get("lag_tickers")
    sessions = spec.get("lag_sessions")
    technical = spec.get("technical_features")
    if (
        type(spec.get("depth")) is not int
        or spec.get("depth") != depth
        or spec.get("lag_semantics") != LAG_SEMANTICS_SOURCE
        or not isinstance(tickers, list)
        or not isinstance(sessions, list)
        or not isinstance(technical, list)
        or len(tickers) != depth
        or len(sessions) != depth
        or any(not isinstance(value, str) for value in technical)
    ):
        raise LineageError("feature_spec_json shape or semantics are invalid.")
    edges = []
    identities = set()
    for position, (predictor, lag) in enumerate(zip(tickers, sessions, strict=True), start=1):
        predictor = _required_text(predictor, "predictor_ticker")
        if predictor != predictor.strip().upper():
            raise LineageError("predictor_ticker is not normalized uppercase.")
        lag = _integer(lag, "lag_sessions", minimum=1)
        if lag > 7:
            raise LineageError("lag_sessions exceeds the governed 1..7 domain.")
        if (predictor, lag) in identities:
            raise LineageError("Normalized edge identities are duplicated within a set.")
        identities.add((predictor, lag))
        if row.get(f"lag{position}_ticker") != predictor or row.get(f"lag{position}_sessions") != lag:
            raise LineageError("feature_spec_json differs from legacy edge columns.")
        edges.append({
            "edge_position": position,
            "predictor_ticker": predictor,
            "lag_sessions": lag,
            "lag_semantics": LAG_SEMANTICS_NORMALIZED,
        })
    for position in range(depth + 1, 6):
        if row.get(f"lag{position}_ticker") is not None or row.get(f"lag{position}_sessions") is not None:
            raise LineageError("Legacy edge columns beyond declared depth are not null.")
    digest_payload = {
        "declared_depth": depth,
        "lag_semantics": LAG_SEMANTICS_NORMALIZED,
        "edges": edges,
    }
    return {
        "declared_depth": depth,
        "lag_semantics": LAG_SEMANTICS_NORMALIZED,
        "edge_spec_sha256": hashlib.sha256(_canonical_json(digest_payload)).hexdigest(),
        "edges": edges,
    }


def build_normalized_edge_audit(
    *,
    run_rows: Iterable[Mapping[str, object]],
    result_rows: Iterable[Mapping[str, object]],
    normalized_counts: Mapping[str, int],
    downstream_counts: Mapping[str, int],
    expected_arms: tuple[ExpectedArm, ...],
    expected_snapshot_id: str,
    expected_source_session_date: str,
    expected_cutoff_utc: str,
    expected_code_version: str,
) -> dict[str, object]:
    arms = {arm.run_id: arm for arm in expected_arms}
    if not arms or len(arms) != len(expected_arms):
        raise LineageError("Expected normalized-edge arms are empty or duplicated.")
    _required_text(expected_snapshot_id, "expected_snapshot_id")
    _validate_lineage_date(expected_source_session_date, "expected_source_session_date")
    _validate_lineage_timestamp(expected_cutoff_utc, "expected_cutoff_utc")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_code_version):
        raise LineageError("expected_code_version must be a Git commit.")

    run_by_id: dict[str, Mapping[str, object]] = {}
    config_hashes: dict[str, str] = {}
    for row in run_rows:
        run_id = _required_text(row.get("screening_run_id"), "screening_run_id")
        if run_id not in arms or run_id in run_by_id:
            raise LineageError("Screening run identity is unexpected or duplicated.")
        arm = arms[run_id]
        if (
            row.get("market_snapshot_id") != expected_snapshot_id
            or row.get("source_session_date") != expected_source_session_date
            or row.get("cutoff_utc") != expected_cutoff_utc
            or row.get("code_version") != expected_code_version
            or row.get("status") != "VALIDATED"
            or row.get("snapshot_status") != "VALIDATED"
            or row.get("expected_ticker_count") != arm.expected_ticker_count
        ):
            raise LineageError("Screening run or snapshot lineage differs from the exact audit scope.")
        config_hashes[run_id] = _validate_config(row.get("config_json"), arm)
        run_by_id[run_id] = row
    if set(run_by_id) != set(arms):
        raise LineageError("Screening run coverage is incomplete.")

    by_run: dict[str, list[Mapping[str, object]]] = {run_id: [] for run_id in arms}
    seen_keys = set()
    for row in result_rows:
        run_id = _required_text(row.get("screening_run_id"), "result screening_run_id")
        ticker = _required_text(row.get("ticker"), "result ticker")
        if run_id not in arms or ticker != ticker.strip().upper() or (run_id, ticker) in seen_keys:
            raise LineageError("Screening result identity is unexpected, unnormalized, or duplicated.")
        seen_keys.add((run_id, ticker))
        by_run[run_id].append(row)
    ticker_sets = []
    normalized_sets = []
    arm_summaries = []
    for run_id in sorted(arms):
        arm = arms[run_id]
        rows = sorted(by_run[run_id], key=lambda row: str(row["ticker"]))
        tickers = tuple(str(row["ticker"]) for row in rows)
        if len(rows) != arm.expected_ticker_count or len(set(tickers)) != arm.expected_ticker_count:
            raise LineageError("Screening result coverage differs from the frozen denominator.")
        ticker_sets.append(set(tickers))
        evaluated = 0
        extractable = 0
        edge_count = 0
        for row in rows:
            eligible = row.get("eligible")
            if type(eligible) is not int or eligible != 0:
                raise LineageError("Exact no-output audit encountered an eligible screening row.")
            _required_text(row.get("rejection_reason"), "non-eligible rejection_reason")
            if _integer(row.get("oos_sessions"), "oos_sessions") > 0:
                evaluated += 1
            spec = _normalized_spec(row)
            if spec is not None:
                extractable += 1
                edge_count += int(spec["declared_depth"])
                normalized_sets.append({
                    "screening_run_id": run_id,
                    "ticker": row["ticker"],
                    "source_eligible": False,
                    **spec,
                })
        if (evaluated, extractable, edge_count) != (
            arm.expected_evaluated_count,
            arm.expected_extractable_set_count,
            arm.expected_edge_count,
        ):
            raise LineageError("Observed evaluated/spec/edge counts differ from preregistered evidence.")
        arm_summaries.append({
            "screening_run_id": run_id,
            "signal_lookback_sessions": arm.signal_lookback_sessions,
            "result_rows": len(rows),
            "evaluated_rows": evaluated,
            "extractable_edge_sets": extractable,
            "evaluated_without_final_spec": evaluated - extractable,
            "normalized_edges": edge_count,
            "eligible_rows": 0,
            "config_sha256": config_hashes[run_id],
        })
    if any(tickers != ticker_sets[0] for tickers in ticker_sets[1:]):
        raise LineageError("Validated screening arms do not share the exact ticker universe.")
    expected_zero = {"screening_sets", "screening_edges", "universe_sets", "universe_edges"}
    if set(normalized_counts) != expected_zero or any(normalized_counts.values()):
        raise LineageError("Normalized production edge tables are not exactly empty.")
    expected_downstream = {"model_runs", "model_scorecards", "etf_priors"}
    if set(downstream_counts) != expected_downstream or any(downstream_counts.values()):
        raise LineageError("Unauthorized downstream model or ETF outputs exist.")
    normalized_sets.sort(key=lambda item: (str(item["screening_run_id"]), str(item["ticker"])))
    payload: dict[str, object] = {
        "evidence_contract": EVIDENCE_CONTRACT,
        "disposition": TERMINAL_DISPOSITION,
        "lineage": {
            "market_snapshot_id": expected_snapshot_id,
            "source_session_date": expected_source_session_date,
            "cutoff_utc": expected_cutoff_utc,
            "code_version": expected_code_version,
        },
        "coverage": {
            "runs_observed": len(expected_arms),
            "runs_expected": len(expected_arms),
            "result_rows_observed": sum(item.expected_ticker_count for item in expected_arms),
            "result_rows_expected": sum(item.expected_ticker_count for item in expected_arms),
            "evaluated_rows_inspected": sum(item.expected_evaluated_count for item in expected_arms),
            "evaluated_rows_expected": sum(item.expected_evaluated_count for item in expected_arms),
            "extractable_edge_sets": sum(item.expected_extractable_set_count for item in expected_arms),
            "evaluated_without_final_spec": sum(
                item.expected_evaluated_count - item.expected_extractable_set_count
                for item in expected_arms
            ),
            "normalized_edges_observed": sum(item.expected_edge_count for item in expected_arms),
            "normalized_edges_expected": sum(item.expected_edge_count for item in expected_arms),
            "eligible_edge_sets": 0,
        },
        "arms": arm_summaries,
        "observational_edge_sets": normalized_sets,
        "normalized_table_counts": dict(sorted(normalized_counts.items())),
        "downstream_counts": dict(sorted(downstream_counts.items())),
        "database_writes": 0,
        "model_fits": 0,
        "etf_prior_outputs": 0,
    }
    payload["evidence_sha256"] = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return payload


def read_normalized_edge_audit(
    db,
    *,
    expected_arms: tuple[ExpectedArm, ...],
    expected_snapshot_id: str,
    expected_source_session_date: str,
    expected_cutoff_utc: str,
    expected_code_version: str,
) -> dict[str, object]:
    run_ids = sorted(arm.run_id for arm in expected_arms)
    placeholders = ",".join("?" for _ in run_ids)
    run_rows = _result_rows(
        _select(db, RUN_SQL.format(placeholders=placeholders), run_ids, "run query"),
        "run query",
    )
    result_rows = _result_rows(
        _select(db, RESULT_SQL.format(placeholders=placeholders), run_ids, "result query"),
        "result query",
    )
    normalized_counts = _one_count_row(
        _result_rows(_select(db, NORMALIZED_COUNT_SQL, [], "normalized count query"), "normalized count query"),
        "normalized count query",
    )
    downstream_counts = _one_count_row(
        _result_rows(_select(db, DOWNSTREAM_COUNT_SQL, [], "downstream count query"), "downstream count query"),
        "downstream count query",
    )
    return build_normalized_edge_audit(
        run_rows=run_rows,
        result_rows=result_rows,
        normalized_counts=normalized_counts,
        downstream_counts=downstream_counts,
        expected_arms=expected_arms,
        expected_snapshot_id=expected_snapshot_id,
        expected_source_session_date=expected_source_session_date,
        expected_cutoff_utc=expected_cutoff_utc,
        expected_code_version=expected_code_version,
    )
