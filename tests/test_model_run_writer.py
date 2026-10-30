import unittest
from datetime import date, datetime, timezone

from model_input_reader import InputSnapshot, StockUniverseEntry
from model_lineage import AssetClass, LineageError, ModelRun, RunStatus
from model_run_writer import ModelRunWriter
from stock_model_preflight import SnapshotApproval, StockModelPreflightEvidence


def value(raw):
    if raw is None:
        return {"type": "null"}
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
        self.readback_rows = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        request = kwargs["json"]["requests"][0]
        if request["type"] == "batch":
            if self.batch == "http_error":
                return Response(503, {})
            if self.batch == "malformed":
                return Response(200, {"results": []})
            if self.batch == "failure":
                step_results = [{"affected_row_count": 0}, None, None, None, None, {"affected_row_count": 0}]
                step_errors = [None, {"message": "insert rejected"}, None, None, None, None]
            else:
                step_results = [
                    {"affected_row_count": 0},
                    {"affected_row_count": 1},
                    {"affected_row_count": 1},
                    {"affected_row_count": 1},
                    {"affected_row_count": 0},
                    None,
                ]
                step_errors = [None] * 6
            return Response(200, {
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "type": "batch",
                            "result": {
                                "step_results": step_results,
                                "step_errors": step_errors,
                            },
                        },
                    },
                    {"type": "ok", "response": {"type": "close"}},
                ]
            })
        columns = [
            "run_id", "model_name", "asset_class", "prediction_date",
            "source_session_date", "as_of_timestamp_utc", "code_version",
            "config_version", "status", "input_role", "snapshot_id",
            "snapshot_checksum_sha256",
        ]
        rows = [[value(item) for item in row] for row in self.readback_rows] if self.readback else []
        return Response(200, {
            "results": [
                {
                    "type": "ok",
                    "response": {
                        "result": {
                            "cols": [{"name": name} for name in columns],
                            "rows": rows,
                        }
                    },
                },
                {"type": "ok", "response": {"result": {}}},
            ]
        })


