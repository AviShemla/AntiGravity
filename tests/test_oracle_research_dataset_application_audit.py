import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from model_lineage import LineageError
from oracle_research_dataset_application_audit import run_application_audit


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Result:
    columns: list[str]
    rows: list[list[object]]


class Client:
    def __init__(self):
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, args))
        return Result(["value"], [[args[0] if args else 1]])


class ApplicationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "artifact.sql").write_text("SELECT 1\n", encoding="utf-8")
        artifact_hash = hashlib.sha256((self.root / "artifact.sql").read_bytes()).hexdigest()
        self.contract = {
            "contract_id": "contract-v1",
            "contract_status": "REVIEW_ONLY",
            "target_database_id": "research-db",
            "source_git_commit": "a" * 40,
            "artifacts": {"schema": {"path": "artifact.sql", "sha256": artifact_hash}},
            "read_only_audits": {
                "pre_schema": [
                    {"id": "literal", "sql": "SELECT ? AS value", "bindings": [7], "expected": "seven"}
                ],
                "post_schema": [
                    {"id": "objects", "sql": "SELECT 1 AS value", "expected": "one"}
                ],
                "pre_freeze": [
                    {"id": "snapshot", "sql": "SELECT ? AS value", "bindings": ["EXPECTED_ID"], "expected": "id"}
                ],
                "post_freeze": [
                    {"id": "version", "sql": "SELECT ? AS value", "bindings": ["EXPECTED_VERSION"], "expected": "version"}
                ],
            },
        }
        self.contract_path = self.root / "contract.json"
        self._write_contract()

    def tearDown(self):
        self.temp.cleanup()

    def _write_contract(self):
        self.contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
        self.contract_hash = hashlib.sha256(self.contract_path.read_bytes()).hexdigest()

    def _run(self, phase="pre_freeze", bindings=None, client=None):
        return run_application_audit(
            repository_root=self.root,
            contract_path=self.contract_path,
            expected_contract_sha256=self.contract_hash,
            phase=phase,
            explicit_bindings={"EXPECTED_ID": "snapshot-1"} if bindings is None else bindings,
            client=client or Client(),
        )

    def test_executes_declared_select_with_positional_explicit_binding(self):
        client = Client()
        result = self._run(client=client)
        self.assertEqual(client.calls, [("SELECT ? AS value", ["snapshot-1"])])
        self.assertEqual(result.queries[0].rows, (("snapshot-1",),))
        self.assertEqual(result.queries[0].row_count, 1)
        self.assertEqual(result.contract_sha256, self.contract_hash)
        self.assertEqual(result.artifacts[0].actual_sha256, result.artifacts[0].expected_sha256)

    def test_evidence_is_deterministic(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first, second)
        self.assertEqual(first.evidence_sha256, second.evidence_sha256)

    def test_wrong_contract_or_artifact_hash_stops_before_client_call(self):
        client = Client()
        with self.assertRaisesRegex(LineageError, "contract hash"):
            run_application_audit(
                repository_root=self.root,
                contract_path=self.contract_path,
                expected_contract_sha256="0" * 64,
                phase="pre_freeze",
                explicit_bindings={"EXPECTED_ID": "snapshot-1"},
                client=client,
            )
        self.assertEqual(client.calls, [])
        self.contract["artifacts"]["schema"]["sha256"] = "0" * 64
        self._write_contract()
        with self.assertRaisesRegex(LineageError, "Artifact schema hash"):
            self._run(client=client)
        self.assertEqual(client.calls, [])

    def test_non_select_and_multi_statement_sql_are_rejected_before_execution(self):
        for sql in ("DELETE FROM evidence", "SELECT 1; DELETE FROM evidence", "SELECT 1 -- comment"):
            with self.subTest(sql=sql):
                self.contract["read_only_audits"]["pre_freeze"][0]["sql"] = sql
                self.contract["read_only_audits"]["pre_freeze"][0]["bindings"] = []
                self._write_contract()
                client = Client()
                with self.assertRaises(LineageError):
                    self._run(bindings={}, client=client)
                self.assertEqual(client.calls, [])

    def test_missing_or_extra_explicit_binding_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "missing explicit binding"):
            self._run(bindings={})
        with self.assertRaisesRegex(LineageError, "Undeclared explicit bindings"):
            self._run(bindings={"EXPECTED_ID": "snapshot-1", "EXTRA": "no"})

    def test_literal_contract_binding_cannot_be_overridden(self):
        client = Client()
        result = self._run(phase="pre_schema", bindings={}, client=client)
        self.assertEqual(client.calls, [("SELECT ? AS value", [7])])
        self.assertEqual(result.queries[0].rows, ((7,),))
        with self.assertRaisesRegex(LineageError, "Undeclared explicit bindings"):
            self._run(phase="pre_schema", bindings={"7": 8})

    def test_placeholder_count_and_malformed_result_fail_closed(self):
        self.contract["read_only_audits"]["pre_freeze"][0]["sql"] = "SELECT 1 AS value"
        self._write_contract()
        with self.assertRaisesRegex(LineageError, "placeholder count"):
            self._run()

        class BadClient:
            def execute(self, sql, args):
                return Result(["a", "b"], [[1]])

        self.contract["read_only_audits"]["pre_freeze"][0]["sql"] = "SELECT ? AS value"
        self._write_contract()
        with self.assertRaisesRegex(LineageError, "malformed row"):
            self._run(client=BadClient())

    def test_unknown_phase_and_path_escape_fail_closed(self):
        with self.assertRaisesRegex(LineageError, "Unknown"):
            self._run(phase="anything")
        self.contract["artifacts"]["schema"]["path"] = "../outside.sql"
        self._write_contract()
        with self.assertRaisesRegex(LineageError, "escapes"):
            self._run()

    def test_current_contract_runs_pre_schema_through_injected_read_only_client(self):
        contract_path = ROOT / "governance" / "oracle_research_dataset_application_contract.json"
        client = Client()
        result = run_application_audit(
            repository_root=ROOT,
            contract_path=contract_path,
            expected_contract_sha256=hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            phase="pre_schema",
            explicit_bindings={},
            client=client,
        )
        self.assertEqual(result.contract_id, "oracle-research-dataset-application-freeze-v1")
        self.assertEqual(len(result.artifacts), 4)
        self.assertEqual(len(result.queries), 2)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(all(sql.startswith("SELECT ") for sql, _ in client.calls))


if __name__ == "__main__":
    unittest.main()
