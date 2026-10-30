from datetime import datetime, timezone
import unittest

import pandas as pd

from canonical_market_history import (
    CanonicalSelectionPolicy,
    reconcile_canonical_history,
    select_canonical_bar_revisions,
)
from model_lineage import LineageError


def row(run, provider, observed, source_hash, *, status="COMPLETE", close=102.0):
    return {
        "run_id": run,
        "run_status": status,
        "provider": provider,
        "ingestion_mode": "DAILY_DELTA",
        "ticker": "AAA",
        "date": "2026-08-21",
        "raw_open": 100.0,
        "raw_high": 103.0,
        "raw_low": 99.0,
        "raw_close": close,
        "raw_volume": 1000.0,
        "adjusted_open": 100.0,
        "adjusted_high": 103.0,
        "adjusted_low": 99.0,
        "adjusted_close": close,
        "adjusted_volume": 1000.0,
        "dividend_cash": 0.0,
        "split_factor": 1.0,
        "source_value_sha256": source_hash,
        "observed_at_utc": observed,
    }


def policy(cutoff="2026-08-24T04:00:00+00:00"):
    return CanonicalSelectionPolicy(
        provider_priority=("ALPACA_MARKET_DATA", "TIINGO_EOD", "YAHOO_FINANCE"),
        evidence_cutoff_utc=datetime.fromisoformat(cutoff),
    )


class CanonicalMarketHistoryTests(unittest.TestCase):
    def test_explicit_priority_beats_later_lower_priority_evidence(self):
        evidence = pd.DataFrame([
            row("alpaca-run-001", "ALPACA_MARKET_DATA", "2026-08-23T01:00:00Z", "a" * 64),
            row("tiingo-run-001", "TIINGO_EOD", "2026-08-24T01:00:00Z", "b" * 64),
        ])
        selected = select_canonical_bar_revisions(evidence, policy())
        self.assertEqual(selected.iloc[0]["canonical_provider"], "ALPACA_MARKET_DATA")
        self.assertEqual(selected.iloc[0]["source_value_sha256"], "a" * 64)

    def test_latest_revision_wins_within_same_provider_before_cutoff(self):
        evidence = pd.DataFrame([
            row("tiingo-run-001", "TIINGO_EOD", "2026-08-22T01:00:00Z", "a" * 64),
            row("tiingo-run-002", "TIINGO_EOD", "2026-08-23T01:00:00Z", "b" * 64),
            row("tiingo-run-003", "TIINGO_EOD", "2026-08-25T01:00:00Z", "c" * 64),
        ])
        selected = select_canonical_bar_revisions(evidence, policy())
        self.assertEqual(selected.iloc[0]["canonical_run_id"], "tiingo-run-002")

    def test_noncomplete_evidence_is_fail_closed(self):
        evidence = pd.DataFrame([
            row("tiingo-run-001", "TIINGO_EOD", "2026-08-22T01:00:00Z", "a" * 64, status="STAGING"),
        ])
        with self.assertRaisesRegex(LineageError, "non-COMPLETE"):
            select_canonical_bar_revisions(evidence, policy())

    def test_unranked_provider_is_fail_closed(self):
        evidence = pd.DataFrame([
            row("unknown-run-001", "UNKNOWN", "2026-08-22T01:00:00Z", "a" * 64),
        ])
        with self.assertRaisesRegex(LineageError, "does not rank"):
            select_canonical_bar_revisions(evidence, policy())

    def test_reconciliation_appends_revises_and_preserves_unchanged(self):
        initial_evidence = pd.DataFrame([
            row("tiingo-run-001", "TIINGO_EOD", "2026-08-22T01:00:00Z", "a" * 64),
        ])
        existing = select_canonical_bar_revisions(initial_evidence, policy())
        revised_evidence = pd.DataFrame([
            row("tiingo-run-002", "TIINGO_EOD", "2026-08-23T01:00:00Z", "b" * 64, close=102.5),
        ])
        revised = select_canonical_bar_revisions(revised_evidence, policy())
        result = reconcile_canonical_history(existing, revised)
        self.assertEqual(result.appended_keys, ())
        self.assertEqual(result.revised_keys, (("AAA", "2026-08-21"),))
        self.assertEqual(result.history.iloc[0]["raw_close"], 102.5)
        repeated = reconcile_canonical_history(result.history, revised)
        self.assertEqual(repeated.revised_keys, ())
        self.assertEqual(repeated.unchanged_keys, (("AAA", "2026-08-21"),))


if __name__ == "__main__":
    unittest.main()
