"""Test-only in-memory behavioral checks for the pure writer contract."""

import sqlite3
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from model_lineage import LineageError
from oracle_research_dataset import (
    OracleProviderLineage,
    compute_provider_lineage_sha256,
)
from oracle_research_dataset_writer import (
    OracleResearchDatasetFreezeEvidence,
    OracleResearchDatasetStageIntent,
    OracleResearchDatasetWriter,
)


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260826_oracle_research_dataset_versions_additive.sql"
)
UTC = timezone.utc


class Result:
    def __init__(self, cursor):
        self.columns = tuple(item[0] for item in (cursor.description or ()))
        self.rows = tuple(cursor.fetchall()) if cursor.description else ()


class MemoryImmediateRunner:
    """SQLite is used only as a no-file, no-network transaction test double."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.operations = []
        self.mutations = []
        self.fail_on_mutation = None
        self.ambiguous_after_commit = False
        self._mutation_number = 0
        self.db.executescript(
            """
            CREATE TABLE model_input_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                dataset_type TEXT NOT NULL,
                source_session_date TEXT NOT NULL,
                available_at_utc TEXT NOT NULL,
                source_checksum_sha256 TEXT NOT NULL,
                expected_row_count INTEGER NOT NULL,
                expected_ticker_count INTEGER NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE market_daily_features (
                snapshot_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                value REAL,
                PRIMARY KEY (snapshot_id,ticker,date)
            );
            CREATE TABLE market_data_provider_lineage (
                snapshot_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                provider TEXT NOT NULL,
                requested_source_session_date TEXT NOT NULL,
                first_available_date TEXT NOT NULL,
                last_available_date TEXT NOT NULL,
                source_row_count INTEGER NOT NULL,
                source_checksum_sha256 TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                PRIMARY KEY (snapshot_id,ticker)
            );
            """
        )
        self.db.executescript(MIGRATION.read_text(encoding="utf-8"))

    def execute(self, query, args):
        return Result(self.db.execute(query, args))

    def execute_mutation(self, query, args):
        self._mutation_number += 1
        self.mutations.append(" ".join(query.upper().split()))
        if self.fail_on_mutation == self._mutation_number:
            raise RuntimeError("injected transaction failure")
        return self.db.execute(query, args).rowcount

    def run_immediate(self, operation_id, callback):
        self.operations.append(operation_id)
        self._mutation_number = 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = callback(self)
        except Exception:
            self.db.rollback()
            raise
        self.db.commit()
        if self.ambiguous_after_commit:
            self.ambiguous_after_commit = False
            raise RuntimeError("injected ambiguous commit response")
        return result

    def scalar(self, query, args=()):
        return self.db.execute(query, args).fetchone()[0]

    def close(self):
        self.db.close()


class OracleResearchDatasetWriterTests(unittest.TestCase):
    def setUp(self):
        self.harness = MemoryImmediateRunner()
        self.harness.db.execute(
            """INSERT INTO model_input_snapshots VALUES (?,?,?,?,?,?,?,?)""",
            (
                "market-1", "MARKET_FEATURES", "2026-08-25",
                "2026-08-26T06:30:00+00:00", "a" * 64, 4, 2, "VALIDATED",
            ),
        )
        self.harness.db.executemany(
            "INSERT INTO market_daily_features VALUES (?,?,?,?)",
            [
                ("market-1", "AAA", "2026-08-24", 1.0),
                ("market-1", "AAA", "2026-08-25", 2.0),
                ("market-1", "BBB", "2026-08-24", 3.0),
                ("market-1", "BBB", "2026-08-25", 4.0),
            ],
        )
        source = (
            OracleProviderLineage(
                "AAA", "YAHOO_FINANCE", date(2026, 8, 25),
                date(2026, 8, 24), date(2026, 8, 25), 2, "1" * 64,
            ),
            OracleProviderLineage(
                "BBB", "TIINGO_EOD", date(2026, 8, 25),
                date(2026, 8, 24), date(2026, 8, 25), 2, "2" * 64,
            ),
        )
        self.harness.db.executemany(
            """INSERT INTO market_data_provider_lineage VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (
                    "market-1", item.ticker, item.provider,
                    item.requested_source_session_date.isoformat(),
                    item.first_available_date.isoformat(),
                    item.last_available_date.isoformat(), item.source_row_count,
                    item.source_checksum_sha256, "2026-08-26T06:30:00+00:00",
                )
                for item in source
            ],
        )
        self.harness.db.commit()
        self.intent = OracleResearchDatasetStageIntent(
            dataset_version_id="research-1",
            market_snapshot_id="market-1",
            market_snapshot_checksum_sha256="a" * 64,
            source_session_date=date(2026, 8, 25),
            evidence_cutoff_utc=datetime(2026, 8, 26, 6, 44, tzinfo=UTC),
            first_session_date=date(2026, 8, 24),
            last_session_date=date(2026, 8, 25),
            expected_row_count=4,
            expected_ticker_count=2,
            expected_session_count=2,
            expected_provider_lineage_count=2,
            content_sha256="b" * 64,
            ticker_universe_sha256="c" * 64,
            provider_lineage_sha256=compute_provider_lineage_sha256(source),
            schema_version="schema-1",
            code_version="b2f6d25",
            created_at_utc=datetime(2026, 8, 26, 7, 0, tzinfo=UTC),
        )
        self.evidence = OracleResearchDatasetFreezeEvidence(
            event_id="freeze-1", actor="owner",
            decided_at_utc=datetime(2026, 8, 26, 7, 40, tzinfo=UTC),
            evidence_sha256="e" * 64,
            market_snapshot_checksum_sha256="a" * 64,
            content_sha256="b" * 64,
            ticker_universe_sha256="c" * 64,
            provider_lineage_sha256=self.intent.provider_lineage_sha256,
        )
        self.writer = OracleResearchDatasetWriter(self.harness, self.harness)

    def tearDown(self):
        self.harness.close()

    def source_counts(self):
        return (
            self.harness.scalar("SELECT COUNT(*) FROM model_input_snapshots"),
            self.harness.scalar("SELECT COUNT(*) FROM market_daily_features"),
            self.harness.scalar("SELECT COUNT(*) FROM market_data_provider_lineage"),
        )

    def test_stage_is_exact_staging_only_idempotent_and_source_read_only(self):
        before = self.source_counts()
        first = self.writer.stage(self.intent)
        second = self.writer.stage(self.intent)
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.status, "STAGING")
        self.assertEqual(
            self.harness.scalar(
                "SELECT status FROM oracle_research_dataset_versions"
            ),
            "STAGING",
        )
        self.assertEqual(
            self.harness.scalar(
                "SELECT COUNT(*) FROM oracle_research_dataset_provider_lineage"
            ),
            2,
        )
        self.assertEqual(self.source_counts(), before)
        self.assertEqual(self.harness.operations, ["stage:research-1"] * 2)

    def test_conflicting_stage_retry_fails_closed_without_duplicates(self):
        self.writer.stage(self.intent)
        with self.assertRaises(LineageError):
            self.writer.stage(replace(self.intent, code_version="different"))
        self.assertEqual(
            self.harness.scalar("SELECT COUNT(*) FROM oracle_research_dataset_versions"), 1
        )

    def test_source_identity_coverage_and_provider_digest_mismatches_do_not_write(self):
        cases = (
            replace(self.intent, market_snapshot_id="market-missing"),
            replace(self.intent, market_snapshot_checksum_sha256="f" * 64),
            replace(self.intent, expected_row_count=5),
            replace(self.intent, expected_session_count=3),
            replace(
                self.intent,
                source_session_date=date(2026, 8, 24),
                last_session_date=date(2026, 8, 24),
            ),
            replace(self.intent, provider_lineage_sha256="f" * 64),
        )
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(LineageError):
                    self.writer.stage(bad)
        self.assertEqual(
            self.harness.scalar("SELECT COUNT(*) FROM oracle_research_dataset_versions"), 0
        )
        self.assertEqual(self.harness.mutations, [])

    def test_stage_identity_whitespace_is_rejected_before_transaction(self):
        malformed = (
            replace(self.intent, dataset_version_id=" research-1"),
            replace(self.intent, market_snapshot_id="market-1 "),
            replace(self.intent, schema_version=" schema-1"),
            replace(self.intent, code_version="b2f6d25 "),
        )
        for intent in malformed:
            with self.subTest(intent=intent):
                with self.assertRaises(LineageError):
                    self.writer.stage(intent)
        self.assertEqual(self.harness.operations, [])
        self.assertEqual(self.harness.mutations, [])
        self.assertEqual(
            self.harness.scalar("SELECT COUNT(*) FROM oracle_research_dataset_versions"), 0
        )

    def test_ambiguous_stage_commit_is_accepted_only_by_exact_readback(self):
        self.harness.ambiguous_after_commit = True
        receipt = self.writer.stage(self.intent)
        self.assertFalse(receipt.created)
        self.assertEqual(receipt.status, "STAGING")

    def test_freeze_requires_matching_explicit_evidence(self):
        self.writer.stage(self.intent)
        mutation_count = len(self.harness.mutations)
        with self.assertRaises(LineageError):
            self.writer.freeze(self.intent, replace(self.evidence, event_id=""))
        with self.assertRaises(LineageError):
            self.writer.freeze(
                self.intent, replace(self.evidence, content_sha256="f" * 64)
            )
        self.assertEqual(len(self.harness.mutations), mutation_count)

    def test_freeze_identity_whitespace_is_rejected_before_transaction(self):
        self.writer.stage(self.intent)
        operation_count = len(self.harness.operations)
        mutation_count = len(self.harness.mutations)
        for evidence in (
            replace(self.evidence, event_id=" freeze-1"),
            replace(self.evidence, actor="owner "),
        ):
            with self.subTest(evidence=evidence):
                with self.assertRaises(LineageError):
                    self.writer.freeze(self.intent, evidence)
        self.assertEqual(len(self.harness.operations), operation_count)
        self.assertEqual(len(self.harness.mutations), mutation_count)
        self.assertEqual(
            self.harness.scalar("SELECT COUNT(*) FROM oracle_research_dataset_events"), 0
        )

    def test_freeze_is_atomic_idempotent_and_source_read_only(self):
        self.writer.stage(self.intent)
        before = self.source_counts()
        first = self.writer.freeze(self.intent, self.evidence)
        second = self.writer.freeze(self.intent, self.evidence)
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.status, "FROZEN")
        self.assertEqual(first.event_id, "freeze-1")
        self.assertEqual(
            self.harness.scalar("SELECT status FROM oracle_research_dataset_versions"),
            "FROZEN",
        )
        self.assertEqual(
            self.harness.scalar("SELECT COUNT(*) FROM oracle_research_dataset_events"), 1
        )
        self.assertEqual(self.source_counts(), before)

    def test_freeze_failure_between_event_and_transition_rolls_back(self):
        self.writer.stage(self.intent)
        self.harness.fail_on_mutation = 2
        with self.assertRaises(LineageError):
            self.writer.freeze(self.intent, self.evidence)
        self.assertEqual(
            self.harness.scalar("SELECT status FROM oracle_research_dataset_versions"),
            "STAGING",
        )
        self.assertEqual(
            self.harness.scalar("SELECT COUNT(*) FROM oracle_research_dataset_events"), 0
        )

    def test_ambiguous_freeze_commit_is_accepted_only_by_exact_readback(self):
        self.writer.stage(self.intent)
        self.harness.ambiguous_after_commit = True
        receipt = self.writer.freeze(self.intent, self.evidence)
        self.assertFalse(receipt.created)
        self.assertEqual(receipt.status, "FROZEN")

    def test_mutation_surface_excludes_all_source_tables(self):
        self.writer.stage(self.intent)
        self.writer.freeze(self.intent, self.evidence)
        targets = [
            sql.split()[2 if sql.startswith("INSERT") else 1]
            for sql in self.harness.mutations
        ]
        self.assertEqual(
            targets,
            [
                "ORACLE_RESEARCH_DATASET_VERSIONS",
                "ORACLE_RESEARCH_DATASET_PROVIDER_LINEAGE",
                "ORACLE_RESEARCH_DATASET_EVENTS",
                "ORACLE_RESEARCH_DATASET_VERSIONS",
            ],
        )


if __name__ == "__main__":
    unittest.main()
