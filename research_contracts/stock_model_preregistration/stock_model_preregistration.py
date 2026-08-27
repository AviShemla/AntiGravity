"""Pure, fixture-only preregistration for the successor stock model.

This module performs no I/O and cannot fit a model. It freezes the exact
lineage and walk-forward geometry that a later, separately authorized runner
must reproduce before any Bayesian computation may begin.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Mapping, Sequence


CONTRACT_ID = "codex-oracle-hierarchical-stock-preregistration-v1"
INDEPENDENT_TOPOLOGY = "INDEPENDENT_TICKER_LAG_EDGES"
CLAIM_SCOPE = "OBSERVATIONAL_PREDICTIVE_ASSOCIATION_NOT_CAUSAL"
OUTPUT_INTENT = "RESEARCH_MODEL_DIAGNOSTICS_ONLY"
RUN_MODE_NEW = "NEW_RUN"
RUN_MODE_RESUME = "RESUME"
EXPECTED_LAGS = tuple(range(1, 8))
EXPECTED_DEPTHS = tuple(range(1, 6))
EXPECTED_BASELINE_COVERAGE = {
    "tickers": 474,
    "folds": 1_896,
    "oos_observations": 56_880,
}
ZERO_BASELINE_SIDE_EFFECTS = {
    "database_writes": 0,
    "bayesian_fits": 0,
    "predictions": 0,
    "recommendations": 0,
    "orders": 0,
    "etf_outputs": 0,
}
MAX_BASELINE_AUDIT_AGE = timedelta(hours=1)
GOVERNED_FOLD_COUNT = 4
GOVERNED_MINIMUM_FIT_OBSERVATIONS = 126
GOVERNED_TRAINING_WIDTH_SESSIONS = 289
GOVERNED_TEST_WIDTH_SESSIONS = 30
GOVERNED_STEP_SESSIONS = 30
GOVERNED_PURGE_SESSIONS = 7
GOVERNED_CALENDAR_LENGTH = 416
SEMANTIC_VALIDATORS = (
    "lineage",
    "baseline_audit_digest_and_semantics",
    "current_baseline_readback",
    "model_contract",
    "walk_forward_geometry",
    "output_intent",
    "zero_execution",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


class PreregistrationError(RuntimeError):
    """Raised before execution when a frozen research contract is unsafe."""


def canonical_sha(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PreregistrationError("canonical payload contains an unsupported value") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ImmutableLineage:
    snapshot_id: str
    snapshot_sha256: str
    universe_id: str
    universe_sha256: str
    session_calendar_sha256: str
    baseline_manifest_sha256: str
    baseline_audit_sha256: str
    code_git_commit: str
    config_sha256: str
    sampler_sha256: str


@dataclass(frozen=True)
class BaselineAuditEvidence:
    status: str
    baseline_manifest_sha256: str
    audit_sha256: str
    completed_at_utc: datetime
    observed_at_utc: datetime
    ticker_count: int
    fold_count: int
    oos_observation_count: int
    side_effects: Mapping[str, int]


@dataclass(frozen=True)
class BaselineReadbackProof:
    status: str
    baseline_manifest_sha256: str
    baseline_audit_sha256: str
    readback_at_utc: datetime
    ticker_count: int
    fold_count: int
    oos_observation_count: int
    side_effects: Mapping[str, int]


@dataclass(frozen=True)
class WalkForwardFold:
    fold_number: int
    train_start_ordinal: int
    train_end_ordinal: int
    test_start_ordinal: int
    test_end_ordinal: int
    fit_observations: int
    purge_sessions: int = 7


@dataclass(frozen=True)
class ModelConfiguration:
    topology: str
    candidate_lags: tuple[int, ...]
    candidate_depths: tuple[int, ...]
    minimum_fit_observations: int
    purge_sessions: int
    claim_scope: str
    fold_count: int
    training_width_sessions: int
    test_width_sessions: int
    step_sessions: int
    calendar_start_ordinal: int
    calendar_end_ordinal: int


@dataclass(frozen=True)
class SamplerConfiguration:
    engine: str
    chains: int
    draws: int
    tune: int
    target_accept: float
    random_seed: int


@dataclass(frozen=True)
class ProhibitedOutputIntent:
    intent: str = OUTPUT_INTENT
    persist_predictions: bool = False
    create_recommendations: bool = False
    create_orders: bool = False
    create_etf_outputs: bool = False
    activate_trading: bool = False


@dataclass(frozen=True)
class PreregistrationRequest:
    run_id: str
    lineage: ImmutableLineage
    model_config: ModelConfiguration
    sampler_config: SamplerConfiguration
    folds: tuple[WalkForwardFold, ...]
    output_intent: ProhibitedOutputIntent
    baseline_audit: BaselineAuditEvidence | None
    session_calendar_ordinals: tuple[int, ...]


def _require_sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PreregistrationError(f"{label} must be a lowercase SHA-256 digest")


def _require_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise PreregistrationError(f"{label} must be an integer")
    return value


def _require_int_mapping(
    value: object, expected_keys: set[str], label: str
) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise PreregistrationError(f"{label} schema differs")
    result = dict(value)
    for key, item in result.items():
        _require_int(item, f"{label}.{key}")
    return result


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PreregistrationError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise PreregistrationError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PreregistrationError(f"{label} must be an ISO-8601 string") from exc
    return _utc(parsed, label)


def _baseline_audit_payload(evidence: BaselineAuditEvidence) -> dict[str, object]:
    """Return the exact independently hashable baseline evidence payload."""
    return {
        "status": evidence.status,
        "baseline_manifest_sha256": evidence.baseline_manifest_sha256,
        "completed_at_utc": _utc(
            evidence.completed_at_utc, "baseline audit completion"
        ).isoformat(),
        "observed_at_utc": _utc(
            evidence.observed_at_utc, "baseline audit observation"
        ).isoformat(),
        "ticker_count": evidence.ticker_count,
        "fold_count": evidence.fold_count,
        "oos_observation_count": evidence.oos_observation_count,
        "side_effects": dict(evidence.side_effects),
    }


def compute_baseline_audit_sha256(evidence: BaselineAuditEvidence) -> str:
    """Recompute baseline evidence identity, excluding its claimed digest."""
    return canonical_sha(_baseline_audit_payload(evidence))


def _validate_lineage(request: PreregistrationRequest) -> None:
    lineage = request.lineage
    if not isinstance(request.run_id, str) or not request.run_id.strip():
        raise PreregistrationError("run_id is required")
    if (
        not isinstance(lineage.snapshot_id, str)
        or not lineage.snapshot_id.strip()
        or not isinstance(lineage.universe_id, str)
        or not lineage.universe_id.strip()
    ):
        raise PreregistrationError("snapshot and universe identities are required")
    for name in (
        "snapshot_sha256", "universe_sha256", "session_calendar_sha256",
        "baseline_manifest_sha256", "baseline_audit_sha256", "config_sha256",
        "sampler_sha256",
    ):
        _require_sha(getattr(lineage, name), name)
    if not isinstance(lineage.code_git_commit, str) or not _GIT_SHA.fullmatch(
        lineage.code_git_commit
    ):
        raise PreregistrationError("code_git_commit must be an immutable Git SHA")
    if lineage.config_sha256 != canonical_sha(asdict(request.model_config)):
        raise PreregistrationError("model configuration lineage mismatch")
    if lineage.sampler_sha256 != canonical_sha(asdict(request.sampler_config)):
        raise PreregistrationError("sampler configuration lineage mismatch")
    calendar = request.session_calendar_ordinals
    governed_calendar = tuple(range(GOVERNED_CALENDAR_LENGTH))
    if not isinstance(calendar, tuple) or len(calendar) != GOVERNED_CALENDAR_LENGTH:
        raise PreregistrationError("session calendar must contain the exact governed ordinals")
    for index, ordinal in enumerate(calendar):
        _require_int(ordinal, f"session calendar ordinal {index}")
        if index and ordinal != calendar[index - 1] + 1:
            raise PreregistrationError("session calendar ordinals are not contiguous")
    if calendar != governed_calendar:
        raise PreregistrationError("session calendar differs from governed ordinals 0 through 415")
    if canonical_sha(list(calendar)) != lineage.session_calendar_sha256:
        raise PreregistrationError("session calendar lineage mismatch")


def _validate_baseline_audit(
    evidence: BaselineAuditEvidence | None,
    lineage: ImmutableLineage,
    observed_at_utc: datetime,
) -> None:
    if evidence is None:
        raise PreregistrationError("verified baseline audit evidence is missing")
    completed = _utc(evidence.completed_at_utc, "baseline audit completion")
    observed = _utc(evidence.observed_at_utc, "baseline audit observation")
    if evidence.status != "VERIFIED":
        raise PreregistrationError("baseline audit is not VERIFIED")
    if evidence.baseline_manifest_sha256 != lineage.baseline_manifest_sha256:
        raise PreregistrationError("baseline audit lineage mismatch")
    for label, value in (
        ("baseline audit ticker_count", evidence.ticker_count),
        ("baseline audit fold_count", evidence.fold_count),
        ("baseline audit oos_observation_count", evidence.oos_observation_count),
    ):
        _require_int(value, label)
    side_effects = _require_int_mapping(
        evidence.side_effects, set(ZERO_BASELINE_SIDE_EFFECTS),
        "baseline audit side effects",
    )
    _require_sha(evidence.audit_sha256, "baseline audit identity")
    recomputed_audit_sha = compute_baseline_audit_sha256(evidence)
    if evidence.audit_sha256 != recomputed_audit_sha:
        raise PreregistrationError("baseline audit evidence digest mismatch")
    if lineage.baseline_audit_sha256 != recomputed_audit_sha:
        raise PreregistrationError("baseline audit identity mismatch")
    if observed < completed or observed > observed_at_utc:
        raise PreregistrationError("baseline audit timestamps are contradictory")
    actual_coverage = {
        "tickers": evidence.ticker_count,
        "folds": evidence.fold_count,
        "oos_observations": evidence.oos_observation_count,
    }
    if actual_coverage != EXPECTED_BASELINE_COVERAGE:
        raise PreregistrationError("baseline audit coverage is partial")
    if side_effects != ZERO_BASELINE_SIDE_EFFECTS:
        raise PreregistrationError("baseline audit reports prohibited side effects")


def _validate_current_readback(
    proof: BaselineReadbackProof | None,
    lineage: ImmutableLineage,
    evidence: BaselineAuditEvidence | None,
    observed_at_utc: datetime,
) -> None:
    if proof is None:
        raise PreregistrationError("current baseline readback proof is required")
    if evidence is None:
        raise PreregistrationError("verified baseline audit evidence is missing")
    if proof.status != "VERIFIED":
        raise PreregistrationError("current baseline readback is not VERIFIED")
    _require_sha(proof.baseline_manifest_sha256, "readback baseline manifest identity")
    _require_sha(proof.baseline_audit_sha256, "readback baseline audit identity")
    if (
        proof.baseline_manifest_sha256 != lineage.baseline_manifest_sha256
        or proof.baseline_audit_sha256 != lineage.baseline_audit_sha256
    ):
        raise PreregistrationError("current baseline readback lineage mismatch")
    readback_at = _utc(proof.readback_at_utc, "current baseline readback")
    immutable_evidence_at = max(
        _utc(evidence.completed_at_utc, "baseline audit completion"),
        _utc(evidence.observed_at_utc, "baseline audit observation"),
    )
    if readback_at < immutable_evidence_at:
        raise PreregistrationError("current baseline readback predates immutable evidence")
    if readback_at > observed_at_utc or observed_at_utc - readback_at > MAX_BASELINE_AUDIT_AGE:
        raise PreregistrationError("current baseline readback proof is stale")
    for label, value in (
        ("readback ticker_count", proof.ticker_count),
        ("readback fold_count", proof.fold_count),
        ("readback oos_observation_count", proof.oos_observation_count),
    ):
        _require_int(value, label)
    readback_side_effects = _require_int_mapping(
        proof.side_effects, set(ZERO_BASELINE_SIDE_EFFECTS),
        "current readback side effects",
    )
    if {
        "tickers": proof.ticker_count,
        "folds": proof.fold_count,
        "oos_observations": proof.oos_observation_count,
    } != EXPECTED_BASELINE_COVERAGE:
        raise PreregistrationError("current baseline readback coverage is partial")
    if readback_side_effects != ZERO_BASELINE_SIDE_EFFECTS:
        raise PreregistrationError("current baseline readback reports prohibited side effects")
    if (
        proof.ticker_count != evidence.ticker_count
        or proof.fold_count != evidence.fold_count
        or proof.oos_observation_count != evidence.oos_observation_count
        or readback_side_effects != dict(evidence.side_effects)
    ):
        raise PreregistrationError("current baseline readback differs from immutable evidence")


def _validate_model_contract(request: PreregistrationRequest) -> None:
    config = request.model_config
    if config.topology != INDEPENDENT_TOPOLOGY:
        raise PreregistrationError("forced-chain topology is prohibited")
    if (
        not isinstance(config.candidate_lags, tuple)
        or any(type(value) is not int for value in config.candidate_lags)
        or config.candidate_lags != EXPECTED_LAGS
    ):
        raise PreregistrationError("candidate lags must be exactly 1 through 7")
    if (
        not isinstance(config.candidate_depths, tuple)
        or any(type(value) is not int for value in config.candidate_depths)
        or config.candidate_depths != EXPECTED_DEPTHS
    ):
        raise PreregistrationError("candidate depths must be exactly 1 through 5")
    if config.claim_scope != CLAIM_SCOPE:
        raise PreregistrationError("research claim must be observational, not causal")
    governed_ints = {
        "minimum_fit_observations": GOVERNED_MINIMUM_FIT_OBSERVATIONS,
        "purge_sessions": GOVERNED_PURGE_SESSIONS,
        "fold_count": GOVERNED_FOLD_COUNT,
        "training_width_sessions": GOVERNED_TRAINING_WIDTH_SESSIONS,
        "test_width_sessions": GOVERNED_TEST_WIDTH_SESSIONS,
        "step_sessions": GOVERNED_STEP_SESSIONS,
    }
    for field, expected in governed_ints.items():
        value = getattr(config, field)
        _require_int(value, f"model configuration {field}")
        if value != expected:
            raise PreregistrationError(f"{field} differs from governed geometry")
    _require_int(config.calendar_start_ordinal, "model configuration calendar_start_ordinal")
    _require_int(config.calendar_end_ordinal, "model configuration calendar_end_ordinal")
    if (
        config.calendar_start_ordinal != request.session_calendar_ordinals[0]
        or config.calendar_end_ordinal != request.session_calendar_ordinals[-1]
    ):
        raise PreregistrationError("configured calendar ordinals differ from bound calendar")
    sampler = request.sampler_config
    for field in ("chains", "draws", "tune", "random_seed"):
        _require_int(getattr(sampler, field), f"sampler {field}")
    if (
        isinstance(sampler.target_accept, bool)
        or not isinstance(sampler.target_accept, (int, float))
        or not math.isfinite(sampler.target_accept)
    ):
        raise PreregistrationError("sampler target_accept must be finite")
    if (
        not isinstance(sampler.engine, str) or not sampler.engine.strip()
        or sampler.chains < 2 or sampler.draws <= 0 or sampler.tune <= 0
        or not 0.5 <= sampler.target_accept < 1.0 or sampler.random_seed < 0
    ):
        raise PreregistrationError("sampler configuration is incomplete or unsafe")


def _validate_folds(
    folds: Sequence[WalkForwardFold], config: ModelConfiguration
) -> None:
    if len(folds) != config.fold_count:
        raise PreregistrationError("walk-forward fold count differs from configuration")
    test_ranges: list[set[int]] = []
    for index, fold in enumerate(folds):
        for field in (
            "fold_number", "train_start_ordinal", "train_end_ordinal",
            "test_start_ordinal", "test_end_ordinal", "fit_observations",
            "purge_sessions",
        ):
            _require_int(getattr(fold, field), f"fold {index + 1} {field}")
        expected_number = index + 1
        expected_train_start = config.calendar_start_ordinal + index * config.step_sessions
        expected_train_end = expected_train_start + config.training_width_sessions - 1
        expected_test_start = expected_train_end + config.purge_sessions + 1
        expected_test_end = expected_test_start + config.test_width_sessions - 1
        if fold.fold_number != expected_number:
            raise PreregistrationError("walk-forward fold numbering is not contiguous")
        if (
            fold.train_start_ordinal, fold.train_end_ordinal,
            fold.test_start_ordinal, fold.test_end_ordinal,
        ) != (
            expected_train_start, expected_train_end,
            expected_test_start, expected_test_end,
        ):
            raise PreregistrationError("walk-forward fold differs from frozen geometry")
        if fold.purge_sessions != config.purge_sessions:
            raise PreregistrationError("walk-forward fold violates configured purge")
        if fold.fit_observations < config.minimum_fit_observations:
            raise PreregistrationError(
                "walk-forward fold has fewer than configured minimum fit observations"
            )
        if fold.fit_observations != config.training_width_sessions:
            raise PreregistrationError(
                "fold fit observations differ from frozen training width"
            )
        test_range = set(range(fold.test_start_ordinal, fold.test_end_ordinal + 1))
        if any(test_range & prior_range for prior_range in test_ranges):
            raise PreregistrationError("walk-forward outer test folds overlap")
        test_ranges.append(test_range)
    if folds[-1].test_end_ordinal != config.calendar_end_ordinal:
        raise PreregistrationError("walk-forward calendar end differs from configuration")


def _validate_output_intent(intent: ProhibitedOutputIntent) -> None:
    flags = (
        intent.persist_predictions, intent.create_recommendations,
        intent.create_orders, intent.create_etf_outputs, intent.activate_trading,
    )
    if (
        intent.intent != OUTPUT_INTENT
        or any(type(value) is not bool for value in flags)
        or any(flags)
    ):
        raise PreregistrationError("prohibited downstream output intent")


def _validate_execution(execution: object) -> None:
    count_keys = {
        "predictions_created", "recommendations_created", "orders_created",
        "etf_outputs_created",
    }
    if not isinstance(execution, Mapping) or set(execution) != {
        "model_fit_started", *count_keys,
    }:
        raise PreregistrationError("preregistration manifest contains downstream outputs")
    if type(execution["model_fit_started"]) is not bool or execution["model_fit_started"]:
        raise PreregistrationError("preregistration manifest contains downstream outputs")
    if any(type(execution[key]) is not int or execution[key] != 0 for key in count_keys):
        raise PreregistrationError("preregistration manifest contains downstream outputs")


def _baseline_audit_manifest_payload(
    evidence: BaselineAuditEvidence,
) -> dict[str, object]:
    return {**_baseline_audit_payload(evidence), "audit_sha256": evidence.audit_sha256}


def _manifest_payload(
    request: PreregistrationRequest, *, preflight_observed_at_utc: datetime
) -> dict[str, object]:
    audit = request.baseline_audit
    assert audit is not None
    return {
        "contract_id": CONTRACT_ID,
        "run_id": request.run_id,
        "lineage": asdict(request.lineage),
        "session_calendar_ordinals": request.session_calendar_ordinals,
        "model_config": asdict(request.model_config),
        "sampler_config": asdict(request.sampler_config),
        "folds": [asdict(fold) for fold in request.folds],
        "baseline_audit": _baseline_audit_manifest_payload(audit),
        "output_intent": asdict(request.output_intent),
        "execution": {
            "model_fit_started": False,
            "predictions_created": 0,
            "recommendations_created": 0,
            "orders_created": 0,
            "etf_outputs_created": 0,
        },
        "preflight": {
            "status": "PASS",
            "observed_at_utc": preflight_observed_at_utc.isoformat(),
            "fixture_only": True,
            "model_fit_authorized": False,
            "registration_mode": RUN_MODE_NEW,
            "semantic_validators": SEMANTIC_VALIDATORS,
        },
    }


def _with_identity(payload: Mapping[str, object]) -> dict[str, object]:
    result = deepcopy(dict(payload))
    result["checkpoint_identity_sha256"] = canonical_sha(payload)
    return result


def _request_from_manifest(manifest: Mapping[str, object]) -> PreregistrationRequest:
    try:
        lineage_raw = manifest["lineage"]
        model_raw = dict(manifest["model_config"])
        sampler_raw = manifest["sampler_config"]
        folds_raw = manifest["folds"]
        calendar_raw = manifest["session_calendar_ordinals"]
        intent_raw = manifest["output_intent"]
        audit_raw = dict(manifest["baseline_audit"])
        if not all(isinstance(value, Mapping) for value in (
            lineage_raw, model_raw, sampler_raw, intent_raw,
        )) or not isinstance(folds_raw, Sequence) or not isinstance(calendar_raw, Sequence):
            raise TypeError("nested manifest type")
        model_raw["candidate_lags"] = tuple(model_raw["candidate_lags"])
        model_raw["candidate_depths"] = tuple(model_raw["candidate_depths"])
        audit = BaselineAuditEvidence(**{
            **audit_raw,
            "completed_at_utc": _parse_utc(
                audit_raw["completed_at_utc"], "baseline audit completion"
            ),
            "observed_at_utc": _parse_utc(
                audit_raw["observed_at_utc"], "baseline audit observation"
            ),
        })
        return PreregistrationRequest(
            run_id=manifest["run_id"],
            lineage=ImmutableLineage(**dict(lineage_raw)),
            model_config=ModelConfiguration(**model_raw),
            sampler_config=SamplerConfiguration(**dict(sampler_raw)),
            folds=tuple(WalkForwardFold(**dict(fold)) for fold in folds_raw),
            output_intent=ProhibitedOutputIntent(**dict(intent_raw)),
            baseline_audit=audit,
            session_calendar_ordinals=tuple(calendar_raw),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PreregistrationError("preregistration manifest payload is invalid") from exc


def _validate_request(
    request: PreregistrationRequest,
    observed_at: datetime,
    current_readback: BaselineReadbackProof | None,
) -> None:
    _validate_lineage(request)
    _validate_baseline_audit(request.baseline_audit, request.lineage, observed_at)
    _validate_current_readback(
        current_readback, request.lineage, request.baseline_audit, observed_at
    )
    _validate_model_contract(request)
    _validate_folds(request.folds, request.model_config)
    _validate_output_intent(request.output_intent)


def preregister_model_run(
    request: PreregistrationRequest,
    *,
    observed_at_utc: datetime,
    mode: str,
    current_readback: BaselineReadbackProof | None,
    expected_checkpoint_identity: str | None = None,
    existing_manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create a new frozen manifest or verify an identity-bound resume."""
    observed_at = _utc(observed_at_utc, "preflight observation")
    if mode == RUN_MODE_NEW:
        if expected_checkpoint_identity is not None or existing_manifest is not None:
            raise PreregistrationError("NEW_RUN cannot accept restart evidence")
        _validate_request(request, observed_at, current_readback)
        return _with_identity(
            _manifest_payload(request, preflight_observed_at_utc=observed_at)
        )
    if mode != RUN_MODE_RESUME:
        raise PreregistrationError("mode must be explicitly NEW_RUN or RESUME")
    if expected_checkpoint_identity is None or existing_manifest is None:
        raise PreregistrationError(
            "RESUME requires prior manifest and restart checkpoint identity"
        )
    _require_sha(expected_checkpoint_identity, "restart checkpoint identity")
    audit_preregistration_manifest(
        existing_manifest,
        observed_at_utc=observed_at,
        current_readback=current_readback,
    )
    actual_identity = existing_manifest["checkpoint_identity_sha256"]
    if actual_identity != expected_checkpoint_identity:
        raise PreregistrationError("restart checkpoint identity mismatch")
    _validate_request(request, observed_at, current_readback)
    preflight_raw = existing_manifest["preflight"]
    frozen_observed_at = _parse_utc(
        preflight_raw["observed_at_utc"], "preflight observation"
    )
    candidate = _with_identity(
        _manifest_payload(request, preflight_observed_at_utc=frozen_observed_at)
    )
    if candidate["checkpoint_identity_sha256"] != actual_identity:
        raise PreregistrationError("restart request differs from frozen manifest")
    return deepcopy(dict(existing_manifest))


