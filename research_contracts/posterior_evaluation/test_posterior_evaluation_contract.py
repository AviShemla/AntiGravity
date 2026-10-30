import ast
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import math
from pathlib import Path
import unittest

from posterior_evaluation_contract import (
    ArtifactLineage,
    ArtifactStatus,
    ChainDiagnostic,
    ConvergencePolicy,
    ContractError,
    EvaluationPolicy,
    HierarchyEntry,
    HierarchyRegistry,
    ParameterDiagnostic,
    PosteriorEvaluationRequest,
    PosteriorOutcome,
    RecordedDecision,
    RecordedDecisionEvidence,
    SamplerPolicy,
    SessionCalendar,
    SizingAdjustment,
    VerifiedSafetyEvidence,
    WalkForwardFold,
    artifact_sha256,
    audit_fixture_posterior_artifact,
    build_fixture_posterior_artifact,
    canonical_json,
    hierarchy_registry_sha256,
    quarantine_registry_sha256,
    session_calendar_sha256,
)


class PosteriorEvaluationContractTests(unittest.TestCase):
    def calendar(self):
        sessions = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(300))
        return SessionCalendar(
            calendar_id="xnys-sessions-v1",
            sessions=sessions,
            session_available_at_utc=tuple(
                datetime(session.year, session.month, session.day, 22, 0, tzinfo=timezone.utc)
                for session in sessions
            ),
        )

    def hierarchy_registry(self):
        return HierarchyRegistry(
            registry_id="stock-hierarchy-v1",
            observed_at_utc=datetime(2024, 12, 1, 0, 0, tzinfo=timezone.utc),
            entries=(
                HierarchyEntry("AAA", "Neutral", ("Stock", "AAA")),
                HierarchyEntry("BBB", "Neutral", ("Stock", "BBB")),
            ),
        )

    def safety_evidence(self, *, quarantined=()):
        evidence = VerifiedSafetyEvidence(
            snapshot_validation_id="snapshot-validation-1",
            validated_snapshot_sha256="a" * 64,
            snapshot_validated_at_utc=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
            universe_approval_id="universe-approval-1",
            approved_universe_sha256="b" * 64,
            universe_approved_at_utc=datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc),
            model_completion_id="model-completion-1",
            completed_model_run_id="fixture-run-1",
            model_completed_at_utc=datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc),
            quarantine_registry_id="quarantine-registry-1",
            quarantine_registry_sha256="0" * 64,
            quarantine_registry_observed_at_utc=datetime(2025, 6, 2, 0, 0, tzinfo=timezone.utc),
            quarantined_prediction_ids=tuple(quarantined),
        )
        return replace(evidence, quarantine_registry_sha256=quarantine_registry_sha256(evidence))

    def lineage(self):
        calendar = self.calendar()
        hierarchy = self.hierarchy_registry()
        return ArtifactLineage(
            contract_version="1.0.0",
            model_run_id="fixture-run-1",
            research_dataset_id="dataset-20260825",
            source_snapshot_id="snapshot-20260825",
            source_snapshot_sha256="a" * 64,
            universe_id="universe-474",
            universe_sha256="b" * 64,
            code_version="d" * 40,
            configuration_sha256="c" * 64,
            preregistration_id="preregistration-1",
            preregistration_sha256="e" * 64,
            preregistration_observed_at_utc=datetime(2024, 12, 2, 0, 0, tzinfo=timezone.utc),
            baseline_audit_id="baseline-audit-1",
            baseline_audit_sha256="f" * 64,
            baseline_audit_observed_at_utc=datetime(2024, 12, 3, 0, 0, tzinfo=timezone.utc),
            session_calendar_id=calendar.calendar_id,
            session_calendar_sha256=session_calendar_sha256(calendar),
            hierarchy_registry_id=hierarchy.registry_id,
            hierarchy_registry_sha256=hierarchy_registry_sha256(hierarchy),
            sampler_name="fixture-sampler",
            seed_policy="fixed-seed-17",
            observed_at_utc=datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc),
        )

    def policy(self, *, expected_predictions=4, expected_folds=2):
        return EvaluationPolicy(
            calibration_bins=2,
            probability_clip=1e-12,
            round_trip_cost_bps=100.0,
            one_way_slippage_bps=0.0,
            charge_terminal_close=True,
            expected_predictions=expected_predictions,
            expected_folds=expected_folds,
            prediction_cutoff_hour_utc=23,
            prediction_cutoff_minute_utc=59,
            sampler=SamplerPolicy(
                sampler_name="fixture-sampler",
                expected_chains=4,
                posterior_draws_per_chain=1000,
                tuning_draws_per_chain=1000,
                required_parameters=("intercept", "lag-1"),
                convergence=ConvergencePolicy(),
            ),
        )

    def folds(self):
        return (
            WalkForwardFold("fold-1", 0, 125, 133, 133, 126, 7, 1, 0),
            WalkForwardFold("fold-2", 1, 133, 141, 141, 133, 7, 1, 0),
        )

    def outcome(self, prediction_id, fold_id, ticker, prediction_date, probability, realized, allocation):
        calendar = self.calendar()
        prediction_index = calendar.sessions.index(prediction_date)
        return PosteriorOutcome(
            prediction_id=prediction_id,
            fold_id=fold_id,
            ticker=ticker,
            persona="Neutral",
            hierarchy_path=("Stock", ticker),
            prediction_date=prediction_date,
            source_session_date=calendar.sessions[prediction_index - 1],
            posterior_available_at_utc=datetime.combine(prediction_date, datetime.min.time(), tzinfo=timezone.utc),
            prediction_cutoff_at_utc=datetime(
                prediction_date.year, prediction_date.month, prediction_date.day,
                23, 59, tzinfo=timezone.utc,
            ),
            probability_up_mean=probability,
            probability_up_std=0.10,
            probability_up_q05=max(0.0, probability - 0.2),
            probability_up_q95=min(1.0, probability + 0.2),
            expected_return_pp=1.0 if probability >= 0.5 else -1.0,
            expected_return_std_pp=0.50,
            expected_risk_pp=2.0,
            realized_return_pp=realized,
            research_signed_allocation=allocation,
        )

    def outcomes(self):
        calendar = self.calendar()
        return (
            self.outcome("p-1-aaa", "fold-1", "AAA", calendar.sessions[133], 0.8, 10.0, 0.5),
            self.outcome("p-1-bbb", "fold-1", "BBB", calendar.sessions[133], 0.2, -10.0, -0.5),
            self.outcome("p-2-aaa", "fold-2", "AAA", calendar.sessions[141], 0.6, -20.0, 0.5),
            self.outcome("p-2-bbb", "fold-2", "BBB", calendar.sessions[141], 0.4, 20.0, -0.5),
        )

    def decision(self, prediction_id):
        return RecordedDecisionEvidence(
            prediction_id=prediction_id,
            old_ag_decision=RecordedDecision.HOLD,
            old_ag_reasons=("LEGACY_THRESHOLD_NOT_MET",),
            proposed_codex_decision=RecordedDecision.NO_TRADE,
            proposed_codex_reasons=("FIXTURE_REVIEW_ONLY",),
            sizing_adjustments=(SizingAdjustment("NO_ADJUSTMENT", 0.0, "Operational sizing is disabled."),),
        )

    def diagnostics(self):
        parameters = (
            ParameterDiagnostic("intercept", 4, 1000, 1.001, 900.0, 800.0),
            ParameterDiagnostic("lag-1", 4, 1000, 1.005, 750.0, 700.0),
        )
        chains = tuple(ChainDiagnostic(index, 1000, 1000, 0, 0.9) for index in range(4))
        return parameters, chains

    def request(self):
        parameters, chains = self.diagnostics()
        outcomes = self.outcomes()
        return PosteriorEvaluationRequest(
            self.lineage(), self.policy(), self.calendar(), self.hierarchy_registry(),
            self.safety_evidence(), self.folds(), parameters, chains,
            outcomes, tuple(self.decision(row.prediction_id) for row in outcomes),
        )

    def test_absent_posterior_is_explicitly_blocked_without_fabricated_outputs(self):
        request = PosteriorEvaluationRequest(
            self.lineage(), self.policy(expected_predictions=4, expected_folds=2),
            self.calendar(), self.hierarchy_registry(), self.safety_evidence(),
            self.folds(), (), (), (), (),
        )
        artifact = build_fixture_posterior_artifact(request)
        self.assertEqual(artifact.status, ArtifactStatus.ABSENT_POSTERIOR_BLOCKED)
        self.assertEqual(artifact.blocker_codes, ("ABSENT_POSTERIOR_OUTPUT",))
        self.assertIsNone(artifact.convergence)
        self.assertIsNone(artifact.calibration)
        self.assertIsNone(artifact.cost_and_drawdown)
        self.assertEqual(artifact.prediction_evidence_rows, ())
        self.assertEqual(artifact.prediction_count, 0)

    def test_absent_posterior_rejects_orphan_decisions_or_diagnostics(self):
        request = PosteriorEvaluationRequest(
            self.lineage(), self.policy(expected_predictions=1, expected_folds=1),
            self.calendar(), self.hierarchy_registry(), self.safety_evidence(),
            self.folds()[:1], (), (), (), (self.decision("ghost"),),
        )
        with self.assertRaisesRegex(ContractError, "orphan"):
            build_fixture_posterior_artifact(request)

    def test_complete_fixture_builds_exact_review_rows(self):
        artifact = build_fixture_posterior_artifact(self.request())
        self.assertEqual(artifact.status, ArtifactStatus.PROMOTION_BLOCKED)
        self.assertIn("RESEARCH_PROMOTION_NOT_APPROVED", artifact.blocker_codes)
        self.assertEqual((artifact.fold_count, artifact.prediction_count), (2, 4))
        self.assertEqual(len(artifact.prediction_evidence_rows), 4)
        row = artifact.prediction_evidence_rows[0]
        self.assertEqual(row.prediction_id, "p-1-aaa")
        self.assertEqual(row.raw_bayesian_output.probability_up_mean, 0.8)
        self.assertEqual(row.old_ag_decision, RecordedDecision.HOLD)
        self.assertEqual(row.proposed_codex_decision, RecordedDecision.NO_TRADE)
        self.assertTrue(row.review_only)
        self.assertFalse(row.operationally_eligible)

    def test_boundary_is_hard_false_for_every_operational_output(self):
        boundary = build_fixture_posterior_artifact(self.request()).boundary
        self.assertTrue(boundary.fixture_only)
        for field in (
            "database_accessed", "network_accessed", "model_fit_performed",
            "recommendation_created", "order_created", "etf_output_created",
            "promotion_authorized",
        ):
            self.assertFalse(getattr(boundary, field))

    def test_convergence_summary_is_exact(self):
        summary = build_fixture_posterior_artifact(self.request()).convergence
        self.assertIsNotNone(summary)
        self.assertEqual((summary.chains, summary.parameters), (4, 2))
        self.assertEqual((summary.posterior_draws, summary.tuning_draws), (4000, 4000))
        self.assertEqual(summary.divergences, 0)
        self.assertEqual(summary.maximum_r_hat, 1.005)
        self.assertEqual(summary.minimum_ess_bulk, 750.0)
        self.assertEqual(summary.minimum_ess_tail, 700.0)
        self.assertEqual(summary.minimum_bfmi, 0.9)
        self.assertTrue(summary.passed)

    def test_failed_convergence_preserves_metrics_but_blocks_review(self):
        request = self.request()
        chains = tuple(replace(row, divergences=1) if row.chain_id == 0 else row for row in request.chain_diagnostics)
        artifact = build_fixture_posterior_artifact(replace(request, chain_diagnostics=chains))
        self.assertEqual(artifact.status, ArtifactStatus.DIAGNOSTIC_BLOCKED)
        self.assertIn("DIVERGENCES_EXCEEDED", artifact.blocker_codes)
        self.assertIn("SAMPLER_QA_FAILED", artifact.blocker_codes)
        self.assertIn("RESEARCH_PROMOTION_NOT_APPROVED", artifact.blocker_codes)
        self.assertIsNotNone(artifact.calibration)
        self.assertEqual(len(artifact.prediction_evidence_rows), 4)

    def test_calibration_metrics_are_exact(self):
        metrics = build_fixture_posterior_artifact(self.request()).calibration
        self.assertEqual(metrics.observations, 4)
        self.assertAlmostEqual(metrics.accuracy, 0.5)
        self.assertAlmostEqual(metrics.brier_score, 0.2)
        self.assertAlmostEqual(metrics.expected_calibration_error, 0.2)
        self.assertAlmostEqual(metrics.expected_return_mae_pp, 15.0)
        self.assertAlmostEqual(metrics.expected_return_rmse_pp, math.sqrt(261.0))
        self.assertAlmostEqual(metrics.log_loss, -(math.log(0.8) + math.log(0.8) + math.log(0.4) + math.log(0.4)) / 4.0)

    def test_cost_turnover_terminal_close_and_drawdown_are_exact(self):
        metrics = build_fixture_posterior_artifact(self.request()).cost_and_drawdown
        self.assertEqual(metrics.sessions, 2)
        self.assertAlmostEqual(metrics.gross_turnover, 2.0)
        self.assertAlmostEqual(metrics.terminal_close_turnover, 1.0)
        self.assertAlmostEqual(metrics.transaction_cost_pp_sum, 1.0)
        self.assertAlmostEqual(metrics.gross_total_return_fraction, -0.12)
        self.assertAlmostEqual(metrics.net_total_return_fraction, -0.12838)
        self.assertAlmostEqual(metrics.max_drawdown_fraction, 0.204)

    def test_artifact_and_json_are_deterministic_under_input_reordering(self):
        request = self.request()
        first = build_fixture_posterior_artifact(request)
        second = build_fixture_posterior_artifact(replace(
            request,
            outcomes=tuple(reversed(request.outcomes)),
            recorded_decisions=tuple(reversed(request.recorded_decisions)),
            parameter_diagnostics=tuple(reversed(request.parameter_diagnostics)),
            chain_diagnostics=tuple(reversed(request.chain_diagnostics)),
        ))
        self.assertEqual(first.artifact_id, second.artifact_id)
        self.assertEqual(first.request_sha256, second.request_sha256)
        self.assertEqual(artifact_sha256(first), artifact_sha256(second))
        self.assertEqual(canonical_json(first), canonical_json(second))

    def test_rejects_prediction_count_mismatch(self):
        with self.assertRaisesRegex(ContractError, "prediction count"):
            build_fixture_posterior_artifact(replace(self.request(), policy=self.policy(expected_predictions=5)))

    def test_rejects_incomplete_portfolio_panel(self):
        request = self.request()
        reduced = request.outcomes[:-1]
        with self.assertRaisesRegex(ContractError, "complete ticker/persona/date panel"):
            build_fixture_posterior_artifact(replace(
                request,
                policy=self.policy(expected_predictions=3),
                outcomes=reduced,
                recorded_decisions=request.recorded_decisions[:-1],
            ))

    def test_rejects_duplicate_prediction_or_decision(self):
        request = self.request()
        with self.assertRaisesRegex(ContractError, "prediction identifiers"):
            build_fixture_posterior_artifact(replace(request, outcomes=(request.outcomes[0],) * 4))
        with self.assertRaisesRegex(ContractError, "unique per prediction"):
            build_fixture_posterior_artifact(replace(request, recorded_decisions=(request.recorded_decisions[0],) * 4))

    def test_rejects_distinct_ids_for_same_ticker_persona_date_cell(self):
        request = self.request()
        duplicate_cell = replace(
            request.outcomes[1],
            ticker=request.outcomes[0].ticker,
            hierarchy_path=request.outcomes[0].hierarchy_path,
        )
        with self.assertRaisesRegex(ContractError, "duplicate ticker/persona/date"):
            build_fixture_posterior_artifact(replace(
                request,
                outcomes=(request.outcomes[0], duplicate_cell) + request.outcomes[2:],
            ))

    def test_rejects_invalid_temporal_contract_and_overlap(self):
        request = self.request()
        bad_fold = replace(request.folds[0], observed_temporal_overlap_sessions=1)
        with self.assertRaisesRegex(ContractError, "geometry"):
            build_fixture_posterior_artifact(replace(request, folds=(bad_fold, request.folds[1])))
        bad_outcome = replace(request.outcomes[0], source_session_date=request.outcomes[0].prediction_date)
        with self.assertRaisesRegex(ContractError, "source session"):
            build_fixture_posterior_artifact(replace(request, outcomes=(bad_outcome,) + request.outcomes[1:]))
        late = replace(
            request.outcomes[0],
            posterior_available_at_utc=request.outcomes[0].prediction_cutoff_at_utc + timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ContractError, "prediction cutoff"):
            build_fixture_posterior_artifact(replace(request, outcomes=(late,) + request.outcomes[1:]))
        source_index = request.session_calendar.sessions.index(request.outcomes[0].source_session_date)
        early = replace(
            request.outcomes[0],
            posterior_available_at_utc=request.session_calendar.session_available_at_utc[source_index] - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ContractError, "predates the latest source/fold"):
            build_fixture_posterior_artifact(replace(request, outcomes=(early,) + request.outcomes[1:]))
        wrong_cutoff = replace(
            request.outcomes[0],
            prediction_cutoff_at_utc=request.outcomes[0].prediction_cutoff_at_utc - timedelta(minutes=1),
        )
        with self.assertRaisesRegex(ContractError, "governed UTC cutoff"):
            build_fixture_posterior_artifact(replace(request, outcomes=(wrong_cutoff,) + request.outcomes[1:]))

    def test_absent_posterior_still_requires_valid_frozen_fold_contract(self):
        request = PosteriorEvaluationRequest(
            self.lineage(), self.policy(expected_predictions=4, expected_folds=2),
            self.calendar(), self.hierarchy_registry(), self.safety_evidence(),
            (replace(self.folds()[0], purge_sessions=0), self.folds()[1]), (), (), (), (),
        )
        with self.assertRaisesRegex(ContractError, "geometry"):
            build_fixture_posterior_artifact(request)

    def test_evidence_row_exposes_every_required_comparison_field(self):
        row = build_fixture_posterior_artifact(self.request()).prediction_evidence_rows[0]
        self.assertEqual(
            set(row.__dataclass_fields__),
            {
                "prediction_id", "model_run_id", "fold_id", "ticker", "persona",
                "prediction_date", "source_session_date", "posterior_available_at_utc",
                "prediction_cutoff_at_utc", "raw_bayesian_output", "old_ag_decision",
                "old_ag_reasons", "proposed_codex_decision", "proposed_codex_reasons",
                "hard_safety_gates", "sizing_adjustments", "review_only",
                "operationally_eligible",
            },
        )

    def test_rejects_weakened_training_or_purge_safeguard(self):
        request = self.request()
        for change, message in (
            ({"train_end_index": 124, "test_start_index": 132, "test_end_index": 132, "training_sessions": 125}, "126-session"),
            ({"test_start_index": 132, "test_end_index": 132, "purge_sessions": 6}, "seven-session"),
        ):
            with self.subTest(change=change):
                bad = replace(request.folds[0], **change)
                with self.assertRaisesRegex(ContractError, message):
                    build_fixture_posterior_artifact(replace(request, folds=(bad, request.folds[1])))

    def test_rejects_nonfinite_or_invalid_posterior_values(self):
        request = self.request()
        invalid = (
            replace(request.outcomes[0], probability_up_mean=float("nan")),
            replace(request.outcomes[0], probability_up_q05=0.9),
            replace(request.outcomes[0], probability_up_std=0.0),
            replace(request.outcomes[0], research_signed_allocation=1.1),
        )
        for row in invalid:
            with self.subTest(row=row):
                with self.assertRaises(ContractError):
                    build_fixture_posterior_artifact(replace(request, outcomes=(row,) + request.outcomes[1:]))

    def test_fixture_boundary_cannot_record_actionable_codex_decision(self):
        request = self.request()
        unsafe = replace(request.recorded_decisions[0], proposed_codex_decision=RecordedDecision.BUY)
        with self.assertRaisesRegex(ContractError, "must remain NO_TRADE"):
            build_fixture_posterior_artifact(replace(request, recorded_decisions=(unsafe,) + request.recorded_decisions[1:]))

    def test_decisions_require_reasons_and_sizing_evidence(self):
        request = self.request()
        invalid = (
            replace(request.recorded_decisions[0], proposed_codex_reasons=()),
            replace(request.recorded_decisions[0], sizing_adjustments=()),
        )
        for row in invalid:
            with self.subTest(row=row):
                with self.assertRaises(ContractError):
                    build_fixture_posterior_artifact(replace(request, recorded_decisions=(row,) + request.recorded_decisions[1:]))

    def test_rejects_arbitrary_decision_strings_and_wrong_lane_enums(self):
        request = self.request()
        invalid = (
            replace(request.recorded_decisions[0], old_ag_decision="HOLD"),
            replace(request.recorded_decisions[0], old_ag_decision=RecordedDecision.NO_TRADE),
        )
        for row in invalid:
            with self.subTest(row=row):
                with self.assertRaisesRegex(ContractError, "exact allowed enum"):
                    build_fixture_posterior_artifact(replace(request, recorded_decisions=(row,) + request.recorded_decisions[1:]))

    def test_session_calendar_digest_and_declared_geometry_are_recomputed(self):
        request = self.request()
        tampered_calendar = replace(
            request.session_calendar,
            sessions=request.session_calendar.sessions[:-1],
            session_available_at_utc=request.session_calendar.session_available_at_utc[:-1],
        )
        with self.assertRaisesRegex(ContractError, "calendar digest"):
            build_fixture_posterior_artifact(replace(request, session_calendar=tampered_calendar))
        false_count = replace(request.folds[0], training_sessions=999)
        with self.assertRaisesRegex(ContractError, "geometry"):
            build_fixture_posterior_artifact(replace(request, folds=(false_count, request.folds[1])))

    def test_sampler_policy_requires_exact_parameter_chain_and_draw_dimensions(self):
        request = self.request()
        variants = (
            replace(request, parameter_diagnostics=request.parameter_diagnostics[:-1]),
            replace(request, parameter_diagnostics=(replace(request.parameter_diagnostics[0], draws_per_chain=999),) + request.parameter_diagnostics[1:]),
            replace(request, chain_diagnostics=(replace(request.chain_diagnostics[0], posterior_draws=999),) + request.chain_diagnostics[1:]),
            replace(request, chain_diagnostics=request.chain_diagnostics[:-1]),
        )
        for variant in variants:
            with self.subTest(variant=variant):
                with self.assertRaises(ContractError):
                    build_fixture_posterior_artifact(variant)

    def test_hierarchy_path_must_match_frozen_ticker_persona_registry(self):
        request = self.request()
        forged_outcome = replace(request.outcomes[0], hierarchy_path=("Stock", "BBB"))
        with self.assertRaisesRegex(ContractError, "frozen ticker/persona registry"):
            build_fixture_posterior_artifact(replace(
                request,
                outcomes=(forged_outcome,) + request.outcomes[1:],
            ))
        changed_entry = replace(request.hierarchy_registry.entries[0], hierarchy_path=("Other", "AAA"))
        changed_registry = replace(
            request.hierarchy_registry,
            entries=(changed_entry,) + request.hierarchy_registry.entries[1:],
        )
        with self.assertRaisesRegex(ContractError, "Hierarchy registry digest"):
            build_fixture_posterior_artifact(replace(request, hierarchy_registry=changed_registry))

    def test_safety_gates_are_derived_not_caller_asserted(self):
        request = self.request()
        artifact = build_fixture_posterior_artifact(request)
        for row in artifact.prediction_evidence_rows:
            gates = {gate.gate_id: gate for gate in row.hard_safety_gates}
            self.assertEqual(set(gates), {
                "SNAPSHOT_VALIDATED", "UNIVERSE_APPROVED", "SOURCE_DATE_ALIGNED",
                "MODEL_RUN_COMPLETED", "SAMPLER_QA_PASSED",
                "RESEARCH_PROMOTION_APPROVED", "NOT_QUARANTINED",
            })
            self.assertTrue(gates["SNAPSHOT_VALIDATED"].passed)
            self.assertTrue(gates["SAMPLER_QA_PASSED"].passed)
            self.assertFalse(gates["RESEARCH_PROMOTION_APPROVED"].passed)
            self.assertEqual(gates["RESEARCH_PROMOTION_APPROVED"].reason_code, "RESEARCH_PROMOTION_NOT_APPROVED")
            self.assertEqual(row.proposed_codex_decision, RecordedDecision.NO_TRADE)
        self.assertEqual(artifact.status, ArtifactStatus.PROMOTION_BLOCKED)

    def test_mismatched_verified_identities_and_quarantine_derive_failed_gates(self):
        request = self.request()
        safety = self.safety_evidence(quarantined=("p-1-aaa",))
        safety = replace(
            safety,
            validated_snapshot_sha256="9" * 64,
            approved_universe_sha256="8" * 64,
            completed_model_run_id="different-run",
        )
        artifact = build_fixture_posterior_artifact(replace(request, safety_evidence=safety))
        row = next(row for row in artifact.prediction_evidence_rows if row.prediction_id == "p-1-aaa")
        gates = {gate.gate_id: gate for gate in row.hard_safety_gates}
        self.assertFalse(gates["SNAPSHOT_VALIDATED"].passed)
        self.assertFalse(gates["UNIVERSE_APPROVED"].passed)
        self.assertFalse(gates["MODEL_RUN_COMPLETED"].passed)
        self.assertFalse(gates["NOT_QUARANTINED"].passed)
        self.assertIn("SNAPSHOT_NOT_VALIDATED", artifact.blocker_codes)
        self.assertIn("ACTIVE_EVIDENCE_QUARANTINE", artifact.blocker_codes)

    def test_diagnostic_failure_is_reflected_in_every_evidence_row(self):
        request = self.request()
        chains = (replace(request.chain_diagnostics[0], divergences=1),) + request.chain_diagnostics[1:]
        artifact = build_fixture_posterior_artifact(replace(request, chain_diagnostics=chains))
        self.assertEqual(artifact.status, ArtifactStatus.DIAGNOSTIC_BLOCKED)
        for row in artifact.prediction_evidence_rows:
            sampler_gate = next(gate for gate in row.hard_safety_gates if gate.gate_id == "SAMPLER_QA_PASSED")
            self.assertFalse(sampler_gate.passed)
            self.assertEqual(sampler_gate.reason_code, "SAMPLER_QA_FAILED")
            self.assertIn("SAMPLER_QA_FAILED", row.proposed_codex_reasons)
            self.assertEqual(row.proposed_codex_decision, RecordedDecision.NO_TRADE)

    def test_identifiers_must_be_actual_strings_not_ints_or_bools(self):
        request = self.request()
        invalid = (
            replace(request, lineage=replace(request.lineage, model_run_id=123)),
            replace(request, folds=(replace(request.folds[0], fold_id=True), request.folds[1])),
            replace(request, recorded_decisions=(
                replace(request.recorded_decisions[0], old_ag_reasons=(123,)),
                *request.recorded_decisions[1:],
            )),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ContractError, "actual string"):
                    build_fixture_posterior_artifact(value)

    def test_exact_git_preregistration_and_baseline_audit_identities_are_required(self):
        request = self.request()
        invalid_lineages = (
            replace(request.lineage, code_version="deadbeef"),
            replace(request.lineage, preregistration_sha256="x" * 64),
            replace(request.lineage, baseline_audit_id=""),
        )
        for lineage in invalid_lineages:
            with self.subTest(lineage=lineage):
                with self.assertRaises(ContractError):
                    build_fixture_posterior_artifact(replace(request, lineage=lineage))

    def test_nested_input_collections_are_deep_frozen_before_hashing(self):
        request = self.request()
        sessions = list(request.session_calendar.sessions)
        availability = list(request.session_calendar.session_available_at_utc)
        parameters = list(request.policy.sampler.required_parameters)
        hierarchy = list(request.outcomes[0].hierarchy_path)
        registry_path = list(request.hierarchy_registry.entries[0].hierarchy_path)
        registry_entries = [replace(request.hierarchy_registry.entries[0], hierarchy_path=registry_path), *request.hierarchy_registry.entries[1:]]
        reasons = list(request.recorded_decisions[0].old_ag_reasons)
        adjustments = list(request.recorded_decisions[0].sizing_adjustments)
        quarantined = list(request.safety_evidence.quarantined_prediction_ids)
        mutable_safety = replace(request.safety_evidence, quarantined_prediction_ids=quarantined)
        mutable_safety = replace(mutable_safety, quarantine_registry_sha256=quarantine_registry_sha256(mutable_safety))
        mutable_request = replace(
            request,
            policy=replace(request.policy, sampler=replace(request.policy.sampler, required_parameters=parameters)),
            session_calendar=replace(request.session_calendar, sessions=sessions, session_available_at_utc=availability),
            hierarchy_registry=replace(request.hierarchy_registry, entries=registry_entries),
            safety_evidence=mutable_safety,
            outcomes=[replace(request.outcomes[0], hierarchy_path=hierarchy), *request.outcomes[1:]],
            recorded_decisions=[replace(
                request.recorded_decisions[0],
                old_ag_reasons=reasons,
                sizing_adjustments=adjustments,
            ), *request.recorded_decisions[1:]],
        )
        artifact = build_fixture_posterior_artifact(mutable_request)
        before = canonical_json(artifact)
        sessions.pop()
        availability.pop()
        parameters.append("forged-parameter")
        hierarchy.append("forged-node")
        registry_path.append("forged-registry-node")
        reasons.append("FORGED_REASON")
        adjustments.clear()
        quarantined.append("p-1-aaa")
        self.assertEqual(canonical_json(artifact), before)
        self.assertIsInstance(artifact.session_calendar.sessions, tuple)
        self.assertIsInstance(artifact.policy.sampler.required_parameters, tuple)
        self.assertIsInstance(artifact.hierarchy_registry.entries, tuple)
        self.assertIsInstance(artifact.hierarchy_registry.entries[0].hierarchy_path, tuple)
        self.assertIsInstance(artifact.safety_evidence.quarantined_prediction_ids, tuple)
        self.assertIsInstance(artifact.prediction_evidence_rows[0].old_ag_reasons, tuple)

    def test_semantic_auditor_reruns_contract_and_accepts_exact_artifact(self):
        request = self.request()
        artifact = build_fixture_posterior_artifact(request)
        audit = audit_fixture_posterior_artifact(request, artifact)
        self.assertTrue(audit.passed)
        self.assertEqual(audit.request_sha256, artifact.request_sha256)
        self.assertEqual(audit.artifact_sha256, artifact_sha256(artifact))
        self.assertEqual((audit.checked_predictions, audit.checked_folds), (4, 2))

    def test_semantic_auditor_rejects_forged_boundary_even_with_recomputed_digest(self):
        request = self.request()
        artifact = build_fixture_posterior_artifact(request)
        for forged, message in (
            (replace(artifact, boundary=replace(artifact.boundary, order_created=True)), "operational boundary"),
            (replace(
                artifact,
                prediction_evidence_rows=(
                    replace(artifact.prediction_evidence_rows[0], operationally_eligible=True),
                    *artifact.prediction_evidence_rows[1:],
                ),
            ), "review-only boundary"),
        ):
            with self.subTest(message=message):
                forged = replace(
                    forged,
                    artifact_id="posterior_research_evidence_" + artifact_sha256(forged),
                )
                with self.assertRaisesRegex(ContractError, message):
                    audit_fixture_posterior_artifact(request, forged)

    def test_semantic_auditor_rebuild_rejects_forged_derived_gate(self):
        request = self.request()
        artifact = build_fixture_posterior_artifact(request)
        first_row = artifact.prediction_evidence_rows[0]
        gates = tuple(
            replace(gate, passed=True, reason_code="PASS")
            if gate.gate_id == "RESEARCH_PROMOTION_APPROVED" else gate
            for gate in first_row.hard_safety_gates
        )
        forged = replace(
            artifact,
            prediction_evidence_rows=(replace(first_row, hard_safety_gates=gates), *artifact.prediction_evidence_rows[1:]),
        )
        forged = replace(
            forged,
            artifact_id="posterior_research_evidence_" + artifact_sha256(forged),
        )
        with self.assertRaisesRegex(ContractError, "semantics"):
            audit_fixture_posterior_artifact(request, forged)

    def test_nonfinite_policy_and_diagnostics_always_raise_contract_error(self):
        request = self.request()
        invalid_requests = (
            replace(request, policy=replace(request.policy, probability_clip=float("nan"))),
            replace(request, policy=replace(request.policy, sampler=replace(
                request.policy.sampler,
                convergence=replace(request.policy.sampler.convergence, minimum_ess_bulk=float("inf")),
            ))),
            replace(request, parameter_diagnostics=(replace(request.parameter_diagnostics[0], r_hat=float("nan")),) + request.parameter_diagnostics[1:]),
        )
        for invalid in invalid_requests:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ContractError):
                    build_fixture_posterior_artifact(invalid)

    def test_observation_timestamp_closes_over_every_bound_evidence_timestamp(self):
        request = self.request()
        last_posterior = max(row.posterior_available_at_utc for row in request.outcomes)
        last_cutoff = max(row.prediction_cutoff_at_utc for row in request.outcomes)
        last_calendar = max(request.session_calendar.session_available_at_utc)
        last_evidence = max(
            request.lineage.preregistration_observed_at_utc,
            request.lineage.baseline_audit_observed_at_utc,
            request.hierarchy_registry.observed_at_utc,
            request.safety_evidence.snapshot_validated_at_utc,
            request.safety_evidence.universe_approved_at_utc,
            request.safety_evidence.model_completed_at_utc,
            request.safety_evidence.quarantine_registry_observed_at_utc,
            last_posterior,
            last_cutoff,
            last_calendar,
        )
        self.assertGreaterEqual(request.lineage.observed_at_utc, last_evidence)
        with self.assertRaisesRegex(ContractError, "close over every bound evidence timestamp"):
            build_fixture_posterior_artifact(replace(
                request,
                lineage=replace(request.lineage, observed_at_utc=last_evidence - timedelta(seconds=1)),
            ))

        future_safety = replace(
            request.safety_evidence,
            quarantine_registry_observed_at_utc=request.lineage.observed_at_utc + timedelta(seconds=1),
        )
        future_safety = replace(
            future_safety,
            quarantine_registry_sha256=quarantine_registry_sha256(future_safety),
        )
        bad_request = replace(request, safety_evidence=future_safety)
        with self.assertRaisesRegex(ContractError, "close over every bound evidence timestamp"):
            build_fixture_posterior_artifact(bad_request)
        with self.assertRaisesRegex(ContractError, "close over every bound evidence timestamp"):
            audit_fixture_posterior_artifact(bad_request, build_fixture_posterior_artifact(request))

    def test_rejects_incoherent_explicit_evidence_chronology(self):
        request = self.request()
        bad_lineage = replace(
            request.lineage,
            baseline_audit_observed_at_utc=request.lineage.preregistration_observed_at_utc - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ContractError, "chronology is incoherent"):
            build_fixture_posterior_artifact(replace(request, lineage=bad_lineage))

        posterior = max(row.posterior_available_at_utc for row in request.outcomes)
        bad_safety = replace(request.safety_evidence, model_completed_at_utc=posterior - timedelta(seconds=1))
        with self.assertRaisesRegex(ContractError, "Model completion predates"):
            build_fixture_posterior_artifact(replace(request, safety_evidence=bad_safety))

    def test_rebound_baseline_after_first_posterior_is_rejected_by_build_and_auditor(self):
        request = self.request()
        first_posterior = min(row.posterior_available_at_utc for row in request.outcomes)
        rebound_lineage = replace(
            request.lineage,
            baseline_audit_observed_at_utc=first_posterior + timedelta(seconds=1),
        )
        rebound = replace(request, lineage=rebound_lineage)
        exact_artifact = build_fixture_posterior_artifact(request)
        with self.assertRaisesRegex(ContractError, "first-posterior chronology"):
            build_fixture_posterior_artifact(rebound)
        with self.assertRaisesRegex(ContractError, "first-posterior chronology"):
            audit_fixture_posterior_artifact(rebound, exact_artifact)

    def test_rebound_stale_quarantine_blocks_every_row_and_auditor_rebuilds_it(self):
        request = self.request()
        stale_safety = replace(
            request.safety_evidence,
            quarantine_registry_observed_at_utc=request.safety_evidence.model_completed_at_utc - timedelta(seconds=1),
        )
        stale_safety = replace(
            stale_safety,
            quarantine_registry_sha256=quarantine_registry_sha256(stale_safety),
        )
        rebound = replace(request, safety_evidence=stale_safety)
        artifact = build_fixture_posterior_artifact(rebound)
        self.assertEqual(artifact.status, ArtifactStatus.PROMOTION_BLOCKED)
        self.assertIn("QUARANTINE_EVIDENCE_NOT_APPLICABLE", artifact.blocker_codes)
        for row in artifact.prediction_evidence_rows:
            gate = next(gate for gate in row.hard_safety_gates if gate.gate_id == "NOT_QUARANTINED")
            self.assertFalse(gate.passed)
            self.assertEqual(gate.reason_code, "QUARANTINE_EVIDENCE_NOT_APPLICABLE")
            self.assertIn("QUARANTINE_EVIDENCE_NOT_APPLICABLE", row.proposed_codex_reasons)
        self.assertTrue(audit_fixture_posterior_artifact(rebound, artifact).passed)

        first = artifact.prediction_evidence_rows[0]
        forged_gates = tuple(
            replace(gate, passed=True, reason_code="PASS")
            if gate.gate_id == "NOT_QUARANTINED" else gate
            for gate in first.hard_safety_gates
        )
        forged = replace(
            artifact,
            prediction_evidence_rows=(
                replace(first, hard_safety_gates=forged_gates),
                *artifact.prediction_evidence_rows[1:],
            ),
        )
        forged = replace(
            forged,
            artifact_id="posterior_research_evidence_" + artifact_sha256(forged),
        )
        with self.assertRaisesRegex(ContractError, "semantics"):
            audit_fixture_posterior_artifact(rebound, forged)

    def test_full_malformed_numeric_probe_rejects_coercions_bools_and_nonfinite(self):
        request = self.request()
        malformed_floats = (True, 1, "0.5", Decimal("0.5"), float("nan"), float("inf"))
        for malformed in malformed_floats:
            variants = (
                replace(request, outcomes=(
                    replace(request.outcomes[0], probability_up_mean=malformed),
                    *request.outcomes[1:],
                )),
                replace(request, outcomes=(
                    replace(request.outcomes[0], expected_return_pp=malformed),
                    *request.outcomes[1:],
                )),
                replace(request, outcomes=(
                    replace(request.outcomes[0], research_signed_allocation=malformed),
                    *request.outcomes[1:],
                )),
                replace(request, policy=replace(request.policy, round_trip_cost_bps=malformed)),
                replace(request, parameter_diagnostics=(
                    replace(request.parameter_diagnostics[0], r_hat=malformed),
                    *request.parameter_diagnostics[1:],
                )),
                replace(request, chain_diagnostics=(
                    replace(request.chain_diagnostics[0], bfmi=malformed),
                    *request.chain_diagnostics[1:],
                )),
                replace(request, recorded_decisions=(
                    replace(
                        request.recorded_decisions[0],
                        sizing_adjustments=(replace(
                            request.recorded_decisions[0].sizing_adjustments[0],
                            multiplier=malformed,
                        ),),
                    ),
                    *request.recorded_decisions[1:],
                )),
            )
            for variant in variants:
                with self.subTest(malformed=malformed, variant=variant):
                    with self.assertRaises(ContractError):
                        build_fixture_posterior_artifact(variant)

        malformed_counts = (True, 2.0, "2", Decimal("2"))
        for malformed in malformed_counts:
            variants = (
                replace(request, policy=replace(request.policy, calibration_bins=malformed)),
                replace(request, policy=replace(
                    request.policy,
                    sampler=replace(request.policy.sampler, expected_chains=malformed),
                )),
                replace(request, chain_diagnostics=(
                    replace(request.chain_diagnostics[0], posterior_draws=malformed),
                    *request.chain_diagnostics[1:],
                )),
            )
            for variant in variants:
                with self.subTest(malformed_count=malformed, variant=variant):
                    with self.assertRaises(ContractError):
                        build_fixture_posterior_artifact(variant)

        malformed_times = (True, date(2026, 8, 27), "2026-08-27T00:00:00Z")
        for malformed in malformed_times:
            variants = (
                replace(request, lineage=replace(request.lineage, observed_at_utc=malformed)),
                replace(request, outcomes=(
                    replace(request.outcomes[0], posterior_available_at_utc=malformed),
                    *request.outcomes[1:],
                )),
            )
            for variant in variants:
                with self.subTest(malformed_time=malformed, variant=variant):
                    with self.assertRaises(ContractError):
                        build_fixture_posterior_artifact(variant)

        malformed_request = replace(request, outcomes=(
            replace(request.outcomes[0], probability_up_mean=Decimal("0.8")),
            *request.outcomes[1:],
        ))
        with self.assertRaises(ContractError):
            audit_fixture_posterior_artifact(
                malformed_request,
                build_fixture_posterior_artifact(request),
            )

    def test_semantic_auditor_rebuild_rejects_malformed_derived_metric(self):
        request = self.request()
        artifact = build_fixture_posterior_artifact(request)
        forged = replace(
            artifact,
            calibration=replace(artifact.calibration, brier_score="0.2"),
        )
        forged = replace(
            forged,
            artifact_id="posterior_research_evidence_" + artifact_sha256(forged),
        )
        with self.assertRaisesRegex(ContractError, "semantics"):
            audit_fixture_posterior_artifact(request, forged)

    def test_source_has_no_external_io_model_fit_or_operational_imports(self):
        path = Path(__file__).with_name("posterior_evaluation_contract.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(imported <= {"__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "math", "re", "typing"})
        forbidden_calls = {"open", "exec", "eval", "compile", "connect", "request", "run", "Popen", "system"}
        called = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
