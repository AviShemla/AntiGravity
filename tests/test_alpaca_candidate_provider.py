import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from alpaca_candidate_provider import (
    fetch_alpaca_adjusted_bars,
    resolve_alpaca_credentials,
)


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if len(self.calls) == 1:
            return FakeResponse({
                "bars": [{"t": "2026-08-20T04:00:00Z", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}],
                "next_page_token": "next-page",
            })
        return FakeResponse({
            "bars": [{"t": "2026-08-21T04:00:00Z", "o": 11, "h": 13, "l": 10, "c": 12, "v": 120}],
            "next_page_token": None,
        })


class AlpacaCandidateProviderTests(unittest.TestCase):
    def test_credentials_are_loaded_from_two_single_line_files(self):
        with TemporaryDirectory() as directory:
            key_id = Path(directory) / "key-id"
            secret = Path(directory) / "secret"
            key_id.write_text("candidate-key-id-123456\n", encoding="utf-8")
            secret.write_text("candidate-secret-key-123456\n", encoding="utf-8")
            self.assertEqual(
                resolve_alpaca_credentials(key_id, secret),
                ("candidate-key-id-123456", "candidate-secret-key-123456"),
            )

    def test_adjusted_bar_request_is_bounded_paginated_and_secret_safe(self):
        session = FakeSession()
        frame = fetch_alpaca_adjusted_bars(
            "AAPL",
            date(2026, 8, 21),
            "2021-08-01",
            key_id="candidate-key-id-123456",
            secret_key="candidate-secret-key-123456",
            session=session,
        )
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.loc[1, "Adj Close"], 12)
        first_url, first = session.calls[0]
        self.assertEqual(first_url, "https://data.alpaca.markets/v2/stocks/AAPL/bars")
        self.assertEqual(first["params"]["adjustment"], "all")
        self.assertEqual(first["params"]["feed"], "sip")
        self.assertNotIn("candidate-secret-key-123456", first_url)
        self.assertEqual(session.calls[1][1]["params"]["page_token"], "next-page")


if __name__ == "__main__":
    unittest.main()
