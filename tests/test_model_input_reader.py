import unittest
from datetime import date, datetime, timezone

from model_input_reader import (
    InputSnapshot,
    load_stock_universe_config,
    select_validated_snapshot,
    verify_snapshot_counts,
)
from model_lineage import LineageError


class Result:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class FakeDB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, query, args):
        self.calls.append((query, args))
        return self.responses.pop(0)


class ModelInputReaderTests(unittest.TestCase):
    cutoff = datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)

    def snapshot_result(self, available="2026-08-21T04:00:00+00:00"):
        return Result(
            [
                "snapshot_id", "dataset_type", "source_session_date", "available_at_utc",
                "provider", "code_version", "expected_row_count", "expected_ticker_count",
            ],
            [["u1", "STOCK_UNIVERSE", "2026-08-20", available, "migration", "v1", 2, 2]],
        )

    def test_selects_exact_validated_snapshot_before_cutoff(self):
        db = FakeDB([self.snapshot_result()])
        snapshot = select_validated_snapshot(
            db,
            dataset_type="STOCK_UNIVERSE",
            source_session_date=date(2026, 8, 20),
            cutoff_utc=self.cutoff,
        )
        self.assertEqual(snapshot.snapshot_id, "u1")
        self.assertIn("status = 'VALIDATED'", db.calls[0][0])
        self.assertEqual(db.calls[0][1][1], "2026-08-20")

    def test_missing_snapshot_fails_closed(self):
        columns = self.snapshot_result().columns
        with self.assertRaisesRegex(LineageError, "No validated"):
            select_validated_snapshot(
                FakeDB([Result(columns, [])]),
                dataset_type="MARKET_FEATURES",
                source_session_date=date(2026, 8, 20),
                cutoff_utc=self.cutoff,
            )

    def test_count_mismatch_fails_closed(self):
        snapshot = InputSnapshot(
            "u1", "STOCK_UNIVERSE", date(2026, 8, 20), self.cutoff,
            "migration", "v1", 2, 2,
        )
        db = FakeDB([Result(["row_count", "ticker_count"], [[1, 1]])])
        with self.assertRaisesRegex(LineageError, "row count"):
            verify_snapshot_counts(db, snapshot, table_name="stock_universe_config")

    def test_loads_complete_lag_chain(self):
        snapshot = InputSnapshot(
            "u1", "STOCK_UNIVERSE", date(2026, 8, 20), self.cutoff,
            "migration", "v1", 1, 1,
        )
        db = FakeDB([
            Result(["row_count", "ticker_count"], [[1, 1]]),
            Result(
                ["ticker", "selection_rank", "oos_accuracy", "causal_depth",
                 "lag1_ticker", "lag2_ticker", "lag3_ticker", "lag4_ticker", "lag5_ticker",
                 "lag1_sessions", "lag2_sessions", "lag3_sessions", "lag4_sessions", "lag5_sessions"],
                [["GPC", 1, 0.6, 3, "GPC", "GPC", "GPC", None, None,
                  7, 5, 2, None, None]],
            ),
        ])
        entries = load_stock_universe_config(db, snapshot)
        self.assertEqual(entries[0].lag_tickers, ("GPC", "GPC", "GPC"))
        self.assertEqual(entries[0].lag_sessions, (7, 5, 2))

    def test_incomplete_lag_chain_fails_closed(self):
        snapshot = InputSnapshot(
            "u1", "STOCK_UNIVERSE", date(2026, 8, 20), self.cutoff,
            "migration", "v1", 1, 1,
        )
        db = FakeDB([
            Result(["row_count", "ticker_count"], [[1, 1]]),
            Result(
                ["ticker", "selection_rank", "oos_accuracy", "causal_depth",
                 "lag1_ticker", "lag2_ticker", "lag3_ticker", "lag4_ticker", "lag5_ticker",
                 "lag1_sessions", "lag2_sessions", "lag3_sessions", "lag4_sessions", "lag5_sessions"],
                [["GPC", 1, 0.6, 3, "GPC", None, "GPC", None, None,
                  7, 5, 2, None, None]],
            ),
        ])
        with self.assertRaisesRegex(LineageError, "incomplete lag specification"):
            load_stock_universe_config(db, snapshot)


if __name__ == "__main__":
    unittest.main()
