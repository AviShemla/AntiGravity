from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import unittest
import uuid
from pathlib import Path

import oracle_production_application_contract_v2 as subject
import oracle_production_authorization_envelope as envelope
from oracle_research_dataset_application_audit import run_application_audit


HERE = Path(__file__).parent
ROOT = HERE.parent
V1_SHA256 = "127f2e5f11944b6489f28c4e6be1cede9487974e863a2da8b19ff04253716f17"
V1_SOURCE = ROOT / "governance" / "oracle_research_dataset_application_contract.json"
V2_SOURCE = ROOT / "governance" / "oracle_research_dataset_application_contract_v2.json"
V2_SHA256 = "da2a83dd7e83ce5d8e93fe4381b0c53e5f96dc9f09b2c8640ffca70ddc4525a6"


class _Result:
    columns = ("type", "name", "sql")
    rows = ()


class _ReadOnlyClient:
    def __init__(self):
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, args))
        return _Result()


class ContractV2Tests(unittest.TestCase):
    def setUp(self):
        self.root = HERE / "_test_io" / f"v2-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.v1_path = self.root / "v1.json"
        shutil.copy2(V1_SOURCE, self.v1_path)
        self.v1 = subject.load_v1(self.v1_path, V1_SHA256)

    def tearDown(self):
        if self.root.exists():
            for directory, _, files in os.walk(self.root):
                for name in files:
                    try:
                        os.chmod(Path(directory) / name, stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
            shutil.rmtree(self.root)

    def test_known_reviewed_v1_identity_is_exact(self):
        self.assertEqual(hashlib.sha256(V1_SOURCE.read_bytes()).hexdigest(), V1_SHA256)
        self.assertEqual(self.v1["contract_id"], envelope.LEGACY_APPLICATION_CONTRACT_ID)

    def test_builder_is_deterministic_canonical_and_v2_valid(self):
        first, first_hash = subject.build_v2_from_path(
            self.v1_path, expected_v1_sha256=V1_SHA256
        )
        second, second_hash = subject.build_v2_from_path(
            self.v1_path, expected_v1_sha256=V1_SHA256
        )
        self.assertEqual(first, second)
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(first_hash, hashlib.sha256(subject.canonical_bytes(first)).hexdigest())
        subject.validate_v2(first, expected_v1_sha256=V1_SHA256)
        self.assertEqual(
            subject.audit_v2_derivation(
                self.v1, first, expected_v1_sha256=V1_SHA256
            ),
            first_hash,
        )

    def test_all_unrelated_v1_fields_and_artifact_evidence_identities_are_preserved(self):
        v2 = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        changed_top = {
            "contract_id",
            "revision",
            "authorization_binding",
            "adapter_selection",
            "artifacts",
            "execution_readiness",
        }
        for key, value in self.v1.items():
            if key not in changed_top:
                self.assertEqual(v2[key], value, key)
        for key, value in self.v1["artifacts"].items():
            if key != "injected_turso_atomic_adapter":
                self.assertEqual(v2["artifacts"][key], value, key)
        old_readiness = self.v1["execution_readiness"]
        new_readiness = v2["execution_readiness"]
        for key, value in old_readiness.items():
            if key not in {"schema_blockers", "freeze_blockers"}:
                self.assertEqual(new_readiness[key], value, key)
        for key in ("schema_blockers", "freeze_blockers"):
            self.assertEqual(new_readiness[key][: len(old_readiness[key])], old_readiness[key])

    def test_concrete_adapter_identity_is_completely_removed(self):
        old_adapter = self.v1["artifacts"]["injected_turso_atomic_adapter"]
        old_sha = old_adapter["sha256"]
        old_path = old_adapter["path"]
        v2 = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        self.assertNotIn("injected_turso_atomic_adapter", v2["artifacts"])
        adapter = v2["adapter_selection"]
        self.assertEqual(adapter["selection"], "AUTHORIZATION_ENVELOPE")
        self.assertNotIn("sha256", adapter)
        self.assertNotIn("path", adapter)
        encoded = subject.canonical_bytes(v2)
        self.assertNotIn(old_sha.encode("ascii"), encoded)
        self.assertNotIn(old_path.encode("utf-8"), encoded)
        envelope.validate_non_circular_application_contract(v2)

    def test_revision_supersedes_and_blockers_are_exact_and_execution_stays_false(self):
        v2 = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        self.assertEqual(
            v2["revision"],
            {
                "revision": 2,
                "revision_kind": subject.V2_REVISION_KIND,
                "supersedes": {
                    "contract_id": envelope.LEGACY_APPLICATION_CONTRACT_ID,
                    "sha256": V1_SHA256,
                },
            },
        )
        readiness = v2["execution_readiness"]
        self.assertIs(readiness["schema_application_executable"], False)
        self.assertIs(readiness["dataset_freeze_executable"], False)
        for key in ("schema_blockers", "freeze_blockers"):
            self.assertIn(subject.ENVELOPE_BLOCKER, readiness[key])
            self.assertIn(subject.APPROVAL_BLOCKER, readiness[key])

    def test_builder_does_not_mutate_v1_input(self):
        before = copy.deepcopy(self.v1)
        subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        self.assertEqual(self.v1, before)

    def test_wrong_v1_hash_missing_adapter_and_executable_v1_fail(self):
        with self.assertRaises(subject.ContractV2Error):
            subject.load_v1(self.v1_path, "0" * 64)
        missing = copy.deepcopy(self.v1)
        del missing["artifacts"]["injected_turso_atomic_adapter"]
        with self.assertRaises(subject.ContractV2Error):
            subject.build_v2(missing, v1_sha256=V1_SHA256)
        executable = copy.deepcopy(self.v1)
        executable["execution_readiness"]["dataset_freeze_executable"] = True
        with self.assertRaises(subject.ContractV2Error):
            subject.build_v2(executable, v1_sha256=V1_SHA256)

    def test_validator_rejects_adapter_identity_execution_or_blocker_tamper(self):
        attacks = []
        concrete = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        concrete["artifacts"]["injected_turso_atomic_adapter"] = {
            "path": "oracle_research_dataset_turso_adapter.py",
            "sha256": "0" * 64,
        }
        attacks.append(concrete)
        executable = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        executable["execution_readiness"]["schema_application_executable"] = True
        attacks.append(executable)
        missing = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        missing["execution_readiness"]["freeze_blockers"].remove(subject.ENVELOPE_BLOCKER)
        attacks.append(missing)
        supersedes = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        supersedes["revision"]["supersedes"]["sha256"] = "0" * 64
        attacks.append(supersedes)
        for attacked in attacks:
            with self.subTest(attacked=attacked), self.assertRaises(
                (subject.ContractV2Error, envelope.AuthorizationEnvelopeError)
            ):
                subject.validate_v2(attacked, expected_v1_sha256=V1_SHA256)

    def test_derivation_audit_rejects_unrelated_evidence_change(self):
        v2 = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        v2["production_evidence"]["actual_586710_row_digest_readback"][
            "status"
        ] = "FABRICATED"
        with self.assertRaises(subject.ContractV2Error):
            subject.audit_v2_derivation(
                self.v1, v2, expected_v1_sha256=V1_SHA256
            )

    def test_write_once_outputs_canonical_json_and_refuses_overwrite(self):
        v2 = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        target = self.root / "evidence" / "contract-v2.json"
        digest = subject.write_v2_once(
            target, v2, expected_v1_sha256=V1_SHA256
        )
        self.assertEqual(target.read_bytes(), subject.canonical_bytes(v2))
        self.assertEqual(digest, hashlib.sha256(target.read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            subject.write_v2_once(target, v2, expected_v1_sha256=V1_SHA256)

    def test_checked_in_v2_is_exact_and_existing_read_only_auditor_compatible(self):
        self.assertEqual(hashlib.sha256(V2_SOURCE.read_bytes()).hexdigest(), V2_SHA256)
        expected = subject.build_v2(self.v1, v1_sha256=V1_SHA256)
        self.assertEqual(json.loads(V2_SOURCE.read_text(encoding="utf-8")), expected)
        client = _ReadOnlyClient()
        evidence = run_application_audit(
            repository_root=ROOT,
            contract_path=V2_SOURCE,
            expected_contract_sha256=V2_SHA256,
            phase="pre_schema",
            explicit_bindings={},
            client=client,
        )
        self.assertEqual(evidence.contract_id, envelope.APPLICATION_CONTRACT_ID)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(all(sql.startswith("SELECT ") for sql, _ in client.calls))


if __name__ == "__main__":
    unittest.main()
