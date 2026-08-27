"""Fail-closed bridge from canonical fixture evidence to real comparisons.

This module intentionally consumes the existing canonical posterior-evaluation
types and digest functions.  It does not define a second lineage structure and
does not reinterpret any canonical digest, including ``universe_sha256``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib

from posterior_evaluation_contract import (  # type: ignore[import-not-found]
    ContractError,
    OperationalBoundary,
    PosteriorEvaluationArtifact,
    PosteriorEvaluationRequest,
    PredictionEvidenceRow,
    SHA256,
    artifact_sha256,
    audit_fixture_posterior_artifact,
    canonical_json,
)


CONTRACT_ID = "codex-oracle-s11-canonical-prediction-comparison-gate-v1"
MAX_INDEPENDENT_AUDIT_AGE = timedelta(minutes=5)


class ComparisonGateStatus(StrEnum):
    FIXTURE_ONLY_BLOCKED = "FIXTURE_ONLY_BLOCKED"
    ABSENT_POSTERIOR_BLOCKED = "ABSENT_POSTERIOR_BLOCKED"


class OldAGDecisionProvenance(StrEnum):
    HISTORICAL_RECORDED_DECISION = "HISTORICAL_RECORDED_DECISION"
    HISTORICAL_RULE_REPLAY = "HISTORICAL_RULE_REPLAY"


@dataclass(frozen=True)
class IndependentDecisionDerivationEvidence:
    prediction_id: str
    old_ag_provenance: OldAGDecisionProvenance
    input_posterior_record_sha256: str
    old_ag_input_bundle_sha256: str
    old_ag_input_max_available_at_utc: datetime
    old_ag_effective_as_of_utc: datetime
    old_ag_evaluator_release_sha256: str
    old_ag_policy_artifact_sha256: str
    old_ag_evaluated_at_utc: datetime
    old_ag_decision_recorded_at_utc: datetime | None
    old_ag_source_record_sha256: str | None
    old_ag_canonical_output_sha256: str
    old_ag_independent_replay_audit_sha256: str
    codex_input_bundle_sha256: str
    codex_input_max_available_at_utc: datetime
    codex_effective_as_of_utc: datetime
    codex_evaluator_release_sha256: str
    codex_policy_artifact_sha256: str
    codex_evaluated_at_utc: datetime
    codex_canonical_output_sha256: str
    codex_independent_replay_audit_sha256: str
    independently_audited_at_utc: datetime


@dataclass(frozen=True)
class IndependentPosteriorAcceptanceReference:
    """Opaque reference to a future canonical non-fixture acceptance artifact.

    This is deliberately not lineage.  The referenced canonical artifact type
    and its independent auditor do not yet exist, so this reference can never
    make a fixture artifact eligible.
    """

    acceptance_contract_id: str
    accepted_posterior_artifact_sha256: str
    independent_audit_sha256: str
    accepted_prediction_count: int
    fixture_only: bool


@dataclass(frozen=True)
class CanonicalPredictionComparisonEnvelope:
    contract_id: str
    status: ComparisonGateStatus
    blocker_codes: tuple[str, ...]
    canonical_request_sha256: str
    canonical_fixture_artifact_sha256: str
    canonical_fixture_review_row_count: int
    accepted_posterior_reference_sha256: str | None
    accepted_prediction_evidence_rows: tuple[PredictionEvidenceRow, ...]
    boundary: OperationalBoundary
    envelope_sha256: str


def _envelope_sha256(payload: dict[str, object]) -> str:
    """Use the canonical contract's JSON semantics, without a parallel codec."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _sha(value: object, label: str) -> str:
    if type(value) is not str or not SHA256.fullmatch(value):
        raise ContractError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise ContractError(f"{label} must be an exact timezone-aware datetime.")
    return value.astimezone(timezone.utc)


