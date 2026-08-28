from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import math
import unittest

from .s08_complete_case_universe import (
    CompleteCaseUniverseError, audit_complete_case_universe,
)


def fixture():
    tickers = tuple(sorted(["FISV", "SNDK"] + [f"T{i:03d}" for i in range(472)]))
    first = date(2025, 7, 5)
    dates = tuple((first + timedelta(days=i)).isoformat() for i in range(417))
    rows = []
    for rank, ticker in enumerate(tickers):
        ticker_dates = dates
        if ticker == "FISV":
            ticker_dates = dates[1:]
        elif ticker == "SNDK":
            ticker_dates = dates[59:]
        for ordinal, session in enumerate(ticker_dates):
            rows.append((ticker, session, 10.0 + rank + ordinal / 1000.0))
    return tickers, dates, tuple(rows)


class CompleteCaseUniverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tickers, cls.dates, cls.rows = fixture()

    def audit(self, **changes):
        values = {"upstream_tickers": self.tickers,
                  "required_session_dates": self.dates,
                  "canonical_presence_rows": self.rows}
        values.update(changes)
        return audit_complete_case_universe(**values)

    def test_exact_472_universe_and_exclusion_evidence(self):
        result = self.audit()
        self.assertEqual(len(result.eligible_tickers), 472)
        self.assertEqual([(x.ticker, x.observed_session_count, len(x.missing_session_dates))
                          for x in result.exclusions], [("FISV", 416, 1), ("SNDK", 358, 59)])
        self.assertNotIn("FISV", result.eligible_tickers)
        self.assertNotIn("SNDK", result.eligible_tickers)
        self.assertEqual((result.database_writes, result.selections, result.model_runs,
                          result.downstream_outputs, result.imputation_count), (0, 0, 0, 0, 0))
        self.assertFalse(result.execution_authorized)

    def test_price_permutation_cannot_change_any_audit_hash_or_eligibility(self):
        prices = [row[2] for row in self.rows][::-1]
        changed = tuple((row[0], row[1], prices[i]) for i, row in enumerate(self.rows))
        left, right = self.audit(), self.audit(canonical_presence_rows=changed)
        self.assertEqual(left, right)

    def test_missing_row_changes_exclusions_and_fails(self):
        with self.assertRaisesRegex(CompleteCaseUniverseError, "exclusions/counts"):
            self.audit(canonical_presence_rows=self.rows[:-1])

    def test_extra_ticker_and_extra_date_fail(self):
        with self.assertRaisesRegex(CompleteCaseUniverseError, "extra or malformed ticker"):
            self.audit(canonical_presence_rows=self.rows + (("ZZZ", self.dates[0], 1.0),))
        extra = (self.rows[-1][0], "2030-01-01", 1.0)
        with self.assertRaisesRegex(CompleteCaseUniverseError, "extra session"):
            self.audit(canonical_presence_rows=self.rows + (extra,))

    def test_duplicate_row_fails(self):
        duplicate = tuple(sorted(self.rows + (self.rows[100],), key=lambda row: (row[0], row[1])))
        with self.assertRaisesRegex(CompleteCaseUniverseError, "duplicated"):
            self.audit(canonical_presence_rows=duplicate)

    def test_invalid_adjusted_close_presence_fails_without_imputation(self):
        for value in (None, True, 0.0, -1.0, math.inf, math.nan):
            with self.subTest(value=value):
                rows = list(self.rows)
                rows[100] = (rows[100][0], rows[100][1], value)
                with self.assertRaises(CompleteCaseUniverseError):
                    self.audit(canonical_presence_rows=tuple(rows))

    def test_changed_exclusion_count_and_reintroduction_fail(self):
        fisv_missing = ("FISV", self.dates[0], 99.0)
        rows = tuple(sorted(self.rows + (fisv_missing,), key=lambda row: (row[0], row[1])))
        with self.assertRaisesRegex(CompleteCaseUniverseError, "exclusions/counts"):
            self.audit(canonical_presence_rows=rows)

    def test_unsorted_universe_fails(self):
        bad = (self.tickers[1], self.tickers[0], *self.tickers[2:])
        with self.assertRaisesRegex(CompleteCaseUniverseError, "sorted unique 474"):
            self.audit(upstream_tickers=bad)

    def test_non_417_date_calendar_fails(self):
        with self.assertRaisesRegex(CompleteCaseUniverseError, "exactly 417"):
            self.audit(required_session_dates=self.dates[:-1])


if __name__ == "__main__":
    unittest.main()
