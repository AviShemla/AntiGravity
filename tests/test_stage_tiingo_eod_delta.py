import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.stage_tiingo_eod_delta import (
    build_run_id,
    manifest_sha256,
    source_code_sha256,
)


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


if __name__ == "__main__":
    unittest.main()
