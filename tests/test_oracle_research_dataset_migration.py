"""Pure test-only in-memory SQL checks; never an application data path."""

import re
import sqlite3
import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260826_oracle_research_dataset_versions_additive.sql"
)


def sql_text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def normalized_sql() -> str:
    return " ".join(sql_text().upper().split())


class OracleResearchDatasetMigrationTests(unittest.TestCase):
    def setUp(self):
        # The standard-library in-memory engine executes Turso-compatible DDL
        # only. It creates no file and has no production credentials/network.
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(
            """
            CREATE TABLE model_input_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                note TEXT
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
        self.db.executescript(sql_text())

    def tearDown(self):
        self.db.close()

    def freeze_fixture(self):
        self.db.executemany(
            "INSERT INTO model_input_snapshots(snapshot_id,note) VALUES (?,?)",
            [("market-bound", "bound"), ("market-other", "other")],
        )
        self.db.executemany(
            "INSERT INTO market_daily_features(snapshot_id,ticker,date,value) VALUES (?,?,?,?)",
            [
                ("market-bound", "AAA", "2026-08-25", 1.0),
                ("market-other", "BBB", "2026-08-25", 2.0),
            ],
        )
        source_lineage = (
            "YAHOO_FINANCE", "2026-08-25", "2026-08-22", "2026-08-25",
            4, "f" * 64, "2026-08-26T06:30:00Z",
        )
        self.db.executemany(
            """INSERT INTO market_data_provider_lineage
               (snapshot_id,ticker,provider,requested_source_session_date,
                first_available_date,last_available_date,source_row_count,
                source_checksum_sha256,created_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                ("market-bound", "AAA", *source_lineage),
                ("market-other", "BBB", *source_lineage),
            ],
        )
        self.db.execute(
            """INSERT INTO oracle_research_dataset_versions
               (dataset_version_id,market_snapshot_id,
                market_snapshot_checksum_sha256,source_session_date,
                evidence_cutoff_utc,first_session_date,last_session_date,
                expected_row_count,expected_ticker_count,expected_session_count,
                expected_provider_lineage_count,content_sha256,
                ticker_universe_sha256,provider_lineage_sha256,schema_version,
                code_version,status,created_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "research-1", "market-bound", "a" * 64, "2026-08-25",
                "2026-08-26T06:44:37Z", "2026-08-25", "2026-08-25",
                1, 1, 1, 1, "b" * 64, "c" * 64, "d" * 64,
                "schema-1", "code-1", "STAGING", "2026-08-26T07:00:00Z",
            ),
        )
        self.db.execute(
            """INSERT INTO oracle_research_dataset_provider_lineage
               (dataset_version_id,ticker,provider,
                requested_source_session_date,first_available_date,
                last_available_date,source_row_count,source_checksum_sha256,
                created_at_utc) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "research-1", "AAA", "YAHOO_FINANCE", "2026-08-25",
                "2026-08-22", "2026-08-25", 4, "f" * 64,
                "2026-08-26T07:00:00Z",
            ),
        )
        self.db.execute(
            """INSERT INTO oracle_research_dataset_events
               (event_id,dataset_version_id,event_type,
                market_snapshot_checksum_sha256,content_sha256,
                ticker_universe_sha256,provider_lineage_sha256,actor,
                decided_at_utc,evidence_sha256,created_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "freeze-1", "research-1", "FREEZE", "a" * 64, "b" * 64,
                "c" * 64, "d" * 64, "owner", "2026-08-26T07:40:43Z",
                "e" * 64, "2026-08-26T07:40:43Z",
            ),
        )
        self.db.execute(
            """UPDATE oracle_research_dataset_versions
               SET status='FROZEN',freeze_approval_id='freeze-1',
                   frozen_by='owner',frozen_at_utc='2026-08-26T07:40:43Z'
               WHERE dataset_version_id='research-1'"""
        )
        self.db.commit()

    def assert_abort(self, sql, params=()):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql, params)
        self.db.rollback()

    def test_review_only_and_no_data_or_destructive_statement(self):
        raw = sql_text()
        self.assertIn("DO NOT APPLY without explicit production schema approval", raw)
        statements = [
            line.strip().upper()
            for line in raw.splitlines()
            if line.strip() and not line.lstrip().startswith("--")
        ]
        forbidden = re.compile(r"^(INSERT\s+INTO|DELETE\s+FROM|DROP\s+|ALTER\s+)")
        self.assertFalse([line for line in statements if forbidden.match(line)])

    def test_preserves_exact_snapshot_counts_checksums_sessions_and_provider_lineage(self):
        sql = normalized_sql()
        for table in (
            "ORACLE_RESEARCH_DATASET_VERSIONS",
            "ORACLE_RESEARCH_DATASET_PROVIDER_LINEAGE",
            "ORACLE_RESEARCH_DATASET_EVENTS",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql)
        for field in (
            "MARKET_SNAPSHOT_ID",
            "MARKET_SNAPSHOT_CHECKSUM_SHA256",
            "SOURCE_SESSION_DATE",
            "EXPECTED_ROW_COUNT",
            "EXPECTED_TICKER_COUNT",
            "EXPECTED_SESSION_COUNT",
            "EXPECTED_PROVIDER_LINEAGE_COUNT",
            "CONTENT_SHA256",
            "TICKER_UNIVERSE_SHA256",
            "PROVIDER_LINEAGE_SHA256",
            "SOURCE_CHECKSUM_SHA256",
        ):
            self.assertIn(field, sql)

    def test_frozen_dataset_and_bound_source_tables_have_immutability_guards(self):
        sql = normalized_sql()
        for table in (
            "ORACLE_RESEARCH_DATASET_VERSIONS",
            "ORACLE_RESEARCH_DATASET_PROVIDER_LINEAGE",
            "ORACLE_RESEARCH_DATASET_EVENTS",
            "MODEL_INPUT_SNAPSHOTS",
            "MARKET_DAILY_FEATURES",
            "MARKET_DATA_PROVIDER_LINEAGE",
        ):
            self.assertIn(f" ON {table}", sql)
        self.assertIn("WHEN OLD.STATUS = 'FROZEN'", sql)
        self.assertIn("STATUS = 'FROZEN'", sql)
        self.assertGreaterEqual(sql.count("SELECT RAISE(ABORT"), 10)

    def test_freeze_requires_identity_actor_time_and_event_evidence(self):
        sql = normalized_sql()
        self.assertIn("STATUS IN ('STAGING', 'FROZEN')", sql)
        self.assertIn("EVENT_TYPE IN ('FREEZE', 'REVOKE')", sql)
        self.assertIn("FREEZE_APPROVAL_ID IS NOT NULL", sql)
        self.assertIn("FROZEN_BY IS NOT NULL", sql)
        self.assertIn("FROZEN_AT_UTC IS NOT NULL", sql)
        self.assertIn("EVIDENCE_SHA256 TEXT NOT NULL", sql)
        self.assertIn("WHERE EVENT_TYPE = 'FREEZE'", sql)

    def test_in_memory_migration_executes_without_production_state(self):
        tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue(
            {
                "oracle_research_dataset_versions",
                "oracle_research_dataset_provider_lineage",
                "oracle_research_dataset_events",
            }.issubset(tables)
        )

    def test_all_frozen_bound_surfaces_abort_but_unrelated_source_remains_writable(self):
        self.freeze_fixture()

        # Frozen version metadata cannot be inserted directly, updated, or deleted.
        self.assert_abort(
            """INSERT INTO oracle_research_dataset_versions
               (dataset_version_id,market_snapshot_id,
                market_snapshot_checksum_sha256,source_session_date,
                evidence_cutoff_utc,first_session_date,last_session_date,
                expected_row_count,expected_ticker_count,expected_session_count,
                expected_provider_lineage_count,content_sha256,
                ticker_universe_sha256,provider_lineage_sha256,schema_version,
                code_version,status,freeze_approval_id,frozen_by,frozen_at_utc,
                created_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "research-direct-frozen", "market-other", "a" * 64,
                "2026-08-25", "2026-08-26T06:44:37Z", "2026-08-25",
                "2026-08-25", 1, 1, 1, 1, "b" * 64, "c" * 64,
                "d" * 64, "schema-1", "code-1", "FROZEN", "freeze-x",
                "owner", "2026-08-26T07:40:43Z", "2026-08-26T07:00:00Z",
            ),
        )
        self.assert_abort(
            "UPDATE oracle_research_dataset_versions SET code_version='changed' "
            "WHERE dataset_version_id='research-1'"
        )
        self.assert_abort(
            "DELETE FROM oracle_research_dataset_versions "
            "WHERE dataset_version_id='research-1'"
        )

        # Frozen provider bindings reject insertion, mutation, and deletion.
        self.assert_abort(
            """INSERT INTO oracle_research_dataset_provider_lineage
               (dataset_version_id,ticker,provider,
                requested_source_session_date,first_available_date,
                last_available_date,source_row_count,source_checksum_sha256,
                created_at_utc) VALUES
               ('research-1','CCC','YAHOO_FINANCE','2026-08-25','2026-08-22',
                '2026-08-25',4,?, '2026-08-26T07:00:00Z')""",
            ("f" * 64,),
        )
        self.assert_abort(
            "UPDATE oracle_research_dataset_provider_lineage SET source_row_count=5 "
            "WHERE dataset_version_id='research-1' AND ticker='AAA'"
        )
        self.assert_abort(
            "DELETE FROM oracle_research_dataset_provider_lineage "
            "WHERE dataset_version_id='research-1' AND ticker='AAA'"
        )

        # Freeze evidence is append-only; duplicate freeze insertion and all
        # mutation/deletion of the existing event abort. REVOKE remains a
        # separately append-only event type by design.
        self.assert_abort(
            """INSERT INTO oracle_research_dataset_events
               (event_id,dataset_version_id,event_type,
                market_snapshot_checksum_sha256,content_sha256,
                ticker_universe_sha256,provider_lineage_sha256,actor,
                decided_at_utc,evidence_sha256,created_at_utc)
               VALUES ('freeze-2','research-1','FREEZE',?,?,?,?,?,?,?,?)""",
            (
                "a" * 64, "b" * 64, "c" * 64, "d" * 64, "owner",
                "2026-08-26T07:41:00Z", "e" * 64, "2026-08-26T07:41:00Z",
            ),
        )
        self.assert_abort(
            "UPDATE oracle_research_dataset_events SET actor='changed' "
            "WHERE event_id='freeze-1'"
        )
        self.assert_abort(
            "DELETE FROM oracle_research_dataset_events WHERE event_id='freeze-1'"
        )

        # Every bound source surface is protected.
        self.assert_abort(
            "UPDATE model_input_snapshots SET note='changed' "
            "WHERE snapshot_id='market-bound'"
        )
        self.assert_abort(
            "DELETE FROM model_input_snapshots WHERE snapshot_id='market-bound'"
        )
        self.assert_abort(
            "INSERT INTO market_daily_features VALUES "
            "('market-bound','AAA','2026-08-24',3.0)"
        )
        self.assert_abort(
            "UPDATE market_daily_features SET value=3.0 "
            "WHERE snapshot_id='market-bound'"
        )
        self.assert_abort(
            "DELETE FROM market_daily_features WHERE snapshot_id='market-bound'"
        )
        self.assert_abort(
            """INSERT INTO market_data_provider_lineage VALUES
               ('market-bound','CCC','YAHOO_FINANCE','2026-08-25','2026-08-22',
                '2026-08-25',4,?,'2026-08-26T06:30:00Z')""",
            ("f" * 64,),
        )
        self.assert_abort(
            "UPDATE market_data_provider_lineage SET source_row_count=5 "
            "WHERE snapshot_id='market-bound'"
        )
        self.assert_abort(
            "DELETE FROM market_data_provider_lineage WHERE snapshot_id='market-bound'"
        )

        # The guards are scoped: unrelated source metadata and rows remain writable.
        self.db.execute(
            "UPDATE model_input_snapshots SET note='updated' "
            "WHERE snapshot_id='market-other'"
        )
        self.db.execute(
            "INSERT INTO market_daily_features VALUES "
            "('market-other','BBB','2026-08-24',4.0)"
        )
        self.db.execute(
            "UPDATE market_daily_features SET value=5.0 "
            "WHERE snapshot_id='market-other' AND date='2026-08-24'"
        )
        self.db.execute(
            "DELETE FROM market_daily_features "
            "WHERE snapshot_id='market-other' AND date='2026-08-24'"
        )
        self.db.execute(
            "UPDATE market_data_provider_lineage SET source_row_count=5 "
            "WHERE snapshot_id='market-other'"
        )
        self.db.execute(
            "DELETE FROM market_data_provider_lineage WHERE snapshot_id='market-other'"
        )
        self.db.execute(
            """INSERT INTO market_data_provider_lineage VALUES
               ('market-other','BBB','TIINGO_EOD','2026-08-25','2026-08-22',
                '2026-08-25',4,?,'2026-08-26T06:30:00Z')""",
            ("f" * 64,),
        )
        self.db.commit()
        self.assertEqual(
            self.db.execute(
                "SELECT note FROM model_input_snapshots WHERE snapshot_id='market-other'"
            ).fetchone()[0],
            "updated",
        )


if __name__ == "__main__":
    unittest.main()
