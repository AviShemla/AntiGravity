from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import stat
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from research_contracts.nightly_continuity_inputs import (
        disabled_only_installer as subject,
    )
except ModuleNotFoundError:  # isolated workspace execution
    from s02_recurring_deployment_impl import disabled_only_installer as subject


class FakeInspector:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    def inspect(self, unit):
        self.calls.append(unit)
        default_file_state = "static" if unit in subject.RECURRING_SERVICES else "disabled"
        return self.overrides.get(
            unit, subject.UnitState("inactive", default_file_state)
        )


class DisabledOnlyInstallerTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).parent / "_test_io"
        self.root = base / f"disabled-installer-{uuid.uuid4().hex}"
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.rollback = self.root / "rollback"
        self.source.mkdir(parents=True)
        self.target.mkdir()
        self.rollback.mkdir()
        self.manifest = self._manifest()
        self.manifest_hash = hashlib.sha256(
            subject.canonical_bytes(self.manifest)
        ).hexdigest()

    def tearDown(self):
        if self.root.exists():
            for directory, _, files in os.walk(self.root):
                for name in files:
                    try:
                        os.chmod(Path(directory) / name, stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
            shutil.rmtree(self.root)

    def _manifest(self):
        specs = {
            "CALENDAR": ("calendar.json", subject.EXACT_ROLE_TARGETS["CALENDAR"]),
            "CONTROLLER_CONFIG": (
                "controller.json",
                subject.EXACT_ROLE_TARGETS["CONTROLLER_CONFIG"],
            ),
        }
        artifacts = []
        for role, (source_name, target) in specs.items():
            source = self.source / source_name
            source.write_bytes((role + "\n").encode())
            artifacts.append(self._artifact(role, source_name, target))
        for role, source_name, release_name, executable in (
            (
                "PREFLIGHT_ENTRYPOINT",
                "preflight.py",
                "market-ingestion-preflight",
                "run-select-only-preflight",
            ),
            (
                "CONTROLLER_ENTRYPOINT",
                "controller.py",
                "nightly-continuity",
                "run-nightly-continuity",
            ),
        ):
            source = self.source / source_name
            source.write_bytes((role + "\n").encode())
            digest = subject.sha256_file(source)
            release_id = "a" * 64 if role == "CONTROLLER_ENTRYPOINT" else digest
            target = f"/opt/codex-oracle/releases/{release_name}-{release_id}/{executable}"
            artifact = self._artifact(role, source_name, target)
            if role == "CONTROLLER_ENTRYPOINT":
                artifact["release_sha256"] = release_id
            artifacts.append(artifact)
        for unit in sorted(subject.RECURRING_UNITS):
            role = f"SYSTEMD_UNIT:{unit}"
            source_name = f"units/{unit}"
            source = self.source / source_name
            source.parent.mkdir(exist_ok=True)
            source.write_bytes((unit + "\n").encode())
            artifacts.append(self._artifact(role, source_name, f"/etc/systemd/system/{unit}"))
        return {
            "contract_id": subject.CONTRACT_ID,
            "deployment_id": "s02-fixture-20260827",
            "apply_mode": "INSTALL_DISABLED_ONLY",
            "no_enable": True,
            "no_start": True,
            "no_restart": True,
            "no_daemon_reload": True,
            "no_turso_writes": True,
            "no_snapshot_lifecycle_changes": True,
            "artifacts": artifacts,
            "required_unit_states": {
                unit: {
                    "active_state": "inactive",
                    "unit_file_state": (
                        "static" if unit in subject.RECURRING_SERVICES else "disabled"
                    ),
                }
                for unit in sorted(subject.ALL_GUARDED_UNITS)
            },
        }

    def _artifact(self, role, source_name, target):
        return {
            "role": role,
            "source": source_name,
            "target": target,
            "sha256": subject.sha256_file(self.source / source_name),
            "mode": f"0{subject.ALLOWED_MODES[role]:o}",
        }

    def _install(self, inspector=None):
        return subject.install_disabled_only(
            self.manifest,
            manifest_sha256=self.manifest_hash,
            source_root=self.source,
            target_root=self.target,
            rollback_root=self.rollback,
            inspector=inspector or FakeInspector(),
            observed_at=datetime(2026, 8, 27, 1, 2, tzinfo=timezone.utc),
            fixture_mode=True,
        )

    def test_valid_manifest_has_exact_role_and_unit_coverage(self):
        subject.validate_deployment_manifest(self.manifest)
        self.assertEqual(
            {item["role"] for item in self.manifest["artifacts"]},
            subject.REQUIRED_ROLES,
        )

    def test_rejects_missing_or_duplicate_role(self):
        for mutation in ("missing", "duplicate"):
            raw = json.loads(json.dumps(self.manifest))
            if mutation == "missing":
                raw["artifacts"].pop()
            else:
                raw["artifacts"].append(dict(raw["artifacts"][0]))
            with self.subTest(mutation=mutation), self.assertRaises(
                subject.InstallerContractError
            ):
                subject.validate_deployment_manifest(raw)

    def test_rejects_every_weakened_safety_flag(self):
        keys = (
            "no_enable",
            "no_start",
            "no_restart",
            "no_daemon_reload",
            "no_turso_writes",
            "no_snapshot_lifecycle_changes",
        )
        for key in keys:
            raw = json.loads(json.dumps(self.manifest))
            raw[key] = False
            with self.subTest(key=key), self.assertRaises(subject.InstallerContractError):
                subject.validate_deployment_manifest(raw)

    def test_rejects_unsafe_unit_state_and_extra_unit(self):
        raw = json.loads(json.dumps(self.manifest))
        raw["required_unit_states"]["ag-sniper.service"]["active_state"] = "active"
        with self.assertRaises(subject.InstallerContractError):
            subject.validate_deployment_manifest(raw)
        raw = json.loads(json.dumps(self.manifest))
        raw["required_unit_states"]["unapproved.service"] = {
            "active_state": "inactive",
            "unit_file_state": "disabled",
        }
        with self.assertRaises(subject.InstallerContractError):
            subject.validate_deployment_manifest(raw)

    def test_rejects_path_traversal_broad_target_and_release_hash_mismatch(self):
        mutations = (
            ("source", "../escape"),
            ("target", "/"),
            (
                "entrypoint",
                "/opt/codex-oracle/releases/market-ingestion-preflight-"
                + "0" * 64
                + "/run-select-only-preflight",
            ),
        )
        for kind, value in mutations:
            raw = json.loads(json.dumps(self.manifest))
            item = next(x for x in raw["artifacts"] if x["role"] == "PREFLIGHT_ENTRYPOINT")
            item["target" if kind in {"target", "entrypoint"} else "source"] = value
            with self.subTest(kind=kind), self.assertRaises(subject.InstallerContractError):
                subject.validate_deployment_manifest(raw)

    def test_in_memory_manifest_hash_must_match(self):
        with self.assertRaises(subject.InstallerContractError):
            subject.install_disabled_only(
                self.manifest,
                manifest_sha256="0" * 64,
                source_root=self.source,
                target_root=self.target,
                rollback_root=self.rollback,
                inspector=FakeInspector(),
                observed_at=datetime.now(timezone.utc),
                fixture_mode=True,
            )

    def test_install_and_independent_audit_are_disabled_only(self):
        inspector = FakeInspector()
        rollback = self._install(inspector)
        self.assertEqual(rollback["status"], "PREPARED_BEFORE_TARGET_MUTATION")
        evidence_dir = self.rollback / self.manifest["deployment_id"]
        self.assertTrue((evidence_dir / "rollback-manifest.json").is_file())
        self.assertTrue((evidence_dir / "installation-completion.json").is_file())
        audit = subject.audit_disabled_installation(
            self.manifest,
            rollback,
            manifest_sha256=self.manifest_hash,
            target_root=self.target,
            inspector=FakeInspector(),
            observed_at=datetime.now(timezone.utc),
            fixture_mode=True,
        )
        self.assertEqual(audit["status"], "OBSERVED_DISABLED_ONLY")
        self.assertEqual(len(audit["artifacts"]), len(subject.REQUIRED_ROLES))
        self.assertEqual(set(inspector.calls), subject.ALL_GUARDED_UNITS)

    def test_existing_target_is_backed_up_before_replacement(self):
        item = next(x for x in self.manifest["artifacts"] if x["role"] == "CALENDAR")
        target = subject._fixture_target(self.target, item["target"])
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old-calendar\n")
        old_hash = subject.sha256_file(target)
        rollback = self._install()
        record = next(x for x in rollback["artifacts"] if x["role"] == "CALENDAR")
        self.assertEqual(record["previous"]["sha256"], old_hash)
        backup = (
            self.rollback
            / self.manifest["deployment_id"]
            / record["previous"]["backup"]
        )
        self.assertEqual(subject.sha256_file(backup), old_hash)

    def test_active_or_enabled_unit_fails_before_target_or_rollback_write(self):
        inspector = FakeInspector(
            {"ag-sniper.service": subject.UnitState("active", "enabled")}
        )
        with self.assertRaises(subject.InstallerContractError):
            self._install(inspector)
        self.assertEqual(list(self.target.rglob("*")), [])
        self.assertEqual(list(self.rollback.rglob("*")), [])

    def test_rollback_manifest_exists_before_first_target_mutation(self):
        original = subject._atomic_copy

        def fail_on_deploy(source, target, mode, *, fixture_mode):
            if str(self.target) in str(target):
                evidence = (
                    self.rollback
                    / self.manifest["deployment_id"]
                    / "rollback-manifest.json"
                )
                self.assertTrue(evidence.is_file())
                raise OSError("injected deployment failure")
            return original(source, target, mode, fixture_mode=fixture_mode)

        with mock.patch.object(subject, "_atomic_copy", side_effect=fail_on_deploy):
            with self.assertRaises(OSError):
                self._install()

    def test_audit_rejects_tampered_target(self):
        rollback = self._install()
        item = next(x for x in self.manifest["artifacts"] if x["role"] == "CALENDAR")
        target = subject._fixture_target(self.target, item["target"])
        target.write_bytes(b"tampered\n")
        with self.assertRaises(subject.InstallerContractError):
            subject.audit_disabled_installation(
                self.manifest,
                rollback,
                manifest_sha256=self.manifest_hash,
                target_root=self.target,
                inspector=FakeInspector(),
                observed_at=datetime.now(timezone.utc),
                fixture_mode=True,
            )

    def test_systemctl_inspector_ast_has_show_only_mutation_free_argv(self):
        tree = ast.parse(Path(subject.__file__).read_text(encoding="utf-8"))
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "SystemctlShowInspector")
        inspect_fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == "inspect")
        constants = {
            x.value for x in ast.walk(inspect_fn) if isinstance(x, ast.Constant) and isinstance(x.value, str)
        }
        self.assertIn("show", constants)
        self.assertTrue({"enable", "start", "restart", "daemon-reload"}.isdisjoint(constants))
        run_calls = [
            x for x in ast.walk(inspect_fn) if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "run"
        ]
        self.assertEqual(len(run_calls), 1)

    def test_systemctl_inspector_accepts_only_missing_allowlisted_recurring_units(self):
        inspector = subject.SystemctlShowInspector()
        missing = mock.Mock(
            returncode=0,
            stdout="UnitFileState=\nActiveState=inactive\nLoadState=not-found\n",
        )
        with mock.patch.object(subject.subprocess, "run", return_value=missing) as run:
            self.assertEqual(
                inspector.inspect("codex-market-nightly-continuity.timer"),
                subject.UnitState("inactive", "", "not-found"),
            )
        argv = run.call_args.args[0]
        self.assertIn("--property=LoadState", argv)
        self.assertNotIn("--value", argv)

    def test_systemctl_inspector_uses_exact_inert_instance_for_templates(self):
        inspector = subject.SystemctlShowInspector()
        missing = mock.Mock(
            returncode=0,
            stdout="LoadState=not-found\nActiveState=inactive\nUnitFileState=\n",
        )
        with mock.patch.object(subject.subprocess, "run", return_value=missing) as run:
            state = inspector.inspect("codex-market-ingestion@.service")
        self.assertEqual(state, subject.UnitState("inactive", "", "not-found"))
        self.assertEqual(
            run.call_args.args[0][2],
            "codex-market-ingestion@codex-install-probe.service",
        )

    def test_require_disabled_units_rejects_missing_legacy_but_accepts_recurring(self):
        overrides = {
            unit: subject.UnitState("inactive", "", "not-found")
            for unit in subject.RECURRING_UNITS
        }
        evidence = subject._require_disabled_units(FakeInspector(overrides))
        self.assertTrue(
            all(
                evidence[unit]["disposition"] == "ALLOWLISTED_RECURRING_NOT_FOUND"
                for unit in subject.RECURRING_UNITS
            )
        )
        overrides["ag-sniper.service"] = subject.UnitState(
            "inactive", "", "not-found"
        )
        with self.assertRaisesRegex(
            subject.InstallerContractError, "legacy safety state"
        ):
            subject._require_disabled_units(FakeInspector(overrides))

    def test_systemctl_inspector_rejects_unsafe_or_malformed_missing_state(self):
        inspector = subject.SystemctlShowInspector()
        for stdout in (
            "LoadState=not-found\nActiveState=inactive\n",
            "LoadState=not-found\nActiveState=inactive\nUnitFileState=\nExtra=x\n",
            "LoadState=not-found\nActiveState=inactive\nActiveState=inactive\nUnitFileState=\n",
            "LoadState:not-found\nActiveState=inactive\nUnitFileState=\n",
        ):
            with self.subTest(stdout=stdout), mock.patch.object(
                subject.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout=stdout),
            ):
                with self.assertRaises(subject.InstallerContractError):
                    inspector.inspect("codex-market-nightly-continuity.timer")

    def test_require_disabled_units_rejects_every_unsafe_recurring_state(self):
        unsafe = (
            subject.UnitState("active", "", "not-found"),
            subject.UnitState("inactive", "enabled", "not-found"),
            subject.UnitState("inactive", "disabled", "not-found"),
            subject.UnitState("inactive", "enabled", "loaded"),
            subject.UnitState("failed", "disabled", "loaded"),
            subject.UnitState("inactive", "masked", "loaded"),
        )
        unit = "codex-market-nightly-continuity.timer"
        for state in unsafe:
            with self.subTest(state=state), self.assertRaises(
                subject.InstallerContractError
            ):
                    subject._require_disabled_units(FakeInspector({unit: state}))

    def test_require_disabled_units_accepts_exact_static_services_only(self):
        service = "codex-market-ingestion@.service"
        evidence = subject._require_disabled_units(FakeInspector())
        self.assertEqual(evidence[service]["disposition"], "INSTALLED_STATIC")
        for state in (
            subject.UnitState("inactive", "disabled", "loaded"),
            subject.UnitState("inactive", "enabled", "loaded"),
            subject.UnitState("active", "static", "loaded"),
        ):
            with self.subTest(state=state), self.assertRaises(
                subject.InstallerContractError
            ):
                subject._require_disabled_units(FakeInspector({service: state}))

    def test_cli_requires_explicit_apply_flag(self):
        manifest_path = self.root / "manifest.json"
        manifest_path.write_bytes(subject.canonical_bytes(self.manifest))
        result = subject.main(
            [
                "--manifest",
                str(manifest_path),
                "--manifest-sha256",
                self.manifest_hash,
                "--source-root",
                str(self.source),
                "--rollback-root",
                str(self.rollback),
            ]
        )
        self.assertEqual(result, 2)
        self.assertEqual(list(self.rollback.rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
