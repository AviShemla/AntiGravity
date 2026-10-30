import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from model_lineage import LineageError
from normalized_edge_extraction import ExpectedArm, VALIDATED_20260825_ARMS
from simple_screening_baseline_audit import (
    RESULT_SQL,
    RUN_SQL,
    build_simple_baseline_audit,
    read_simple_baseline_audit,
)
from scripts.audit_simple_screening_baselines import main
from scripts.audit_simple_screening_baselines import run_audit_cli


SNAPSHOT = "market_features_2026-08-25_5b1044ee45605a3d"
SOURCE_DATE = "2026-08-25"
CUTOFF = "2026-08-26T07:00:00Z"
CODE = "2ef4a1082c91c023b9b0204611730492f03ad576"
EXECUTOR = "a" * 40


def config(window, count):
    return json.dumps(
        {
            "candidate_lags": [1, 2, 3, 4, 5, 6, 7],
            "eligibility_hypotheses": count,
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


def fixture(arms=VALIDATED_20260825_ARMS):
    runs = [
        {
            "screening_run_id": arm.run_id,
            "market_snapshot_id": SNAPSHOT,
            "source_session_date": SOURCE_DATE,
            "cutoff_utc": "2026-08-26T07:00:00+00:00",
            "code_version": CODE,
            "config_json": config(arm.signal_lookback_sessions, arm.expected_ticker_count),
            "status": "VALIDATED",
            "snapshot_status": "VALIDATED",
            "expected_ticker_count": arm.expected_ticker_count,
        }
        for arm in arms
    ]
    rows = []
    for arm in arms:
        for index in range(arm.expected_ticker_count):
            evaluated = index < arm.expected_evaluated_count
            row = {
                "screening_run_id": arm.run_id,
                "ticker": f"T{index:03d}",
                "eligible": 0,
                "rejection_reason": "ACCURACY_CI_DOES_NOT_BEAT_MAJORITY" if evaluated else "NO_ADMISSIBLE_INNER_SPEC",
                "oos_sessions": 60 if evaluated else 0,
            }
            values = {
                "oos_accuracy": 0.51 + (index % 2) / 100,
                "accuracy_ci_low": 0.35,
                "accuracy_ci_high": 0.67,
                "brier_score": 0.25,
                "log_loss": 0.70,
                "calibration_error": 0.09,
                "majority_accuracy": 0.50,
                "own_lag_accuracy": 0.49,
                "own_lag_brier": 0.26,
            }
            row.update(values if evaluated else {key: None for key in values})
            rows.append(row)
    return runs, rows


def build(runs=None, rows=None, arms=VALIDATED_20260825_ARMS):
    base_runs, base_rows = fixture(arms)
    return build_simple_baseline_audit(
        run_rows=base_runs if runs is None else runs,
        result_rows=base_rows if rows is None else rows,
        expected_arms=arms,
        expected_snapshot_id=SNAPSHOT,
        expected_source_session_date=SOURCE_DATE,
        expected_cutoff_utc=CUTOFF,
        expected_code_version=CODE,
    )


def test_real_three_arm_contract_has_exact_denominators_and_separates_baselines():
    evidence = build()
    assert evidence["coverage"] == {
        "runs_observed": 3,
        "runs_expected": 3,
        "result_rows_observed": 1422,
        "result_rows_expected": 1422,
        "evaluated_rows_observed": 23,
        "evaluated_rows_expected": 23,
        "unevaluated_rows_observed": 1399,
        "unevaluated_rows_expected": 1399,
        "eligible_rows": 0,
    }
    assert [arm["evaluated_count"] for arm in evidence["arms"]] == [0, 3, 20]
    record = evidence["evaluated_screening_records"][0]
    assert set(record["candidate_screening_metrics"]) == {
        "oos_accuracy", "accuracy_ci_low", "accuracy_ci_high", "brier_score",
        "log_loss", "calibration_error",
    }
    assert set(record["simple_baselines"]) == {
        "training_fold_majority_direction_accuracy",
        "own_lag_direction_accuracy",
        "own_lag_direction_brier",
    }
    assert evidence["side_effects"] == {
        "database_writes": 0,
        "model_fits": 0,
        "predictions_created": 0,
        "recommendations_created": 0,
        "orders_created": 0,
        "etf_priors_created": 0,
    }
    payload = dict(evidence)
    claimed = payload.pop("evidence_sha256")
    assert hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest() == claimed


def test_deterministic_under_input_reordering():
    runs, rows = fixture()
    assert build(runs=runs, rows=rows) == build(runs=reversed(runs), rows=reversed(rows))


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda rows: rows[474].update(majority_accuracy=None), "stored finite"),
        (lambda rows: rows[-1].update(own_lag_brier=0.2), "fabricated"),
        (lambda rows: rows[474].update(oos_accuracy=float("nan")), "finite"),
        (lambda rows: rows[474].update(majority_accuracy=True), "stored finite"),
        (lambda rows: rows[474].update(accuracy_ci_low=0.60), "confidence interval"),
        (lambda rows: rows[474].update(eligible=1), "zero eligible"),
        (lambda rows: rows[474].update(eligible=False), "integer"),
        (lambda rows: rows[-1].update(rejection_reason=""), "rejection_reason"),
    ],
)
def test_metric_and_eligibility_contracts_fail_closed(mutation, match):
    runs, rows = fixture()
    mutation(rows)
    with pytest.raises(LineageError, match=match):
        build(runs=runs, rows=rows)


