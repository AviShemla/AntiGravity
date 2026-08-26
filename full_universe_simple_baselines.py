"""Governed, SELECT-only full-universe simple-baseline successor.

The three validated screening arms differ only in signal-discovery lookback.
Their reference baselines therefore form one common 474-ticker evaluation, not
three replicated evaluations.  No result from this module is an investment
prediction or authorization for a downstream model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


class BaselineContractError(RuntimeError):
    """Raised when immutable lineage or evaluation evidence is not exact."""


CONTRACT_ID = "full-universe-common-simple-baselines-v1"
SNAPSHOT_ID = "market_features_2026-08-25_5b1044ee45605a3d"
SNAPSHOT_SHA256 = "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011"
SOURCE_SESSION_DATE = "2026-08-25"
SCREENING_CODE_VERSION = "2ef4a1082c91c023b9b0204611730492f03ad576"
EXPECTED_TICKERS = 474
EXPECTED_SESSIONS = 1246
EXPECTED_FOLDS = 4
TEST_SESSIONS = 30
EXPECTED_OOS_PER_TICKER = EXPECTED_FOLDS * TEST_SESSIONS
EXPECTED_TOTAL_FOLDS = EXPECTED_TICKERS * EXPECTED_FOLDS
EXPECTED_TOTAL_OOS = EXPECTED_TICKERS * EXPECTED_OOS_PER_TICKER
SESSION_SHA256 = "030b17a6d94cfebdd24582b8206357b6905c58e5b3d10796b0c8ee3c87b53eeb"
MODEL_NAMES = ("majority_direction", "constant_training_rate", "lag1_logistic")
REQUIRED_EXECUTOR_ARTIFACTS = frozenset({
    "full_universe_simple_baselines.py",
    "scripts/run_full_universe_simple_baselines.py",
    "scripts/audit_full_universe_simple_baselines.py",
    "turso_read_pipeline.py",
    "predictive_screener.py",
    "model_lineage.py",
    "stock_lag_governance.py",
})


@dataclass(frozen=True)
class ExpectedArm:
    run_id: str
    signal_lookback_sessions: int
    config_sha256: str


ARMS = (
    ExpectedArm("predictive_screening_2026-08-25_w060_2ef4a10", 60,
        "073d4092b2655afd24b47a92a03eed9c299bb0aa0f28db9927bbe7b60a287f48"),
    ExpectedArm("predictive_screening_2026-08-25_w126_2ef4a10", 126,
        "aaa817550e53ec1695e06b322b9ce1712ff52d146c1bc21065f1b4895d3d0469"),
    ExpectedArm("predictive_screening_2026-08-25_w252_2ef4a10", 252,
        "58b5f36f0315ba8eefa755bb0f25d5a4a39fe9922f6028a41a869b80121e5325"),
)

RUN_SQL = """SELECT r.screening_run_id,r.market_snapshot_id,r.source_session_date,
 r.code_version,r.config_json,r.status,s.source_checksum_sha256,s.status AS snapshot_status,
 s.expected_ticker_count FROM predictive_screening_runs r JOIN model_input_snapshots s
 ON s.snapshot_id=r.market_snapshot_id WHERE r.screening_run_id IN (?,?,?)
 ORDER BY r.screening_run_id"""
TICKER_SQL = """SELECT screening_run_id,ticker FROM predictive_screening_results
 WHERE screening_run_id IN (?,?,?) ORDER BY screening_run_id,ticker"""
SESSION_SQL = """SELECT DISTINCT date FROM market_daily_features
 WHERE snapshot_id=? ORDER BY date"""
RETURN_SQL = """SELECT date,daily_return_pct FROM market_daily_features
 WHERE snapshot_id=? AND ticker=? ORDER BY date"""

_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)
_TICKER = re.compile(r"^[A-Z0-9.^-]{1,24}$")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _records(result: object, columns: Sequence[str], label: str) -> list[dict[str, object]]:
    if tuple(getattr(result, "columns", ())) != tuple(columns):
        raise BaselineContractError(f"{label} column contract differs")
    output = []
    for row in getattr(result, "rows", ()):
        if not isinstance(row, (list, tuple)) or len(row) != len(columns):
            raise BaselineContractError(f"{label} returned malformed evidence")
        output.append(dict(zip(columns, row)))
    return output


def select_only(db, sql: str, args: list[object], label: str):
    statement = " ".join(sql.split())
    if not statement.upper().startswith("SELECT ") or _FORBIDDEN_SQL.search(statement):
        raise BaselineContractError(f"{label} is not SELECT-only")
    if ";" in statement or "--" in statement or "/*" in statement:
        raise BaselineContractError(f"{label} contains disallowed SQL syntax")
    return db.execute(statement, args)


def _validate_config(raw: object, arm: ExpectedArm) -> dict[str, object]:
    if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() != arm.config_sha256:
        raise BaselineContractError("screening configuration hash differs")
    try:
        config = json.loads(raw)
    except ValueError as exc:
        raise BaselineContractError("screening configuration is not JSON") from exc
    exact = {
        "training_window_sessions": 289, "min_train_sessions": 289,
        "test_sessions": 30, "outer_folds": 4, "purge_sessions": 7,
        "min_fit_observations": 126, "min_oos_sessions": 120,
        "signal_lookback_sessions": arm.signal_lookback_sessions,
    }
    if not isinstance(config, dict) or any(type(config.get(k)) is not int or config.get(k) != v
                                          for k, v in exact.items()):
        raise BaselineContractError("screening configuration differs from governed common baseline")
    return config


def read_lineage(db) -> dict[str, object]:
    ids = [arm.run_id for arm in ARMS]
    runs = _records(select_only(db, RUN_SQL, ids, "run lineage"), (
        "screening_run_id", "market_snapshot_id", "source_session_date", "code_version",
        "config_json", "status", "source_checksum_sha256", "snapshot_status",
        "expected_ticker_count"), "run lineage")
    by_id = {str(row["screening_run_id"]): row for row in runs}
    if len(by_id) != len(runs) or set(by_id) != set(ids):
        raise BaselineContractError("screening run coverage is not exact")
    configs: list[dict[str, object]] = []
    for arm in ARMS:
        row = by_id[arm.run_id]
        if (row["market_snapshot_id"] != SNAPSHOT_ID or
                row["source_session_date"] != SOURCE_SESSION_DATE or
                row["code_version"] != SCREENING_CODE_VERSION or row["status"] != "VALIDATED" or
                row["snapshot_status"] != "VALIDATED" or
                row["source_checksum_sha256"] != SNAPSHOT_SHA256 or
                row["expected_ticker_count"] != EXPECTED_TICKERS):
            raise BaselineContractError("screening/snapshot lineage differs")
        configs.append(_validate_config(row["config_json"], arm))
    common = [{k: v for k, v in config.items() if k not in {
        "signal_lookback_sessions", "signal_lookback_governance_status"}}
        for config in configs]
    if any(value != common[0] for value in common[1:]):
        raise BaselineContractError("screening arms differ beyond discovery lookback")

    ticker_rows = _records(select_only(db, TICKER_SQL, ids, "ticker universe"),
                           ("screening_run_id", "ticker"), "ticker universe")
    by_run: dict[str, list[str]] = {run_id: [] for run_id in ids}
    for row in ticker_rows:
        run_id, ticker = row["screening_run_id"], row["ticker"]
        if run_id not in by_run or not isinstance(ticker, str) or not _TICKER.fullmatch(ticker):
            raise BaselineContractError("ticker universe contains an invalid identity")
        by_run[str(run_id)].append(ticker)
    sets = []
    for run_id in ids:
        values = by_run[run_id]
        if len(values) != EXPECTED_TICKERS or len(set(values)) != EXPECTED_TICKERS:
            raise BaselineContractError("ticker universe denominator is not exact")
        sets.append(tuple(sorted(values)))
    if any(values != sets[0] for values in sets[1:]):
        raise BaselineContractError("screening arms do not share one ticker universe")

    dates = [str(row["date"]) for row in _records(
        select_only(db, SESSION_SQL, [SNAPSHOT_ID], "session calendar"), ("date",),
        "session calendar")]
    if (len(dates) != EXPECTED_SESSIONS or len(set(dates)) != EXPECTED_SESSIONS or
            dates[-1] != SOURCE_SESSION_DATE or canonical_sha(dates) != SESSION_SHA256):
        raise BaselineContractError("snapshot session calendar differs")
    return {
        "snapshot_id": SNAPSHOT_ID, "snapshot_sha256": SNAPSHOT_SHA256,
        "source_session_date": SOURCE_SESSION_DATE, "screening_code_version": SCREENING_CODE_VERSION,
        "screening_runs": [{"run_id": arm.run_id, "signal_lookback_sessions": arm.signal_lookback_sessions,
                            "config_sha256": arm.config_sha256} for arm in ARMS],
        "common_config": {"training_window_sessions": 289, "min_train_sessions": 289,
                          "test_sessions": 30, "outer_folds": 4, "purge_sessions": 7,
                          "min_fit_observations": 126, "min_oos_sessions": 120},
        "ticker_universe": list(sets[0]), "ticker_universe_sha256": canonical_sha(list(sets[0])),
        "sessions": dates, "sessions_sha256": canonical_sha(dates),
    }


def _metric_accumulator(truth: np.ndarray, probabilities: np.ndarray) -> dict[str, object]:
    if (truth.ndim != 1 or probabilities.shape != truth.shape or not len(truth) or
            not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any()):
        raise BaselineContractError("invalid metric input")
    clipped = np.clip(probabilities, 1e-12, 1 - 1e-12)
    bins = np.minimum((probabilities * 10).astype(int), 9)
    return {
        "observations": int(len(truth)),
        "correct": int(((probabilities >= .5).astype(int) == truth).sum()),
        "brier_sum": float(np.square(probabilities - truth).sum()),
        "log_loss_sum": float((-(truth * np.log(clipped) + (1-truth) * np.log(1-clipped))).sum()),
        "calibration_bins": [
            {"count": int((bins == i).sum()), "truth_sum": int(truth[bins == i].sum()),
             "probability_sum": float(probabilities[bins == i].sum())} for i in range(10)
        ],
    }


def _metrics(acc: Mapping[str, object]) -> dict[str, float]:
    n = int(acc["observations"])
    if n <= 0:
        raise BaselineContractError("metric accumulator is empty")
    calibration = sum((int(b["count"])/n) * abs(int(b["truth_sum"])/int(b["count"])
        - float(b["probability_sum"])/int(b["count"])) for b in acc["calibration_bins"]
        if int(b["count"]))
    return {"accuracy": int(acc["correct"])/n, "brier": float(acc["brier_sum"])/n,
            "log_loss": float(acc["log_loss_sum"])/n, "calibration_error": calibration}


def _merge_accumulators(values: Iterable[Mapping[str, object]]) -> dict[str, object]:
    result = {"observations": 0, "correct": 0, "brier_sum": 0.0, "log_loss_sum": 0.0,
              "calibration_bins": [{"count": 0, "truth_sum": 0, "probability_sum": 0.0}
                                   for _ in range(10)]}
    for value in values:
        for key in ("observations", "correct"):
            result[key] += int(value[key])
        for key in ("brier_sum", "log_loss_sum"):
            result[key] += float(value[key])
        for target, source in zip(result["calibration_bins"], value["calibration_bins"], strict=True):
            target["count"] += int(source["count"])
            target["truth_sum"] += int(source["truth_sum"])
            target["probability_sum"] += float(source["probability_sum"])
    return result


def evaluate_ticker(ticker: str, dates: Sequence[str], return_rows: Sequence[Mapping[str, object]],
                    *, primitives=None) -> dict[str, object]:
    """Evaluate three preregistered baselines without persisting probabilities."""
    if not _TICKER.fullmatch(ticker) or len(dates) != EXPECTED_SESSIONS:
        raise BaselineContractError("ticker or calendar contract differs")
    if primitives is None:
        from predictive_screener import ScreeningConfig, expanding_windows, fit_probabilities
    else:
        ScreeningConfig, expanding_windows, fit_probabilities = primitives
    seen: dict[str, float] = {}
    for row in return_rows:
        date, value = row.get("date"), row.get("daily_return_pct")
        if not isinstance(date, str) or date in seen or date not in dates or value is None:
            raise BaselineContractError("return rows contain missing/duplicate/off-calendar evidence")
        number = float(value)
        if not math.isfinite(number):
            raise BaselineContractError("return rows contain a non-finite value")
        seen[date] = number
    series = pd.Series([seen.get(date, np.nan) for date in dates], index=pd.Index(dates), dtype=float)
    config = ScreeningConfig(min_train_sessions=289, training_window_sessions=289,
        test_sessions=30, outer_folds=4, purge_sessions=7, min_oos_sessions=120,
        min_depth=1, max_depth=1, candidate_lags=(1, 2, 3, 4, 5, 6, 7),
        min_fit_observations=126,
        eligibility_hypotheses=EXPECTED_TICKERS)
    windows = expanding_windows(series.index, config)
    lagged = series.shift(1).to_frame("own_return_lag1")
    target = (series > 0).astype(float).where(series.notna())
    fold_payloads, aggregate_by_model = [], {name: [] for name in (
        "majority_direction", "constant_training_rate", "lag1_logistic")}
    for window in windows:
        train_target = target.iloc[window.train_positions].dropna()
        test_target = target.iloc[window.test_positions]
        if len(train_target) < 126 or test_target.isna().any() or len(test_target) != TEST_SESSIONS:
            raise BaselineContractError(f"{ticker} fold lacks exact governed observations")
        truth = test_target.to_numpy(dtype=int)
        rate = float(train_target.mean())
        majority = np.full(len(truth), 1.0 if rate >= .5 else 0.0)
        constant = np.full(len(truth), rate)
        logistic = np.asarray(fit_probabilities(lagged.iloc[window.train_positions],
            target.iloc[window.train_positions], lagged.iloc[window.test_positions],
            min_fit_observations=126), dtype=float)
        models = {"majority_direction": majority, "constant_training_rate": constant,
                  "lag1_logistic": logistic}
        accumulators = {name: _metric_accumulator(truth, probabilities)
                        for name, probabilities in models.items()}
        for name, acc in accumulators.items():
            aggregate_by_model[name].append(acc)
        fold_payloads.append({
            "fold_number": int(window.fold_number),
            "train_start_date": dates[int(window.train_positions[0])],
            "train_end_date": dates[int(window.train_positions[-1])],
            "test_start_date": dates[int(window.test_positions[0])],
            "test_end_date": dates[int(window.test_positions[-1])],
            "purge_sessions": 7, "train_direction_observations": int(len(train_target)),
            "test_observations": int(len(truth)), "training_positive_rate": rate,
            "baselines": {name: {"metrics": _metrics(acc), "accumulator": acc}
                          for name, acc in accumulators.items()},
        })
    aggregate = {name: _merge_accumulators(values) for name, values in aggregate_by_model.items()}
    result = {"contract_id": CONTRACT_ID, "ticker": ticker,
              "input": {"row_count": len(seen), "return_rows_sha256": canonical_sha(
                  [[date, seen[date]] for date in dates if date in seen])},
              "coverage": {"folds": len(fold_payloads), "oos_observations": sum(
                  int(fold["test_observations"]) for fold in fold_payloads)},
              "folds": fold_payloads,
              "aggregate": {name: {"metrics": _metrics(acc), "accumulator": acc}
                            for name, acc in aggregate.items()},
              "persisted_probabilities": 0}
    result["ticker_evidence_sha256"] = canonical_sha(result)
    return result


def checkpoint_name(ticker: str) -> str:
    return f"ticker-{hashlib.sha256(ticker.encode()).hexdigest()[:24]}.json"


def write_json_once(path: Path, payload: Mapping[str, object]) -> str:
    path = Path(path)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise BaselineContractError("output target must be a new absolute path")
    parent = path.parent.resolve(strict=True)
    if parent != path.parent or not parent.is_dir() or parent.is_symlink():
        raise BaselineContractError("output parent identity differs")
    raw = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    temporary = parent / f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise BaselineContractError("output write did not make progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise BaselineContractError("output target was created concurrently") from exc
    finally:
        os.unlink(temporary)
    if os.name == "posix":
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise BaselineContractError("output metadata is not mode-0600 single-link regular")
    return hashlib.sha256(raw).hexdigest()


def _validate_accumulator(value: object, observations: int) -> None:
    expected_keys = {"observations", "correct", "brier_sum", "log_loss_sum",
                     "calibration_bins"}
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise BaselineContractError("checkpoint accumulator schema differs")
    if (type(value["observations"]) is not int or value["observations"] != observations or
            type(value["correct"]) is not int or not 0 <= value["correct"] <= observations or
            any(not isinstance(value[key], (int, float)) or not math.isfinite(float(value[key]))
                or float(value[key]) < 0 for key in ("brier_sum", "log_loss_sum"))):
        raise BaselineContractError("checkpoint accumulator totals differ")
    bins = value["calibration_bins"]
    if not isinstance(bins, list) or len(bins) != 10:
        raise BaselineContractError("checkpoint calibration-bin schema differs")
    for item in bins:
        if (not isinstance(item, dict) or set(item) != {
                "count", "truth_sum", "probability_sum"} or
                type(item["count"]) is not int or type(item["truth_sum"]) is not int or
                not 0 <= item["truth_sum"] <= item["count"] or
                not isinstance(item["probability_sum"], (int, float)) or
                not math.isfinite(float(item["probability_sum"])) or
                not 0 <= float(item["probability_sum"]) <= item["count"]):
            raise BaselineContractError("checkpoint calibration-bin values differ")
    if sum(item["count"] for item in bins) != observations:
        raise BaselineContractError("checkpoint calibration-bin denominator differs")


def validate_checkpoint_payload(payload: Mapping[str, object], ticker: str,
                                lineage: Mapping[str, object]) -> None:
    if set(payload) != {"contract_id", "ticker", "input", "coverage", "folds", "aggregate",
                        "persisted_probabilities", "ticker_evidence_sha256", "lineage_sha256",
                        "checkpoint_sha256"}:
        raise BaselineContractError("checkpoint top-level schema differs")
    evidence = dict(payload)
    checkpoint_digest = evidence.pop("checkpoint_sha256", None)
    if checkpoint_digest != canonical_sha(evidence):
        raise BaselineContractError("checkpoint digest differs")
    ticker_digest = evidence.pop("ticker_evidence_sha256", None)
    evidence.pop("lineage_sha256", None)
    if ticker_digest != canonical_sha(evidence):
        raise BaselineContractError("ticker evidence digest differs")
    if (payload.get("contract_id") != CONTRACT_ID or payload.get("ticker") != ticker or
            payload.get("lineage_sha256") != canonical_sha(lineage) or
            payload.get("coverage") != {"folds": EXPECTED_FOLDS,
                                        "oos_observations": EXPECTED_OOS_PER_TICKER} or
            payload.get("persisted_probabilities") != 0):
        raise BaselineContractError("checkpoint contract differs")
    input_evidence = payload.get("input")
    if (not isinstance(input_evidence, dict) or set(input_evidence) != {
            "row_count", "return_rows_sha256"} or type(input_evidence["row_count"]) is not int or
            not EXPECTED_OOS_PER_TICKER <= input_evidence["row_count"] <= EXPECTED_SESSIONS or
            not isinstance(input_evidence["return_rows_sha256"], str) or
            not re.fullmatch(r"[0-9a-f]{64}", input_evidence["return_rows_sha256"])):
        raise BaselineContractError("checkpoint input evidence differs")
    folds, aggregate = payload.get("folds"), payload.get("aggregate")
    if (not isinstance(folds, list) or len(folds) != EXPECTED_FOLDS or
            not isinstance(aggregate, dict) or set(aggregate) != set(MODEL_NAMES)):
        raise BaselineContractError("checkpoint fold/model schema differs")
    sessions = list(lineage.get("sessions", ()))
    if len(sessions) != EXPECTED_SESSIONS:
        raise BaselineContractError("checkpoint lineage calendar differs")
    first_test = EXPECTED_SESSIONS - EXPECTED_OOS_PER_TICKER
    fold_accumulators = {name: [] for name in MODEL_NAMES}
    for offset, fold in enumerate(folds):
        test_start = first_test + offset * TEST_SESSIONS
        train_end = test_start - 7
        train_start = train_end - 289
        geometry = {
            "fold_number": offset + 1,
            "train_start_date": sessions[train_start],
            "train_end_date": sessions[train_end - 1],
            "test_start_date": sessions[test_start],
            "test_end_date": sessions[test_start + TEST_SESSIONS - 1],
            "purge_sessions": 7,
            "test_observations": TEST_SESSIONS,
        }
        if (not isinstance(fold, dict) or set(fold) != {
                "fold_number", "train_start_date", "train_end_date", "test_start_date",
                "test_end_date", "purge_sessions", "train_direction_observations",
                "test_observations", "training_positive_rate", "baselines"} or
                any(fold.get(key) != value for key, value in geometry.items())):
            raise BaselineContractError("checkpoint fold geometry differs")
        if (type(fold.get("train_direction_observations")) is not int or
                not 126 <= fold["train_direction_observations"] <= 289):
            raise BaselineContractError("checkpoint training denominator differs")
        rate = fold.get("training_positive_rate")
        if (not isinstance(rate, (int, float)) or not math.isfinite(float(rate)) or
                not 0 <= float(rate) <= 1 or abs(float(rate) * fold[
                    "train_direction_observations"] - round(float(rate) * fold[
                        "train_direction_observations"])) > 1e-9):
            raise BaselineContractError("checkpoint training rate differs")
        baselines = fold.get("baselines")
        if not isinstance(baselines, dict) or set(baselines) != set(MODEL_NAMES):
            raise BaselineContractError("checkpoint fold models differ")
        for name in MODEL_NAMES:
            item = baselines[name]
            if not isinstance(item, dict) or set(item) != {"metrics", "accumulator"}:
                raise BaselineContractError("checkpoint fold metric schema differs")
            _validate_accumulator(item["accumulator"], TEST_SESSIONS)
            if item["metrics"] != _metrics(item["accumulator"]):
                raise BaselineContractError("checkpoint fold metrics differ")
            fold_accumulators[name].append(item["accumulator"])
    for name in MODEL_NAMES:
        item = aggregate[name]
        if not isinstance(item, dict) or set(item) != {"metrics", "accumulator"}:
            raise BaselineContractError("checkpoint aggregate schema differs")
        _validate_accumulator(item["accumulator"], EXPECTED_OOS_PER_TICKER)
        recomputed = _merge_accumulators(fold_accumulators[name])
        if item["accumulator"] != recomputed or item["metrics"] != _metrics(recomputed):
            raise BaselineContractError("checkpoint aggregate differs from folds")


def read_checkpoint(path: Path, ticker: str, lineage: Mapping[str, object]) -> dict[str, object]:
    metadata = os.lstat(path)
    if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600 or
            metadata.st_nlink != 1 or path.is_symlink()):
        raise BaselineContractError("resume checkpoint metadata differs")
    payload = json.loads(path.read_text("utf-8"))
    validate_checkpoint_payload(payload, ticker, lineage)
    return payload


def build_final_manifest(lineage: Mapping[str, object], checkpoints: Sequence[Mapping[str, object]],
                         *, executor_git_commit: str, observed_at: datetime) -> dict[str, object]:
    if len(checkpoints) != EXPECTED_TICKERS:
        raise BaselineContractError("final checkpoint denominator is incomplete")
    ordered = sorted(checkpoints, key=lambda item: str(item["ticker"]))
    if [item["ticker"] for item in ordered] != list(lineage["ticker_universe"]):
        raise BaselineContractError("final ticker universe differs")
    for item in ordered:
        validate_checkpoint_payload(item, str(item["ticker"]), lineage)
    merged = {name: _merge_accumulators(item["aggregate"][name]["accumulator"]
                                        for item in ordered) for name in MODEL_NAMES}
    folds = sum(int(item["coverage"]["folds"]) for item in ordered)
    oos = sum(int(item["coverage"]["oos_observations"]) for item in ordered)
    if folds != EXPECTED_TOTAL_FOLDS or oos != EXPECTED_TOTAL_OOS:
        raise BaselineContractError("final fold/OOS denominator differs")
    deterministic = {
        "contract_id": CONTRACT_ID, "lineage_sha256": canonical_sha(lineage),
        "coverage": {"tickers": len(ordered), "folds": folds, "oos_observations": oos},
        "aggregate": {name: {"metrics": _metrics(acc), "accumulator": acc}
                      for name, acc in merged.items()},
        "ticker_checkpoints": [{"ticker": item["ticker"],
                                "checkpoint_sha256": item["checkpoint_sha256"]} for item in ordered],
        "side_effects": {"database_writes": 0, "bayesian_fits": 0, "predictions": 0,
                         "recommendations": 0, "orders": 0, "etf_outputs": 0},
    }
    if observed_at.tzinfo is None or not re.fullmatch(r"[0-9a-f]{40}", executor_git_commit):
        raise BaselineContractError("runtime lineage is invalid")
    return {**deterministic, "deterministic_evidence_sha256": canonical_sha(deterministic),
            "runtime": {"executor_git_commit": executor_git_commit,
                        "observed_at_utc": observed_at.astimezone(timezone.utc).isoformat()}}


def run(db, checkpoint_dir: Path, final_manifest: Path, *, executor_git_commit: str,
        primitives=None, observed_at: datetime | None = None,
        writer: Callable[[Path, Mapping[str, object]], str] = write_json_once,
        progress: Callable[[int, int, str], None] | None = None) -> dict[str, object]:
    lineage = read_lineage(db)
    lineage_sha = canonical_sha(lineage)
    completed = []
    progress = progress or (lambda completed, total, ticker: print(
        f"baseline_checkpoint={completed}/{total} ticker={ticker}", flush=True))
    for position, ticker in enumerate(lineage["ticker_universe"], start=1):
        path = checkpoint_dir / checkpoint_name(ticker)
        if path.exists() or path.is_symlink():
            completed.append(read_checkpoint(path, ticker, lineage))
            progress(position, EXPECTED_TICKERS, ticker)
            continue
        rows = _records(select_only(db, RETURN_SQL, [SNAPSHOT_ID, ticker], f"{ticker} returns"),
                        ("date", "daily_return_pct"), f"{ticker} returns")
        result = evaluate_ticker(ticker, lineage["sessions"], rows, primitives=primitives)
        payload = {**result, "lineage_sha256": lineage_sha}
        payload["checkpoint_sha256"] = canonical_sha(payload)
        validate_checkpoint_payload(payload, ticker, lineage)
        writer(path, payload)
        completed.append(payload)
        progress(position, EXPECTED_TICKERS, ticker)
    manifest = build_final_manifest(lineage, completed, executor_git_commit=executor_git_commit,
        observed_at=observed_at or datetime.now(timezone.utc))
    writer(final_manifest, manifest)
    return manifest


def production_credentials(path: Path) -> tuple[str, str]:
    if not path.is_absolute() or path.is_symlink():
        raise BaselineContractError("credential file must be an absolute non-symlink")
    metadata = os.lstat(path)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1 or
            stat.S_IMODE(metadata.st_mode) != 0o600):
        raise BaselineContractError("credential file must be root-owned mode-0600 single-link")
    values = {}
    for line in path.read_text("utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line: continue
        key, value = line.split("=", 1)
        if key.strip() in {"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"}:
            values[key.strip()] = value.strip().strip("\"'")
    if not values.get("TURSO_DATABASE_URL") or not values.get("TURSO_AUTH_TOKEN"):
        raise BaselineContractError("required database credentials are absent")
    return values["TURSO_DATABASE_URL"], values["TURSO_AUTH_TOKEN"]


def require_root_output_directory(path: Path, label: str) -> Path:
    """Bind output creation to an existing root-only deployment directory."""
    if not path.is_absolute() or path.is_symlink():
        raise BaselineContractError(f"{label} must be an absolute non-symlink directory")
    resolved = path.resolve(strict=True)
    metadata = os.lstat(resolved)
    if (resolved != path or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or
            stat.S_IMODE(metadata.st_mode) != 0o700):
        raise BaselineContractError(f"{label} must be root-owned mode-0700")
    return resolved


def load_executor_manifest(path: Path, module_path: Path, entrypoint_path: Path) -> str:
    """Verify the root-owned deployed artifact set and return its bound Git commit."""
    if not path.is_absolute() or path.is_symlink():
        raise BaselineContractError("executor manifest must be an absolute non-symlink")
    metadata = os.lstat(path)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1 or
            stat.S_IMODE(metadata.st_mode) != 0o600):
        raise BaselineContractError("executor manifest must be root-owned mode-0600 single-link")
    manifest = json.loads(path.read_text("utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"executor_git_commit", "artifacts"}:
        raise BaselineContractError("executor manifest schema differs")
    commit = manifest["executor_git_commit"]
    artifacts = manifest["artifacts"]
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise BaselineContractError("executor Git identity differs")
    if not isinstance(artifacts, dict) or not artifacts:
        raise BaselineContractError("executor artifact set is empty")
    root = path.parent.resolve(strict=True)
    root_metadata = os.lstat(root)
    scripts_metadata = os.lstat(root / "scripts")
    if (root_metadata.st_uid != 0 or not stat.S_ISDIR(root_metadata.st_mode) or
            stat.S_IMODE(root_metadata.st_mode) != 0o555 or scripts_metadata.st_uid != 0 or
            not stat.S_ISDIR(scripts_metadata.st_mode) or
            stat.S_IMODE(scripts_metadata.st_mode) != 0o555 or
            set(artifacts) != set(REQUIRED_EXECUTOR_ARTIFACTS)):
        raise BaselineContractError("executor deployment boundary differs")
    for relative, expected_sha in artifacts.items():
        if (not isinstance(relative, str) or not isinstance(expected_sha, str) or
                not re.fullmatch(r"[0-9a-f]{64}", expected_sha)):
            raise BaselineContractError("executor artifact manifest contains invalid identity")
        candidate_relative = Path(relative)
        if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
            raise BaselineContractError("executor artifact path escapes deployment root")
        candidate = (root / candidate_relative).resolve(strict=True)
        if root not in candidate.parents or candidate.is_symlink():
            raise BaselineContractError("executor artifact path differs")
        artifact_metadata = os.lstat(candidate)
        if (not stat.S_ISREG(artifact_metadata.st_mode) or artifact_metadata.st_uid != 0 or
                artifact_metadata.st_nlink != 1 or stat.S_IMODE(artifact_metadata.st_mode) != 0o444 or
                hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_sha):
            raise BaselineContractError("executor artifact identity differs")
    expected_module = (root / "full_universe_simple_baselines.py").resolve(strict=True)
    expected_entrypoint = (root / "scripts" / "run_full_universe_simple_baselines.py").resolve(
        strict=True)
    if (module_path.resolve(strict=True) != expected_module or
            entrypoint_path.resolve(strict=True) != expected_entrypoint or
            "full_universe_simple_baselines.py" not in artifacts or
            "scripts/run_full_universe_simple_baselines.py" not in artifacts):
        raise BaselineContractError("executing artifact is not bound by executor manifest")
    return commit


def _effective_uid() -> int:
    getter = getattr(os, "geteuid", None)
    return int(getter()) if getter is not None else -1


def run_cli(argv: list[str] | None = None, *, effective_uid=_effective_uid,
            credentials_loader=production_credentials, executor_loader=load_executor_manifest,
            client_factory=None, runner=run, module_path: Path | None = None,
            entrypoint_path: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument("--executor-manifest", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    if effective_uid() != 0: raise BaselineContractError("baseline runner must execute as root")
    if not all(path.is_absolute() for path in (
            args.env_file, args.checkpoint_dir, args.final_manifest, args.executor_manifest)):
        raise BaselineContractError("all runtime paths must be absolute")
    checkpoint_dir = require_root_output_directory(args.checkpoint_dir, "checkpoint directory")
    manifest_parent = require_root_output_directory(args.final_manifest.parent,
                                                     "manifest directory")
    final_manifest = manifest_parent / args.final_manifest.name
    if final_manifest.exists() or final_manifest.is_symlink():
        raise BaselineContractError("final manifest target must not already exist")
    if not 10 <= args.timeout_seconds <= 300: raise BaselineContractError("timeout is out of range")
    executor_git_commit = executor_loader(args.executor_manifest,
        module_path or Path(__file__), entrypoint_path or Path(sys.argv[0]))
    endpoint, token = credentials_loader(args.env_file)
    if client_factory is None:
        from turso_read_pipeline import TursoReadPipeline
        client_factory = lambda url, secret, timeout: TursoReadPipeline(url, secret,
            timeout_seconds=timeout)
    runner(client_factory(endpoint, token, args.timeout_seconds), checkpoint_dir,
           final_manifest, executor_git_commit=executor_git_commit)
    return 0


def main(argv: list[str] | None = None, **injected) -> int:
    try:
        return run_cli(argv, **injected)
    except (Exception, SystemExit):
        print("Full-universe baseline run failed; inspect only redacted durable evidence.", file=sys.stderr)
        return 1