def canonical_posterior_record_sha256(row: PredictionEvidenceRow) -> str:
    """Hash only the canonical posterior-record inputs using canonical JSON."""
    if type(row) is not PredictionEvidenceRow:
        raise ContractError("Posterior record must use the exact canonical row type.")
    payload = {
        "prediction_id": row.prediction_id,
        "model_run_id": row.model_run_id,
        "fold_id": row.fold_id,
        "ticker": row.ticker,
        "persona": row.persona,
        "prediction_date": row.prediction_date,
        "source_session_date": row.source_session_date,
        "posterior_available_at_utc": row.posterior_available_at_utc,
        "prediction_cutoff_at_utc": row.prediction_cutoff_at_utc,
        "raw_bayesian_output": row.raw_bayesian_output,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_old_ag_output_sha256(
    row: PredictionEvidenceRow,
    provenance: OldAGDecisionProvenance,
) -> str:
    if type(row) is not PredictionEvidenceRow or type(provenance) is not OldAGDecisionProvenance:
        raise ContractError("Old-AG output requires exact canonical row and provenance types.")
    payload = {
        "prediction_id": row.prediction_id,
        "provenance": provenance,
        "old_ag_decision": row.old_ag_decision,
        "old_ag_reasons": row.old_ag_reasons,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_codex_output_sha256(row: PredictionEvidenceRow) -> str:
    if type(row) is not PredictionEvidenceRow:
        raise ContractError("Codex output requires the exact canonical row type.")
    payload = {
        "prediction_id": row.prediction_id,
        "proposed_codex_decision": row.proposed_codex_decision,
        "proposed_codex_reasons": row.proposed_codex_reasons,
        "sizing_adjustments": row.sizing_adjustments,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_cutoff_safe_input_bundle_sha256(
    row: PredictionEvidenceRow,
    *,
    lane: str,
    effective_as_of_utc: datetime,
    maximum_available_at_utc: datetime,
) -> str:
    """Hash the allowlisted evaluator inputs; realized outcomes are excluded.

    The payload intentionally contains no realized return, evaluation metric,
    later decision, or other outcome field.  Evaluator and policy identities
    are bound separately in decision-derivation evidence.
    """
    if type(row) is not PredictionEvidenceRow or lane not in {"OLD_AG", "CODEX"}:
        raise ContractError("Cutoff-safe input bundle lane/type differs.")
    payload = {
        "lane": lane,
        "prediction_id": row.prediction_id,
        "posterior_record_sha256": canonical_posterior_record_sha256(row),
        "effective_as_of_utc": _utc(effective_as_of_utc, "Input effective-as-of"),
        "maximum_available_at_utc": _utc(maximum_available_at_utc, "Input maximum availability"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def validate_independent_decision_derivations(
    rows: tuple[PredictionEvidenceRow, ...],
    evidence: tuple[IndependentDecisionDerivationEvidence, ...],
    *,
    envelope_observed_at_utc: datetime,
) -> str:
    """Require structurally linked replay evidence for every comparison row.

    This validator is a prerequisite for the future accepted-population builder;
    it is intentionally not a mechanism for making fixture rows accepted.  It
    validates identities and chronology but does not read the referenced audit
    bytes; a future independent auditor must recompute those artifacts.
    """
    if type(rows) is not tuple or any(type(row) is not PredictionEvidenceRow for row in rows):
        raise ContractError("Decision derivation rows must be exact canonical prediction rows.")
    if type(evidence) is not tuple or len(evidence) != len(rows):
        raise ContractError("Decision derivation evidence coverage differs from canonical rows.")
    observed = _utc(envelope_observed_at_utc, "Envelope observation")
    by_id: dict[str, IndependentDecisionDerivationEvidence] = {}
    for item in evidence:
        if type(item) is not IndependentDecisionDerivationEvidence:
            raise ContractError("Decision derivation evidence type differs.")
        if item.prediction_id in by_id:
            raise ContractError("Decision derivation prediction identifiers are duplicated.")
        by_id[item.prediction_id] = item
    if set(by_id) != {row.prediction_id for row in rows}:
        raise ContractError("Decision derivation evidence is missing or references another prediction.")

    for row in rows:
        item = by_id[row.prediction_id]
        if type(item.old_ag_provenance) is not OldAGDecisionProvenance:
            raise ContractError("Old-AG decision provenance is absent or conflated.")
        for value, label in (
            (item.input_posterior_record_sha256, "Input posterior record"),
            (item.old_ag_input_bundle_sha256, "Old-AG cutoff-safe input bundle"),
            (item.old_ag_evaluator_release_sha256, "Old-AG evaluator release"),
            (item.old_ag_policy_artifact_sha256, "Old-AG policy artifact"),
            (item.old_ag_canonical_output_sha256, "Old-AG canonical output"),
            (item.old_ag_independent_replay_audit_sha256, "Old-AG replay audit"),
            (item.codex_input_bundle_sha256, "Codex cutoff-safe input bundle"),
            (item.codex_evaluator_release_sha256, "Codex evaluator release"),
            (item.codex_policy_artifact_sha256, "Codex policy artifact"),
            (item.codex_canonical_output_sha256, "Codex canonical output"),
            (item.codex_independent_replay_audit_sha256, "Codex replay audit"),
        ):
            _sha(value, label)
        if item.input_posterior_record_sha256 != canonical_posterior_record_sha256(row):
            raise ContractError("Decision derivation input posterior-record digest differs.")
        old_input_max = _utc(item.old_ag_input_max_available_at_utc, "Old-AG input maximum availability")
        old_effective = _utc(item.old_ag_effective_as_of_utc, "Old-AG effective-as-of")
        codex_input_max = _utc(item.codex_input_max_available_at_utc, "Codex input maximum availability")
        codex_effective = _utc(item.codex_effective_as_of_utc, "Codex effective-as-of")
        if item.old_ag_input_bundle_sha256 != canonical_cutoff_safe_input_bundle_sha256(
            row,
            lane="OLD_AG",
            effective_as_of_utc=old_effective,
            maximum_available_at_utc=old_input_max,
        ):
            raise ContractError("Old-AG cutoff-safe input bundle digest differs.")
        if item.codex_input_bundle_sha256 != canonical_cutoff_safe_input_bundle_sha256(
            row,
            lane="CODEX",
            effective_as_of_utc=codex_effective,
            maximum_available_at_utc=codex_input_max,
        ):
            raise ContractError("Codex cutoff-safe input bundle digest differs.")
        if item.old_ag_canonical_output_sha256 != canonical_old_ag_output_sha256(
            row, item.old_ag_provenance
        ):
            raise ContractError("Old-AG decision/reasons do not match independently replayed output.")
        if item.codex_canonical_output_sha256 != canonical_codex_output_sha256(row):
            raise ContractError("Codex decision/reasons/sizing do not match independently replayed output.")

        available = _utc(row.posterior_available_at_utc, "Posterior availability")
        cutoff = _utc(row.prediction_cutoff_at_utc, "Prediction cutoff")
        old_evaluated = _utc(item.old_ag_evaluated_at_utc, "Old-AG evaluation")
        codex_evaluated = _utc(item.codex_evaluated_at_utc, "Codex evaluation")
        audited = _utc(item.independently_audited_at_utc, "Independent decision audit")
        if not available <= old_input_max <= cutoff or not available <= old_effective <= cutoff:
            raise ContractError("Old-AG replay input is not cutoff-safe.")
        if not available <= codex_input_max <= cutoff or not available <= codex_effective <= cutoff:
            raise ContractError("Codex replay input is not cutoff-safe.")
        if old_evaluated < old_input_max or codex_evaluated < codex_input_max:
            raise ContractError("A decision evaluation predates its complete as-of input bundle.")
        if old_evaluated > audited or codex_evaluated > audited:
            raise ContractError("A decision evaluation occurs after its independent replay audit.")

        if item.old_ag_provenance is OldAGDecisionProvenance.HISTORICAL_RECORDED_DECISION:
            recorded = _utc(item.old_ag_decision_recorded_at_utc, "Historical AG decision record")
            if not available <= recorded <= cutoff or old_evaluated != recorded:
                raise ContractError("Historical AG recorded decision is not an original pre-cutoff record.")
            _sha(item.old_ag_source_record_sha256, "Historical AG source record")
        else:
            if item.old_ag_decision_recorded_at_utc is not None or item.old_ag_source_record_sha256 is not None:
                raise ContractError("Historical AG rule replay is conflated with a recorded decision.")
        if audited > observed or observed - audited > MAX_INDEPENDENT_AUDIT_AGE:
            raise ContractError("Independent decision audit is stale or after envelope observation.")

    normalized = tuple(sorted(evidence, key=lambda item: item.prediction_id))
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def gate_canonical_fixture_comparisons(
    request: PosteriorEvaluationRequest,
    artifact: PosteriorEvaluationArtifact,
    *,
    acceptance: IndependentPosteriorAcceptanceReference | None = None,
) -> CanonicalPredictionComparisonEnvelope:
    """Audit a canonical fixture artifact and expose zero real comparison rows.

    A fixture can retain its canonical review rows for fixture QA, including the
    inherited-AG and proposed-Codex fields, but those rows never cross into the
    accepted comparison-row field.  A caller-supplied acceptance reference
    cannot bless a fixture.  Population remains unavailable until canonical S10
    defines a non-fixture posterior artifact plus independent auditor.
    """
    if type(request) is not PosteriorEvaluationRequest:
        raise ContractError("Request must use the exact canonical posterior-evaluation type.")
    if type(artifact) is not PosteriorEvaluationArtifact:
        raise ContractError("Artifact must use the exact canonical posterior-evaluation type.")

    audit = audit_fixture_posterior_artifact(request, artifact)
    if not audit.passed:
        raise ContractError("Canonical fixture artifact failed its independent semantic audit.")
    if artifact.boundary != OperationalBoundary() or artifact.boundary.fixture_only is not True:
        raise ContractError("Only the exact canonical fixture boundary is accepted by this bridge.")
    if acceptance is not None:
        if type(acceptance) is not IndependentPosteriorAcceptanceReference:
            raise ContractError("Acceptance reference type is not canonical-gate evidence.")
        raise ContractError(
            "Fixture-only posterior evidence cannot be blessed by a non-fixture acceptance reference."
        )

    if artifact.prediction_count == 0:
        status = ComparisonGateStatus.ABSENT_POSTERIOR_BLOCKED
        blockers = ("ABSENT_POSTERIOR_OUTPUT", "ACCEPTED_NON_FIXTURE_POSTERIOR_ABSENT")
    else:
        status = ComparisonGateStatus.FIXTURE_ONLY_BLOCKED
        blockers = ("FIXTURE_ONLY_POSTERIOR", "ACCEPTED_NON_FIXTURE_POSTERIOR_ABSENT")

    boundary = OperationalBoundary()
    payload: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "status": status,
        "blocker_codes": blockers,
        "canonical_request_sha256": artifact.request_sha256,
        "canonical_fixture_artifact_sha256": artifact_sha256(artifact),
        "canonical_fixture_review_row_count": len(artifact.prediction_evidence_rows),
        "accepted_posterior_reference_sha256": None,
        "accepted_prediction_evidence_rows": (),
        "boundary": boundary,
    }
    return CanonicalPredictionComparisonEnvelope(
        **payload,
        envelope_sha256=_envelope_sha256(payload),
    )
