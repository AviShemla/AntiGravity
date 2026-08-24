import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.stage_tiingo_eod_delta import (
    build_run_id,
    complete_session_run,
    latest_stock_rows,
    manifest_sha256,
    source_code_sha256,
)


class _Result:
    def __init__(self, rows):
        self.rows = rows


class _Reader:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, args):
        self.calls.append((query, args))
        return _Result(self.rows)


class StageTiingoEodDeltaTests(unittest.TestCase):
    def test_manifest_is_sorted_deduplicated_and_case_normalized(self):
        first = manifest_sha256(["spy", "AAPL", "SPY"])
        second = manifest_sha256(["SPY", "AAPL"])
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            hashlib.sha256(b"AAPL\nSPY\n").hexdigest(),
        )

    def test_run_identity_changes_with_manifest_or_code(self):
        session = date(2026, 8, 21)
        base = build_run_id(session, "a" * 64, "b" * 64)
        self.assertNotEqual(base, build_run_id(session, "c" * 64, "b" * 64))
        self.assertNotEqual(base, build_run_id(session, "a" * 64, "d" * 64))

    def test_code_hash_is_path_order_independent_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as folder:
            one = Path(folder) / "one.py"
            two = Path(folder) / "two.py"
            one.write_text("one", encoding="utf-8")
            two.write_text("two", encoding="utf-8")
            first = source_code_sha256([one, two])
            self.assertEqual(first, source_code_sha256([two, one]))
            two.write_text("changed", encoding="utf-8")
            self.assertNotEqual(first, source_code_sha256([one, two]))

    def test_complete_session_is_idempotent_across_code_versions(self):
        reader = _Reader([["complete-run", 471]])
        result = complete_session_run(reader, date(2026, 8, 24), 471)
        self.assertEqual(result, "complete-run")
        query, args = reader.calls[0]
        self.assertIn("r.status='COMPLETE'", query)
        self.assertIn("HAVING COUNT(b.ticker)=?", query)
        self.assertEqual(
            args,
            ["TIINGO_EOD", "DAILY_DELTA", "2026-08-24", 471, 471],
        )

    def test_incomplete_session_is_not_treated_as_complete(self):
        self.assertIsNone(
            complete_session_run(_Reader([]), date(2026, 8, 24), 471)
        )

    def test_stock_universe_read_uses_only_latest_indexed_session(self):
        reader = _Reader([["AAPL", "Technology"], ["SPY", "ETF"]])
        self.assertEqual(
            latest_stock_rows(reader, "snapshot-1"),
            [["AAPL", "Technology"], ["SPY", "ETF"]],
        )
        query, args = reader.calls[0]
        self.assertIn("date=(SELECT MAX(date)", query)
        self.assertNotIn("GROUP BY", query)
        self.assertEqual(args, ["snapshot-1", "snapshot-1"])


if __name__ == "__main__":
    unittest.main()
