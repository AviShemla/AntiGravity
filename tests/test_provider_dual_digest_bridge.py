from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import unittest

from scripts.audit_provider_dual_digest_bridge import (
    APPROVED_LEGACY_SHA256,
    BridgeError,
    COLUMNS,
    CONTRACT_ID,
    EXPECTED_ROW_COUNT,
    SELECT_SQL,
    QueryResult,
    audit_provider_dual_digest,
    canonical_jsonl_bytes,
    legacy_bytes,
)


def fixture_rows():
    rows = []
    for index in range(EXPECTED_ROW_COUNT):
        ticker = f"T{index:03d}"
        provider = "TIINGO_EOD" if index < 24 else "YAHOO_FINANCE"
        rows.append([
            ticker,
            provider,
            "2026-08-25",
            "2021-08-02",
            "2026-08-25",
            1246 + index,
            f"{index + 1:064x}",
        ])
    return rows


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class RecordingReader:
    def __init__(self, rows=None, columns=COLUMNS):
        self.rows = fixture_rows() if rows is None else rows
        self.columns = columns
        self.calls = []

    def execute(self, query, args):
        self.calls.append((query, args))
        return QueryResult(self.columns, self.rows)


class ProviderDualDigestBridgeTests(unittest.TestCase):
    def valid_audit(self, reader=None):
        reader = reader or RecordingReader()
        expected = digest(legacy_bytes(reader.rows))
        evidence = audit_provider_dual_digest(
            reader, snapshot_id="market_features_2026-08-25_fixture", expected_legacy_sha256=expected
        )
        return reader, evidence

    def test_valid_bridge_is_deterministic_sanitized_and_select_only(self):
        reader, first = self.valid_audit()
        _, second = self.valid_audit(RecordingReader())
        self.assertEqual(first, second)
        self.assertEqual(reader.calls, [(SELECT_SQL, ["market_features_2026-08-25_fixture"])])
        self.assertTrue(SELECT_SQL.startswith("SELECT"))
        self.assertEqual(first["contract_id"], CONTRACT_ID)
        self.assertEqual(first["row_count"], 476)
        self.assertEqual(first["scalar_count"], 3332)
        self.assertEqual(first["write_statement_count"], 0)
        self.assertNotEqual(first["legacy"]["sha256"], first["canonical"]["sha256"])
        rendered = json.dumps(first, sort_keys=True)
        self.assertNotIn("T000", rendered)
        self.assertNotIn("YAHOO_FINANCE", rendered)
        self.assertNotIn("market_features_2026-08-25_fixture", rendered)

    def test_framing_exactly_matches_both_contracts(self):
        rows = fixture_rows()[:2]
        legacy = legacy_bytes(rows)
        canonical = canonical_jsonl_bytes(rows)
        self.assertTrue(legacy.startswith(b"[["))
        self.assertTrue(legacy.endswith(b"]]"))
        self.assertNotIn(b"\n", legacy)
        self.assertEqual(canonical.count(b"\n"), 2)
        self.assertTrue(canonical.endswith(b"\n"))
        self.assertFalse(canonical.startswith(b"[["))

    def test_approved_legacy_digest_is_the_pinned_value(self):
        self.assertEqual(
            APPROVED_LEGACY_SHA256,
            "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a",
        )

    def test_default_approved_digest_rejects_fixture(self):
        with self.assertRaisesRegex(BridgeError, "differs from approval"):
            audit_provider_dual_digest(
                RecordingReader(), snapshot_id="market_features_2026-08-25_fixture"
            )

    def test_requires_exact_476_rows(self):
        with self.assertRaisesRegex(BridgeError, "exactly 476"):
            self.valid_audit(RecordingReader(fixture_rows()[:-1]))

    def test_rejects_wrong_columns(self):
        columns = tuple(reversed(COLUMNS))
        with self.assertRaisesRegex(BridgeError, "columns"):
            self.valid_audit(RecordingReader(columns=columns))

    def test_rejects_unsorted_or_duplicate_tickers(self):
        for rows in (
            list(reversed(fixture_rows())),
            [fixture_rows()[0]] + fixture_rows()[:-1],
        ):
            with self.subTest():
                with self.assertRaisesRegex(BridgeError, "uniquely ticker-ordered"):
                    self.valid_audit(RecordingReader(rows))

    def test_rejects_any_scalar_that_would_change_under_canonicalization(self):
        mutations = {
            "ticker": (0, " t000 "),
            "provider": (1, "yahoo_finance"),
            "requested": (2, "2026-8-25"),
            "first": (3, "2021-8-2"),
            "last": (4, "2026-08-24"),
            "count": (5, "1246"),
            "checksum": (6, "A" * 64),
        }
        for label, (column, value) in mutations.items():
            rows = fixture_rows()
            rows[0][column] = value
            with self.subTest(label=label):
                with self.assertRaises(BridgeError):
                    self.valid_audit(RecordingReader(rows))

    def test_rejects_unsafe_snapshot_identity_before_query(self):
        reader = RecordingReader()
        with self.assertRaisesRegex(BridgeError, "unsafe"):
            audit_provider_dual_digest(
                reader,
                snapshot_id="x' OR 1=1 --",
                expected_legacy_sha256=digest(legacy_bytes(reader.rows)),
            )
        self.assertEqual(reader.calls, [])

    def test_reader_failure_is_sanitized(self):
        class FailingReader:
            def execute(self, query, args):
                raise RuntimeError("secret-token-and-row-body")

        with self.assertRaisesRegex(BridgeError, "SELECT-only provider read failed") as caught:
            audit_provider_dual_digest(
                FailingReader(),
                snapshot_id="safe_snapshot",
                expected_legacy_sha256="a" * 64,
            )
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
