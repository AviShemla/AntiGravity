import unittest
from datetime import date

import pandas as pd

from market_eod_revision_writer import (
    prepare_revision_rows,
    stage_ingestion_run,
    stage_revision_rows,
)
from turso_read_pipeline import PipelineResult


def evidence():
    return pd.DataFrame({
        "Ticker": ["AAPL"], "Date": ["2026-08-21"],
        "Raw Open": [100.0], "Raw High": [103.0], "Raw Low": [99.0],
        "Raw Close": [102.0], "Raw Volume": [1000.0],
        "Adjusted Open": [50.0], "Adjusted High": [51.5],
        "Adjusted Low": [49.5], "Adjusted Close": [51.0],
        "Adjusted Volume": [2000.0], "Dividends": [0.0],
        "Split Factor": [2.0],
    })


class Reader:
    def __init__(self, responses):
        self.responses = iter(responses)

    def execute(self, query, args):
        response = next(self.responses)
        if isinstance(response, int):
            return PipelineResult(["n"], [[response]])
        return PipelineResult(
            ["ticker", "date", "source_value_sha256"],
            response,
        )


class Response:
    status_code = 200

    def __init__(self, count):
        self.count = count

    def json(self):
        return {"results": [{"type": "ok"} for _ in range(self.count)]}


class Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(len(kwargs["json"]["requests"]) - 1)


class MarketEodRevisionWriterTests(unittest.TestCase):
    def test_stages_exact_idempotent_parent_run_metadata(self):
        session = Session()
        code_hash = "a" * 64
        stored = [[
            "TIINGO_EOD", "DAILY_DELTA", "2026-08-21",
            "2026-08-22T01:00:00+00:00", code_hash, 471, "STAGING",
        ]]
        stage_ingestion_run(
            session=session, reader=Reader([stored]),
            endpoint="https://example.test/v2/pipeline", token="secret-token-value",
            run_id="tiingo-2026-08-21-run-001", provider="TIINGO_EOD",
            ingestion_mode="DAILY_DELTA", source_session=date(2026, 8, 21),
            available_at_utc="2026-08-22T01:00:00+00:00",
            code_version_sha256=code_hash, expected_ticker_count=471,
        )
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("secret-token-value", str(session.calls[0][1]["json"]))

    def test_rejects_reused_parent_run_with_different_metadata(self):
        code_hash = "a" * 64
        conflicting = [[
            "YAHOO_FINANCE", "DAILY_DELTA", "2026-08-21",
            "2026-08-22T01:00:00+00:00", code_hash, 471, "STAGING",
        ]]
        with self.assertRaisesRegex(RuntimeError, "metadata does not match"):
            stage_ingestion_run(
                session=Session(), reader=Reader([conflicting]),
                endpoint="https://example.test/v2/pipeline",
                token="secret-token-value",
                run_id="tiingo-2026-08-21-run-001", provider="TIINGO_EOD",
                ingestion_mode="DAILY_DELTA", source_session=date(2026, 8, 21),
                available_at_utc="2026-08-22T01:00:00+00:00",
                code_version_sha256=code_hash, expected_ticker_count=471,
            )

    def test_prepares_deterministic_complete_evidence(self):
        args = dict(
            run_id="alpaca-2026-08-21-run-001",
            provider="ALPACA_MARKET_DATA",
            source_session=date(2026, 8, 21),
            observed_at_utc="2026-08-22T01:00:00+00:00",
        )
        first = prepare_revision_rows(evidence(), **args)
        second = prepare_revision_rows(evidence(), **args)
        self.assertEqual(first, second)
        self.assertEqual(first[0][2], "AAPL")
        self.assertEqual(len(first[0][16]), 64)

    def test_rejects_future_and_invalid_ohlc(self):
        frame = evidence()
        frame.loc[0, "Date"] = "2026-08-22"
        with self.assertRaisesRegex(ValueError, "future"):
            prepare_revision_rows(
                frame, run_id="alpaca-2026-08-21-run-001",
                provider="ALPACA_MARKET_DATA", source_session=date(2026, 8, 21),
                observed_at_utc="2026-08-22T01:00:00+00:00",
            )
        frame = evidence()
        frame.loc[0, "Raw High"] = 90.0
        with self.assertRaisesRegex(ValueError, "raw OHLC"):
            prepare_revision_rows(
                frame, run_id="alpaca-2026-08-21-run-001",
                provider="ALPACA_MARKET_DATA", source_session=date(2026, 8, 21),
                observed_at_utc="2026-08-22T01:00:00+00:00",
            )

    def test_resumable_writer_proves_final_count_and_hides_token_from_payload(self):
        rows = prepare_revision_rows(
            evidence(), run_id="alpaca-2026-08-21-run-001",
            provider="ALPACA_MARKET_DATA", source_session=date(2026, 8, 21),
            observed_at_utc="2026-08-22T01:00:00+00:00",
        )
        session = Session()
        stored = [[rows[0][2], rows[0][3], rows[0][16]]]
        count = stage_revision_rows(
            session=session, reader=Reader([0, 1, stored]),
            endpoint="https://example.test/v2/pipeline", token="secret-token-value",
            run_id="alpaca-2026-08-21-run-001", rows=rows,
        )
        self.assertEqual(count, 1)
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("secret-token-value", str(session.calls[0][1]["json"]))

    def test_rejects_same_count_with_conflicting_stored_hash(self):
        rows = prepare_revision_rows(
            evidence(), run_id="alpaca-2026-08-21-run-001",
            provider="ALPACA_MARKET_DATA", source_session=date(2026, 8, 21),
            observed_at_utc="2026-08-22T01:00:00+00:00",
        )
        conflicting = [[rows[0][2], rows[0][3], "0" * 64]]
        with self.assertRaisesRegex(RuntimeError, "keys or source hashes"):
            stage_revision_rows(
                session=Session(), reader=Reader([1, 1, conflicting]),
                endpoint="https://example.test/v2/pipeline",
                token="secret-token-value",
                run_id="alpaca-2026-08-21-run-001", rows=rows,
            )


if __name__ == "__main__":
    unittest.main()
