from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

try:
    from .execution_contract import (
        AUTHORIZATION_SCOPE, CONTRACT_ID, EXPECTED_DEPTHS, EXPECTED_LAGS,
        AuthorizationStatus, CheckpointEvidence, CheckpointState, CodeClosure,
        ExecutionAuthorizationArtifact, ExecutionContractError, ExecutionRequest,
        ExplicitRunAuthorization, LaunchCommand, OutputBoundary,
        PreregistrationProof, ResourceEnvelope, TerminalReadback,
        audit_checkpoint_sequence, audit_execution_authorization,
        audit_terminal_readback, build_execution_authorization, canonical_sha256,
        authorization_record_sha256,
    )
except ImportError:  # pragma: no cover - direct staging-directory execution
    from execution_contract import (
    AUTHORIZATION_SCOPE, CONTRACT_ID, EXPECTED_DEPTHS, EXPECTED_LAGS,
    AuthorizationStatus, CheckpointEvidence, CheckpointState, CodeClosure,
    ExecutionAuthorizationArtifact, ExecutionContractError, ExecutionRequest,
    ExplicitRunAuthorization, LaunchCommand, OutputBoundary,
    PreregistrationProof, ResourceEnvelope, TerminalReadback,
    audit_checkpoint_sequence, audit_execution_authorization,
    audit_terminal_readback, build_execution_authorization, canonical_sha256,
    authorization_record_sha256,
    )


SHA = "a" * 64
GIT = "b" * 40


