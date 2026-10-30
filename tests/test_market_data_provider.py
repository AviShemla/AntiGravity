import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from scripts.rebuild_market_features_to_turso import build_provider_lineage

from market_data_provider import (
    fetch_tiingo_history,
    fetch_tiingo_revision_bars,
    fetch_validated_daily_bars,
    resolve_tiingo_api_key,
)


SOURCE_SESSION = date(2026, 8, 21)


def valid_bars(*, end="2026-08-21", rows=320):
    dates = pd.bdate_range(end=end, periods=rows)
    close = np.linspace(100.0, 130.0, rows)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close - 0.2,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Adj Close": close,
            "Volume": np.arange(rows) + 1000,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        }
    )


class FakeResponse:
    status_code = 200

    def json(self):
        return [
            {
                "date": "2026-08-21T00:00:00.000Z",
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "adjClose": 5.5,
                "adjOpen": 5.0,
                "adjHigh": 6.0,
                "adjLow": 4.5,
                "adjVolume": 200,
                "volume": 100,
                "divCash": 0.25,
                "splitFactor": 2.0,
            }
        ]


class FakeSession:
    def __init__(self):
        self.call = None

    def get(self, url, **kwargs):
        self.call = (url, kwargs)
        return FakeResponse()


class MarketDataProviderTests(unittest.TestCase):
    def test_tiingo_token_file_is_loaded_without_environment_dependency(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tiingo.token"
            path.write_text("rotated-token-value-1234567890\n", encoding="utf-8")
            self.assertEqual(
                resolve_tiingo_api_key(path), "rotated-token-value-1234567890"
            )

    def test_multiline_tiingo_token_file_fails_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tiingo.token"
            path.write_text("first-token-value-12345\nsecond-line\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one line"):
                resolve_tiingo_api_key(path)

    def test_valid_yahoo_is_preferred_and_tiingo_is_not_called(self):
        calls = {"tiingo": 0}

        def tiingo(*_args):
            calls["tiingo"] += 1
            return valid_bars()

        ticker, bars, provider, error = fetch_validated_daily_bars(
            "AAA",
            SOURCE_SESSION,
            "2021-08-01",
            tiingo_api_key="rotated-test-key",
            yahoo_fetcher=lambda *_args: valid_bars(),
            tiingo_fetcher=tiingo,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(ticker, "AAA")
        self.assertEqual(provider, "YAHOO_FINANCE")
        self.assertIsNone(error)
        self.assertEqual(calls["tiingo"], 0)
        self.assertEqual(len(bars), 320)

    def test_invalid_yahoo_uses_valid_tiingo_fallback(self):
        ticker, bars, provider, error = fetch_validated_daily_bars(
            "AAA",
            SOURCE_SESSION,
            "2021-08-01",
            tiingo_api_key="rotated-test-key",
            yahoo_fetcher=lambda *_args: valid_bars(end="2026-08-20"),
            tiingo_fetcher=lambda *_args: valid_bars(),
            yahoo_attempts=1,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(ticker, "AAA")
        self.assertEqual(provider, "TIINGO_EOD")
        self.assertIsNone(error)
        self.assertEqual(len(bars), 320)

    def test_one_cent_yahoo_ohlc_violations_trigger_full_tiingo_fallback(self):
        cases = {
            "DG": (124.77999877929688, 124.7699966430664),
            "ELV": (402.6700134277344, 402.6600036621094),
            "OTIS": (72.20999908447266, 72.19999694824219),
            "TPR": (132.35000610351562, 132.33999633789062),
        }
        for ticker, (open_value, high_value) in cases.items():
            with self.subTest(ticker=ticker):
                yahoo = valid_bars()
                yahoo.loc[yahoo.index[-1], ["Open", "High", "Low", "Close"]] = [
                    open_value,
                    high_value,
                    high_value - 1.0,
                    high_value - 0.5,
                ]
                tiingo = valid_bars()
                tiingo[["Open", "High", "Low", "Close", "Adj Close"]] = (
                    tiingo[["Open", "High", "Low", "Close", "Adj Close"]] + 10.0
                )
                calls = {"tiingo": 0}

                def fetch_tiingo(*_args):
                    calls["tiingo"] += 1
                    return tiingo

                _, bars, provider, error = fetch_validated_daily_bars(
                    ticker,
                    SOURCE_SESSION,
                    "2021-08-01",
                    tiingo_api_key="rotated-test-key",
                    yahoo_fetcher=lambda *_args: yahoo,
                    tiingo_fetcher=fetch_tiingo,
                    yahoo_attempts=1,
                    sleep_fn=lambda _seconds: None,
                )

                self.assertEqual(provider, "TIINGO_EOD")
                self.assertIsNone(error)
                self.assertEqual(calls["tiingo"], 1)
                self.assertEqual(len(bars), len(tiingo))
                pd.testing.assert_series_equal(
                    bars["Close"], tiingo["Close"], check_names=False
                )

    def test_strict_ohlc_failure_in_both_providers_fails_closed(self):
        invalid = valid_bars()
        invalid.loc[invalid.index[-1], "Open"] = (
            invalid.loc[invalid.index[-1], "High"] + 0.01
        )
        _, bars, provider, error = fetch_validated_daily_bars(
            "AAA",
            SOURCE_SESSION,
            "2021-08-01",
            tiingo_api_key="rotated-test-key",
            yahoo_fetcher=lambda *_args: invalid,
            tiingo_fetcher=lambda *_args: invalid,
            yahoo_attempts=1,
            sleep_fn=lambda _seconds: None,
        )
        self.assertIsNone(bars)
        self.assertIsNone(provider)
        self.assertIn("YAHOO_FINANCE[1]: LineageError", error)
        self.assertIn("TIINGO: LineageError", error)

    def test_one_cent_yahoo_ohlc_violation_triggers_tiingo_fallback(self):
        yahoo = valid_bars()
        yahoo.loc[yahoo.index[-1], "High"] = (
            yahoo.loc[yahoo.index[-1], "Open"] - 0.01
        )
        tiingo = valid_bars()

        ticker, bars, provider, error = fetch_validated_daily_bars(
            "AAA",
            SOURCE_SESSION,
            "2021-08-01",
            tiingo_api_key="rotated-test-key",
            yahoo_fetcher=lambda *_args: yahoo,
            tiingo_fetcher=lambda *_args: tiingo,
            yahoo_attempts=1,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(ticker, "AAA")
        self.assertEqual(provider, "TIINGO_EOD")
        self.assertIsNone(error)
        self.assertEqual(len(bars), 320)
        self.assertGreaterEqual(bars.iloc[-1]["High"], bars.iloc[-1]["Open"])
        lineage = build_provider_lineage(
            {ticker: bars}, {ticker: provider}, source_session=SOURCE_SESSION
        )
        self.assertEqual(lineage[0][0], "AAA")
        self.assertEqual(lineage[0][1], "TIINGO_EOD")

    def test_missing_tiingo_credential_fails_closed(self):
        ticker, bars, provider, error = fetch_validated_daily_bars(
            "AAA",
            SOURCE_SESSION,
            "2021-08-01",
            tiingo_api_key=None,
            yahoo_fetcher=lambda *_args: valid_bars(end="2026-08-20"),
            yahoo_attempts=1,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(ticker, "AAA")
        self.assertIsNone(bars)
        self.assertIsNone(provider)
        self.assertIn("credential unavailable", error)

    def test_zero_yahoo_attempts_exercises_tiingo_only(self):
        calls = {"yahoo": 0, "tiingo": 0}

        def yahoo(*_args):
            calls["yahoo"] += 1
            return valid_bars()

        def tiingo(*_args):
            calls["tiingo"] += 1
            return valid_bars()

        _, bars, provider, error = fetch_validated_daily_bars(
            "AAA",
            SOURCE_SESSION,
            "2021-08-01",
            tiingo_api_key="rotated-test-key",
            yahoo_fetcher=yahoo,
            tiingo_fetcher=tiingo,
            yahoo_attempts=0,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(provider, "TIINGO_EOD")
        self.assertIsNone(error)
        self.assertEqual(len(bars), 320)
        self.assertEqual(calls, {"yahoo": 0, "tiingo": 1})

    def test_tiingo_request_uses_header_and_normalizes_corporate_actions(self):
        session = FakeSession()
        frame = fetch_tiingo_history(
            "BRK.B",
            SOURCE_SESSION,
            "2026-08-21",
            api_key="secret-test-token",
            session=session,
        )
        url, kwargs = session.call
        self.assertEqual(url, "https://api.tiingo.com/tiingo/daily/BRK-B/prices")
        self.assertNotIn("secret-test-token", url)
        self.assertEqual(kwargs["headers"]["Authorization"], "Token secret-test-token")
        self.assertEqual(frame.loc[0, "Adj Close"], 5.5)
        self.assertEqual(frame.loc[0, "Dividends"], 0.25)
        self.assertEqual(frame.loc[0, "Stock Splits"], 2.0)
        self.assertIsNone(frame.loc[0, "Date"].tzinfo)

    def test_tiingo_revision_fetch_preserves_provider_native_fields(self):
        session = FakeSession()
        frame = fetch_tiingo_revision_bars(
            "BRK.B", SOURCE_SESSION, "2026-08-21",
            session=session, **{"api" + "_key": "secret-" + "test-token"},
        )
        url, kwargs = session.call
        self.assertEqual(url, "https://api.tiingo.com/tiingo/daily/BRK-B/prices")
        self.assertNotIn("secret-test-token", url)
        self.assertEqual(frame.loc[0, "Ticker"], "BRK.B")
        self.assertEqual(frame.loc[0, "Raw Close"], 11.0)
        self.assertEqual(frame.loc[0, "Adjusted Open"], 5.0)
        self.assertEqual(frame.loc[0, "Adjusted Close"], 5.5)
        self.assertEqual(frame.loc[0, "Adjusted Volume"], 200)
        self.assertEqual(frame.loc[0, "Dividends"], 0.25)
        self.assertEqual(frame.loc[0, "Split Factor"], 2.0)
        self.assertIsNone(frame.loc[0, "Date"].tzinfo)


if __name__ == "__main__":
    unittest.main()