def test_denominator_and_shared_universe_drift_fail_closed():
    runs, rows = fixture()
    with pytest.raises(LineageError, match="denominator"):
        build(runs=runs, rows=rows[:-1])
    runs, rows = fixture()
    rows[-1]["ticker"] = "DIFFERENT"
    with pytest.raises(LineageError, match="exact ticker universe"):
        build(runs=runs, rows=rows)


def test_lineage_and_config_drift_fail_closed():
    runs, rows = fixture()
    runs[0]["market_snapshot_id"] = "wrong"
    with pytest.raises(LineageError, match="lineage"):
        build(runs=runs, rows=rows)
    runs, rows = fixture()
    changed = json.loads(runs[0]["config_json"])
    changed["outer_folds"] = 3
    runs[0]["config_json"] = json.dumps(changed)
    with pytest.raises(LineageError, match="configuration"):
        build(runs=runs, rows=rows)


class Result:
    def __init__(self, records):
        self.columns = list(records[0]) if records else []
        self.rows = [[record[column] for column in self.columns] for record in records]


class Reader:
    def __init__(self, runs, rows):
        self.runs = runs
        self.rows = rows
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        return Result(self.runs if "FROM predictive_screening_runs" in sql else self.rows)


def test_reader_issues_exact_two_selects_with_exact_bindings():
    runs, rows = fixture()
    reader = Reader(runs, rows)
    evidence = read_simple_baseline_audit(
        reader,
        expected_snapshot_id=SNAPSHOT,
        expected_source_session_date=SOURCE_DATE,
        expected_cutoff_utc=CUTOFF,
        expected_code_version=CODE,
    )
    expected_ids = sorted(arm.run_id for arm in VALIDATED_20260825_ARMS)
    assert len(reader.calls) == 2
    assert reader.calls[0] == (RUN_SQL.format(placeholders="?,?,?"), expected_ids)
    assert reader.calls[1] == (RESULT_SQL.format(placeholders="?,?,?"), expected_ids)
    assert evidence["coverage"]["result_rows_observed"] == 1422
    assert all(call[0].lstrip().upper().startswith("SELECT") for call in reader.calls)


def cli_args(output, env_file):
    result = []
    for arm in VALIDATED_20260825_ARMS:
        result += ["--run-id", arm.run_id]
    return result + [
        "--expected-snapshot-id", SNAPSHOT,
        "--expected-source-session-date", SOURCE_DATE,
        "--expected-cutoff-utc", CUTOFF,
        "--expected-code-version", CODE,
        "--executor-git-commit", EXECUTOR,
        "--env-file", str(env_file.resolve()),
        "--evidence-json", str(output.resolve()),
    ]


