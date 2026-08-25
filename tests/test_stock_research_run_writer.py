import unittest
from datetime import date, datetime, timezone

from model_input_reader import InputSnapshot, StockUniverseEntry
from model_lineage import (
    AssetClass,
    LineageError,
    ModelRun,
    ModelScorecard,
    Recommendation,
    RunStatus,
)
from stock_model_preflight import SnapshotApproval, StockModelPreflightEvidence
from stock_research_run_writer import StockResearchRunWriter


def encoded(raw):
    if raw is None:
        return {"type": "null"}
    if isinstance(raw, int):
        return {"type": "integer", "value": str(raw)}
    return {"type": "text", "value": str(raw)}


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def __init__(self, *, batch="success", readback=True):
        self.batch = batch
        self.readback = readback
        self.calls = []
        self.scorecard_count = 1

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        request = kwargs["json"]["requests"][0]
        if request["type"] == "batch":
            steps = request["batch"]["steps"]
            if self.batch == "http_error":
                return Response(503, {})
            results = [{"affected_row_count": 1} for _ in steps]
            errors = [None] * len(steps)
            results[-1] = None
            if self.batch == "failure":
                results[4] = None
                errors[4] = {"message": "scorecard rejected"}
                for index in range(5, len(steps) - 1):
                    results[index] = None
                results[-1] = {"affected_row_count": 0}
            return Response(200, {
                "results": [{
                    "type": "ok",
                    "response": {
                        "type": "batch",
                        "result": {"step_results": results, "step_errors": errors},
                    },
                }, {"type": "ok", "response": {"type": "close"}}]
            })
        columns = [
            "run_id", "model_name", "asset_class", "prediction_date",
            "source_session_date", "as_of_timestamp_utc", "code_version",
            "config_version", "status", "input_count", "scorecard_count",
            "frozen_count",
        ]
        rows = []
        if self.readback:
            rows = [[encoded(value) for value in [
                "run-1", "STOCK_PYMC_RESEARCH", "STOCK", "2026-08-25",
                "2026-08-24", "2026-08-25T03:30:00+00:00", "code-1",
                "config-1", "COMPLETED", 2, self.scorecard_count,
                self.scorecard_count,
            ]]]
        return Response(200, {
            "results": [{
                "type": "ok",
                "response": {
                    "result": {
                        "cols": [{"name": name} for name in columns],
                        "rows": rows,
                    }
                },
            }, {"type": "ok", "response": {"result": {}}}]
        })


class StockResearchRunWriterTests(unittest.TestCase):
    def setUp(self):
        source = date(2026, 8, 24)
        prediction = date(2026, 8, 25)
        cutoff = datetime(2026, 8, 25, 3, 30, tzinfo=timezone.utc)
        self.run = ModelRun(
            "run-1", "STOCK_PYMC_RESEARCH", AssetClass.STOCK,
            prediction, source, cutoff, "code-1", "config-1", RunStatus.STARTED,
        )
        market = InputSnapshot(
            "market-1", "MARKET_FEATURES", source,
            datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
            "YAHOO", "code-1", 10, 2, "a" * 64,
        )
        universe = InputSnapshot(
            "universe-1", "STOCK_UNIVERSE", source,
            datetime(2026, 8, 25, 3, 0, tzinfo=timezone.utc),
            "SCREENING", "code-1", 1, 1, "b" * 64,
        )
        approval = SnapshotApproval(
            "approval-1", "APPROVED", "Avi",
            datetime(2026, 8, 25, 3, 10, tzinfo=timezone.utc),
            "b" * 64, "PREDICTIVE_SCREENING", "screen-1",
        )
        entry = StockUniverseEntry("AAA", 1, 0.61, 1, ("BBB",), (2,))
        self.evidence = StockModelPreflightEvidence(
            source, prediction, cutoff, market, universe, approval, "screen-1",
            (entry,), ("AAA", "BBB"), 30,
        )
        self.card = ModelScorecard(
            "run-1", "AAA", "Neutral", 0.72, 0.04, 0.55, 0.84,
            1.25, 0.30, 2.50, Recommendation.NO_TRADE, 0.0,
            "RESEARCH_ONLY;PROMOTION_DISABLED",
        )

    @staticmethod
    def writer(session):
        return StockResearchRunWriter(
            "https://example.turso.io/v2/pipeline", "fake", session=session
        )

    def test_one_batch_contains_started_evidence_completed_commit_and_rollback(self):
        session = Session()
        receipt = self.writer(session).persist_completed_stock_run(
            self.run, self.evidence, (self.card,)
        )
        self.assertEqual(receipt.status, RunStatus.COMPLETED)
        steps = session.calls[0][1]["json"]["requests"][0]["batch"]["steps"]
        sql = [step["stmt"]["sql"] for step in steps]
        self.assertEqual(sql[0], "BEGIN IMMEDIATE")
        self.assertIn("INSERT INTO model_runs", sql[1])
        self.assertIn("model_run_inputs", sql[2])
        self.assertIn("model_run_inputs", sql[3])
        self.assertIn("model_scorecards", sql[4])
        self.assertIn("SET status='COMPLETED'", sql[5])
        self.assertEqual(sql[-2], "COMMIT")
        self.assertEqual(sql[-1], "ROLLBACK")

    def test_non_no_trade_or_allocation_is_rejected_before_network(self):
        for recommendation, allocation in (
            (Recommendation.BUY, 0.0),
            (Recommendation.NO_TRADE, 0.1),
        ):
            bad = ModelScorecard(
                **{
                    **self.card.__dict__,
                    "recommendation": recommendation,
                    "proposed_allocation": allocation,
                }
            )
            session = Session()
            with self.assertRaises(LineageError):
                self.writer(session).persist_completed_stock_run(
                    self.run, self.evidence, (bad,)
                )
            self.assertEqual(session.calls, [])

    def test_failed_batch_without_completed_readback_fails_closed(self):
        session = Session(batch="failure", readback=False)
        with self.assertRaisesRegex(LineageError, "not proven"):
            self.writer(session).persist_completed_stock_run(
                self.run, self.evidence, (self.card,)
            )
        self.assertEqual(len(session.calls), 2)

    def test_http_ambiguity_accepts_only_exact_completed_readback(self):
        session = Session(batch="http_error")
        receipt = self.writer(session).persist_completed_stock_run(
            self.run, self.evidence, (self.card,)
        )
        self.assertEqual(receipt.scorecard_count, 1)
        session = Session(batch="http_error")
        session.scorecard_count = 0
        with self.assertRaisesRegex(LineageError, "reconciliation"):
            self.writer(session).persist_completed_stock_run(
                self.run, self.evidence, (self.card,)
            )


if __name__ == "__main__":
    unittest.main()
