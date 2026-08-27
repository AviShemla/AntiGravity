"""Pure, fail-closed binding of verified v4 baselines to model preregistration.

The caller is responsible for secure file reads and supplies already-decoded
JSON objects plus independently calculated raw-file SHA-256 identities.  This
module performs no I/O, database access, model fitting, or operational action.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Mapping

try:
    from .stock_model_preregistration import (
        BaselineAuditEvidence,
        BaselineReadbackProof,
        CLAIM_SCOPE,
        EXPECTED_DEPTHS,
        EXPECTED_LAGS,
        INDEPENDENT_TOPOLOGY,
        ImmutableLineage,
        ModelConfiguration,
        PreregistrationError,
        PreregistrationRequest,
        ProhibitedOutputIntent,
        RUN_MODE_NEW,
        SamplerConfiguration,
        WalkForwardFold,
        canonical_sha,
        compute_baseline_audit_sha256,
        preregister_model_run,
    )
except ImportError:  # Direct execution from the artifact directory.
    from stock_model_preregistration import (
        BaselineAuditEvidence,
        BaselineReadbackProof,
        CLAIM_SCOPE,
        EXPECTED_DEPTHS,
        EXPECTED_LAGS,
        INDEPENDENT_TOPOLOGY,
        ImmutableLineage,
        ModelConfiguration,
        PreregistrationError,
        PreregistrationRequest,
        ProhibitedOutputIntent,
        RUN_MODE_NEW,
        SamplerConfiguration,
        WalkForwardFold,
        canonical_sha,
        compute_baseline_audit_sha256,
        preregister_model_run,
    )


PRODUCER_CONTRACT_ID = "full-universe-common-simple-baselines-v1"
AUDIT_CONTRACT_ID = "full-universe-common-simple-baselines-audit-v1"
SNAPSHOT_ID = "market_features_2026-08-25_5b1044ee45605a3d"
SNAPSHOT_SHA256 = "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011"
SOURCE_SESSION_DATE = "2026-08-25"
SCREENING_CODE_VERSION = "2ef4a1082c91c023b9b0204611730492f03ad576"
SESSION_SHA256 = "030b17a6d94cfebdd24582b8206357b6905c58e5b3d10796b0c8ee3c87b53eeb"
PINNED_FINAL_MANIFEST_RAW_SHA256 = "54746936464af077886908bf818b7e0703c06685997ac501167b755470ad4a7e"
PINNED_IMMUTABLE_AUDIT_RAW_SHA256 = "46ea3bf6e8526f802de4d39000c8201c091fbb2cf1c2f33e5dce8381701ebaff"
PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256 = "76ca072ee8e964b6b52f4e405e29ac806b8c920bf002aecddce9157107c05b8b"
PINNED_EXECUTOR_COMMIT = "4a0d8ecf600451aca56de07cbf449f3f95bafee2"
PINNED_EXECUTOR_MANIFEST_RAW_SHA256 = "b934fad0ad7e3cc4aa3f2c496aaa54ee1fe73c4a369a4ffb6d5bcfe60efcb29b"
PINNED_CHECKPOINT_SET_SHA256 = "5972593eaeeffa632eee5aacea7d039730e80336786e5ce11837773f9c29ec8a"
PINNED_DETERMINISTIC_EVIDENCE_SHA256 = "305686770071fc24a1e43d836dc9fc3ced23a250d79243654e6db4ae842adfef"
PINNED_BASELINE_LINEAGE_SHA256 = "6f3b2aad35dee281bf186b7b4f079c6f656e799769cbaf1df67a99e9620a0a98"
PINNED_UNIVERSE_SHA256 = "aab998d86840441e5a4cf75113a7b2f2c6260229181d2045f1f311de74cdfb9e"
PINNED_MODEL_SLICE_SHA256 = "ad119e6e33114a241fdd20268d4ca5cfabd1d6c08636f48f58545f4ccad2d66e"
EXPECTED_COVERAGE = {"tickers": 474, "folds": 1_896, "oos_observations": 56_880}
ZERO_SIDE_EFFECTS = {
    "database_writes": 0, "bayesian_fits": 0, "predictions": 0,
    "recommendations": 0, "orders": 0, "etf_outputs": 0,
}
ZERO_DOWNSTREAM = {
    "model_runs": 0, "model_scorecards": 0, "etf_prior_lineage": 0,
    "stock_prediction_decision_audits": 0,
    "stock_prediction_criterion_audits": 0, "execution_plans": 0,
    "execution_events": 0, "execution_plan_approvals": 0,
}
AUDIT_CHECKS = {
    "root_only_directories", "root_owned_executor_manifest",
    "executor_artifact_digests", "runtime_commit_binding",
    "exact_checkpoint_file_set", "checkpoint_metadata",
    "checkpoint_and_ticker_digests", "fold_and_oos_denominators",
    "per_model_reconciliation", "live_calendar_and_fold_geometry",
    "independent_downstream_zero_readback", "zero_unauthorized_side_effects",
    "one_hour_freshness_window",
}
DOWNSTREAM_TABLES = tuple(ZERO_DOWNSTREAM)
MODEL_NAMES = ("majority_direction", "constant_training_rate", "lag1_logistic")
EXPECTED_ARMS = (
    {"run_id": "predictive_screening_2026-08-25_w060_2ef4a10", "signal_lookback_sessions": 60,
     "config_sha256": "073d4092b2655afd24b47a92a03eed9c299bb0aa0f28db9927bbe7b60a287f48"},
    {"run_id": "predictive_screening_2026-08-25_w126_2ef4a10", "signal_lookback_sessions": 126,
     "config_sha256": "aaa817550e53ec1695e06b322b9ce1712ff52d146c1bc21065f1b4895d3d0469"},
    {"run_id": "predictive_screening_2026-08-25_w252_2ef4a10", "signal_lookback_sessions": 252,
     "config_sha256": "58b5f36f0315ba8eefa755bb0f25d5a4a39fe9922f6028a41a869b80121e5325"},
)
EXPECTED_COMMON_CONFIG = {
    "training_window_sessions": 289, "min_train_sessions": 289,
    "test_sessions": 30, "outer_folds": 4, "purge_sessions": 7,
    "min_fit_observations": 126, "min_oos_sessions": 120,
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_TICKER = re.compile(r"[A-Z0-9.^-]{1,24}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _fail(message: str) -> None:
    raise PreregistrationError(message)


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} schema differs")
    return value  # type: ignore[return-value]


def _sha(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def _git(value: object, label: str) -> str:
    if type(value) is not str or not _GIT_SHA.fullmatch(value):
        _fail(f"{label} must be a full immutable Git commit")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if type(value) is not str:
        _fail(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PreregistrationError(f"{label} must be an ISO-8601 string") from exc
    if parsed.tzinfo is None:
        _fail(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _finite(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        _fail(f"{label} is outside its contract")
    return number


def _validate_metric_pair(value: object, label: str) -> None:
    pair = _exact(value, {"metrics", "accumulator"}, label)
    acc = _exact(pair["accumulator"], {
        "observations", "correct", "brier_sum", "log_loss_sum", "calibration_bins",
    }, f"{label} accumulator")
    if type(acc["observations"]) is not int or acc["observations"] != 56_880:
        _fail(f"{label} observation denominator differs")
    if type(acc["correct"]) is not int or not 0 <= acc["correct"] <= 56_880:
        _fail(f"{label} correct count differs")
    _finite(acc["brier_sum"], f"{label} brier_sum")
    _finite(acc["log_loss_sum"], f"{label} log_loss_sum")
    bins = acc["calibration_bins"]
    if type(bins) is not list or len(bins) != 10:
        _fail(f"{label} calibration bins differ")
    total = 0
    for index, raw in enumerate(bins):
        item = _exact(raw, {"count", "truth_sum", "probability_sum"}, f"{label} bin {index}")
        if (type(item["count"]) is not int or type(item["truth_sum"]) is not int or
                not 0 <= item["truth_sum"] <= item["count"]):
            _fail(f"{label} calibration counts differ")
        probability_sum = _finite(item["probability_sum"], f"{label} probability_sum")
        if probability_sum > item["count"]:
            _fail(f"{label} probability sum differs")
        total += item["count"]
    if total != 56_880:
        _fail(f"{label} calibration denominator differs")
    metrics = _exact(pair["metrics"], {"accuracy", "brier", "log_loss", "calibration_error"},
                     f"{label} metrics")
    for name, metric in metrics.items():
        _finite(metric, f"{label} {name}")


def _validate_lineage(value: object) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    lineage = _exact(value, {
        "snapshot_id", "snapshot_sha256", "source_session_date", "screening_code_version",
        "screening_runs", "common_config", "ticker_universe", "ticker_universe_sha256",
        "sessions", "sessions_sha256",
    }, "v4 lineage mapping")
    if (lineage["snapshot_id"] != SNAPSHOT_ID or lineage["snapshot_sha256"] != SNAPSHOT_SHA256 or
            lineage["source_session_date"] != SOURCE_SESSION_DATE or
            lineage["screening_code_version"] != SCREENING_CODE_VERSION or
            lineage["screening_runs"] != list(EXPECTED_ARMS) or
            lineage["common_config"] != EXPECTED_COMMON_CONFIG):
        _fail("v4 lineage constants differ")
    tickers = lineage["ticker_universe"]
    sessions = lineage["sessions"]
    if (type(tickers) is not list or len(tickers) != 474 or
            any(type(item) is not str or not _TICKER.fullmatch(item) for item in tickers) or
            tickers != sorted(set(tickers))):
        _fail("v4 ticker universe is not the exact sorted 474-ticker mapping")
    if (type(sessions) is not list or len(sessions) != 1_246 or
            any(type(item) is not str or not _DATE.fullmatch(item) for item in sessions) or
            sessions != sorted(set(sessions)) or sessions[-1] != SOURCE_SESSION_DATE):
        _fail("v4 session mapping is not the exact increasing 1246-date calendar")
    if (lineage["ticker_universe_sha256"] != canonical_sha(tickers) or
            lineage["ticker_universe_sha256"] != PINNED_UNIVERSE_SHA256 or
            lineage["sessions_sha256"] != canonical_sha(sessions) or
            lineage["sessions_sha256"] != SESSION_SHA256):
        _fail("v4 lineage embedded digest differs")
    return lineage, tuple(tickers), tuple(sessions)


def _validate_final_manifest(value: object, *, raw_sha256: str,
                             lineage: Mapping[str, object], tickers: tuple[str, ...]) -> tuple[str, datetime]:
    manifest = _exact(value, {
        "contract_id", "lineage_sha256", "coverage", "aggregate", "ticker_checkpoints",
        "side_effects", "deterministic_evidence_sha256", "runtime",
    }, "v4 final manifest")
    if (manifest["contract_id"] != PRODUCER_CONTRACT_ID or
            manifest["lineage_sha256"] != canonical_sha(lineage) or
            manifest["lineage_sha256"] != PINNED_BASELINE_LINEAGE_SHA256 or
            manifest["coverage"] != EXPECTED_COVERAGE or manifest["side_effects"] != ZERO_SIDE_EFFECTS):
        _fail("v4 final manifest contract, lineage, coverage, or side effects differ")
    deterministic = dict(manifest)
    embedded = _sha(deterministic.pop("deterministic_evidence_sha256"),
                    "final deterministic evidence")
    deterministic.pop("runtime")
    if (embedded != canonical_sha(deterministic) or
            embedded != PINNED_DETERMINISTIC_EVIDENCE_SHA256 or raw_sha256 == embedded):
        _fail("v4 final manifest raw and deterministic identities differ or are conflated")
    entries = manifest["ticker_checkpoints"]
    if type(entries) is not list or len(entries) != 474:
        _fail("v4 checkpoint denominator differs")
    actual_tickers = []
    for index, raw_entry in enumerate(entries):
        entry = _exact(raw_entry, {"ticker", "checkpoint_sha256"}, f"checkpoint {index}")
        if type(entry["ticker"]) is not str or not _TICKER.fullmatch(entry["ticker"]):
            _fail("checkpoint ticker differs")
        _sha(entry["checkpoint_sha256"], "checkpoint identity")
        actual_tickers.append(entry["ticker"])
    if tuple(actual_tickers) != tickers:
        _fail("v4 checkpoint universe differs from independent lineage")
    aggregate = _exact(manifest["aggregate"], set(MODEL_NAMES), "v4 aggregate")
    for name in MODEL_NAMES:
        _validate_metric_pair(aggregate[name], f"v4 aggregate {name}")
    runtime = _exact(manifest["runtime"], {"executor_git_commit", "observed_at_utc"}, "v4 runtime")
    executor_commit = _git(runtime["executor_git_commit"], "v4 executor commit")
    if executor_commit != PINNED_EXECUTOR_COMMIT:
        _fail("v4 executor commit differs from the immutable binding")
    return executor_commit, _timestamp(runtime["observed_at_utc"], "v4 completion")


def _validate_audit(value: object, *, raw_sha256: str, final_raw_sha256: str,
                    deterministic_sha256: str, executor_commit: str,
                    completion: datetime, sessions_sha256: str,
                    immutable: bool) -> tuple[dict[str, object], datetime]:
    audit = _exact(value, {
        "audit_contract_id", "audited_contract_id", "stage", "verified_at_utc",
        "executor_git_commit", "coverage", "checks", "source_artifacts", "side_effects",
        "audit_evidence_sha256",
    }, "v4 audit")
    embedded = _sha(audit["audit_evidence_sha256"], "v4 embedded audit evidence")
    payload = dict(audit)
    payload.pop("audit_evidence_sha256")
    if embedded != canonical_sha(payload) or raw_sha256 == embedded:
        _fail("v4 audit raw and embedded identities differ or are conflated")
    if immutable and embedded != PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256:
        _fail("immutable v4 embedded audit identity differs")
    if (audit["audit_contract_id"] != AUDIT_CONTRACT_ID or
            audit["audited_contract_id"] != PRODUCER_CONTRACT_ID or audit["stage"] != "VERIFIED" or
            audit["executor_git_commit"] != executor_commit or audit["coverage"] != EXPECTED_COVERAGE or
            audit["side_effects"] != ZERO_SIDE_EFFECTS):
        _fail("v4 audit contract, executor, coverage, or side effects differ")
    checks = _exact(audit["checks"], AUDIT_CHECKS, "v4 audit checks")
    if any(value is not True for value in checks.values()):
        _fail("v4 audit checks are not exactly true")
    source = _exact(audit["source_artifacts"], {
        "executor_manifest_file_sha256", "final_manifest_file_sha256",
        "final_deterministic_evidence_sha256", "checkpoint_file_set_sha256",
        "live_session_count", "live_session_sha256", "live_downstream_schema_presence",
        "live_downstream_counts", "live_select_statements",
    }, "v4 audit source artifacts")
    for name in ("executor_manifest_file_sha256", "checkpoint_file_set_sha256"):
        _sha(source[name], f"v4 {name}")
    if (source["final_manifest_file_sha256"] != final_raw_sha256 or
            source["final_deterministic_evidence_sha256"] != deterministic_sha256 or
            source["executor_manifest_file_sha256"] != PINNED_EXECUTOR_MANIFEST_RAW_SHA256 or
            source["checkpoint_file_set_sha256"] != PINNED_CHECKPOINT_SET_SHA256 or
            type(source["live_session_count"]) is not int or source["live_session_count"] != 1_246 or
            source["live_session_sha256"] != sessions_sha256 or
            source["live_session_sha256"] != SESSION_SHA256 or
            source["live_downstream_counts"] != ZERO_DOWNSTREAM or
            type(source["live_select_statements"]) is not int or source["live_select_statements"] != 3):
        _fail("v4 audit source identity or live readback differs")
    presence = _exact(source["live_downstream_schema_presence"], set(DOWNSTREAM_TABLES),
                      "v4 downstream schema presence")
    if any(item not in {"present", "schema_absent"} for item in presence.values()):
        _fail("v4 downstream schema presence differs")
    verified = _timestamp(audit["verified_at_utc"], "v4 audit observation")
    if not completion <= verified <= completion + timedelta(hours=1):
        _fail("v4 audit chronology differs")
    return audit, verified


def _model_configuration() -> ModelConfiguration:
    return ModelConfiguration(
        topology=INDEPENDENT_TOPOLOGY, candidate_lags=EXPECTED_LAGS,
        candidate_depths=EXPECTED_DEPTHS, minimum_fit_observations=126,
        purge_sessions=7, claim_scope=CLAIM_SCOPE, fold_count=4,
        training_width_sessions=289, test_width_sessions=30, step_sessions=30,
        calendar_start_ordinal=0, calendar_end_ordinal=415,
    )


def _folds() -> tuple[WalkForwardFold, ...]:
    return tuple(WalkForwardFold(
        fold_number=index + 1, train_start_ordinal=index * 30,
        train_end_ordinal=index * 30 + 288, test_start_ordinal=index * 30 + 296,
        test_end_ordinal=index * 30 + 325, fit_observations=289, purge_sessions=7,
    ) for index in range(4))


def bind_verified_v4_baseline(
    *, final_manifest: Mapping[str, object], immutable_audit: Mapping[str, object],
    fresh_readback_audit: Mapping[str, object], lineage_mapping: Mapping[str, object],
    final_manifest_file_sha256: str, immutable_audit_file_sha256: str,
    fresh_readback_file_sha256: str, current_model_git_commit: str,
    observed_at_utc: datetime, run_id: str,
) -> dict[str, object]:
    """Return a one-time, fixture-only PASS binding, or fail closed.

    The v4 audit contract permits verification only within one hour of baseline
    completion.  This adapter therefore creates the immutable one-time binding;
    later perpetual runtime readback belongs to a separate governed contract.
    """
    final_raw = _sha(final_manifest_file_sha256, "final manifest raw identity")
    immutable_raw = _sha(immutable_audit_file_sha256, "immutable audit raw identity")
    fresh_raw = _sha(fresh_readback_file_sha256, "fresh readback raw identity")
    model_commit = _git(current_model_git_commit, "current model Git commit")
    if type(run_id) is not str or not run_id.strip() or run_id != run_id.strip():
        _fail("run_id is required and must be normalized")
    if not isinstance(observed_at_utc, datetime) or observed_at_utc.tzinfo is None:
        _fail("binding observation must be timezone-aware")
    observed = observed_at_utc.astimezone(timezone.utc)
    if (final_raw != PINNED_FINAL_MANIFEST_RAW_SHA256 or
            immutable_raw != PINNED_IMMUTABLE_AUDIT_RAW_SHA256):
        _fail("v4 immutable raw artifact identity differs")
    lineage, tickers, sessions = _validate_lineage(lineage_mapping)
    executor_commit, completion = _validate_final_manifest(
        final_manifest, raw_sha256=final_raw, lineage=lineage, tickers=tickers)
    deterministic_sha = final_manifest["deterministic_evidence_sha256"]
    immutable, immutable_at = _validate_audit(
        immutable_audit, raw_sha256=immutable_raw, final_raw_sha256=final_raw,
        deterministic_sha256=deterministic_sha, executor_commit=executor_commit,
        completion=completion, sessions_sha256=lineage["sessions_sha256"], immutable=True)
    fresh, fresh_at = _validate_audit(
        fresh_readback_audit, raw_sha256=fresh_raw, final_raw_sha256=final_raw,
        deterministic_sha256=deterministic_sha, executor_commit=executor_commit,
        completion=completion, sessions_sha256=lineage["sessions_sha256"], immutable=False)
    if (fresh_at < immutable_at or fresh_at > observed or observed - fresh_at > timedelta(hours=1)):
        _fail("fresh readback audit is stale or predates immutable evidence")
    immutable_source = immutable["source_artifacts"]
    fresh_source = fresh["source_artifacts"]
    if immutable_source != fresh_source:
        _fail("fresh readback audit does not match immutable baseline identities")
    immutable_embedded = immutable["audit_evidence_sha256"]
    fresh_embedded = fresh["audit_evidence_sha256"]
    if len({final_raw, deterministic_sha, immutable_raw, immutable_embedded,
            fresh_raw, fresh_embedded}) != 6:
        _fail("raw and embedded source identities are conflated")
    universe_sha = lineage["ticker_universe_sha256"]
    universe_id = f"codex-oracle-stock-universe-v1:{SNAPSHOT_ID}:{universe_sha}"
    model_dates = sessions[-416:]
    if canonical_sha(list(model_dates)) != PINNED_MODEL_SLICE_SHA256:
        _fail("v4 governed 416-session model slice identity differs")
    audit_evidence = BaselineAuditEvidence(
        status="VERIFIED", baseline_manifest_sha256=final_raw,
        snapshot_id=SNAPSHOT_ID, snapshot_sha256=SNAPSHOT_SHA256,
        universe_id=universe_id, universe_sha256=universe_sha,
        full_session_calendar_sha256=lineage["sessions_sha256"],
        model_session_dates_sha256=canonical_sha(list(model_dates)),
        source_audit_artifact_sha256=immutable_raw,
        embedded_audit_evidence_sha256=immutable_embedded,
        audit_sha256="0" * 64, completed_at_utc=completion,
        observed_at_utc=immutable_at, ticker_count=474, fold_count=1_896,
        oos_observation_count=56_880, side_effects=dict(ZERO_SIDE_EFFECTS),
        downstream_counts=dict(ZERO_DOWNSTREAM),
    )
    audit_evidence = replace(
        audit_evidence, audit_sha256=compute_baseline_audit_sha256(audit_evidence))
    model_config = _model_configuration()
    sampler = SamplerConfiguration("pymc-nuts", 4, 1_000, 1_000, 0.9, 20260827)
    request = PreregistrationRequest(
        run_id=run_id,
        lineage=ImmutableLineage(
            snapshot_id=SNAPSHOT_ID, snapshot_sha256=SNAPSHOT_SHA256,
            universe_id=universe_id, universe_sha256=universe_sha,
            session_calendar_sha256=canonical_sha(list(range(416))),
            full_session_calendar_sha256=lineage["sessions_sha256"],
            model_session_dates_sha256=canonical_sha(list(model_dates)),
            baseline_manifest_sha256=final_raw,
            source_audit_artifact_sha256=immutable_raw,
            embedded_audit_evidence_sha256=immutable_embedded,
            baseline_audit_sha256=audit_evidence.audit_sha256,
            code_git_commit=model_commit, config_sha256=canonical_sha(asdict(model_config)),
            sampler_sha256=canonical_sha(asdict(sampler)),
        ),
        model_config=model_config, sampler_config=sampler, folds=_folds(),
        output_intent=ProhibitedOutputIntent(), baseline_audit=audit_evidence,
        session_calendar_ordinals=tuple(range(416)),
        full_session_calendar_dates=sessions, model_session_dates=model_dates,
    )
    readback = BaselineReadbackProof(
        status="VERIFIED", baseline_manifest_sha256=final_raw,
        snapshot_id=SNAPSHOT_ID, snapshot_sha256=SNAPSHOT_SHA256,
        universe_id=universe_id, universe_sha256=universe_sha,
        full_session_calendar_sha256=lineage["sessions_sha256"],
        model_session_dates_sha256=canonical_sha(list(model_dates)),
        source_audit_artifact_sha256=immutable_raw,
        embedded_audit_evidence_sha256=immutable_embedded,
        baseline_audit_sha256=audit_evidence.audit_sha256,
        source_readback_artifact_sha256=fresh_raw,
        source_readback_embedded_evidence_sha256=fresh_embedded,
        source_readback_observed_at_utc=fresh_at, readback_at_utc=fresh_at,
        ticker_count=474, fold_count=1_896, oos_observation_count=56_880,
        side_effects=dict(ZERO_SIDE_EFFECTS), downstream_counts=dict(ZERO_DOWNSTREAM),
    )
    return preregister_model_run(
        request, observed_at_utc=observed, mode=RUN_MODE_NEW, current_readback=readback)


def bind_verified_v4_baseline_with_current_readback(
    *, final_manifest: Mapping[str, object], immutable_audit: Mapping[str, object],
    lineage_mapping: Mapping[str, object], final_manifest_file_sha256: str,
    immutable_audit_file_sha256: str, current_readback: BaselineReadbackProof,
    current_model_git_commit: str, observed_at_utc: datetime, run_id: str,
) -> dict[str, object]:
    """Bind immutable v4 evidence using a separate perpetual current proof.

    Unlike :func:`bind_verified_v4_baseline`, this path does not pretend that
    the v4 completion auditor can be rerun after its one-hour evidence window.
    The caller must independently validate a fresh SELECT-only readback and
    supply the resulting ``BaselineReadbackProof``.  The core preregistration
    validator then replays its freshness, lineage, coverage, zero-output, and
    raw-versus-embedded identity gates before returning a fixture-only manifest.
    """
    final_raw = _sha(final_manifest_file_sha256, "final manifest raw identity")
    immutable_raw = _sha(immutable_audit_file_sha256, "immutable audit raw identity")
    model_commit = _git(current_model_git_commit, "current model Git commit")
    if type(run_id) is not str or not run_id.strip() or run_id != run_id.strip():
        _fail("run_id is required and must be normalized")
    if type(current_readback) is not BaselineReadbackProof:
        _fail("current readback must use the exact BaselineReadbackProof type")
    if not isinstance(observed_at_utc, datetime) or observed_at_utc.tzinfo is None:
        _fail("binding observation must be timezone-aware")
    observed = observed_at_utc.astimezone(timezone.utc)
    if (final_raw != PINNED_FINAL_MANIFEST_RAW_SHA256 or
            immutable_raw != PINNED_IMMUTABLE_AUDIT_RAW_SHA256):
        _fail("v4 immutable raw artifact identity differs")

    lineage, tickers, sessions = _validate_lineage(lineage_mapping)
    executor_commit, completion = _validate_final_manifest(
        final_manifest, raw_sha256=final_raw, lineage=lineage, tickers=tickers)
    deterministic_sha = final_manifest["deterministic_evidence_sha256"]
    immutable, immutable_at = _validate_audit(
        immutable_audit, raw_sha256=immutable_raw, final_raw_sha256=final_raw,
        deterministic_sha256=deterministic_sha, executor_commit=executor_commit,
        completion=completion, sessions_sha256=lineage["sessions_sha256"],
        immutable=True)
    immutable_embedded = immutable["audit_evidence_sha256"]
    if len({
        final_raw, deterministic_sha, immutable_raw, immutable_embedded,
        current_readback.source_readback_artifact_sha256,
        current_readback.source_readback_embedded_evidence_sha256,
    }) != 6:
        _fail("immutable and current readback identities are conflated")

    universe_sha = lineage["ticker_universe_sha256"]
    universe_id = f"codex-oracle-stock-universe-v1:{SNAPSHOT_ID}:{universe_sha}"
    model_dates = sessions[-416:]
    if canonical_sha(list(model_dates)) != PINNED_MODEL_SLICE_SHA256:
        _fail("v4 governed 416-session model slice identity differs")
    audit_evidence = BaselineAuditEvidence(
        status="VERIFIED", baseline_manifest_sha256=final_raw,
        snapshot_id=SNAPSHOT_ID, snapshot_sha256=SNAPSHOT_SHA256,
        universe_id=universe_id, universe_sha256=universe_sha,
        full_session_calendar_sha256=lineage["sessions_sha256"],
        model_session_dates_sha256=canonical_sha(list(model_dates)),
        source_audit_artifact_sha256=immutable_raw,
        embedded_audit_evidence_sha256=immutable_embedded,
        audit_sha256="0" * 64, completed_at_utc=completion,
        observed_at_utc=immutable_at, ticker_count=474, fold_count=1_896,
        oos_observation_count=56_880, side_effects=dict(ZERO_SIDE_EFFECTS),
        downstream_counts=dict(ZERO_DOWNSTREAM),
    )
    audit_evidence = replace(
        audit_evidence, audit_sha256=compute_baseline_audit_sha256(audit_evidence))
    model_config = _model_configuration()
    sampler = SamplerConfiguration("pymc-nuts", 4, 1_000, 1_000, 0.9, 20260827)
    request = PreregistrationRequest(
        run_id=run_id,
        lineage=ImmutableLineage(
            snapshot_id=SNAPSHOT_ID, snapshot_sha256=SNAPSHOT_SHA256,
            universe_id=universe_id, universe_sha256=universe_sha,
            session_calendar_sha256=canonical_sha(list(range(416))),
            full_session_calendar_sha256=lineage["sessions_sha256"],
            model_session_dates_sha256=canonical_sha(list(model_dates)),
            baseline_manifest_sha256=final_raw,
            source_audit_artifact_sha256=immutable_raw,
            embedded_audit_evidence_sha256=immutable_embedded,
            baseline_audit_sha256=audit_evidence.audit_sha256,
            code_git_commit=model_commit,
            config_sha256=canonical_sha(asdict(model_config)),
            sampler_sha256=canonical_sha(asdict(sampler)),
        ),
        model_config=model_config, sampler_config=sampler, folds=_folds(),
        output_intent=ProhibitedOutputIntent(), baseline_audit=audit_evidence,
        session_calendar_ordinals=tuple(range(416)),
        full_session_calendar_dates=sessions, model_session_dates=model_dates,
    )
    return preregister_model_run(
        request, observed_at_utc=observed, mode=RUN_MODE_NEW,
        current_readback=current_readback)


__all__ = [
    "bind_verified_v4_baseline",
    "bind_verified_v4_baseline_with_current_readback",
]
