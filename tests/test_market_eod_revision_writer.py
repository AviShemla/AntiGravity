import unittest
from datetime import date

import pandas as pd

from market_eod_revision_writer import prepare_revision_rows, stage_revision_rows
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
    def __init__(self, counts):
        self.counts = iter(counts)

    def execute(self, query, args):
        return PipelineResult(["n"], [[next(self.counts)]])


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
        count = stage_revision_rows(
            session=session, reader=Reader([0, 1]),
            endpoint="https://example.test/v2/pipeline", token="secret-token-value",
            run_id="alpaca-2026-08-21-run-001", rows=rows,
        )
        self.assertEqual(count, 1)
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("secret-token-value", str(session.calls[0][1]["json"]))


if __name__ == "__main__":
    unittest.main()
