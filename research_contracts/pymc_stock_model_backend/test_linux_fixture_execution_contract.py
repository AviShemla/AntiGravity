from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import shutil
import tempfile
import unittest
import uuid

try:
    from hierarchical_model_impl.independent_edge_hierarchy import (
        SamplerDiagnosticsEvidence,
    )
except ModuleNotFoundError:
    from research_contracts.hierarchical_stock_model.independent_edge_hierarchy import (
        SamplerDiagnosticsEvidence,
    )

from .linux_fixture_execution_contract import (
    ResourceObservation, audit_fixture_terminal, build_dependency_lock,
    build_resource_bounded_plan, build_synthetic_convergence_evidence,
    run_resource_bounded_fixture, verify_dependency_lock,
    verify_synthetic_convergence_evidence,
)
from .pymc_hierarchical_backend import PyMCBackendError, freeze_backend_config


NOW = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
FIXTURE_SHA = "a" * 64


def _identity(**changes):
    value = {
        "platform_system": "Linux", "platform_machine": "x86_64",
        "python_version": "3.14.4", "python_implementation": "CPython",
        "python_executable_sha256": "1" * 64, "pymc_version": "6.1.0",
        "pytensor_version": "2.38.2", "arviz_version": "1.2.0",
        "numpy_version": "2.4.6", "blas_identity_sha256": "2" * 64,
        "distribution_records_sha256": "3" * 64,
    }
    value.update(changes)
    return value


def _diagnostics(**changes):
    value = dict(chains=4, draws=1000, tune=1000, max_rhat=1.005,
                 min_bulk_ess=800.0, min_tail_ess=700.0, bfmi_min=0.8,
                 divergences=0, max_treedepth_fraction=0.0)
    value.update(changes)
    return SamplerDiagnosticsEvidence(**value)


def _observation(**changes):
    value = dict(observed_at_utc=NOW, available_cpu_count=4,
                 available_memory_bytes=8_000_000_000,
                 available_disk_bytes=10_000_000_000,
                 guarded_ingestion_active=False,
                 next_guarded_ingestion_at_utc=NOW + timedelta(hours=3),
                 no_duplicate_worker=True)
    value.update(changes)
    return ResourceObservation(**value)


class LinuxLockAndConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.lock = build_dependency_lock(**_identity())
        self.config = freeze_backend_config()

    def evidence(self, diagnostics=None):
        return build_synthetic_convergence_evidence(
            run_id="fixture-four-chain", fixture_sha256=FIXTURE_SHA,
            lock=self.lock, config=self.config,
            diagnostics=diagnostics or _diagnostics(),
        )

    def test_dependency_lock_is_deterministic_and_exact(self):
        self.assertEqual(self.lock, build_dependency_lock(**_identity()))
        verify_dependency_lock(self.lock, _identity())

    def test_dependency_lock_rejects_non_linux_or_runtime_drift(self):
        with self.assertRaisesRegex(PyMCBackendError, "Linux"):
            build_dependency_lock(**_identity(platform_system="Windows"))
        with self.assertRaisesRegex(PyMCBackendError, "differs from lock"):
            verify_dependency_lock(self.lock, _identity(numpy_version="2.4.7"))

    def test_dependency_lock_tamper_is_rejected(self):
        with self.assertRaisesRegex(PyMCBackendError, "content address"):
            verify_dependency_lock(replace(self.lock, pymc_version="6.1.1"), _identity())

    def test_four_chain_evidence_is_fixture_only_and_content_addressed(self):
        value = self.evidence()
        self.assertTrue(value.synthetic_convergence_verified)
        self.assertFalse(value.scientific_evidence)
        self.assertFalse(value.posterior_persisted)
        self.assertEqual(value.database_write_scope, "NONE")
        self.assertEqual(set(value.downstream_counts.values()), {0})
        verify_synthetic_convergence_evidence(value, lock=self.lock,
                                              config=self.config,
                                              fixture_sha256=FIXTURE_SHA)

    def test_four_chain_counts_cannot_be_weakened(self):
        with self.assertRaisesRegex(PyMCBackendError, "frozen sampler counts"):
            self.evidence(_diagnostics(chains=3))

    def test_convergence_failures_are_rejected(self):
        cases = (_diagnostics(max_rhat=1.02), _diagnostics(min_bulk_ess=399),
                 _diagnostics(min_tail_ess=399), _diagnostics(bfmi_min=0.29),
                 _diagnostics(divergences=1),
                 _diagnostics(max_treedepth_fraction=0.02))
        for case in cases:
            with self.subTest(case=case), self.assertRaisesRegex(PyMCBackendError, "gates failed"):
                self.evidence(case)

    def test_nonfinite_convergence_diagnostic_is_rejected(self):
        with self.assertRaisesRegex(PyMCBackendError, "not numeric"):
            self.evidence(_diagnostics(max_rhat=float("nan")))

    def test_convergence_evidence_tamper_is_rejected(self):
        value = replace(self.evidence(), scientific_evidence=True)
        with self.assertRaisesRegex(PyMCBackendError, "identity or claim"):
            verify_synthetic_convergence_evidence(value, lock=self.lock,
                                                  config=self.config,
                                                  fixture_sha256=FIXTURE_SHA)


class ResourceBoundedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.lock = build_dependency_lock(**_identity())
        self.config = freeze_backend_config()
        self.plan = build_resource_bounded_plan(
            run_id="fixture-resource-run", lock=self.lock, config=self.config,
            fixture_sha256=FIXTURE_SHA, observation=_observation(), now=NOW,
        )
        self.root = Path(tempfile.gettempdir()) / f"codex-s08-fixture-{uuid.uuid4().hex}"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def evidence(self):
        return build_synthetic_convergence_evidence(
            run_id=self.plan.run_id, fixture_sha256=FIXTURE_SHA, lock=self.lock,
            config=self.config, diagnostics=_diagnostics())

    def test_plan_is_low_priority_and_non_authorizing(self):
        self.assertLessEqual(self.plan.cpu_quota_percent, 50)
        self.assertLessEqual(self.plan.io_weight, 100)
        self.assertGreaterEqual(self.plan.nice, 5)
        self.assertTrue(self.plan.fixture_only)
        self.assertFalse(self.plan.downstream_authorized)

    def test_plan_rejects_active_ingestion(self):
        with self.assertRaisesRegex(PyMCBackendError, "must yield"):
            build_resource_bounded_plan(
                run_id="fixture-resource-run", lock=self.lock, config=self.config,
                fixture_sha256=FIXTURE_SHA,
                observation=_observation(guarded_ingestion_active=True), now=NOW)

    def test_plan_rejects_stale_probe_duplicate_or_missing_buffer(self):
        cases = (
            (_observation(observed_at_utc=NOW - timedelta(minutes=3)), "stale"),
            (_observation(no_duplicate_worker=False), "duplicate"),
            (_observation(next_guarded_ingestion_at_utc=NOW + timedelta(minutes=45)), "buffer"),
        )
        for observation, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(PyMCBackendError, message):
                build_resource_bounded_plan(
                    run_id="fixture-resource-run", lock=self.lock,
                    config=self.config, fixture_sha256=FIXTURE_SHA,
                    observation=observation, now=NOW)

    @unittest.skipIf(os.name == "nt", "durable POSIX fixture store is Linux-verified")
    def test_success_has_durable_independent_audit(self):
        times = iter((NOW, NOW, NOW + timedelta(seconds=1),
                      NOW + timedelta(seconds=2), NOW + timedelta(seconds=2)))
        terminal = run_resource_bounded_fixture(
            root=self.root, plan=self.plan,
            observation_reader=lambda: _observation(),
            now_reader=lambda: next(times), executor=self.evidence)
        self.assertEqual(terminal.state, "TERMINAL_FIXTURE_SMOKE")
        audit = audit_fixture_terminal(self.root, self.plan)
        self.assertEqual(audit.checkpoint_count, 2)
        self.assertTrue(audit.exact_fixture_coverage)
        self.assertTrue(audit.zero_downstream_outputs)

    @unittest.skipIf(os.name == "nt", "durable POSIX fixture store is Linux-verified")
    def test_ingestion_activation_before_execute_yields_and_quarantines(self):
        called = False
        def execute():
            nonlocal called
            called = True
            return self.evidence()
        times = iter((NOW, NOW, NOW + timedelta(seconds=1)))
        with self.assertRaisesRegex(PyMCBackendError, "must yield"):
            run_resource_bounded_fixture(
                root=self.root, plan=self.plan,
                observation_reader=lambda: _observation(guarded_ingestion_active=True),
                now_reader=lambda: next(times), executor=execute)
        self.assertFalse(called)
        from .checkpoint_quarantine_contract import DurableFixtureStore
        terminal = DurableFixtureStore(self.root).read_terminal()
        self.assertTrue(terminal.outputs_quarantined)
        self.assertEqual(terminal.failure_class, "PyMCBackendError")

    @unittest.skipIf(os.name == "nt", "durable POSIX fixture store is Linux-verified")
    def test_ingestion_activation_after_execute_quarantines_result(self):
        observations = iter((_observation(), _observation(guarded_ingestion_active=True)))
        times = iter((NOW, NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))
        with self.assertRaisesRegex(PyMCBackendError, "must yield"):
            run_resource_bounded_fixture(
                root=self.root, plan=self.plan,
                observation_reader=lambda: next(observations),
                now_reader=lambda: next(times), executor=self.evidence)
        from .checkpoint_quarantine_contract import DurableFixtureStore
        terminal = DurableFixtureStore(self.root).read_terminal()
        self.assertTrue(terminal.outputs_quarantined)

    def test_tampered_plan_is_rejected_before_filesystem_write(self):
        attacked = replace(self.plan, nice=4)
        with self.assertRaisesRegex(PyMCBackendError, "plan identity"):
            run_resource_bounded_fixture(
                root=self.root, plan=attacked,
                observation_reader=lambda: _observation(),
                now_reader=lambda: NOW, executor=self.evidence)
        self.assertFalse(self.root.exists())