class ModelRunWriterTests(unittest.TestCase):
    def setUp(self):
        self.source = date(2026, 8, 24)
        self.prediction = date(2026, 8, 25)
        self.cutoff = datetime(2026, 8, 25, 3, 30, tzinfo=timezone.utc)
        self.created = datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)
        self.market_checksum = "a" * 64
        self.universe_checksum = "b" * 64
        self.run = ModelRun(
            run_id="stock-run-1",
            model_name="STOCK_PYMC",
            asset_class=AssetClass.STOCK,
            prediction_date=self.prediction,
            source_session_date=self.source,
            as_of_timestamp_utc=self.cutoff,
            code_version="code-1",
            config_version="config-1",
            status=RunStatus.STARTED,
        )
        market = InputSnapshot(
            "market-1", "MARKET_FEATURES", self.source,
            datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
            "YAHOO_WITH_TIINGO_FALLBACK", "code-1", 1000, 10,
            self.market_checksum,
        )
        universe = InputSnapshot(
            "universe-1", "STOCK_UNIVERSE", self.source,
            datetime(2026, 8, 25, 3, 0, tzinfo=timezone.utc),
            "PREDICTIVE_SCREENING", "code-1", 1, 1,
            self.universe_checksum,
        )
        approval = SnapshotApproval(
            "approval-1", "APPROVED", "Avi",
            datetime(2026, 8, 25, 3, 10, tzinfo=timezone.utc),
            self.universe_checksum, "PREDICTIVE_SCREENING", "screen-1",
        )
        entry = StockUniverseEntry("AAPL", 1, 0.6, 1, ("MSFT",), (2,))
        self.evidence = StockModelPreflightEvidence(
            self.source, self.prediction, self.cutoff, market, universe,
            approval, "screen-1", (entry,), ("AAPL", "MSFT"), 30,
        )

    def readback_rows(self):
        common = [
            self.run.run_id, self.run.model_name, self.run.asset_class.value,
            self.run.prediction_date.isoformat(), self.run.source_session_date.isoformat(),
            self.run.as_of_timestamp_utc.isoformat(), self.run.code_version,
            self.run.config_version, self.run.status.value,
        ]
        return [
            common + ["MARKET_FEATURES", "market-1", self.market_checksum],
            common + ["STOCK_UNIVERSE", "universe-1", self.universe_checksum],
        ]

    def writer(self, session):
        return ModelRunWriter(
            "https://example.turso.io/v2/pipeline", "fake", session=session
        )

    def test_success_uses_one_conditional_batch_and_exact_readback(self):
        session = Session()
        session.readback_rows = self.readback_rows()
        receipt = self.writer(session).create_bound_stock_run(
            self.run, self.evidence, created_at=self.created
        )
        self.assertEqual(receipt.run_id, self.run.run_id)
        self.assertEqual(len(session.calls), 2)
        request = session.calls[0][1]["json"]["requests"][0]
        self.assertEqual(request["type"], "batch")
        steps = request["batch"]["steps"]
        self.assertEqual(steps[0]["stmt"]["sql"], "BEGIN IMMEDIATE")
        self.assertEqual(steps[4]["stmt"]["sql"], "COMMIT")
        self.assertEqual(steps[5]["stmt"]["sql"], "ROLLBACK")
        self.assertIn("status='VALIDATED'", steps[2]["stmt"]["sql"])
        self.assertIn("model_input_approval_events", steps[3]["stmt"]["sql"])
        self.assertEqual(steps[4]["condition"], {
            "type": "and",
            "conds": [{"type": "ok", "step": index} for index in range(4)],
        })

    def test_http_ambiguity_reconciles_without_retry(self):
        session = Session(batch="http_error")
        session.readback_rows = self.readback_rows()
        receipt = self.writer(session).create_bound_stock_run(
            self.run, self.evidence, created_at=self.created
        )
        self.assertEqual(receipt.market_snapshot_id, "market-1")
        self.assertEqual(len(session.calls), 2)

    def test_failed_batch_without_readback_fails_closed(self):
        session = Session(batch="failure", readback=False)
        with self.assertRaisesRegex(LineageError, "not proven"):
            self.writer(session).create_bound_stock_run(
                self.run, self.evidence, created_at=self.created
            )
        self.assertEqual(len(session.calls), 2)

    def test_malformed_checksum_is_rejected_before_network(self):
        bad_market = InputSnapshot(
            self.evidence.market_snapshot.snapshot_id,
            self.evidence.market_snapshot.dataset_type,
            self.source,
            self.evidence.market_snapshot.available_at_utc,
            self.evidence.market_snapshot.provider,
            self.evidence.market_snapshot.code_version,
            self.evidence.market_snapshot.expected_row_count,
            self.evidence.market_snapshot.expected_ticker_count,
            "not-a-checksum",
        )
        bad = StockModelPreflightEvidence(
            self.source, self.prediction, self.cutoff, bad_market,
            self.evidence.universe_snapshot, self.evidence.universe_approval,
            "screen-1", self.evidence.universe, self.evidence.required_market_tickers, 30,
        )
        session = Session()
        with self.assertRaisesRegex(LineageError, "checksum"):
            self.writer(session).create_bound_stock_run(self.run, bad)
        self.assertEqual(session.calls, [])

    def test_run_preflight_mismatch_is_rejected(self):
        run = ModelRun(
            run_id="stock-run-2",
            model_name="STOCK_PYMC",
            asset_class=AssetClass.STOCK,
            prediction_date=date(2026, 8, 26),
            source_session_date=self.source,
            as_of_timestamp_utc=self.cutoff,
            code_version="code-1",
            config_version="config-1",
            status=RunStatus.STARTED,
        )
        with self.assertRaisesRegex(LineageError, "prediction date"):
            self.writer(Session()).create_bound_stock_run(run, self.evidence)


if __name__ == "__main__":
    unittest.main()