class ExecutionContractTests(unittest.TestCase):
    now = datetime(2026, 8, 27, 6, 30, tzinfo=timezone.utc)
    run_id = "stock-fit-20260827-v1"

    def prereg(self, **changes):
        values = dict(
            contract_id="codex-oracle-hierarchical-stock-preregistration-v2",
            run_id=self.run_id, raw_sha256="1" * 64,
            checkpoint_identity_sha256="2" * 64,
            independent_audit_raw_sha256="3" * 64,
            independent_audit_status="VERIFIED_FIXTURE_ONLY",
            independent_audit_observed_at_utc=self.now - timedelta(minutes=4),
            current_readback_raw_sha256="4" * 64,
            current_readback_status="VERIFIED_SELECT_ONLY",
            current_readback_observed_at_utc=self.now - timedelta(minutes=2),
            snapshot_id="market-features-20260826", snapshot_sha256="5" * 64,
            universe_id="approved-universe-v1", universe_sha256="6" * 64,
            full_session_calendar_sha256="7" * 64,
            model_session_dates_sha256="8" * 64,
            model_code_git_commit=GIT, model_config_sha256="9" * 64,
            sampler_sha256="c" * 64, candidate_lags=EXPECTED_LAGS,
            candidate_depths=EXPECTED_DEPTHS, target_count=474, fold_count=4,
            model_calendar_sessions=416, training_only_selection=True,
            multiple_testing_control="BH_FDR_PREREGISTERED",
            zero_temporal_overlap=True, fixture_only=True,
            model_fit_authorized=False, model_fit_started=False,
            downstream_counts={"predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0},
        )
        values.update(changes)
        return PreregistrationProof(**values)

    def request(self, *, prereg=None, authorization=None, code=None, resources=None, output=None, launch=None):
        prereg = prereg or self.prereg()
        release = f"/opt/codex-oracle/releases/stock-fit-{GIT}"
        code = code or CodeClosure(
            git_commit=GIT, release_root=release, release_manifest_sha256="d" * 64,
            model_entrypoint=f"{release}/run_model.py", model_entrypoint_sha256="e" * 64,
            dependency_lock_sha256="f" * 64, python_executable=f"{release}/venv/bin/python",
            python_identity_sha256="0" * 64, closure_file_count=42,
            root_owned=True, immutable=True, secret_scan_passed=True,
        )
        if authorization is None:
            unsigned = ExplicitRunAuthorization(
                authorization_id="avi-s08-stock-fit-v1", authorization_record_sha256="0" * 64,
                authorized_by="Avi", authorized_at_utc=self.now - timedelta(minutes=1),
                launch_deadline_utc=self.now + timedelta(hours=2), scope=AUTHORIZATION_SCOPE,
                run_id=self.run_id, preregistration_raw_sha256=prereg.raw_sha256,
                single_run_only=True, exact_model_only=True, research_only=True,
                database_write_scope="NONE", prediction_persistence_authorized=False,
                recommendation_authorized=False, order_authorized=False,
                etf_output_authorized=False, trading_authorized=False,
                snapshot_validation_or_promotion_authorized=False,
            )
            authorization = replace(
                unsigned,
                authorization_record_sha256=authorization_record_sha256(unsigned),
            )
        resources = resources or ResourceEnvelope(
            observed_at_utc=self.now - timedelta(seconds=30), available_cpu_count=4,
            cpu_quota_percent=50, available_memory_bytes=16_000_000_000,
            memory_max_bytes=8_000_000_000, available_disk_bytes=100_000_000_000,
            minimum_free_disk_bytes=20_000_000_000, io_weight=50, nice=10,
            expected_max_runtime_seconds=3600, guarded_ingestion_active=False,
            next_guarded_ingestion_at_utc=self.now + timedelta(hours=4),
            ingestion_priority_reserved=True, no_duplicate_writer_observed=True,
        )
        output = output or OutputBoundary(
            output_root=f"/var/lib/codex-oracle/s08/{self.run_id}",
            checkpoint_path=f"/var/lib/codex-oracle/s08/{self.run_id}/checkpoint.json",
            terminal_manifest_path=f"/var/lib/codex-oracle/s08/{self.run_id}/terminal.json",
            quarantine_root=f"/var/lib/codex-oracle/s08/{self.run_id}/quarantine",
        )
        launch = launch or LaunchCommand(
            argv=(
                code.python_executable, code.model_entrypoint,
                "--execution-contract",
                f"/run/codex-oracle/s08/{prereg.run_id}/execution-authorization.json",
                "--output-root", output.output_root, "--mode", "NEW_RUN",
            ),
            shell=False, working_directory=code.release_root, environment_keys=("PYTHONHASHSEED",),
            checkpoint_interval_seconds=900, resume_supported=True,
            idempotency_key=canonical_sha256({"run_id": prereg.run_id, "preregistration_raw_sha256": prereg.raw_sha256, "code_git_commit": code.git_commit}),
        )
        return ExecutionRequest(prereg, authorization, code, resources, output, launch)

    def artifact(self, request=None):
        return build_execution_authorization(request or self.request(), created_at_utc=self.now)

    def test_valid_request_creates_content_addressed_not_started_artifact(self):
        artifact = self.artifact()
        self.assertEqual(artifact.contract_id, CONTRACT_ID)
        self.assertIs(artifact.status, AuthorizationStatus.AUTHORIZED_NOT_STARTED)
        self.assertFalse(artifact.model_fit_started)
        self.assertFalse(artifact.database_writes_authorized)
        self.assertFalse(artifact.downstream_authorized)
        self.assertFalse(artifact.launch_performed)
        self.assertEqual(audit_execution_authorization(self.request(), artifact, observed_at_utc=self.now), canonical_sha256(artifact))

    def test_preregistration_itself_must_remain_non_authorizing(self):
        for changes in ({"model_fit_authorized": True}, {"model_fit_started": True}, {"fixture_only": False}):
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                self.artifact(self.request(prereg=self.prereg(**changes)))

    def test_exact_lag_depth_calendar_target_fold_and_selection_geometry_is_frozen(self):
        mutations = (
            {"candidate_lags": (1, 2)}, {"candidate_depths": (1, 2)},
            {"target_count": 473}, {"fold_count": 3}, {"model_calendar_sessions": 415},
            {"training_only_selection": False}, {"multiple_testing_control": ""},
            {"zero_temporal_overlap": False},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                self.artifact(self.request(prereg=self.prereg(**changes)))

    def test_stale_or_unverified_evidence_fails_closed(self):
        mutations = (
            {"independent_audit_status": "PASS"}, {"current_readback_status": "PASS"},
            {"independent_audit_observed_at_utc": self.now - timedelta(hours=2)},
            {"current_readback_observed_at_utc": self.now + timedelta(seconds=1)},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                self.artifact(self.request(prereg=self.prereg(**changes)))

    def test_authorization_must_be_explicit_exact_current_and_closed(self):
        base = self.request().authorization
        mutations = (
            {"scope": "GENERAL_RESEARCH"}, {"run_id": "other"},
            {"preregistration_raw_sha256": "f" * 64}, {"single_run_only": False},
            {"exact_model_only": False}, {"research_only": False},
            {"database_write_scope": "TURSO"}, {"prediction_persistence_authorized": True},
            {"recommendation_authorized": True}, {"order_authorized": True},
            {"etf_output_authorized": True}, {"trading_authorized": True},
            {"snapshot_validation_or_promotion_authorized": True},
            {"launch_deadline_utc": self.now - timedelta(seconds=1)},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                candidate = replace(
                    base, authorization_record_sha256="0" * 64, **changes
                )
                candidate = replace(
                    candidate,
                    authorization_record_sha256=authorization_record_sha256(candidate),
                )
                self.artifact(self.request(authorization=candidate))

    def test_authorization_record_digest_is_recomputed_not_trusted(self):
        base = self.request().authorization
        attacked = replace(base, authorized_by="Mallory")
        with self.assertRaisesRegex(ExecutionContractError, "identity mismatch"):
            self.artifact(self.request(authorization=attacked))

    def test_code_closure_is_exact_immutable_root_owned_and_secret_scanned(self):
        base = self.request().code
        mutations = (
            {"git_commit": "c" * 40}, {"release_root": "/tmp/release"},
            {"model_entrypoint": "/tmp/run.py"}, {"closure_file_count": 0},
            {"root_owned": False}, {"immutable": False}, {"secret_scan_passed": False},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                code = replace(base, **changes)
                self.artifact(self.request(code=code))

    def test_resources_preserve_ingestion_and_host_headroom(self):
        base = self.request().resources
        mutations = (
            {"available_cpu_count": 1}, {"memory_max_bytes": 15_000_000_000},
            {"available_disk_bytes": 10}, {"io_weight": 101}, {"nice": 0},
            {"guarded_ingestion_active": True}, {"ingestion_priority_reserved": False},
            {"no_duplicate_writer_observed": False},
            {"next_guarded_ingestion_at_utc": self.now + timedelta(hours=1)},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                self.artifact(self.request(resources=replace(base, **changes)))

    def test_output_boundary_forbids_database_and_downstream_actions(self):
        base = self.request().output
        mutations = (
            {"output_root": "/tmp/run"}, {"checkpoint_path": "/tmp/checkpoint"},
            {"append_only": False}, {"overwrite_allowed": True},
            {"database_write_scope": "TURSO"}, {"persist_predictions": True},
            {"create_recommendations": True}, {"create_orders": True},
            {"create_etf_outputs": True}, {"activate_trading": True},
            {"validate_or_promote_snapshot": True},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                self.artifact(self.request(output=replace(base, **changes)))

    def test_launch_is_no_shell_immutable_allowlisted_and_idempotent(self):
        request = self.request()
        base = request.launch
        mutations = (
            {"shell": True}, {"argv": ("/bin/sh", "-c", "run")},
            {"working_directory": "/tmp"},
            {"environment_keys": ("TURSO_AUTH_TOKEN",)},
            {"environment_keys": ("Z", "A")}, {"resume_supported": False},
            {"idempotency_key": "f" * 64},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                self.artifact(self.request(launch=replace(base, **changes)))

    def checkpoint(self, artifact, sequence, state, minute, **changes):
        values = dict(
            contract_artifact_id=artifact.artifact_id, run_id=artifact.run_id,
            sequence=sequence, state=state,
            observed_at_utc=self.now + timedelta(minutes=minute),
            code_git_commit=artifact.code_git_commit,
            preregistration_raw_sha256=artifact.preregistration_raw_sha256,
            payload_sha256=f"{sequence:x}" * 64,
            completed_targets=min(sequence, 474), completed_folds=0,
            divergences=0,
            downstream_counts={"predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0},
        )
        values.update(changes)
        return CheckpointEvidence(**values)

    def test_checkpoint_sequence_is_append_only_identity_bound_and_fresh(self):
        artifact = self.artifact()
        checkpoints = (
            self.checkpoint(artifact, 1, CheckpointState.RUNNING, 1),
            self.checkpoint(artifact, 2, CheckpointState.RUNNING, 10),
        )
        self.assertEqual(audit_checkpoint_sequence(artifact, checkpoints, observed_at_utc=self.now + timedelta(minutes=20)).sequence, 2)
        with self.assertRaisesRegex(ExecutionContractError, "stale"):
            audit_checkpoint_sequence(artifact, checkpoints, observed_at_utc=self.now + timedelta(minutes=71))

    def test_checkpoint_rejects_gap_post_terminal_identity_drift_and_side_effects(self):
        artifact = self.artifact()
        first = self.checkpoint(artifact, 1, CheckpointState.RUNNING, 1)
        bad_cases = (
            (first, self.checkpoint(artifact, 3, CheckpointState.RUNNING, 2)),
            (self.checkpoint(artifact, 1, CheckpointState.TERMINAL_SUCCESS, 1), self.checkpoint(artifact, 2, CheckpointState.RUNNING, 2)),
            (first, self.checkpoint(artifact, 2, CheckpointState.RUNNING, 2, code_git_commit="c" * 40)),
            (first, self.checkpoint(artifact, 2, CheckpointState.RUNNING, 2, downstream_counts={"orders": 1})),
            (first, self.checkpoint(artifact, 2, CheckpointState.RUNNING, 2, downstream_counts={})),
            (first, self.checkpoint(artifact, 2, "RUNNING", 2)),
            (first, self.checkpoint(artifact, 2, CheckpointState.RUNNING, 2, completed_targets=True)),
        )
        for checkpoints in bad_cases:
            with self.subTest(), self.assertRaises(ExecutionContractError):
                audit_checkpoint_sequence(artifact, checkpoints, observed_at_utc=self.now + timedelta(minutes=3))

    def terminal(self, artifact, state=CheckpointState.TERMINAL_SUCCESS, **changes):
        prereg = self.prereg()
        values = dict(
            contract_artifact_id=artifact.artifact_id, run_id=artifact.run_id,
            state=state, terminal_manifest_raw_sha256="f" * 64,
            observed_at_utc=self.now + timedelta(hours=1), target_count=474,
            fold_count=4, ticker_count=474, candidate_lags=EXPECTED_LAGS,
            candidate_depths=EXPECTED_DEPTHS, snapshot_sha256=prereg.snapshot_sha256,
            universe_sha256=prereg.universe_sha256, model_code_git_commit=artifact.code_git_commit,
            model_config_sha256=prereg.model_config_sha256, sampler_sha256=prereg.sampler_sha256,
            zero_temporal_overlap=True, convergence_passed=True,
            partial_outputs_quarantined=False,
            downstream_counts={"predictions": 0, "recommendations": 0, "orders": 0, "etf_outputs": 0},
        )
        values.update(changes)
        return TerminalReadback(**values)

    def test_terminal_success_requires_exact_coverage_convergence_and_zero_side_effects(self):
        artifact = self.artifact()
        result = audit_terminal_readback(artifact, self.prereg(), self.terminal(artifact))
        self.assertEqual(result.scientific_outcome, "ACCEPTED_RESEARCH_POSTERIOR")
        for changes in (
            {"target_count": 473}, {"fold_count": 3}, {"convergence_passed": False},
            {"downstream_counts": {"orders": 1}}, {"downstream_counts": {}},
            {"observed_at_utc": self.now - timedelta(seconds=1)},
            {"state": "TERMINAL_SUCCESS"}, {"target_count": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ExecutionContractError):
                audit_terminal_readback(artifact, self.prereg(), self.terminal(artifact, **changes))

    def test_scientific_failure_is_preserved_and_quarantined_not_rewritten(self):
        artifact = self.artifact()
        terminal = self.terminal(
            artifact, state=CheckpointState.TERMINAL_SCIENTIFIC_FAILURE,
            target_count=137, ticker_count=137, fold_count=2,
            convergence_passed=False, partial_outputs_quarantined=True,
        )
        result = audit_terminal_readback(artifact, self.prereg(), terminal)
        self.assertEqual(result.scientific_outcome, "PRESERVED_SCIENTIFIC_FAILURE_NO_DOWNSTREAM_USE")
        with self.assertRaises(ExecutionContractError):
            audit_terminal_readback(artifact, self.prereg(), replace(terminal, partial_outputs_quarantined=False))

    def test_rehashed_privilege_or_identity_drift_fails_independent_audit(self):
        request = self.request()
        artifact = self.artifact(request)
        attacked = replace(artifact, database_writes_authorized=True)
        with self.assertRaisesRegex(ExecutionContractError, "semantics"):
            audit_execution_authorization(request, attacked, observed_at_utc=self.now)

    def test_contract_module_is_pure_and_has_no_process_network_or_database_client(self):
        source = Path(__file__).with_name("execution_contract.py").read_text(
            encoding="utf-8"
        ).lower()
        for forbidden in (
            "import os", "subprocess", "requests", "urllib", "libsql",
            "sqlite", "pymc", "pending_orders", "save_model", "send_email",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
