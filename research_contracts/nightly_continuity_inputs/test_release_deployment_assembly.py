from __future__ import annotations

import hashlib
import ast
import json
import os
import shutil
import stat
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from s02_recurring_deployment_impl import disabled_only_installer as installer
    from s02_recurring_deployment_impl import release_deployment_assembly as subject
except ModuleNotFoundError:  # Canonical repository package path.
    from research_contracts.nightly_continuity_inputs import (
        disabled_only_installer as installer,
    )
    from research_contracts.nightly_continuity_inputs import (
        release_deployment_assembly as subject,
    )


HERE = Path(__file__).parent


class FakeInspector:
    def inspect(self, unit):
        if unit not in installer.ALL_GUARDED_UNITS:
            raise AssertionError("unexpected unit")
        return installer.UnitState("inactive", "disabled")


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.root = HERE / "_test_io" / f"assembly-{uuid.uuid4().hex}"
        self.source = self.root / "source"
        self.source.mkdir(parents=True)
        shutil.copy2(HERE / "nyse_calendar_2026.json", self.source / "calendar.json")
        shutil.copy2(HERE / "nyse_ruleset_2026.json", self.source / "ruleset.json")
        shutil.copy2(
            HERE / "turso_idempotency_preflight.py", self.source / "preflight.py"
        )
        self.ruleset_hash = subject.sha256_file(self.source / "ruleset.json")
        self.preflight_hash = subject.sha256_file(self.source / "preflight.py")
        self.release_root = self.source / "releases"
        self.release_root.mkdir()
        self.release_ids = self._release_set()
        self._config()
        self._units()

    def tearDown(self):
        if self.root.exists():
            for directory, _, files in os.walk(self.root):
                for name in files:
                    try:
                        os.chmod(Path(directory) / name, stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
            shutil.rmtree(self.root)

    def _release(self, kind, files):
        staging = self.release_root / f"{kind}-staging"
        staging.mkdir()
        rows = []
        for relative, (content, mode) in sorted(files.items()):
            path = staging.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            rows.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "mode": mode,
                }
            )
        manifest = {
            "contract_id": subject.RELEASE_CONTRACT_ID,
            "release_kind": kind,
            "files": rows,
        }
        encoded = subject.canonical_bytes(manifest)
        release_id = hashlib.sha256(encoded).hexdigest()
        (staging / "release-manifest.json").write_bytes(encoded)
        staging.rename(self.release_root / f"{kind}-{release_id}")
        return release_id

    def _release_set(self):
        controller = self._release(
            "nightly-continuity",
            {
                "run-nightly-continuity": (b"#!/bin/sh\nexit 0\n", "0700"),
                "run-nightly-continuity-watchdog": (b"#!/bin/sh\nexit 0\n", "0700"),
                "continuity_controller.py": (b"# controller\n", "0600"),
                "release_layout.py": (b"# release verifier\n", "0600"),
            },
        )
        ingestion = self._release(
            "market-ingestion",
            {
                "run-market-ingestion": (b"#!/bin/sh\nexit 0\n", "0700"),
                "stage_runner.py": (b"# runner\n", "0600"),
                "release_layout.py": (b"# release verifier\n", "0600"),
                "payload/run-market-ingestion-impl": (b"#!/bin/sh\nexit 0\n", "0700"),
            },
        )
        handoff = self._release(
            "market-ingestion-handoff",
            {
                "run-market-ingestion-postflight": (b"#!/bin/sh\nexit 0\n", "0700"),
                "run-market-ingestion-handoff": (b"#!/bin/sh\nexit 0\n", "0700"),
                "stage_runner.py": (b"# runner\n", "0600"),
                "release_layout.py": (b"# release verifier\n", "0600"),
                "payload/run-market-ingestion-postflight-impl": (b"#!/bin/sh\nexit 0\n", "0700"),
                "payload/run-market-ingestion-handoff-impl": (b"#!/bin/sh\nexit 0\n", "0700"),
            },
        )
        return controller, ingestion, handoff

    def _config(self):
        raw = {
            "calendar_path": installer.EXACT_ROLE_TARGETS["CALENDAR"],
            "calendar_sha256": subject.sha256_file(self.source / "calendar.json"),
            "preflight_executable": (
                "/opt/codex-oracle/releases/market-ingestion-preflight-"
                f"{self.preflight_hash}/run-select-only-preflight"
            ),
            "preflight_sha256": self.preflight_hash,
            **subject.CONFIG_EXACT,
            "settlement_delay_seconds": 900,
            "calendar_min_future_horizon_seconds": 604800,
            "max_preflight_age_seconds": 300,
            "max_handoff_age_seconds": 604800,
            "max_checkpoint_age_seconds": 900,
            "max_load_per_cpu": 1.5,
            "min_available_memory_mb": 1024,
            "min_free_disk_mb": 4096,
        }
        (self.source / "config.json").write_bytes(subject.canonical_bytes(raw))

    def _runner_target(self, role):
        controller, ingestion, handoff = self.release_ids
        ids = {
            "nightly-continuity": controller,
            "market-ingestion": ingestion,
            "market-ingestion-handoff": handoff,
        }
        kind, relative = subject.RUNNERS[role]
        return f"/opt/codex-oracle/releases/{kind}-{ids[kind]}/{relative}"

    def _units(self):
        units = self.source / "units"
        units.mkdir()
        for name in sorted(installer.RECURRING_UNITS):
            role = subject.UNIT_RUNNER_BINDINGS.get(name)
            binding = f"ExecStart={self._runner_target(role)}\n" if role else ""
            (units / name).write_text("[Unit]\n" + binding, encoding="utf-8", newline="\n")

    def assemble(self):
        controller, ingestion, handoff = self.release_ids
        return subject.assemble(
            source_root=self.source,
            calendar_source="calendar.json",
            ruleset_source="ruleset.json",
            ruleset_sha256=self.ruleset_hash,
            preflight_source="preflight.py",
            preflight_sha256=self.preflight_hash,
            controller_config_source="config.json",
            release_root_source="releases",
            controller_release_id=controller,
            ingestion_release_id=ingestion,
            handoff_release_id=handoff,
            units_source="units",
            deployment_id="s02-concrete-fixture-20260827",
        )

    def test_concrete_assembly_has_five_runners_seven_units_and_exact_identities(self):
        raw = self.assemble()
        subject.validate_assembly(raw)
        self.assertEqual(len(raw["runners"]), 5)
        self.assertEqual(len(raw["units"]), 7)
        self.assertEqual(raw["rollback"]["contract_id"], installer.ROLLBACK_CONTRACT_ID)
        self.assertEqual(raw["audit"]["contract_id"], installer.AUDIT_CONTRACT_ID)
        self.assertEqual(raw["activation"], "EXPLICITLY_OUT_OF_SCOPE")

    def test_nested_manifest_is_accepted_and_fixture_installs_then_audits(self):
        raw = self.assemble()
        deployment = raw["disabled_installation"]["manifest"]
        deployment_hash = raw["disabled_installation"]["manifest_sha256"]
        rollback = installer.install_disabled_only(
            deployment,
            manifest_sha256=deployment_hash,
            source_root=self.source,
            target_root=self.root / "target",
            rollback_root=self.root / "rollback",
            inspector=FakeInspector(),
            observed_at=datetime(2026, 8, 27, 2, 0, tzinfo=timezone.utc),
            fixture_mode=True,
        )
        audit = installer.audit_disabled_installation(
            deployment,
            rollback,
            manifest_sha256=deployment_hash,
            target_root=self.root / "target",
            inspector=FakeInspector(),
            observed_at=datetime(2026, 8, 27, 2, 1, tzinfo=timezone.utc),
            fixture_mode=True,
        )
        self.assertEqual(audit["status"], "OBSERVED_DISABLED_ONLY")

    def test_release_file_tamper_is_rejected(self):
        controller = self.release_ids[0]
        path = self.release_root / f"nightly-continuity-{controller}" / "continuity_controller.py"
        path.write_bytes(b"tamper\n")
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()

    def test_required_release_mode_tamper_is_rejected(self):
        controller = self.release_ids[0]
        path = self.release_root / f"nightly-continuity-{controller}" / "release-manifest.json"
        raw = json.loads(path.read_text())
        next(x for x in raw["files"] if x["path"] == "run-nightly-continuity")["mode"] = "0600"
        encoded = subject.canonical_bytes(raw)
        path.write_bytes(encoded)
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()

    def test_controller_config_binding_tamper_is_rejected(self):
        raw = json.loads((self.source / "config.json").read_text())
        raw["calendar_sha256"] = "0" * 64
        (self.source / "config.json").write_bytes(subject.canonical_bytes(raw))
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()
        self._config()
        raw = json.loads((self.source / "config.json").read_text())
        raw["max_checkpoint_age_seconds"] = 0
        (self.source / "config.json").write_bytes(subject.canonical_bytes(raw))
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()

    def test_missing_unit_and_mutable_binding_are_rejected(self):
        missing = self.source / "units" / "codex-market-nightly-continuity.timer"
        missing.unlink()
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()
        self._units_reset()
        service = self.source / "units" / "codex-market-nightly-continuity.service"
        service.write_text("ExecStart=/opt/codex-oracle/current/run-nightly-continuity\n")
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()

    def _units_reset(self):
        units = self.source / "units"
        for path in units.iterdir():
            path.unlink()
        units.rmdir()
        self._units()

    def test_wrong_runner_binding_and_activation_command_are_rejected(self):
        service = self.source / "units" / "codex-market-ingestion@.service"
        service.write_text("ExecStart=/wrong/run-market-ingestion\n")
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()
        self._units_reset()
        service = self.source / "units" / "codex-market-ingestion@.service"
        service.write_text(
            f"ExecStart={self._runner_target('INGESTION')}\n"
            "ExecStart=/usr/bin/systemctl enable unsafe.service\n"
        )
        with self.assertRaises(subject.AssemblyContractError):
            self.assemble()

    def test_rollback_or_nested_manifest_identity_tamper_is_rejected(self):
        raw = self.assemble()
        raw["rollback"]["deployment_manifest_sha256"] = "0" * 64
        with self.assertRaises(subject.AssemblyContractError):
            subject.validate_assembly(raw)
        raw = self.assemble()
        raw["disabled_installation"]["manifest"]["no_enable"] = False
        with self.assertRaises(installer.InstallerContractError):
            subject.validate_assembly(raw)

    def test_runner_unit_and_release_cross_identity_tamper_are_rejected(self):
        mutations = (
            lambda raw: raw["runners"][0].__setitem__("mode", "0600"),
            lambda raw: raw["runners"][0].__setitem__("target", "/wrong"),
            lambda raw: raw["units"][0].__setitem__("deployment_mode", "0600"),
            lambda raw: raw["releases"][0].__setitem__("manifest_sha256", "0" * 64),
            lambda raw: raw["controller"].__setitem__("config_sha256", "0" * 64),
        )
        for mutation in mutations:
            raw = self.assemble()
            mutation(raw)
            with self.subTest(mutation=mutation), self.assertRaises(
                subject.AssemblyContractError
            ):
                subject.validate_assembly(raw)

    def test_write_once_is_canonical_and_rejects_overwrite(self):
        raw = self.assemble()
        path = self.root / "evidence" / "assembly.json"
        digest = subject.write_assembly_once(path, raw)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(path.read_bytes(), subject.canonical_bytes(raw))
        with self.assertRaises(FileExistsError):
            subject.write_assembly_once(path, raw)

    def test_no_subprocess_or_network_surface_exists(self):
        source = Path(subject.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue({"subprocess", "urllib", "requests", "socket"}.isdisjoint(imported))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue({"run", "Popen", "urlopen", "connect"}.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
