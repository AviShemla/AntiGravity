from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SUBJECT = ROOT / "scripts/oracle_production_schema_freeze.py"
if not SUBJECT.exists():
    SUBJECT = Path(__file__).with_name("oracle_production_schema_freeze.py")


class ProductionLauncherStaticTests(unittest.TestCase):
    def setUp(self):
        self.text = SUBJECT.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def test_exact_approved_hashes_are_pinned(self):
        for value in (
            "665fe03c889a96ec095e0b51ff69697b94e84de314d43af6a7c2fcfa880a796e",
            "d21aa91b356666c6509e234a74f3041130fc1e4ae62455086aa86b2b18e6e01e",
            "8e6a6f411803857950a6792b3729abedf41ae5026ec358211079f12004a63350",
            "oracle-research-20260825-60f2d9d6f68d7d7d9930abce00d4ba41",
        ):
            self.assertIn(value, self.text)

    def test_no_forbidden_operational_surface(self):
        forbidden_calls = {"remove", "unlink", "rmtree", "system", "popen", "run", "check_call"}
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))
        sql_literals = [
            node.value
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        sql_text = "\n".join(value for value in sql_literals if "SELECT " in value.upper())
        for forbidden in ("DROP ", "DELETE ", "TRUNCATE "):
            self.assertNotIn(forbidden, sql_text.upper())

    def test_transport_does_not_log_secrets_or_response_bodies(self):
        transport = next(node for node in self.tree.body if isinstance(node, ast.ClassDef) and node.name == "AtomicPipelineTransport")
        calls = [node for node in ast.walk(transport) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(node.func, ast.Name) and node.func.id == "print" for node in calls))


try:
    from scripts import oracle_production_schema_freeze as runtime_subject
    from turso_read_pipeline import PipelineResult
except ModuleNotFoundError:
    runtime_subject = None


@unittest.skipIf(runtime_subject is None, "canonical repository modules unavailable")
class ProductionLauncherBehaviorTests(unittest.TestCase):
    class Reader:
        def __init__(self, rows_by_call):
            self.rows_by_call = list(rows_by_call)

        def execute(self, query, args):
            return PipelineResult(columns=("value",), rows=self.rows_by_call.pop(0))

    def test_pre_schema_requires_zero_objects_and_zero_ledger_rows(self):
        with mock.patch.object(runtime_subject, "verify_envelope_approval") as gate:
            evidence = runtime_subject.verify_pre_schema(
                Path("."), self.Reader([(), ()]), Path("authorization.json")
            )
        gate.assert_called_once()
        self.assertEqual(evidence, {"schema_object_count": 0, "migration_event_count": 0})

        for rows in ((("existing",),), ((), (("existing",),))):
            supplied = [rows[0], ()] if len(rows) == 1 else list(rows)
            with self.subTest(rows=rows), mock.patch.object(
                runtime_subject, "verify_envelope_approval"
            ), self.assertRaises(runtime_subject.LineageError):
                runtime_subject.verify_pre_schema(
                    Path("."), self.Reader(supplied), Path("authorization.json")
                )


if __name__ == "__main__":
    unittest.main()