def audit_preregistration_manifest(
    manifest: Mapping[str, object], *, observed_at_utc: datetime,
    current_readback: BaselineReadbackProof | None,
) -> None:
    """Independently replay every semantic validator and reject any bypass."""
    expected = {
        "contract_id", "run_id", "lineage", "session_calendar_ordinals",
        "model_config", "sampler_config",
        "folds", "baseline_audit", "output_intent", "execution",
        "checkpoint_identity_sha256", "preflight",
    }
    if not isinstance(manifest, Mapping) or set(manifest) != expected:
        raise PreregistrationError("preregistration manifest schema differs")
    if manifest["contract_id"] != CONTRACT_ID:
        raise PreregistrationError("preregistration contract identity differs")
    preflight = manifest["preflight"]
    if not isinstance(preflight, Mapping) or set(preflight) != {
        "status", "observed_at_utc", "fixture_only", "model_fit_authorized",
        "registration_mode", "semantic_validators",
    }:
        raise PreregistrationError("preregistration preflight schema differs")
    semantic_validators = preflight["semantic_validators"]
    if (
        not isinstance(semantic_validators, Sequence)
        or isinstance(semantic_validators, (str, bytes))
    ):
        raise PreregistrationError("preregistration preflight evidence differs")
    if (
        preflight["status"] != "PASS"
        or preflight["fixture_only"] is not True
        or preflight["model_fit_authorized"] is not False
        or preflight["registration_mode"] != RUN_MODE_NEW
        or tuple(semantic_validators) != SEMANTIC_VALIDATORS
    ):
        raise PreregistrationError("preregistration preflight evidence differs")
    preflight_observed_at = _parse_utc(
        preflight["observed_at_utc"], "preflight observation"
    )
    observed_at = _utc(observed_at_utc, "independent audit observation")
    if observed_at < preflight_observed_at:
        raise PreregistrationError("independent audit predates preflight")
    identity = manifest["checkpoint_identity_sha256"]
    _require_sha(identity, "checkpoint identity")
    identity_payload = dict(manifest)
    identity_payload.pop("checkpoint_identity_sha256")
    if identity != canonical_sha(identity_payload):
        raise PreregistrationError("preregistration manifest identity mismatch")
    request = _request_from_manifest(manifest)
    _validate_request(request, observed_at, current_readback)
    _validate_execution(manifest["execution"])
    canonical_payload = _manifest_payload(
        request, preflight_observed_at_utc=preflight_observed_at
    )
    if canonical_sha(canonical_payload) != identity:
        raise PreregistrationError("preregistration manifest is not canonical")
