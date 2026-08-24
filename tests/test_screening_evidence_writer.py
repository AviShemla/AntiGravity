import unittest

from screening_evidence_writer import ScreeningEvidenceWriter


class Response:
    status_code = 200

    def __init__(self, request_count, *, select=False, count=1, affected=1):
        self.request_count = request_count
        self.select = select
        self.count = count
        self.affected = affected

    def json(self):
        if self.select:
            return {
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "result": {
                                "cols": [{"name": "n"}],
                                "rows": [[{"type": "integer", "value": str(self.count)}]],
                            }
                        },
                    },
                    {"type": "ok", "response": {"result": {}}},
                ]
            }
        results = []
        for index in range(self.request_count):
            result = {"affected_row_count": self.affected if index == 1 else 0}
            results.append({"type": "ok", "response": {"result": result}})
        return {"results": results}


class Session:
    def __init__(self):
        self.calls = []
        self.select_count = 1

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        requests = kwargs["json"]["requests"]
        first_sql = requests[0]["stmt"]["sql"].lstrip().upper()
        return Response(
            len(requests),
            select=first_sql.startswith("SELECT"),
            count=self.select_count,
        )


class ScreeningEvidenceWriterTests(unittest.TestCase):
    def writer(self):
        self.session = Session()
        return ScreeningEvidenceWriter(
            "https://example.turso.io/v2/pipeline", "fake", session=self.session
        )

    def test_start_run_is_insert_only_and_transactional(self):
        self.writer().start_run(
            screening_run_id="r1",
            market_snapshot_id="m1",
            source_session_date="2026-08-20",
            cutoff_utc="2026-08-21T00:00:00+00:00",
            code_version="test",
            config_json="{}",
        )
        requests = self.session.calls[0][1]["json"]["requests"]
        self.assertEqual(requests[0]["stmt"]["sql"], "BEGIN")
        self.assertIn("INSERT INTO predictive_screening_runs", requests[1]["stmt"]["sql"])
        self.assertEqual(requests[-2]["stmt"]["sql"], "COMMIT")

    def test_finish_requires_exact_result_count(self):
        writer = self.writer()
        self.session.select_count = 2
        with self.assertRaisesRegex(Exception, "count"):
            writer.finish_run("r1", expected_tickers=1, evidence="checked")

    def test_finish_validates_only_running_run(self):
        writer = self.writer()
        writer.finish_run("r1", expected_tickers=1, evidence="checked")
        update_call = self.session.calls[1][1]["json"]["requests"][1]["stmt"]
        self.assertIn("status='VALIDATED'", update_call["sql"])
        self.assertIn("status='RUNNING'", update_call["sql"])

    def test_rejection_is_evidence_only_insert(self):
        self.writer().record_rejection("r1", "adm", "no admissible specification")
        stmt = self.session.calls[0][1]["json"]["requests"][1]["stmt"]
        self.assertIn("predictive_screening_results", stmt["sql"])
        self.assertIn("eligible", stmt["sql"])
        self.assertEqual(stmt["args"][1]["value"], "ADM")


if __name__ == "__main__":
    unittest.main()
