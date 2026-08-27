from __future__ import annotations

import unittest
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from market_staging_content import ENCODING, STAGING_COLUMNS, digest_rows
from scripts.audit_staged_snapshot_content import StagedSnapshotAuditError, audit_staged_snapshot


def row(ticker, session, value=1.0):
    result = []
    text = {"ticker": ticker, "sector": "Tech", "ras_signal": "HOLD", "analyst_consensus": None, "sector_regime": "BULL", "market_fear_level": "CALM"}
    for name in STAGING_COLUMNS:
        result.append(session if name == "date" else text[name] if name in text else value)
    return result


class Result:
    def __init__(self, rows): self.rows = rows


ROOT = Path(__file__).resolve().parents[1]
REBUILD_HASH = hashlib.sha256((ROOT / "scripts" / "rebuild_market_features_to_turso.py").read_bytes()).hexdigest()


class FakeClient:
    def __init__(self, rows, *, checksum=None, status="STAGING", duplicate=False, metadata=None):
        self.data = sorted(rows, key=lambda item: (item[0], item[1]))
        self.checksum = checksum or digest_rows(self.data)
        self.status = status
        self.duplicate = duplicate
        self.metadata = metadata or {}

    def execute(self, sql, args):
        if sql.startswith("SELECT snapshot_id"):
            canonical_id = f"market_features_2026-08-27_{self.checksum[:16]}"
            metadata = [[
                self.metadata.get("snapshot_id", canonical_id), self.status,
                self.metadata.get("checksum", self.checksum),
                self.metadata.get("rows", len(self.data)),
                self.metadata.get("tickers", len({r[0] for r in self.data})),
                self.metadata.get("code_version", REBUILD_HASH),
                self.metadata.get("notes", f"checksum_encoding={ENCODING}; test"),
            ]]
            return Result(metadata * (2 if self.duplicate else 1))
        snapshot, last_ticker, repeated_ticker, last_date, limit = args
        if snapshot != f"market_features_2026-08-27_{self.checksum[:16]}" or last_ticker != repeated_ticker:
            raise AssertionError("query arguments differ")
        page = [r for r in self.data if r[0] > last_ticker or (r[0] == last_ticker and r[1] > last_date)][:limit]
        return Result(page)


class AuditTests(unittest.TestCase):
    def test_exact_multi_page_readback(self):
        rows = [row("AAA", "2026-08-26"), row("AAA", "2026-08-27"), row("BBB", "2026-08-27")]
        snapshot, audit = audit_staged_snapshot(FakeClient(rows), source_session="2026-08-27", page_size=1)
        self.assertEqual(snapshot, f"market_features_2026-08-27_{FakeClient(rows).checksum[:16]}")
        self.assertEqual((audit.row_count, audit.ticker_count), (3, 2))

    def test_content_tamper_wrong_status_duplicate_and_wrong_date_fail(self):
        rows = [row("AAA", "2026-08-27")]
        cases = [
            FakeClient(rows, checksum="0" * 64),
            FakeClient(rows, status="VALIDATED"),
            FakeClient(rows, duplicate=True),
        ]
        for client in cases:
            with self.subTest(client=client):
                with self.assertRaises(StagedSnapshotAuditError):
                    audit_staged_snapshot(client, source_session="2026-08-27", page_size=1)
        with self.assertRaises(StagedSnapshotAuditError):
            audit_staged_snapshot(FakeClient(rows), source_session="2026-08-28", page_size=1)

    def test_count_preserving_tamper_rejected(self):
        original = [row("AAA", "2026-08-27")]
        changed = [row("AAA", "2026-08-27", 1.01)]
        with self.assertRaises(StagedSnapshotAuditError):
            audit_staged_snapshot(
                FakeClient(changed, checksum=digest_rows(original)),
                source_session="2026-08-27",
                page_size=1,
            )

    def test_page_bounds(self):
        for page_size in (0, 5001, True):
            with self.assertRaises(StagedSnapshotAuditError):
                audit_staged_snapshot(FakeClient([row("AAA", "2026-08-27")]), source_session="2026-08-27", page_size=page_size)

    def test_metadata_types_release_encoding_and_session_are_strict(self):
        rows = [row("AAA", "2026-08-27")]
        bad = [
            {"snapshot_id": ""}, {"snapshot_id": "market_features_2026-08-26_" + "0" * 16},
            {"snapshot_id": "market_features_2026-08-27_" + "0" * 16},
            {"checksum": "A" * 64}, {"checksum": None}, {"checksum": 7}, {"rows": "1"},
            {"rows": True}, {"tickers": 0}, {"code_version": "0" * 64},
            {"notes": "legacy pandas checksum"},
            {"notes": f"not_checksum_encoding={ENCODING}; test"},
            {"notes": f"checksum_encoding={ENCODING}; checksum_encoding=other; test"},
        ]
        for metadata in bad:
            with self.subTest(metadata=metadata):
                with self.assertRaises(StagedSnapshotAuditError):
                    audit_staged_snapshot(FakeClient(rows, metadata=metadata), source_session="2026-08-27")
        for source_session in (None, "2026-8-27", "2026-08-27T00:00:00"):
            with self.subTest(source_session=source_session):
                with self.assertRaises(StagedSnapshotAuditError):
                    audit_staged_snapshot(FakeClient(rows), source_session=source_session)

    def test_direct_cli_help_starts_with_clean_pythonpath(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "audit_staged_snapshot_content.py"), "--help"],
            cwd=ROOT / "scripts", env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--source-session", result.stdout)


if __name__ == "__main__":
    unittest.main()
