from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import shutil
import tempfile
import unittest

try:
    from .checkpoint_quarantine_contract import DurableFixtureStore, FixtureStoreError
    from .pymc_hierarchical_backend import PyMCBackendError, freeze_backend_config, pack_design
    from .synthetic_sampling_rehearsal import SyntheticSamplerRehearsal, rehearse_synthetic_sampling
    from .test_pymc_backend_runner import _FakeAz, _FakePM, _request
except ImportError:  # isolated workspace execution
    from pymc_backend_runner_impl.checkpoint_quarantine_contract import (
        DurableFixtureStore,
        FixtureStoreError,
    )
    from pymc_backend_runner_impl.pymc_hierarchical_backend import (
        PyMCBackendError,
        freeze_backend_config,
        pack_design,
    )
    from pymc_backend_runner_impl.synthetic_sampling_rehearsal import (
        SyntheticSamplerRehearsal,
        rehearse_synthetic_sampling,
    )
    from pymc_backend_runner_impl.test_pymc_backend_runner import _FakeAz, _FakePM, _request


NOW = datetime.now(timezone.utc) - timedelta(seconds=1)


class _FixturePathMixin:
    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix="s08-store-parent-", dir=tempfile.gettempdir())).resolve()
        self.root = self.parent / "codex-s08-fixture-test"

    def tearDown(self):
        if self.parent.exists():
            shutil.rmtree(self.parent)

    def store(self):
        return DurableFixtureStore.create(
            self.root, run_id="fixture-run", plan_sha256="a" * 64,
            created_at_utc=NOW,
        )


