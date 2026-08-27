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

import oracle_production_authorization_envelope as subject


HERE = Path(__file__).parent


class AuthorizationEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.root = HERE / "_test_io" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.application_path = self.root / "application-contract.json"
        self.application = {
            "contract_id": subject.APPLICATION_CONTRACT_ID,
            "target_database_id": subject.TARGET_DATABASE_ID,
            "authorization_binding": dict(subject.AUTHORIZATION_BINDING),
            "artifacts": {"schema_migration": {"sha256": "1" * 64}},
            "adapter_selection": dict(subject.ADAPTER_SELECTION),
        }
        self.application_path.write_bytes(subject.canonical_bytes(self.application))
        self.release_root = self.root / "releases"
        self.release_root.mkdir()
        self.release_id = self._release()
        self.envelope = subject.build_envelope(
            application_contract_path=self.application_path,
            adapter_release_root=self.release_root,
            adapter_release_manifest_sha256=self.release_id,
            content_audit_evidence_sha256="b" * 64,
        )
        self.envelope_sha = subject.canonical_sha256(self.envelope)
        self.authorization = {
            "contract_id": subject.AUTHORIZATION_CONTRACT_ID,
            "authorization_id": "auth-envelope-fixture-1",
            "envelope_sha256": self.envelope_sha,
            "authorized_by": "avi-fixture",
            "authorized_at_utc": "2026-08-27T01:00:00Z",
            "expires_at_utc": "2026-08-27T02:00:00Z",
            "schema_application_gate_satisfied": True,
            "schema_application_approval_id": "schema-approval-1",
            "dataset_freeze_gate_satisfied": True,
            "dataset_freeze_approval_id": "freeze-approval-1",
            "authorized_dataset_version_id": "dataset-version-1",
            "authorized_freeze_event_id": "freeze-approval-1",
            **{key: 0 for key in subject.ZERO_OUTPUT_FIELDS},
        }

    def tearDown(self):
        if self.root.exists():
            for directory, _, files in os.walk(self.root):
                for name in files:
                    try:
                        os.chmod(Path(directory) / name, stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
            shutil.rmtree(self.root)

    def _release(self):
        staging = self.release_root / "staging"
        staging.mkdir()
        files = {
            subject.ADAPTER_ENTRYPOINT: b"# adapter imports gate; no concrete contract hash\n",
            "authorization_envelope.py": Path(subject.__file__).read_bytes(),
        }
        rows = []
        for relative, content in sorted(files.items()):
            (staging / relative).write_bytes(content)
            rows.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "mode": "0600",
                }
            )
        manifest = {
            "contract_id": subject.RELEASE_CONTRACT_ID,
            "release_kind": subject.RELEASE_KIND,
            "files": rows,
        }
        encoded = subject.canonical_bytes(manifest)
        release_id = hashlib.sha256(encoded).hexdigest()
        (staging / "release-manifest.json").write_bytes(encoded)
        staging.rename(self.release_root / f"{subject.RELEASE_KIND}-{release_id}")
        return release_id

    def validate(self, operation="stage:dataset-version-1"):
        return subject.validate_runtime_authorization(
            self.envelope,
            self.authorization,
            expected_envelope_sha256=self.envelope_sha,
            application_contract_path=self.application_path,
            adapter_release_root=self.release_root,
            operation_id=operation,
            observed_at_utc=datetime(2026, 8, 27, 1, 30, tzinfo=timezone.utc),
        )

    def test_valid_non_circular_envelope_and_both_exact_operations(self):
        self.assertEqual(self.validate(), self.envelope_sha)
        self.assertEqual(
            self.validate("freeze:dataset-version-1:freeze-approval-1"),
            self.envelope_sha,
        )
        self.assertNotIn("envelope_sha256", self.application)
        self.assertNotIn("injected_turso_atomic_adapter", self.application["artifacts"])

    def test_current_circular_contract_shape_is_fail_closed(self):
        current = {
            "contract_id": subject.APPLICATION_CONTRACT_ID,
            "target_database_id": subject.TARGET_DATABASE_ID,
            "artifacts": {
                "injected_turso_atomic_adapter": {
                    "sha256": "3" * 64,
                    "path": subject.ADAPTER_ENTRYPOINT,
                }
            },
        }
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            subject.validate_non_circular_application_contract(current)
        current["authorization_binding"] = dict(subject.AUTHORIZATION_BINDING)
        current["adapter_selection"] = dict(subject.ADAPTER_SELECTION)
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            subject.validate_non_circular_application_contract(current)

    def test_adapter_and_contract_are_leaf_nodes_not_mutual_hash_pins(self):
        application_text = self.application_path.read_text()
        adapter = (
            self.release_root
            / f"{subject.RELEASE_KIND}-{self.release_id}"
            / subject.ADAPTER_ENTRYPOINT
        ).read_text()
        self.assertNotIn(self.release_id, application_text)
        self.assertNotIn(subject.sha256_file(self.application_path), adapter)
        self.assertEqual(
            self.envelope["application_contract"]["sha256"],
            subject.sha256_file(self.application_path),
        )
        self.assertEqual(
            self.envelope["adapter_release"]["manifest_sha256"], self.release_id
        )

    def test_covert_concrete_leaf_pins_are_rejected(self):
        attacked_application = dict(self.application)
        attacked_application["covert_adapter_release_pin"] = self.release_id
        self.application_path.write_bytes(subject.canonical_bytes(attacked_application))
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            subject.build_envelope(
                application_contract_path=self.application_path,
                adapter_release_root=self.release_root,
                adapter_release_manifest_sha256=self.release_id,
                content_audit_evidence_sha256="b" * 64,
            )

        self.application_path.write_bytes(subject.canonical_bytes(self.application))
        alternate_root = self.root / "alternate-releases"
        alternate_root.mkdir()
        staging = alternate_root / "staging"
        staging.mkdir()
        app_hash = subject.sha256_file(self.application_path)
        files = {
            subject.ADAPTER_ENTRYPOINT: (
                f'_CONTRACT_SHA256 = "{app_hash}"\n'.encode("ascii")
            ),
            "authorization_envelope.py": Path(subject.__file__).read_bytes(),
        }
        rows = []
        for relative, content in sorted(files.items()):
            (staging / relative).write_bytes(content)
            rows.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "mode": "0600",
                }
            )
        manifest = {
            "contract_id": subject.RELEASE_CONTRACT_ID,
            "release_kind": subject.RELEASE_KIND,
            "files": rows,
        }
        encoded = subject.canonical_bytes(manifest)
        release_id = hashlib.sha256(encoded).hexdigest()
        (staging / "release-manifest.json").write_bytes(encoded)
        staging.rename(alternate_root / f"{subject.RELEASE_KIND}-{release_id}")
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            subject.build_envelope(
                application_contract_path=self.application_path,
                adapter_release_root=alternate_root,
                adapter_release_manifest_sha256=release_id,
                content_audit_evidence_sha256="b" * 64,
            )

    def test_external_expected_envelope_hash_is_mandatory(self):
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            subject.validate_runtime_authorization(
                self.envelope,
                self.authorization,
                expected_envelope_sha256="0" * 64,
                application_contract_path=self.application_path,
                adapter_release_root=self.release_root,
                operation_id="stage:dataset-version-1",
                observed_at_utc=datetime(2026, 8, 27, 1, 30, tzinfo=timezone.utc),
            )
        attacked = json.loads(json.dumps(self.envelope))
        attacked["content_audit_evidence_sha256"] = "c" * 64
        attacked_auth = dict(self.authorization)
        attacked_auth["envelope_sha256"] = subject.canonical_sha256(attacked)
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            subject.validate_runtime_authorization(
                attacked,
                attacked_auth,
                expected_envelope_sha256=self.envelope_sha,
                application_contract_path=self.application_path,
                adapter_release_root=self.release_root,
                operation_id="stage:dataset-version-1",
                observed_at_utc=datetime(2026, 8, 27, 1, 30, tzinfo=timezone.utc),
            )

    def test_contract_and_adapter_byte_tamper_fail(self):
        self.application["new"] = "tamper"
        self.application_path.write_bytes(subject.canonical_bytes(self.application))
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            self.validate()
        self.application.pop("new")
        self.application_path.write_bytes(subject.canonical_bytes(self.application))
        adapter = (
            self.release_root
            / f"{subject.RELEASE_KIND}-{self.release_id}"
            / subject.ADAPTER_ENTRYPOINT
        )
        adapter.write_bytes(b"tamper\n")
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            self.validate()

    def test_release_manifest_and_unmanifested_file_tamper_fail(self):
        release = self.release_root / f"{subject.RELEASE_KIND}-{self.release_id}"
        (release / "unexpected.py").write_text("# injected\n")
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            self.validate()

    def test_runtime_authorization_exact_keys_expiry_approvals_and_zeros(self):
        attacks = []
        extra = dict(self.authorization)
        extra["unexpected"] = True
        attacks.append(extra)
        same = dict(self.authorization)
        same["schema_application_approval_id"] = "freeze-approval-1"
        attacks.append(same)
        expired = dict(self.authorization)
        expired["expires_at_utc"] = "2026-08-27T01:20:00Z"
        attacks.append(expired)
        nonzero = dict(self.authorization)
        nonzero["order_count"] = 1
        attacks.append(nonzero)
        wrong_envelope = dict(self.authorization)
        wrong_envelope["envelope_sha256"] = "0" * 64
        attacks.append(wrong_envelope)
        for authorization in attacks:
            with self.subTest(authorization=authorization), self.assertRaises(
                subject.AuthorizationEnvelopeError
            ):
                subject.validate_runtime_authorization(
                    self.envelope,
                    authorization,
                    expected_envelope_sha256=self.envelope_sha,
                    application_contract_path=self.application_path,
                    adapter_release_root=self.release_root,
                    operation_id="stage:dataset-version-1",
                    observed_at_utc=datetime(2026, 8, 27, 1, 30, tzinfo=timezone.utc),
                )

    def test_operation_scope_is_exact(self):
        for operation in (
            "stage:other",
            "freeze:dataset-version-1:other",
            "schema:dataset-version-1",
        ):
            with self.subTest(operation=operation), self.assertRaises(
                subject.AuthorizationEnvelopeError
            ):
                self.validate(operation)

    def test_path_traversal_and_symlink_are_rejected(self):
        release = self.release_root / f"{subject.RELEASE_KIND}-{self.release_id}"
        manifest_path = release / "release-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["path"] = "../escape.py"
        encoded = subject.canonical_bytes(manifest)
        manifest_path.write_bytes(encoded)
        with self.assertRaises(subject.AuthorizationEnvelopeError):
            subject.verify_adapter_release(self.release_root, self.release_id)

    def test_envelope_structure_cross_fields_are_exact(self):
        attacks = []
        extra = json.loads(json.dumps(self.envelope))
        extra["extra"] = True
        attacks.append(extra)
        outputs = json.loads(json.dumps(self.envelope))
        outputs["forbidden_output_counts"]["order_count"] = 1
        attacks.append(outputs)
        operations = json.loads(json.dumps(self.envelope))
        operations["allowed_operations"].append("TRADE")
        attacks.append(operations)
        for envelope in attacks:
            with self.subTest(envelope=envelope), self.assertRaises(
                subject.AuthorizationEnvelopeError
            ):
                subject.validate_envelope_structure(envelope)

    def test_module_has_no_transport_subprocess_environment_or_write_surface(self):
        tree = ast.parse(Path(subject.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue(
            {"subprocess", "socket", "urllib", "requests", "httpx"}.isdisjoint(imported)
        )
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            {
                "run",
                "Popen",
                "urlopen",
                "connect",
                "getenv",
                "write_bytes",
                "write_text",
                "unlink",
            }.isdisjoint(calls)
        )
        os_mutations = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and node.func.attr in {"replace", "rename", "remove", "unlink"}
        ]
        self.assertEqual(os_mutations, [])


if __name__ == "__main__":
    unittest.main()
