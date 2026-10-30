import unittest

from model_lineage import LineageError
from screening_universe_reader import load_screening_universe


class Result:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class DB:
    def __init__(self, responses):
        self.responses = list(responses)

    def execute(self, _query, _args):
        return self.responses.pop(0)


RUN_COLUMNS = ["screening_run_id", "market_snapshot_id", "source_session_date", "status"]
RESULT_COLUMNS = [
    "ticker", "oos_accuracy", "selected_depth", "lag1_ticker", "lag2_ticker",
    "lag3_ticker", "lag4_ticker", "lag5_ticker",
    "lag1_sessions", "lag2_sessions", "lag3_sessions", "lag4_sessions", "lag5_sessions",
    "feature_spec_json",
]


class ScreeningUniverseReaderTests(unittest.TestCase):
    def load(self, result_rows, status="VALIDATED"):
        return load_screening_universe(
            DB([
                Result(RUN_COLUMNS, [["r1", "s1", "2026-08-20", status]]),
                Result(RESULT_COLUMNS, result_rows),
            ]),
            screening_run_id="r1",
            expected_market_snapshot_id="s1",
            expected_source_session_date="2026-08-20",
        )

    def test_zero_eligible_is_explicit_no_trade(self):
        universe = self.load([])
        self.assertEqual(universe.disposition, "NO_TRADE")
        self.assertEqual(universe.candidates, ())

    def test_complete_candidate_is_loaded(self):
        universe = self.load([[
            "AAA", 0.61, 3, "BBB", "CCC", "DDD", None, None,
            7, 2, 5, None, None,
            '{"depth":3,"lag_semantics":"target_relative_sessions",'
            '"lag_sessions":[7,2,5],"lag_tickers":["BBB","CCC","DDD"]}',
        ]])
        self.assertEqual(universe.disposition, "MODEL_CANDIDATES")
        self.assertEqual(universe.candidates[0].lag_tickers, ("BBB", "CCC", "DDD"))
        self.assertEqual(universe.candidates[0].lag_sessions, (7, 2, 5))

    def test_unvalidated_run_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "not validated"):
            self.load([], status="RUNNING")

    def test_incomplete_lag_chain_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "incomplete"):
            self.load([[
                "AAA", 0.61, 3, "BBB", None, "DDD", None, None,
                7, 2, 5, None, None,
                '{"depth":3}',
            ]])


if __name__ == "__main__":
    unittest.main()
