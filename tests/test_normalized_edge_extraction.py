import hashlib
import json
import os

import pytest

from model_lineage import LineageError
from normalized_edge_extraction import (
    COUNT_SQL_BY_TABLE,
    ExpectedArm,
    OPTIONAL_TABLES,
    RESULT_SQL,
    RUN_SQL,
    SCHEMA_DISCOVERY_SQL,
    TERMINAL_DISPOSITION,
    VALIDATED_20260825_ARMS,
    build_normalized_edge_audit,
    read_normalized_edge_audit,
)
from scripts.audit_normalized_screening_edges import _write_durable_evidence, main


SNAPSHOT = "market_features_2026-08-25_fixture"
SOURCE_DATE = "2026-08-25"
CUTOFF = "2026-08-26T07:00:00Z"
CODE = "a" * 40
ARMS = (
    ExpectedArm("run-60", 60, 2, 1, 1, 2),
    ExpectedArm("run-126", 126, 2, 1, 0, 0),
)


def config(window, ticker_count=2):
    return json.dumps(
        {
            "candidate_lags": [1, 2, 3, 4, 5, 6, 7],
            "eligibility_hypotheses": ticker_count,
            "max_depth": 5,
            "min_depth": 1,
            "model_family": "selected_chain",
            "outer_folds": 4,
            "purge_sessions": 7,
            "signal_lookback_governance_status": "ENABLED",
            "signal_lookback_sessions": window,
            "window_semantics_contract_id": "screening-window-separation-v1-20260825",
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def run_rows():
    return [
        {
            "screening_run_id": arm.run_id,
            "market_snapshot_id": SNAPSHOT,
            "source_session_date": SOURCE_DATE,
            "cutoff_utc": CUTOFF,
            "code_version": CODE,
            "config_json": config(arm.signal_lookback_sessions),
            "status": "VALIDATED",
            "snapshot_status": "VALIDATED",
            "expected_ticker_count": 2,
        }
        for arm in ARMS
    ]


def blank(run_id, ticker, *, oos=0, reason="NO_ADMISSIBLE_INNER_SPEC"):
    row = {
        "screening_run_id": run_id,
        "ticker": ticker,
        "eligible": 0,
        "rejection_reason": reason,
        "oos_sessions": oos,
        "selected_depth": None,
        "feature_spec_json": None,
    }
    for position in range(1, 6):
        row[f"lag{position}_ticker"] = None
        row[f"lag{position}_sessions"] = None
    return row


def result_rows():
    edge = blank("run-60", "AAA", oos=120, reason="ACCURACY_CI_DOES_NOT_BEAT_MAJORITY")
    edge.update(
        {
            "selected_depth": 2,
            "lag1_ticker": "BBB",
            "lag2_ticker": "CCC",
            "lag1_sessions": 1,
            "lag2_sessions": 7,
            "feature_spec_json": json.dumps(
                {
                    "depth": 2,
                    "lag_tickers": ["BBB", "CCC"],
                    "lag_sessions": [1, 7],
                    "lag_semantics": "target_relative_sessions",
                    "technical_features": [],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    )
    return [
        edge,
        blank("run-60", "BBB"),
        blank(
            "run-126",
            "AAA",
            oos=120,
            reason="ACCURACY_CI_DOES_NOT_BEAT_MAJORITY,NO_FINAL_ADMISSIBLE_SPECIFICATION",
        ),
        blank("run-126", "BBB"),
    ]


def real_contract_rows():
    tickers = [f"T{number:03d}" for number in range(474)]
    runs = [
        {
            "screening_run_id": arm.run_id,
            "market_snapshot_id": SNAPSHOT,
            "source_session_date": SOURCE_DATE,
            "cutoff_utc": CUTOFF,
            "code_version": CODE,
            "config_json": config(arm.signal_lookback_sessions, ticker_count=474),
            "status": "VALIDATED",
            "snapshot_status": "VALIDATED",
            "expected_ticker_count": 474,
        }
        for arm in VALIDATED_20260825_ARMS
    ]
    rows = []
    specifications = {
        60: [],
        126: [2, 3],
        252: [2, 2, 2, 2, 2, 2, 1, 1],
    }
    evaluated = {60: 0, 126: 3, 252: 20}
    for arm in VALIDATED_20260825_ARMS:
        depths = specifications[arm.signal_lookback_sessions]
        for index, ticker in enumerate(tickers):
            is_evaluated = index < evaluated[arm.signal_lookback_sessions]
            reason = "NO_ADMISSIBLE_INNER_SPEC"
            if is_evaluated:
                reason = "ACCURACY_CI_DOES_NOT_BEAT_MAJORITY,NO_FINAL_ADMISSIBLE_SPECIFICATION"
            row = blank(arm.run_id, ticker, oos=120 if is_evaluated else 0, reason=reason)
            if index < len(depths):
                depth = depths[index]
                predictors = [f"P{index:03d}{position}" for position in range(1, depth + 1)]
                lags = list(range(1, depth + 1))
                row["rejection_reason"] = "ACCURACY_CI_DOES_NOT_BEAT_MAJORITY"
                row["selected_depth"] = depth
                row["feature_spec_json"] = json.dumps(
                    {
                        "depth": depth,
                        "lag_tickers": predictors,
                        "lag_sessions": lags,
                        "lag_semantics": "target_relative_sessions",
                        "technical_features": [],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for position, (predictor, lag) in enumerate(zip(predictors, lags), start=1):
                    row[f"lag{position}_ticker"] = predictor
                    row[f"lag{position}_sessions"] = lag
            rows.append(row)
    return runs, rows


def optional_schema_objects(normalized_counts, downstream_counts, *, present=None):
    present = set(OPTIONAL_TABLES if present is None else present)
    evidence = {}
    for name, (category, key) in OPTIONAL_TABLES.items():
        count = (normalized_counts if category == "normalized" else downstream_counts)[key]
        evidence[name] = (
            {"object_type": "table", "presence": "PRESENT", "row_count": count}
            if name in present
            else {"object_type": None, "presence": "ABSENT", "row_count": None}
        )
    return evidence


def build(**overrides):
    values = {
        "run_rows": run_rows(),
        "result_rows": result_rows(),
        "normalized_counts": {
            "screening_sets": 0,
            "screening_edges": 0,
            "universe_sets": 0,
            "universe_edges": 0,
        },
        "downstream_counts": {"model_runs": 0, "model_scorecards": 0, "etf_priors": 0},
        "expected_arms": ARMS,
        "expected_snapshot_id": SNAPSHOT,
        "expected_source_session_date": SOURCE_DATE,
        "expected_cutoff_utc": CUTOFF,
        "expected_code_version": CODE,
    }
    values.update(overrides)
    if "schema_objects" not in overrides:
        values["schema_objects"] = optional_schema_objects(
            values["normalized_counts"], values["downstream_counts"]
        )
    return build_normalized_edge_audit(**values)


def test_golden_normalization_is_deterministic_order_independent_and_terminal():
    first = build()
    second = build(run_rows=reversed(run_rows()), result_rows=reversed(result_rows()))
    assert first == second
    assert first["disposition"] == TERMINAL_DISPOSITION
    assert first["coverage"] == {
        "runs_observed": 2,
        "runs_expected": 2,
        "result_rows_observed": 4,
        "result_rows_expected": 4,
        "evaluated_rows_inspected": 2,
        "evaluated_rows_expected": 2,
        "extractable_edge_sets": 1,
        "evaluated_without_final_spec": 1,
        "normalized_edges_observed": 2,
        "normalized_edges_expected": 2,
        "eligible_edge_sets": 0,
    }
    edge_set = first["observational_edge_sets"][0]
    assert edge_set["ticker"] == "AAA"
    assert [edge["edge_position"] for edge in edge_set["edges"]] == [1, 2]
    assert len(edge_set["edge_spec_sha256"]) == 64
    payload = dict(first)
    claimed = payload.pop("evidence_sha256")
    assert hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest() == claimed


def test_real_three_arm_contract_has_exact_frozen_denominators_and_edges():
    runs, rows = real_contract_rows()
    evidence = build(
        run_rows=runs,
        result_rows=rows,
        expected_arms=VALIDATED_20260825_ARMS,
    )
    assert evidence["coverage"] == {
        "runs_observed": 3,
        "runs_expected": 3,
        "result_rows_observed": 1422,
        "result_rows_expected": 1422,
        "evaluated_rows_inspected": 23,
        "evaluated_rows_expected": 23,
        "extractable_edge_sets": 10,
        "evaluated_without_final_spec": 13,
        "normalized_edges_observed": 19,
        "normalized_edges_expected": 19,
        "eligible_edge_sets": 0,
    }
    assert len(evidence["observational_edge_sets"]) == 10
    assert sum(len(item["edges"]) for item in evidence["observational_edge_sets"]) == 19


@pytest.mark.parametrize("mutation", ["denominator", "eligible"])
def test_real_three_arm_contract_fails_closed_on_denominator_drift_or_eligible_row(mutation):
    runs, rows = real_contract_rows()
    if mutation == "denominator":
        rows.pop()
    else:
        rows[0]["eligible"] = 1
    with pytest.raises(LineageError):
        build(run_rows=runs, result_rows=rows, expected_arms=VALIDATED_20260825_ARMS)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda runs, rows: runs.__setitem__(0, {**runs[0], "market_snapshot_id": "wrong"}),
        lambda runs, rows: runs.__setitem__(0, {**runs[0], "status": "RUNNING"}),
        lambda runs, rows: runs.append(dict(runs[0])),
        lambda runs, rows: rows.pop(),
        lambda runs, rows: rows.__setitem__(1, {**rows[1], "ticker": "AAA"}),
    ],
)
def test_lineage_duplicate_and_coverage_fail_closed(mutation):
    runs, rows = run_rows(), result_rows()
    mutation(runs, rows)
    with pytest.raises(LineageError):
        build(run_rows=runs, result_rows=rows)


@pytest.mark.parametrize(
    "field,value",
    [
        ("selected_depth", 6),
        ("lag1_ticker", "bbb"),
        ("lag1_sessions", 8),
    ],
)
def test_depth_lag_and_legacy_json_mismatch_fail_closed(field, value):
    rows = result_rows()
    rows[0][field] = value
    with pytest.raises(LineageError):
        build(result_rows=rows)


def test_boolean_integer_aliases_and_config_drift_fail_closed():
    runs = run_rows()
    changed = json.loads(runs[0]["config_json"])
    changed["purge_sessions"] = True
    runs[0]["config_json"] = json.dumps(changed)
    with pytest.raises(LineageError):
        build(run_rows=runs)

    rows = result_rows()
    rows[0]["eligible"] = False
    with pytest.raises(LineageError):
        build(result_rows=rows)


def test_semantics_duplicates_tail_columns_and_missing_terminal_reason_fail_closed():
    rows = result_rows()
    spec = json.loads(rows[0]["feature_spec_json"])
    spec["lag_semantics"] = "forced_chain"
    rows[0]["feature_spec_json"] = json.dumps(spec)
    with pytest.raises(LineageError):
        build(result_rows=rows)

    rows = result_rows()
    spec = json.loads(rows[0]["feature_spec_json"])
    spec["lag_tickers"] = ["BBB", "BBB"]
    spec["lag_sessions"] = [1, 1]
    rows[0]["feature_spec_json"] = json.dumps(spec)
    rows[0]["lag2_ticker"] = "BBB"
    rows[0]["lag2_sessions"] = 1
    with pytest.raises(LineageError, match="duplicated"):
        build(result_rows=rows)

    rows = result_rows()
    rows[0]["lag3_ticker"] = "DDD"
    with pytest.raises(LineageError):
        build(result_rows=rows)

    rows = result_rows()
    rows[2]["rejection_reason"] = "ACCURACY_CI_DOES_NOT_BEAT_MAJORITY"
    with pytest.raises(LineageError):
        build(result_rows=rows)


def test_existing_normalized_or_downstream_outputs_stop_audit():
    with pytest.raises(LineageError, match="not exactly empty"):
        build(normalized_counts={
            "screening_sets": 1, "screening_edges": 0,
            "universe_sets": 0, "universe_edges": 0,
        })
    with pytest.raises(LineageError, match="downstream"):
        build(downstream_counts={"model_runs": 1, "model_scorecards": 0, "etf_priors": 0})


class Result:
    def __init__(self, rows):
        self.columns = list(rows[0]) if rows else []
        self.rows = [[row[column] for column in self.columns] for row in rows]


class Client:
    def __init__(self, *, schema_rows=(), table_counts=None):
        self.calls = []
        self.schema_rows = list(schema_rows)
        self.table_counts = dict(table_counts or {})

    def execute(self, sql, args):
        self.calls.append((sql, args))
        if "FROM predictive_screening_runs" in sql:
            return Result(run_rows())
        if "FROM predictive_screening_results" in sql:
            return Result(result_rows())
        if "FROM sqlite_schema" in sql:
            return Result(self.schema_rows)
        for name, count_sql in COUNT_SQL_BY_TABLE.items():
            if sql == count_sql:
                return Result([{"row_count": self.table_counts[name]}])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_injected_reader_all_optional_tables_absent_uses_only_three_selects():
    client = Client()
    evidence = read_normalized_edge_audit(
        client,
        expected_arms=ARMS,
        expected_snapshot_id=SNAPSHOT,
        expected_source_session_date=SOURCE_DATE,
        expected_cutoff_utc=CUTOFF,
        expected_code_version=CODE,
    )
    assert evidence["coverage"]["normalized_edges_observed"] == 2
    assert len(client.calls) == 3
    assert all(sql.strip().upper().split(None, 1)[0] == "SELECT" for sql, _ in client.calls)
    assert client.calls[0][1] == ["run-126", "run-60"]
    assert client.calls[1][1] == ["run-126", "run-60"]
    assert client.calls[2] == (SCHEMA_DISCOVERY_SQL, sorted(OPTIONAL_TABLES))
    assert all(
        item == {"object_type": None, "presence": "ABSENT", "row_count": None}
        for item in evidence["optional_schema_objects"].values()
    )


def test_injected_reader_present_empty_tables_are_counted_by_exact_allowlist():
    schema_rows = [{"name": name, "type": "table"} for name in sorted(OPTIONAL_TABLES)]
    client = Client(
        schema_rows=schema_rows,
        table_counts={name: 0 for name in OPTIONAL_TABLES},
    )
    evidence = read_normalized_edge_audit(
        client,
        expected_arms=ARMS,
        expected_snapshot_id=SNAPSHOT,
        expected_source_session_date=SOURCE_DATE,
        expected_cutoff_utc=CUTOFF,
        expected_code_version=CODE,
    )
    expected_run_sql = RUN_SQL.format(placeholders="?,?")
    expected_result_sql = RESULT_SQL.format(placeholders="?,?")
    assert [sql for sql, _ in client.calls] == [
        expected_run_sql,
        expected_result_sql,
        SCHEMA_DISCOVERY_SQL,
        *(COUNT_SQL_BY_TABLE[name] for name in sorted(OPTIONAL_TABLES)),
    ]
    assert all(not args for _, args in client.calls[3:])
    assert all(
        item == {"object_type": "table", "presence": "PRESENT", "row_count": 0}
        for item in evidence["optional_schema_objects"].values()
    )


@pytest.mark.parametrize(
    "name,error",
    [
        ("model_runs", "downstream"),
        ("predictive_screening_edges_v2", "not exactly empty"),
    ],
)
def test_injected_reader_present_nonempty_optional_table_fails_closed(name, error):
    client = Client(
        schema_rows=[{"name": name, "type": "table"}],
        table_counts={name: 1},
    )
    with pytest.raises(LineageError, match=error):
        read_normalized_edge_audit(
            client,
            expected_arms=ARMS,
            expected_snapshot_id=SNAPSHOT,
            expected_source_session_date=SOURCE_DATE,
            expected_cutoff_utc=CUTOFF,
            expected_code_version=CODE,
        )


@pytest.mark.parametrize(
    "schema_rows",
    [
        [{"name": "unexpected_table", "type": "table"}],
        [{"name": "model_runs", "type": "view"}],
        [
            {"name": "model_runs", "type": "table"},
            {"name": "model_runs", "type": "table"},
        ],
    ],
)
def test_malformed_schema_discovery_evidence_fails_before_count(schema_rows):
    client = Client(schema_rows=schema_rows, table_counts={"model_runs": 0})
    with pytest.raises(LineageError, match="schema"):
        read_normalized_edge_audit(
            client,
            expected_arms=ARMS,
            expected_snapshot_id=SNAPSHOT,
            expected_source_session_date=SOURCE_DATE,
            expected_cutoff_utc=CUTOFF,
            expected_code_version=CODE,
        )
    assert len(client.calls) == 3


def test_cli_redacts_credentials_and_rejects_wrong_scope(monkeypatch, capsys):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://theoracle-avishe.example.test")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "sensitive-test-token")
    exit_code = main(
        [
            "--run-id", "wrong",
            "--expected-snapshot-id", SNAPSHOT,
            "--expected-source-session-date", SOURCE_DATE,
            "--expected-cutoff-utc", CUTOFF,
            "--expected-code-version", CODE,
        ],
        pipeline_factory=lambda *args, **kwargs: pytest.fail("must not connect"),
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "sensitive-test-token" not in captured.out + captured.err
    assert "libsql://" not in captured.out + captured.err


def test_cli_success_is_deterministic_and_never_prints_connection_material(
    monkeypatch, capsys
):
    import scripts.audit_normalized_screening_edges as module

    captured_factory = {}
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://theoracle-avishe.example.test")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "sensitive-test-token")
    monkeypatch.setattr(
        module,
        "read_normalized_edge_audit",
        lambda db, **kwargs: {"evidence_contract": "fixture", "evidence_sha256": "b" * 64},
    )

    def factory(endpoint, token, **kwargs):
        captured_factory.update(endpoint=endpoint, token=token, kwargs=kwargs)
        return object()

    argv = []
    for arm in module.VALIDATED_20260825_ARMS:
        argv.extend(("--run-id", arm.run_id))
    argv.extend(
        (
            "--expected-snapshot-id", SNAPSHOT,
            "--expected-source-session-date", SOURCE_DATE,
            "--expected-cutoff-utc", CUTOFF,
            "--expected-code-version", CODE,
        )
    )
    assert main(argv, pipeline_factory=factory) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "evidence_contract": "fixture",
        "evidence_sha256": "b" * 64,
    }
    assert output.err == ""
    assert captured_factory["endpoint"] == "https://theoracle-avishe.example.test/v2/pipeline"
    assert "sensitive-test-token" not in output.out + output.err
    assert "libsql://" not in output.out + output.err


def test_cli_redacts_arbitrary_pipeline_exception(monkeypatch, capsys):
    import scripts.audit_normalized_screening_edges as module

    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://theoracle-avishe.example.test")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "sensitive-test-token")
    argv = []
    for arm in module.VALIDATED_20260825_ARMS:
        argv.extend(("--run-id", arm.run_id))
    argv.extend(
        (
            "--expected-snapshot-id", SNAPSHOT,
            "--expected-source-session-date", SOURCE_DATE,
            "--expected-cutoff-utc", CUTOFF,
            "--expected-code-version", CODE,
        )
    )

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive-test-token libsql://hidden.example")

    assert main(argv, pipeline_factory=fail) == 1
    output = capsys.readouterr()
    assert "sensitive-test-token" not in output.out + output.err
    assert "libsql://" not in output.out + output.err


def test_durable_evidence_is_atomic_mode_0600_and_non_overwritable(tmp_path):
    target = tmp_path / "evidence.json"
    _write_durable_evidence(str(target.resolve()), b'{"ok":true}\n')
    assert target.read_bytes() == b'{"ok":true}\n'
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert os.stat(target).st_nlink == 1
    with pytest.raises(FileExistsError):
        _write_durable_evidence(str(target.resolve()), b'{"changed":true}\n')
    assert target.read_bytes() == b'{"ok":true}\n'


def test_durable_evidence_rejects_relative_path_and_existing_symlink(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        _write_durable_evidence("relative.json", b"{}\n")
    target = tmp_path / "evidence.json"
    destination = tmp_path / "destination.json"
    target.symlink_to(destination)
    with pytest.raises(FileExistsError):
        _write_durable_evidence(str(target.absolute()), b"{}\n")
    assert not destination.exists()
