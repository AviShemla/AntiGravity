import unittest

from model_input_writer import ModelInputSnapshotAdmin
from model_lineage import LineageError


class Response:
    status_code = 200

    def __init__(self, affected=1):
        self.affected = affected

    def json(self):
        return {"results": [{"type": "ok", "response": {"result": {"affected_row_count": self.affected}}}]}


class Session:
    def __init__(self, affected=1):
        self.affected = affected
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return Response(self.affected)


class ModelInputWriterTests(unittest.TestCase):
    def admin(self, affected=1):
        self.session = Session(affected)
        return ModelInputSnapshotAdmin(
            "https://example.turso.io/v2/pipeline", "fake", session=self.session
        )

    def test_rejects_only_staging_snapshot(self):
        self.admin().reject_staging_snapshot("s1", "market QA mismatch")
        stmt = self.session.calls[0][1]["json"]["requests"][0]["stmt"]
        self.assertIn("status='REJECTED'", stmt["sql"])
        self.assertIn("status='STAGING'", stmt["sql"])

    def test_requires_exactly_one_row(self):
        with self.assertRaisesRegex(LineageError, "exactly one"):
            self.admin(affected=0).reject_staging_snapshot("s1", "reason")

    def test_validation_requires_staging_and_evidence(self):
        self.admin().validate_staging_snapshot("s1", "all QA gates passed")
        stmt = self.session.calls[0][1]["json"]["requests"][0]["stmt"]
        self.assertIn("status='VALIDATED'", stmt["sql"])
        self.assertIn("status='STAGING'", stmt["sql"])
        with self.assertRaises(LineageError):
            self.admin().validate_staging_snapshot("s1", "")


if __name__ == "__main__":
    unittest.main()
