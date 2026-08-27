from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import hashlib
import unittest

from posterior_evaluation_contract import (
    ContractError,
    OperationalBoundary,
    RecordedDecision,
    artifact_sha256,
    build_fixture_posterior_artifact,
    canonical_json,
)
from test_posterior_evaluation_contract import PosteriorEvaluationContractTests

from canonical_prediction_comparison_gate import (
    CONTRACT_ID,
    CanonicalPredictionComparisonEnvelope,
    ComparisonGateStatus,
    IndependentPosteriorAcceptanceReference,
    IndependentDecisionDerivationEvidence,
    OldAGDecisionProvenance,
    canonical_codex_output_sha256,
    canonical_cutoff_safe_input_bundle_sha256,
    canonical_old_ag_output_sha256,
    canonical_posterior_record_sha256,
    gate_canonical_fixture_comparisons,
    validate_independent_decision_derivations,
)


class CanonicalPredictionComparisonGateTests(unittest.TestCase):
    def setUp(self):
        self.factory = PosteriorEvaluationContractTests()
        self.request = self.factory.request()
        self.artifact = build_fixture_posterior_artifact(self.request)

    def gate(self, artifact=None, acceptance=None):
        return gate_canonical_fixture_comparisons(
            self.request,
            self.artifact if artifact is None else artifact,
            acceptance=acceptance,
        )

    def derivations(self, rows=None):
        rows = self.artifact.prediction_evidence_rows if rows is None else rows
        evidence = []
        audited = max(row.prediction_cutoff_at_utc for row in rows) + timedelta(days=1)
        for index, row in enumerate(rows):
            provenance = (
                OldAGDecisionProvenance.HISTORICAL_RECORDED_DECISION
                if index % 2 == 0
                else OldAGDecisionProvenance.HISTORICAL_RULE_REPLAY
            )
            evidence.append(IndependentDecisionDerivationEvidence(
                prediction_id=row.prediction_id,
                old_ag_provenance=provenance,
                input_posterior_record_sha256=canonical_posterior_record_sha256(row),
                old_ag_input_bundle_sha256=canonical_cutoff_safe_input_bundle_sha256(
                    row,
                    lane="OLD_AG",
                    effective_as_of_utc=row.prediction_cutoff_at_utc,
                    maximum_available_at_utc=row.posterior_available_at_utc,
                ),
                old_ag_input_max_available_at_utc=row.posterior_available_at_utc,
                old_ag_effective_as_of_utc=row.prediction_cutoff_at_utc,
                old_ag_evaluator_release_sha256="1" * 64,
                old_ag_policy_artifact_sha256="2" * 64,
                old_ag_evaluated_at_utc=(
                    row.prediction_cutoff_at_utc - timedelta(minutes=2)
                    if provenance is OldAGDecisionProvenance.HISTORICAL_RECORDED_DECISION
                    else audited - timedelta(minutes=2)
                ),
                old_ag_decision_recorded_at_utc=(
                    row.prediction_cutoff_at_utc - timedelta(minutes=2)
                    if provenance is OldAGDecisionProvenance.HISTORICAL_RECORDED_DECISION
                    else None
                ),
                old_ag_source_record_sha256=(
                    "7" * 64
                    if provenance is OldAGDecisionProvenance.HISTORICAL_RECORDED_DECISION
                    else None
                ),
                old_ag_canonical_output_sha256=canonical_old_ag_output_sha256(row, provenance),
                old_ag_independent_replay_audit_sha256="3" * 64,
                codex_input_bundle_sha256=canonical_cutoff_safe_input_bundle_sha256(
                    row,
                    lane="CODEX",
                    effective_as_of_utc=row.prediction_cutoff_at_utc,
                    maximum_available_at_utc=row.posterior_available_at_utc,
                ),
                codex_input_max_available_at_utc=row.posterior_available_at_utc,
                codex_effective_as_of_utc=row.prediction_cutoff_at_utc,
                codex_evaluator_release_sha256="4" * 64,
                codex_policy_artifact_sha256="5" * 64,
                codex_evaluated_at_utc=audited - timedelta(minutes=1),
                codex_canonical_output_sha256=canonical_codex_output_sha256(row),
                codex_independent_replay_audit_sha256="6" * 64,
                independently_audited_at_utc=audited,
            ))
        return tuple(evidence)

    def test_complete_fixture_rows_never_populate_real_comparison_rows(self):
        self.assertEqual(len(self.artifact.prediction_evidence_rows), 4)
        envelope = self.gate()
        self.assertEqual(envelope.status, ComparisonGateStatus.FIXTURE_ONLY_BLOCKED)
        self.assertEqual(envelope.canonical_fixture_review_row_count, 4)
        self.assertEqual(envelope.accepted_prediction_evidence_rows, ())
        self.assertIsNone(envelope.accepted_posterior_reference_sha256)

    def test_preserves_canonical_ag_codex_fields_only_in_fixture_source(self):
        row = self.artifact.prediction_evidence_rows[0]
        self.assertIn(row.old_ag_decision.value, {"BUY", "SELL", "HOLD"})
        self.assertIs(row.proposed_codex_decision, RecordedDecision.NO_TRADE)
        self.assertTrue(row.old_ag_reasons)
        self.assertTrue(row.proposed_codex_reasons)
        self.assertEqual(self.gate().accepted_prediction_evidence_rows, ())

    def test_fake_acceptance_cannot_bless_fixture(self):
        fake = IndependentPosteriorAcceptanceReference(
            acceptance_contract_id="fake-acceptance-v1",
            accepted_posterior_artifact_sha256="a" * 64,
            independent_audit_sha256="b" * 64,
            accepted_prediction_count=474,
            fixture_only=False,
        )
        with self.assertRaisesRegex(ContractError, "cannot be blessed"):
            self.gate(acceptance=fake)

    def test_forged_nonfixture_boundary_is_rejected_even_with_rehashed_artifact(self):
        forged = replace(self.artifact, boundary=replace(self.artifact.boundary, fixture_only=False))
        with self.assertRaisesRegex(ContractError, "boundary was forged"):
            self.gate(artifact=forged)

    def test_forged_operational_row_is_rejected_even_with_caller_digest(self):
        row = replace(self.artifact.prediction_evidence_rows[0], operationally_eligible=True)
        forged = replace(
            self.artifact,
            prediction_evidence_rows=(row, *self.artifact.prediction_evidence_rows[1:]),
        )
        with self.assertRaisesRegex(ContractError, "review-only boundary"):
            self.gate(artifact=forged)

    def test_ag_codex_tamper_is_rejected_by_canonical_semantic_rebuild(self):
        first = self.artifact.prediction_evidence_rows[0]
        forged_row = replace(first, old_ag_decision=RecordedDecision.BUY)
        forged = replace(
            self.artifact,
            prediction_evidence_rows=(forged_row, *self.artifact.prediction_evidence_rows[1:]),
        )
        with self.assertRaisesRegex(ContractError, "semantics do not match"):
            self.gate(artifact=forged)

    def test_uses_canonical_artifact_and_json_digest_semantics(self):
        envelope = self.gate()
        self.assertEqual(envelope.canonical_fixture_artifact_sha256, artifact_sha256(self.artifact))
        payload = {
            "contract_id": CONTRACT_ID,
            "status": envelope.status,
            "blocker_codes": envelope.blocker_codes,
            "canonical_request_sha256": envelope.canonical_request_sha256,
            "canonical_fixture_artifact_sha256": envelope.canonical_fixture_artifact_sha256,
            "canonical_fixture_review_row_count": envelope.canonical_fixture_review_row_count,
            "accepted_posterior_reference_sha256": None,
            "accepted_prediction_evidence_rows": (),
            "boundary": OperationalBoundary(),
        }
        expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        self.assertEqual(envelope.envelope_sha256, expected)

    def test_does_not_reinterpret_universe_digest(self):
        envelope = self.gate()
        self.assertEqual(envelope.canonical_request_sha256, self.artifact.request_sha256)
        self.assertFalse(hasattr(envelope, "universe_sha256"))

    def test_absent_canonical_posterior_remains_empty(self):
        request = replace(
            self.request,
            parameter_diagnostics=(),
            chain_diagnostics=(),
            outcomes=(),
            recorded_decisions=(),
        )
        artifact = build_fixture_posterior_artifact(request)
        envelope = gate_canonical_fixture_comparisons(request, artifact)
        self.assertEqual(envelope.status, ComparisonGateStatus.ABSENT_POSTERIOR_BLOCKED)
        self.assertEqual(envelope.accepted_prediction_evidence_rows, ())

    def test_output_boundary_is_exactly_zero_operational(self):
        envelope = self.gate()
        self.assertEqual(envelope.boundary, OperationalBoundary())
        self.assertTrue(envelope.boundary.fixture_only)
        self.assertFalse(envelope.boundary.database_accessed)
        self.assertFalse(envelope.boundary.network_accessed)
        self.assertFalse(envelope.boundary.model_fit_performed)
        self.assertFalse(envelope.boundary.recommendation_created)
        self.assertFalse(envelope.boundary.order_created)
        self.assertFalse(envelope.boundary.etf_output_created)
        self.assertFalse(envelope.boundary.promotion_authorized)

    def test_independent_decision_derivations_bind_exact_canonical_outputs(self):
        rows = self.artifact.prediction_evidence_rows
        evidence = self.derivations(rows)
        digest = validate_independent_decision_derivations(
            rows,
            evidence,
            envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence),
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            canonical_old_ag_output_sha256(
                rows[0], OldAGDecisionProvenance.HISTORICAL_RECORDED_DECISION
            ),
            canonical_old_ag_output_sha256(
                rows[0], OldAGDecisionProvenance.HISTORICAL_RULE_REPLAY
            ),
        )

    def test_forged_decision_or_reasons_fail_replay_output_digest(self):
        rows = self.artifact.prediction_evidence_rows
        evidence = self.derivations(rows)
        forged = (replace(rows[0], old_ag_reasons=("FORGED_REASON",)), *rows[1:])
        with self.assertRaisesRegex(ContractError, "Old-AG decision/reasons"):
            validate_independent_decision_derivations(
                forged,
                evidence,
                envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence),
            )
        forged = (replace(rows[0], proposed_codex_reasons=("FORGED_REASON",)), *rows[1:])
        with self.assertRaisesRegex(ContractError, "Codex decision/reasons/sizing"):
            validate_independent_decision_derivations(
                forged,
                evidence,
                envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence),
            )

    def test_swapped_prediction_ids_fail_exact_posterior_binding(self):
        rows = self.artifact.prediction_evidence_rows
        evidence = list(self.derivations(rows))
        first_id, second_id = evidence[0].prediction_id, evidence[1].prediction_id
        evidence[0] = replace(evidence[0], prediction_id=second_id)
        evidence[1] = replace(evidence[1], prediction_id=first_id)
        with self.assertRaisesRegex(ContractError, "posterior-record digest"):
            validate_independent_decision_derivations(
                rows,
                tuple(evidence),
                envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence),
            )

    def test_stale_independent_decision_audit_is_rejected(self):
        rows = self.artifact.prediction_evidence_rows
        evidence = self.derivations(rows)
        with self.assertRaisesRegex(ContractError, "stale"):
            validate_independent_decision_derivations(
                rows,
                evidence,
                envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence) + timedelta(minutes=6),
            )

    def test_post_cutoff_replay_is_allowed_with_cutoff_safe_inputs(self):
        rows = self.artifact.prediction_evidence_rows
        evidence = self.derivations(rows)
        self.assertTrue(all(
            item.codex_evaluated_at_utc > row.prediction_cutoff_at_utc
            for item, row in zip(evidence, rows)
        ))
        digest = validate_independent_decision_derivations(
            rows,
            evidence,
            envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence),
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_future_data_input_is_rejected_even_when_bundle_digest_is_recomputed(self):
        rows = self.artifact.prediction_evidence_rows
        evidence = list(self.derivations(rows))
        future = rows[0].prediction_cutoff_at_utc + timedelta(seconds=1)
        evidence[0] = replace(
            evidence[0],
            codex_input_max_available_at_utc=future,
            codex_input_bundle_sha256=canonical_cutoff_safe_input_bundle_sha256(
                rows[0],
                lane="CODEX",
                effective_as_of_utc=evidence[0].codex_effective_as_of_utc,
                maximum_available_at_utc=future,
            ),
        )
        with self.assertRaisesRegex(ContractError, "not cutoff-safe"):
            validate_independent_decision_derivations(
                rows,
                tuple(evidence),
                envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence),
            )

    def test_cutoff_safe_input_digest_excludes_decisions_gates_and_sizing_outputs(self):
        row = self.artifact.prediction_evidence_rows[0]
        baseline = canonical_cutoff_safe_input_bundle_sha256(
            row,
            lane="CODEX",
            effective_as_of_utc=row.prediction_cutoff_at_utc,
            maximum_available_at_utc=row.posterior_available_at_utc,
        )
        changed_output = replace(
            row,
            proposed_codex_reasons=("CHANGED_OUTPUT_ONLY",),
            sizing_adjustments=(),
            hard_safety_gates=(),
        )
        self.assertEqual(
            baseline,
            canonical_cutoff_safe_input_bundle_sha256(
                changed_output,
                lane="CODEX",
                effective_as_of_utc=row.prediction_cutoff_at_utc,
                maximum_available_at_utc=row.posterior_available_at_utc,
            ),
        )

    def test_recorded_ag_decision_requires_original_pre_cutoff_source_record(self):
        rows = self.artifact.prediction_evidence_rows
        evidence = list(self.derivations(rows))
        self.assertIs(
            evidence[0].old_ag_provenance,
            OldAGDecisionProvenance.HISTORICAL_RECORDED_DECISION,
        )
        evidence[0] = replace(evidence[0], old_ag_source_record_sha256=None)
        with self.assertRaisesRegex(ContractError, "source record"):
            validate_independent_decision_derivations(
                rows,
                tuple(evidence),
                envelope_observed_at_utc=max(item.independently_audited_at_utc for item in evidence),
            )


if __name__ == "__main__":
    unittest.main()