@unittest.skipIf(os.name == "nt", "POSIX durability semantics are verified on Linux")
class DurableFixtureStoreTests(_FixturePathMixin, unittest.TestCase):
    def test_manifest_is_private_fixture_only(self):
        store = self.store()
        manifest = store.manifest()
        self.assertTrue(manifest.fixture_only)
        self.assertEqual(manifest.database_write_scope, "NONE")
        if __import__("os").name != "nt":
            self.assertEqual(store.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual((store.root / "manifest.json").stat().st_mode & 0o777, 0o600)

    def test_rejects_non_fixture_path(self):
        with self.assertRaisesRegex(FixtureStoreError, "isolated fixture"):
            DurableFixtureStore.create(
                self.parent / "production", run_id="fixture-run",
                plan_sha256="a" * 64, created_at_utc=NOW,
            )

    def test_checkpoint_sequence_is_hash_linked(self):
        store = self.store()
        first = store.append_checkpoint(
            observed_at_utc=NOW, completed_targets=0, total_targets=2,
            completed_folds=0, total_folds=1, divergences=0,
        )
        second = store.append_checkpoint(
            observed_at_utc=NOW + timedelta(seconds=1),
            completed_targets=2, total_targets=2,
            completed_folds=1, total_folds=1, divergences=0,
        )
        self.assertEqual(second.sequence, 2)
        self.assertEqual(second.previous_checkpoint_sha256, first.payload_sha256)
        self.assertEqual(len(store.read_checkpoints()), 2)

    def test_tampered_checkpoint_is_rejected(self):
        store = self.store()
        store.append_checkpoint(
            observed_at_utc=NOW, completed_targets=0, total_targets=2,
            completed_folds=0, total_folds=1, divergences=0,
        )
        path = next(store.checkpoints.glob("*.json"))
        raw = path.read_text(encoding="utf-8").replace('"divergences":0', '"divergences":1')
        path.write_text(raw, encoding="utf-8", newline="")
        with self.assertRaisesRegex(FixtureStoreError, "content address"):
            store.read_checkpoints()

    def test_success_requires_exact_coverage(self):
        store = self.store()
        store.append_checkpoint(
            observed_at_utc=NOW, completed_targets=0, total_targets=2,
            completed_folds=0, total_folds=1, divergences=0,
        )
        with self.assertRaisesRegex(FixtureStoreError, "coverage is incomplete"):
            store.finish(
                observed_at_utc=NOW, success=True,
                completed_targets=1, total_targets=2,
                completed_folds=1, total_folds=1,
            )

    def test_failure_is_quarantined_and_non_scientific(self):
        store = self.store()
        store.append_checkpoint(
            observed_at_utc=NOW, completed_targets=0, total_targets=2,
            completed_folds=0, total_folds=1, divergences=0,
        )
        terminal = store.finish(
            observed_at_utc=NOW + timedelta(seconds=1), success=False,
            completed_targets=0, total_targets=2,
            completed_folds=0, total_folds=1,
            failure_class="SyntheticFailure",
        )
        self.assertEqual(terminal.state, "TERMINAL_FIXTURE_FAILURE")
        self.assertTrue(terminal.outputs_quarantined)
        self.assertFalse(terminal.scientific_evidence)
        self.assertEqual(len(tuple(store.quarantine.glob("*.json"))), 1)

    def test_terminal_store_rejects_more_checkpoints(self):
        store = self.store()
        store.append_checkpoint(
            observed_at_utc=NOW, completed_targets=2, total_targets=2,
            completed_folds=1, total_folds=1, divergences=0,
        )
        store.finish(
            observed_at_utc=NOW + timedelta(seconds=1), success=True,
            completed_targets=2, total_targets=2,
            completed_folds=1, total_folds=1,
        )
        with self.assertRaisesRegex(FixtureStoreError, "already terminal"):
            store.append_checkpoint(
                observed_at_utc=NOW + timedelta(seconds=2),
                completed_targets=2, total_targets=2,
                completed_folds=1, total_folds=1, divergences=0,
            )

    def test_existing_root_is_not_reused(self):
        self.store()
        with self.assertRaises(FileExistsError):
            DurableFixtureStore.create(
                self.root, run_id="fixture-run", plan_sha256="a" * 64,
                created_at_utc=NOW,
            )


class _FailingPM(_FakePM):
    def sample(self, **_kwargs):
        raise RuntimeError("synthetic sampler failure")


@unittest.skipIf(os.name == "nt", "POSIX durability semantics are verified on Linux")
class SyntheticRehearsalTests(_FixturePathMixin, unittest.TestCase):
    def test_success_is_durable_smoke_not_science(self):
        config = freeze_backend_config()
        pm = _FakePM()
        terminal = rehearse_synthetic_sampling(
            root=self.root, run_id="fixture-run", plan_sha256="b" * 64,
            packed=pack_design(_request(config)), backend_config=config,
            started_at_utc=NOW,
            importer=lambda name: pm if name == "pymc" else _FakeAz(),
        )
        self.assertEqual(terminal.state, "TERMINAL_FIXTURE_SMOKE")
        self.assertFalse(terminal.convergence_claimed)
        self.assertFalse(terminal.scientific_evidence)
        self.assertFalse(terminal.outputs_quarantined)
        self.assertEqual(len(DurableFixtureStore(self.root).read_checkpoints()), 2)

    def test_sampler_failure_is_quarantined_and_reraised(self):
        config = freeze_backend_config()
        pm = _FailingPM()
        with self.assertRaisesRegex(RuntimeError, "synthetic sampler failure"):
            rehearse_synthetic_sampling(
                root=self.root, run_id="fixture-run", plan_sha256="b" * 64,
                packed=pack_design(_request(config)), backend_config=config,
                started_at_utc=NOW,
                importer=lambda name: pm if name == "pymc" else _FakeAz(),
            )
        terminal = DurableFixtureStore(self.root).read_terminal()
        self.assertEqual(terminal.state, "TERMINAL_FIXTURE_FAILURE")
        self.assertTrue(terminal.outputs_quarantined)

    def test_rehearsal_cannot_claim_science(self):
        config = freeze_backend_config()
        with self.assertRaisesRegex(PyMCBackendError, "claim boundary"):
            rehearse_synthetic_sampling(
                root=self.root, run_id="fixture-run", plan_sha256="b" * 64,
                packed=pack_design(_request(config)), backend_config=config,
                started_at_utc=NOW, importer=lambda _name: _FakePM(),
                rehearsal=SyntheticSamplerRehearsal(scientific_evidence=True),
            )
        self.assertFalse(self.root.exists())

    def test_rehearsal_resource_envelope_is_bounded(self):
        config = freeze_backend_config()
        with self.assertRaisesRegex(PyMCBackendError, "resource envelope"):
            rehearse_synthetic_sampling(
                root=self.root, run_id="fixture-run", plan_sha256="b" * 64,
                packed=pack_design(_request(config)), backend_config=config,
                started_at_utc=NOW, importer=lambda _name: _FakePM(),
                rehearsal=SyntheticSamplerRehearsal(draws=1000),
            )
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