def test_cli_writes_mode_0600_durable_evidence_and_never_overwrites(tmp_path, monkeypatch):
    runs, rows = fixture()
    reader = Reader(runs, rows)
    env_file = tmp_path / "production.env"
    env_file.write_text("unused=test-only\n", encoding="utf-8")
    env_file.chmod(0o600)
    created = []

    def factory(endpoint, token, timeout_seconds):
        created.append((endpoint, token, timeout_seconds))
        return reader

    target = tmp_path / "baseline-evidence.json"
    injected = {
        "credentials_loader": lambda _: (
            "libsql://theoracle-test.turso.io",
            "test-only-token",
            "https://theoracle-test.turso.io/v2/pipeline",
        ),
        "pipeline_factory": factory,
        "effective_uid": lambda: 0,
        "time_source": lambda: __import__("datetime").datetime(
            2026, 8, 26, 22, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    }
    assert main(cli_args(target, env_file), **injected) == 0
    metadata = target.stat(follow_symlinks=False)
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1
    payload = json.loads(target.read_text())
    assert payload["coverage"]["evaluated_rows_observed"] == 23
    assert payload["audit_runtime"] == {
        "executor_git_commit": EXECUTOR,
        "observed_at_utc": "2026-08-26T22:00:00Z",
    }
    original = target.read_bytes()
    assert main(cli_args(target, env_file), **injected) == 1
    assert target.read_bytes() == original
    assert len(created) == 2


def test_cli_rejects_wrong_run_set_before_connection(tmp_path, monkeypatch):
    env_file = tmp_path / "production.env"
    env_file.write_text("unused=test-only\n", encoding="utf-8")
    env_file.chmod(0o600)
    called = []
    assert main([
        "--run-id", "wrong", "--expected-snapshot-id", SNAPSHOT,
        "--expected-source-session-date", SOURCE_DATE, "--expected-cutoff-utc", CUTOFF,
        "--expected-code-version", CODE, "--executor-git-commit", EXECUTOR,
        "--env-file", str(env_file.resolve()),
        "--evidence-json", str((tmp_path / "x.json").resolve()),
    ], credentials_loader=lambda path: called.append(path), effective_uid=lambda: 0) == 1
    assert called == []


def test_cli_redacts_arbitrary_exception_text(tmp_path, monkeypatch, capsys):
    secret = "libsql://token-value@host"
    env_file = tmp_path / "production.env"
    env_file.write_text("unused=test-only\n", encoding="utf-8")
    env_file.chmod(0o600)

    def failure(*args, **kwargs):
        raise RuntimeError(secret)

    assert main(
        cli_args(tmp_path / "x.json", env_file),
        credentials_loader=lambda _: (
            "libsql://theoracle-test.turso.io",
            "token-value",
            "https://theoracle-test.turso.io/v2/pipeline",
        ),
        pipeline_factory=failure,
        effective_uid=lambda: 0,
    ) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "token-value" not in captured.out + captured.err


def test_cli_requires_root_absolute_env_and_exact_executor_before_credentials(tmp_path):
    env_file = tmp_path / "production.env"
    env_file.write_text("unused=test-only\n", encoding="utf-8")
    env_file.chmod(0o600)
    target = tmp_path / "x.json"
    called = []
    args = cli_args(target, env_file)
    with pytest.raises(LineageError, match="run as root"):
        run_audit_cli(args, credentials_loader=lambda path: called.append(path), effective_uid=lambda: 1)
    assert called == []

    relative = list(args)
    relative[relative.index("--env-file") + 1] = "production.env"
    with pytest.raises(LineageError, match="must be absolute"):
        run_audit_cli(relative, credentials_loader=lambda path: called.append(path), effective_uid=lambda: 0)
    assert called == []

    bad_commit = list(args)
    bad_commit[bad_commit.index("--executor-git-commit") + 1] = "not-a-commit"
    with pytest.raises(LineageError, match="exact lowercase SHA-1"):
        run_audit_cli(
            bad_commit,
            credentials_loader=lambda _: (
                "libsql://theoracle-test.turso.io",
                "token",
                "https://theoracle-test.turso.io/v2/pipeline",
            ),
            pipeline_factory=lambda *args, **kwargs: Reader(*fixture()),
            effective_uid=lambda: 0,
        )


def test_direct_file_execution_from_unrelated_cwd_has_no_import_failure(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_simple_screening_baselines.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"], cwd=tmp_path, capture_output=True, text=True
    )
    assert completed.returncode == 0
    assert "ModuleNotFoundError" not in completed.stderr
