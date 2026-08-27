#!/usr/bin/env python3
"""Independently audit the common full-universe simple-baseline artifacts.

The validation logic is standard-library-only.  At the CLI boundary it uses the
deployed, digest-bound Turso read client for two strictly SELECT-only independent
readbacks.  It treats the producer's terminal status as untrusted, reopens every
persisted artifact, recomputes all digest and accumulator relationships, and
writes one immutable audit artifact only after the complete contract is proven.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlsplit


class AuditError(RuntimeError):
    """Raised when independent completion evidence is not exact."""


AUDIT_CONTRACT_ID = "full-universe-common-simple-baselines-audit-v1"
PRODUCER_CONTRACT_ID = "full-universe-common-simple-baselines-v1"
SNAPSHOT_ID = "market_features_2026-08-25_5b1044ee45605a3d"
SOURCE_SESSION_DATE = "2026-08-25"
EXPECTED_SESSIONS = 1246
SESSION_SHA256 = "030b17a6d94cfebdd24582b8206357b6905c58e5b3d10796b0c8ee3c87b53eeb"
EXPECTED_TICKERS = 474
EXPECTED_FOLDS_PER_TICKER = 4
EXPECTED_TEST_OBSERVATIONS = 30
EXPECTED_OOS_PER_TICKER = EXPECTED_FOLDS_PER_TICKER * EXPECTED_TEST_OBSERVATIONS
EXPECTED_TOTAL_FOLDS = EXPECTED_TICKERS * EXPECTED_FOLDS_PER_TICKER
EXPECTED_TOTAL_OOS = EXPECTED_TICKERS * EXPECTED_OOS_PER_TICKER
MODEL_NAMES = ("majority_direction", "constant_training_rate", "lag1_logistic")
ZERO_SIDE_EFFECTS = {
    "database_writes": 0,
    "bayesian_fits": 0,
    "predictions": 0,
    "recommendations": 0,
    "orders": 0,
    "etf_outputs": 0,
}
REQUIRED_EXECUTOR_ARTIFACTS = {
    "full_universe_simple_baselines.py",
    "scripts/run_full_universe_simple_baselines.py",
    "scripts/audit_full_universe_simple_baselines.py",
    "turso_read_pipeline.py",
    "predictive_screener.py",
    "model_lineage.py",
    "stock_lag_governance.py",
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}")
_TICKER = re.compile(r"[A-Z0-9.^-]{1,24}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|"
    r"PRAGMA|VACUUM)\b", re.IGNORECASE)

SESSION_SQL = """SELECT DISTINCT date FROM market_daily_features
 WHERE snapshot_id=? ORDER BY date"""
DOWNSTREAM_TABLES = (
    "model_runs", "model_scorecards", "etf_prior_lineage",
    "stock_prediction_decision_audits", "stock_prediction_criterion_audits",
    "execution_plans", "execution_events", "execution_plan_approvals",
)
SCHEMA_SQL = """SELECT name,type FROM sqlite_schema
 WHERE name IN (?,?,?,?,?,?,?,?) ORDER BY name"""
DOWNSTREAM_COUNT_FRAGMENTS = {
    "model_runs": "SELECT COUNT(*) FROM model_runs WHERE code_version=?",
    "model_scorecards": "SELECT COUNT(*) FROM model_scorecards s JOIN model_runs r"
                        " ON r.run_id=s.run_id WHERE r.code_version=?",
    "etf_prior_lineage": "SELECT COUNT(*) FROM etf_prior_lineage e JOIN model_runs r"
                         " ON r.run_id=e.etf_run_id WHERE r.code_version=?",
    "stock_prediction_decision_audits":
        "SELECT COUNT(*) FROM stock_prediction_decision_audits a JOIN model_runs r"
        " ON r.run_id=a.model_run_id WHERE r.code_version=?",
    "stock_prediction_criterion_audits":
        "SELECT COUNT(*) FROM stock_prediction_criterion_audits c"
        " JOIN stock_prediction_decision_audits a ON a.audit_id=c.audit_id"
        " JOIN model_runs r ON r.run_id=a.model_run_id WHERE r.code_version=?",
    "execution_plans": "SELECT COUNT(*) FROM execution_plans WHERE code_version=?",
    "execution_events": "SELECT COUNT(*) FROM execution_events e JOIN execution_plans p"
                        " ON p.plan_id=e.plan_id WHERE p.code_version=?",
    "execution_plan_approvals":
        "SELECT COUNT(*) FROM execution_plan_approvals a JOIN execution_plans p"
        " ON p.plan_id=a.plan_id WHERE p.code_version=?",
}
DOWNSTREAM_DEPENDENCIES = {
    "model_scorecards": "model_runs",
    "etf_prior_lineage": "model_runs",
    "stock_prediction_decision_audits": "model_runs",
    "stock_prediction_criterion_audits": "stock_prediction_decision_audits",
    "execution_events": "execution_plans",
    "execution_plan_approvals": "execution_plans",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize_turso_pipeline_endpoint(raw: str) -> str:
    """Normalize an exact Turso database URL to its HTTPS pipeline endpoint."""
    if (not isinstance(raw, str) or raw != raw.strip() or not raw or
            any(ord(character) < 0x21 or ord(character) > 0x7e for character in raw) or
            "\\" in raw or "%" in raw or "?" in raw or "#" in raw):
        raise AuditError("Turso database URL is invalid")
    if raw.startswith("libsql://"):
        endpoint = "https://" + raw[len("libsql://"):]
    elif raw.startswith("https://"):
        endpoint = raw
    else:
        raise AuditError("Turso database URL scheme is invalid")
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise AuditError("Turso database URL shape is invalid") from exc
    hostname = parsed.hostname
    if (parsed.scheme != "https" or not hostname or parsed.username is not None or
            parsed.password is not None or parsed.query or parsed.fragment or
            parsed.path not in ("", "/", "/v2/pipeline") or
            parsed.netloc != hostname or
            re.fullmatch(
                r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                hostname,
            ) is None):
        raise AuditError("Turso database URL shape is invalid")
    return endpoint.rstrip("/") if parsed.path == "/v2/pipeline" else endpoint.rstrip("/") + "/v2/pipeline"


def checkpoint_name(ticker: str) -> str:
    return f"ticker-{hashlib.sha256(ticker.encode('utf-8')).hexdigest()[:24]}.json"


def _reject_constant(value: str) -> object:
    raise AuditError("artifact JSON contains a non-finite number")


def _unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AuditError("artifact JSON contains a duplicate key")
        result[key] = value
    return result


def decode_json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError("artifact is not strict UTF-8 JSON") from exc


def _records(result: object, columns: Sequence[str], label: str) -> list[dict[str, object]]:
    if tuple(getattr(result, "columns", ())) != tuple(columns):
        raise AuditError(f"{label} column contract differs")
    output: list[dict[str, object]] = []
    for row in getattr(result, "rows", ()):
        if not isinstance(row, (list, tuple)) or len(row) != len(columns):
            raise AuditError(f"{label} returned malformed evidence")
        output.append(dict(zip(columns, row)))
    return output


def select_only(db, sql: str, args: list[object], label: str):
    statement = " ".join(sql.split())
    if (not statement.upper().startswith("SELECT ") or _FORBIDDEN_SQL.search(statement) or
            ";" in statement or "--" in statement or "/*" in statement):
        raise AuditError(f"{label} is not SELECT-only")
    return db.execute(statement, args)


def read_live_evidence(db, executor_git_commit: str) -> dict[str, object]:
    """Read the pinned calendar and downstream absence without trusting artifacts."""
    session_rows = _records(
        select_only(db, SESSION_SQL, [SNAPSHOT_ID], "session calendar"),
        ("date",), "session calendar")
    sessions = [row["date"] for row in session_rows]
    if (len(sessions) != EXPECTED_SESSIONS or len(set(sessions)) != EXPECTED_SESSIONS or
            any(not isinstance(value, str) or not _ISO_DATE.fullmatch(value)
                for value in sessions) or sessions != sorted(sessions) or
            sessions[-1] != SOURCE_SESSION_DATE or canonical_sha(sessions) != SESSION_SHA256):
        raise AuditError("live pinned session calendar differs")
    schema_rows = _records(select_only(
        db, SCHEMA_SQL, list(DOWNSTREAM_TABLES), "downstream schema"),
        ("name", "type"), "downstream schema")
    present: set[str] = set()
    for row in schema_rows:
        name, kind = row["name"], row["type"]
        if (not isinstance(name, str) or name not in DOWNSTREAM_TABLES or
                name in present or kind != "table"):
            raise AuditError("downstream schema evidence is malformed")
        present.add(name)
    for child, parent in DOWNSTREAM_DEPENDENCIES.items():
        if child in present and parent not in present:
            raise AuditError(f"downstream schema has {child} without required parent {parent}")
    ordered_present = [name for name in DOWNSTREAM_TABLES if name in present]
    if ordered_present:
        count_sql = "SELECT " + ", ".join(
            f"({DOWNSTREAM_COUNT_FRAGMENTS[name]}) AS {name}" for name in ordered_present)
        count_columns = tuple(ordered_present)
        count_args = [executor_git_commit] * len(ordered_present)
    else:
        count_sql = "SELECT 0 AS no_present_downstream_tables"
        count_columns = ("no_present_downstream_tables",)
        count_args = []
    count_rows = _records(select_only(db, count_sql, count_args, "downstream absence"),
                          count_columns, "downstream absence")
    if len(count_rows) != 1:
        raise AuditError("downstream absence did not return one exact row")
    returned = count_rows[0]
    if any(type(returned[name]) is not int or returned[name] != 0 for name in count_columns):
        raise AuditError("unauthorized downstream output exists for executor commit")
    schema_presence = {
        name: ("present" if name in present else "schema_absent")
        for name in DOWNSTREAM_TABLES
    }
    downstream = {name: (returned[name] if name in present else 0)
                  for name in DOWNSTREAM_TABLES}
    return {
        "snapshot_id": SNAPSHOT_ID,
        "source_session_date": SOURCE_SESSION_DATE,
        "session_count": len(sessions),
        "session_sha256": canonical_sha(sessions),
        "sessions": sessions,
        "schema_presence": schema_presence,
        "downstream_counts": downstream,
        "select_statements": 3,
    }


def _exact_dict(value: object, keys: Iterable[str], label: str) -> dict[str, object]:
    expected = set(keys)
    if not isinstance(value, dict) or set(value) != expected:
        raise AuditError(f"{label} schema differs")
    return value


def _finite_number(value: object, label: str, *, minimum: float | None = None,
                   maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuditError(f"{label} is not numeric")
    number = float(value)
    if (not math.isfinite(number) or (minimum is not None and number < minimum) or
            (maximum is not None and number > maximum)):
        raise AuditError(f"{label} is outside its contract")
    return number


def _metrics(accumulator: Mapping[str, object]) -> dict[str, float]:
    observations = int(accumulator["observations"])
    if observations <= 0:
        raise AuditError("metric accumulator is empty")
    calibration = 0.0
    for item in accumulator["calibration_bins"]:  # type: ignore[index]
        count = int(item["count"])
        if count:
            calibration += (count / observations) * abs(
                int(item["truth_sum"]) / count - float(item["probability_sum"]) / count)
    return {
        "accuracy": int(accumulator["correct"]) / observations,
        "brier": float(accumulator["brier_sum"]) / observations,
        "log_loss": float(accumulator["log_loss_sum"]) / observations,
        "calibration_error": calibration,
    }


def _validate_accumulator(value: object, observations: int, label: str) -> dict[str, object]:
    accumulator = _exact_dict(value, {
        "observations", "correct", "brier_sum", "log_loss_sum", "calibration_bins"
    }, f"{label} accumulator")
    if type(accumulator["observations"]) is not int or accumulator["observations"] != observations:
        raise AuditError(f"{label} observation denominator differs")
    if (type(accumulator["correct"]) is not int or
            not 0 <= accumulator["correct"] <= observations):
        raise AuditError(f"{label} correct count differs")
    _finite_number(accumulator["brier_sum"], f"{label} Brier sum", minimum=0)
    _finite_number(accumulator["log_loss_sum"], f"{label} log-loss sum", minimum=0)
    bins = accumulator["calibration_bins"]
    if not isinstance(bins, list) or len(bins) != 10:
        raise AuditError(f"{label} calibration-bin schema differs")
    bin_count = 0
    for position, raw_item in enumerate(bins):
        item = _exact_dict(raw_item, {"count", "truth_sum", "probability_sum"},
                           f"{label} calibration bin {position}")
        if (type(item["count"]) is not int or type(item["truth_sum"]) is not int or
                not 0 <= item["truth_sum"] <= item["count"]):
            raise AuditError(f"{label} calibration-bin counts differ")
        _finite_number(item["probability_sum"], f"{label} probability sum",
                       minimum=0, maximum=float(item["count"]))
        bin_count += item["count"]
    if bin_count != observations:
        raise AuditError(f"{label} calibration-bin denominator differs")
    return accumulator


def _merge_accumulators(values: Iterable[Mapping[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {
        "observations": 0, "correct": 0, "brier_sum": 0.0, "log_loss_sum": 0.0,
        "calibration_bins": [
            {"count": 0, "truth_sum": 0, "probability_sum": 0.0} for _ in range(10)
        ],
    }
    for value in values:
        result["observations"] = int(result["observations"]) + int(value["observations"])
        result["correct"] = int(result["correct"]) + int(value["correct"])
        result["brier_sum"] = float(result["brier_sum"]) + float(value["brier_sum"])
        result["log_loss_sum"] = float(result["log_loss_sum"]) + float(value["log_loss_sum"])
        for target, source in zip(result["calibration_bins"], value["calibration_bins"],
                                  strict=True):  # type: ignore[arg-type]
            target["count"] += int(source["count"])
            target["truth_sum"] += int(source["truth_sum"])
            target["probability_sum"] += float(source["probability_sum"])
    return result


def _validate_metric_pair(value: object, observations: int, label: str) -> dict[str, object]:
    pair = _exact_dict(value, {"metrics", "accumulator"}, f"{label} metric pair")
    accumulator = _validate_accumulator(pair["accumulator"], observations, label)
    metrics = _exact_dict(pair["metrics"], {
        "accuracy", "brier", "log_loss", "calibration_error"
    }, f"{label} metrics")
    for name, expected in _metrics(accumulator).items():
        actual = _finite_number(metrics[name], f"{label} {name}", minimum=0)
        if actual != expected:
            raise AuditError(f"{label} {name} does not reconcile")
    return accumulator


def validate_checkpoint(payload: object, expected_ticker: str,
                        expected_lineage_sha: str,
                        sessions: Sequence[str]) -> dict[str, object]:
    checkpoint = _exact_dict(payload, {
        "contract_id", "ticker", "input", "coverage", "folds", "aggregate",
        "persisted_probabilities", "ticker_evidence_sha256", "lineage_sha256",
        "checkpoint_sha256",
    }, f"{expected_ticker} checkpoint")
    if (checkpoint["contract_id"] != PRODUCER_CONTRACT_ID or
            checkpoint["ticker"] != expected_ticker or
            checkpoint["lineage_sha256"] != expected_lineage_sha or
            checkpoint["coverage"] != {
                "folds": EXPECTED_FOLDS_PER_TICKER,
                "oos_observations": EXPECTED_OOS_PER_TICKER,
            } or checkpoint["persisted_probabilities"] != 0):
        raise AuditError(f"{expected_ticker} checkpoint contract differs")
    checkpoint_digest = checkpoint["checkpoint_sha256"]
    without_checkpoint_digest = dict(checkpoint)
    without_checkpoint_digest.pop("checkpoint_sha256")
    if (not isinstance(checkpoint_digest, str) or not _SHA256.fullmatch(checkpoint_digest) or
            checkpoint_digest != canonical_sha(without_checkpoint_digest)):
        raise AuditError(f"{expected_ticker} checkpoint digest differs")
    ticker_digest = checkpoint["ticker_evidence_sha256"]
    ticker_evidence = dict(without_checkpoint_digest)
    ticker_evidence.pop("ticker_evidence_sha256")
    ticker_evidence.pop("lineage_sha256")
    if (not isinstance(ticker_digest, str) or not _SHA256.fullmatch(ticker_digest) or
            ticker_digest != canonical_sha(ticker_evidence)):
        raise AuditError(f"{expected_ticker} ticker digest differs")
    input_evidence = _exact_dict(checkpoint["input"], {"row_count", "return_rows_sha256"},
                                 f"{expected_ticker} input")
    if (type(input_evidence["row_count"]) is not int or
            not EXPECTED_OOS_PER_TICKER <= input_evidence["row_count"] <= EXPECTED_SESSIONS or
            not isinstance(input_evidence["return_rows_sha256"], str) or
            not _SHA256.fullmatch(input_evidence["return_rows_sha256"])):
        raise AuditError(f"{expected_ticker} input identity differs")
    if (len(sessions) != EXPECTED_SESSIONS or list(sessions) != sorted(set(sessions)) or
            sessions[-1] != SOURCE_SESSION_DATE):
        raise AuditError("independent session calendar is not exact")
    folds = checkpoint["folds"]
    aggregate = checkpoint["aggregate"]
    if (not isinstance(folds, list) or len(folds) != EXPECTED_FOLDS_PER_TICKER or
            not isinstance(aggregate, dict) or set(aggregate) != set(MODEL_NAMES)):
        raise AuditError(f"{expected_ticker} fold/model schema differs")
    fold_accumulators: dict[str, list[dict[str, object]]] = {name: [] for name in MODEL_NAMES}
    first_test = EXPECTED_SESSIONS - EXPECTED_OOS_PER_TICKER
    for offset, raw_fold in enumerate(folds):
        fold = _exact_dict(raw_fold, {
            "fold_number", "train_start_date", "train_end_date", "test_start_date",
            "test_end_date", "purge_sessions", "train_direction_observations",
            "test_observations", "training_positive_rate", "baselines",
        }, f"{expected_ticker} fold {offset + 1}")
        test_start = first_test + offset * EXPECTED_TEST_OBSERVATIONS
        train_end = test_start - 7
        train_start = train_end - 289
        expected_geometry = {
            "fold_number": offset + 1,
            "train_start_date": sessions[train_start],
            "train_end_date": sessions[train_end - 1],
            "test_start_date": sessions[test_start],
            "test_end_date": sessions[test_start + EXPECTED_TEST_OBSERVATIONS - 1],
            "purge_sessions": 7,
            "test_observations": EXPECTED_TEST_OBSERVATIONS,
        }
        if any(fold[key] != value for key, value in expected_geometry.items()):
            raise AuditError(f"{expected_ticker} fold geometry differs from live calendar")
        if (fold["fold_number"] != offset + 1 or fold["purge_sessions"] != 7 or
                fold["test_observations"] != EXPECTED_TEST_OBSERVATIONS or
                type(fold["train_direction_observations"]) is not int or
                not 126 <= fold["train_direction_observations"] <= 289):
            raise AuditError(f"{expected_ticker} fold denominator differs")
        rate = _finite_number(fold["training_positive_rate"],
                              f"{expected_ticker} training rate", minimum=0, maximum=1)
        positive_count = rate * fold["train_direction_observations"]
        if abs(positive_count - round(positive_count)) > 1e-9:
            raise AuditError(f"{expected_ticker} training rate is not integer-consistent")
        baselines = fold["baselines"]
        if not isinstance(baselines, dict) or set(baselines) != set(MODEL_NAMES):
            raise AuditError(f"{expected_ticker} fold models differ")
        for model in MODEL_NAMES:
            fold_accumulators[model].append(_validate_metric_pair(
                baselines[model], EXPECTED_TEST_OBSERVATIONS,
                f"{expected_ticker} fold {offset + 1} {model}"))
    for model in MODEL_NAMES:
        actual = _validate_metric_pair(aggregate[model], EXPECTED_OOS_PER_TICKER,
                                       f"{expected_ticker} aggregate {model}")
        expected = _merge_accumulators(fold_accumulators[model])
        if actual != expected:
            raise AuditError(f"{expected_ticker} aggregate does not reconcile with folds")
    return checkpoint


def validate_executor_manifest(payload: object) -> str:
    manifest = _exact_dict(payload, {"executor_git_commit", "artifacts"},
                           "executor manifest")
    commit = manifest["executor_git_commit"]
    artifacts = manifest["artifacts"]
    if not isinstance(commit, str) or not _GIT_COMMIT.fullmatch(commit):
        raise AuditError("executor Git commit differs")
    if not isinstance(artifacts, dict) or not artifacts:
        raise AuditError("executor artifact set is empty")
    for relative, digest in artifacts.items():
        if (not isinstance(relative, str) or not relative or Path(relative).is_absolute() or
                ".." in Path(relative).parts or not isinstance(digest, str) or
                not _SHA256.fullmatch(digest)):
            raise AuditError("executor artifact identity differs")
    if set(artifacts) != REQUIRED_EXECUTOR_ARTIFACTS:
        raise AuditError("executor artifact closure differs")
    return commit


def validate_manifest(payload: object, checkpoints: Mapping[str, object],
                      executor_git_commit: str, sessions: Sequence[str], *,
                      verified_at: datetime) -> dict[str, object]:
    manifest = _exact_dict(payload, {
        "contract_id", "lineage_sha256", "coverage", "aggregate", "ticker_checkpoints",
        "side_effects", "deterministic_evidence_sha256", "runtime",
    }, "final manifest")
    lineage_sha = manifest["lineage_sha256"]
    if (manifest["contract_id"] != PRODUCER_CONTRACT_ID or
            not isinstance(lineage_sha, str) or not _SHA256.fullmatch(lineage_sha) or
            manifest["coverage"] != {
                "tickers": EXPECTED_TICKERS, "folds": EXPECTED_TOTAL_FOLDS,
                "oos_observations": EXPECTED_TOTAL_OOS,
            } or manifest["side_effects"] != ZERO_SIDE_EFFECTS):
        raise AuditError("final manifest contract or side-effect boundary differs")
    runtime = _exact_dict(manifest["runtime"], {"executor_git_commit", "observed_at_utc"},
                          "runtime")
    if runtime["executor_git_commit"] != executor_git_commit:
        raise AuditError("runtime Git commit does not match executor manifest")
    try:
        observed = datetime.fromisoformat(str(runtime["observed_at_utc"]))
    except ValueError as exc:
        raise AuditError("runtime timestamp is invalid") from exc
    if observed.tzinfo is None or verified_at.tzinfo is None:
        raise AuditError("runtime timestamp is not timezone-aware")
    observed_utc = observed.astimezone(timezone.utc)
    verified_utc = verified_at.astimezone(timezone.utc)
    if not observed_utc <= verified_utc <= observed_utc + timedelta(hours=1):
        raise AuditError("audit timestamp is outside the one-hour completion window")
    deterministic = dict(manifest)
    deterministic_digest = deterministic.pop("deterministic_evidence_sha256")
    deterministic.pop("runtime")
    if (not isinstance(deterministic_digest, str) or
            not _SHA256.fullmatch(deterministic_digest) or
            deterministic_digest != canonical_sha(deterministic)):
        raise AuditError("final deterministic evidence digest differs")
    entries = manifest["ticker_checkpoints"]
    if not isinstance(entries, list) or len(entries) != EXPECTED_TICKERS:
        raise AuditError("final ticker denominator differs")
    tickers: list[str] = []
    for raw_entry in entries:
        entry = _exact_dict(raw_entry, {"ticker", "checkpoint_sha256"},
                            "ticker checkpoint entry")
        ticker, digest = entry["ticker"], entry["checkpoint_sha256"]
        if (not isinstance(ticker, str) or not _TICKER.fullmatch(ticker) or
                not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            raise AuditError("ticker checkpoint identity differs")
        tickers.append(ticker)
    if tickers != sorted(set(tickers)) or set(checkpoints) != set(tickers):
        raise AuditError("checkpoint file/universe coverage differs")
    validated: list[dict[str, object]] = []
    for entry in entries:
        ticker = str(entry["ticker"])
        checkpoint = validate_checkpoint(checkpoints[ticker], ticker, str(lineage_sha), sessions)
        if checkpoint["checkpoint_sha256"] != entry["checkpoint_sha256"]:
            raise AuditError(f"{ticker} checkpoint is not bound by final manifest")
        validated.append(checkpoint)
    aggregate = manifest["aggregate"]
    if not isinstance(aggregate, dict) or set(aggregate) != set(MODEL_NAMES):
        raise AuditError("final aggregate model schema differs")
    for model in MODEL_NAMES:
        actual = _validate_metric_pair(aggregate[model], EXPECTED_TOTAL_OOS,
                                       f"final aggregate {model}")
        expected = _merge_accumulators(
            checkpoint["aggregate"][model]["accumulator"] for checkpoint in validated)
        if actual != expected:
            raise AuditError(f"final {model} aggregate does not reconcile with checkpoints")
    return manifest


def _secure_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise AuditError(f"{label} must be an absolute non-symlink directory")
    resolved = path.resolve(strict=True)
    metadata = os.lstat(path)
    if (resolved != path or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or
            stat.S_IMODE(metadata.st_mode) != 0o700):
        raise AuditError(f"{label} must be root-owned mode-0700")
    return resolved


def _secure_executor_root(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise AuditError("executor directory must be an absolute non-symlink directory")
    resolved = path.resolve(strict=True)
    root_metadata = os.lstat(resolved)
    scripts_metadata = os.lstat(resolved / "scripts")
    if (resolved != path or root_metadata.st_uid != 0 or
            not stat.S_ISDIR(root_metadata.st_mode) or
            stat.S_IMODE(root_metadata.st_mode) != 0o555 or scripts_metadata.st_uid != 0 or
            not stat.S_ISDIR(scripts_metadata.st_mode) or
            stat.S_IMODE(scripts_metadata.st_mode) != 0o555):
        raise AuditError("executor deployment boundary differs")
    return resolved


def _read_secure_json(path: Path, label: str) -> tuple[object, str]:
    if not path.is_absolute() or path.is_symlink():
        raise AuditError(f"{label} must be an absolute non-symlink file")
    before = os.lstat(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0 or opened.st_nlink != 1 or
                stat.S_IMODE(opened.st_mode) != 0o600 or
                (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise AuditError(f"{label} must be root-owned mode-0600 single-link")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    return decode_json(raw), hashlib.sha256(raw).hexdigest()


def production_credentials(path: Path) -> tuple[str, str]:
    """Read only the two required secrets from a root-owned deployment file."""
    if not path.is_absolute() or path.is_symlink():
        raise AuditError("credential file must be an absolute non-symlink")
    metadata = os.lstat(path)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or
            metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise AuditError("credential file must be root-owned mode-0600 single-link")
    values: dict[str, str] = {}
    for line in path.read_text("utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        name = key.strip()
        if name in {"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"}:
            values[name] = value.strip().strip("\"'")
    if not values.get("TURSO_DATABASE_URL") or not values.get("TURSO_AUTH_TOKEN"):
        raise AuditError("required database credentials are absent")
    return values["TURSO_DATABASE_URL"], values["TURSO_AUTH_TOKEN"]


def _verify_executor_artifacts(executor_manifest_path: Path,
                               executor_payload: Mapping[str, object]) -> None:
    root = executor_manifest_path.parent.resolve(strict=True)
    for relative, expected_digest in executor_payload["artifacts"].items():
        candidate = (root / relative).resolve(strict=True)
        if root not in candidate.parents or candidate.is_symlink():
            raise AuditError("executor artifact escapes deployment root")
        metadata = os.lstat(candidate)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or
                metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o444):
            raise AuditError("executor artifact metadata differs")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_digest:
            raise AuditError("executor artifact digest differs")


def _require_bound_auditor(executor_root: Path) -> None:
    expected = (executor_root / "scripts" / "audit_full_universe_simple_baselines.py").resolve(
        strict=True)
    if Path(__file__).resolve(strict=True) != expected:
        raise AuditError("executing auditor is not bound by executor manifest")


def verify_runtime_boundary(executor_manifest_path: Path) -> tuple[str, object, str]:
    """Prove the deployed executable closure before any secret or client loading."""
    executor_root = _secure_executor_root(executor_manifest_path.parent)
    payload, file_sha = _read_secure_json(executor_manifest_path, "executor manifest")
    commit = validate_executor_manifest(payload)
    _verify_executor_artifacts(executor_manifest_path, payload)
    _require_bound_auditor(executor_root)
    return commit, payload, file_sha


def audit_files(db, checkpoint_dir: Path, final_manifest_path: Path,
                executor_manifest_path: Path, *, verified_at: datetime) -> dict[str, object]:
    checkpoint_dir = _secure_directory(checkpoint_dir, "checkpoint directory")
    _secure_directory(final_manifest_path.parent, "manifest directory")
    commit, _executor_payload, executor_file_sha = verify_runtime_boundary(
        executor_manifest_path)
    live = read_live_evidence(db, commit)
    manifest_payload, manifest_file_sha = _read_secure_json(final_manifest_path,
                                                             "final manifest")
    entries = manifest_payload.get("ticker_checkpoints") if isinstance(manifest_payload, dict) else None
    if not isinstance(entries, list):
        raise AuditError("final ticker checkpoint list is absent")
    expected_names: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("ticker"), str):
            raise AuditError("ticker checkpoint identity differs")
        ticker = entry["ticker"]
        expected_names[checkpoint_name(ticker)] = ticker
    actual_names = {entry.name for entry in checkpoint_dir.iterdir()}
    if actual_names != set(expected_names):
        raise AuditError("checkpoint directory contains missing or extra artifacts")
    checkpoints: dict[str, object] = {}
    checkpoint_file_hashes: list[dict[str, str]] = []
    for name in sorted(expected_names):
        payload, file_sha = _read_secure_json(checkpoint_dir / name, f"checkpoint {name}")
        ticker = expected_names[name]
        checkpoints[ticker] = payload
        checkpoint_file_hashes.append({"ticker": ticker, "file_sha256": file_sha})
    manifest = validate_manifest(manifest_payload, checkpoints, commit, live["sessions"],
                                 verified_at=verified_at)
    evidence: dict[str, object] = {
        "audit_contract_id": AUDIT_CONTRACT_ID,
        "audited_contract_id": PRODUCER_CONTRACT_ID,
        "stage": "VERIFIED",
        "verified_at_utc": verified_at.astimezone(timezone.utc).isoformat(),
        "executor_git_commit": commit,
        "coverage": manifest["coverage"],
        "checks": {
            "root_only_directories": True,
            "root_owned_executor_manifest": True,
            "executor_artifact_digests": True,
            "runtime_commit_binding": True,
            "exact_checkpoint_file_set": True,
            "checkpoint_metadata": True,
            "checkpoint_and_ticker_digests": True,
            "fold_and_oos_denominators": True,
            "per_model_reconciliation": True,
            "live_calendar_and_fold_geometry": True,
            "independent_downstream_zero_readback": True,
            "zero_unauthorized_side_effects": True,
            "one_hour_freshness_window": True,
        },
        "source_artifacts": {
            "executor_manifest_file_sha256": executor_file_sha,
            "final_manifest_file_sha256": manifest_file_sha,
            "final_deterministic_evidence_sha256": manifest["deterministic_evidence_sha256"],
            "checkpoint_file_set_sha256": canonical_sha(checkpoint_file_hashes),
            "live_session_count": live["session_count"],
            "live_session_sha256": live["session_sha256"],
            "live_downstream_schema_presence": live["schema_presence"],
            "live_downstream_counts": live["downstream_counts"],
            "live_select_statements": live["select_statements"],
        },
        "side_effects": dict(ZERO_SIDE_EFFECTS),
    }
    evidence["audit_evidence_sha256"] = canonical_sha(evidence)
    return evidence


def write_json_once(path: Path, payload: Mapping[str, object]) -> str:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise AuditError("audit output must be a new absolute path")
    parent = _secure_directory(path.parent, "audit evidence directory")
    raw = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    temporary = parent / f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise AuditError("audit evidence write did not make progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise AuditError("audit evidence was created concurrently") from exc
    finally:
        os.unlink(temporary)
    directory_descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    metadata = os.lstat(path)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or
            metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise AuditError("audit evidence metadata differs after write")
    return hashlib.sha256(raw).hexdigest()


def _effective_uid() -> int:
    getter = getattr(os, "geteuid", None)
    return int(getter()) if getter is not None else -1


def run_cli(argv: list[str] | None = None, *, effective_uid=_effective_uid,
            credentials_loader=production_credentials, client_factory=None,
            runtime_verifier=verify_runtime_boundary,
            auditor=audit_files, writer=write_json_once,
            now=lambda: datetime.now(timezone.utc)) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument("--executor-manifest", type=Path, required=True)
    parser.add_argument("--audit-evidence", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    if effective_uid() != 0:
        raise AuditError("completion auditor must execute as root")
    paths = (args.checkpoint_dir, args.final_manifest, args.executor_manifest,
             args.audit_evidence, args.env_file)
    if not all(path.is_absolute() for path in paths):
        raise AuditError("all audit paths must be absolute")
    if args.audit_evidence.exists() or args.audit_evidence.is_symlink():
        raise AuditError("audit evidence target already exists")
    if not 10 <= args.timeout_seconds <= 300:
        raise AuditError("timeout is out of range")
    runtime_verifier(args.executor_manifest)
    endpoint, token = credentials_loader(args.env_file)
    endpoint = normalize_turso_pipeline_endpoint(endpoint)
    if client_factory is None:
        executor_root = Path(__file__).resolve(strict=True).parents[1]
        if str(executor_root) not in sys.path:
            sys.path.insert(0, str(executor_root))
        from turso_read_pipeline import TursoReadPipeline
        client_factory = lambda url, secret, timeout: TursoReadPipeline(
            url, secret, timeout_seconds=timeout)
    db = client_factory(endpoint, token, args.timeout_seconds)
    evidence = auditor(db, args.checkpoint_dir, args.final_manifest, args.executor_manifest,
                       verified_at=now())
    writer(args.audit_evidence, evidence)
    return 0


def main(argv: list[str] | None = None, **injected) -> int:
    try:
        return run_cli(argv, **injected)
    except (Exception, SystemExit):
        print("Full-universe baseline completion audit failed; inspect redacted durable evidence.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
