import unittest
from unittest.mock import patch

import database_manager
from model_lineage import LineageError
from turso_read_pipeline import PipelineResult


class FakeReadPipeline:
    instances = []

    def __init__(self, endpoint, token):
        self.endpoint = endpoint
        self.token = token
        self.calls = []
        type(self).instances.append(self)

    def execute(self, query, args):
        self.calls.append((query, list(args)))
        return PipelineResult(
            columns=["persona", "date"],
            rows=[["BallsForBrains", "2026-08-24"]],
        )


class DatabaseManagerReadTransportTests(unittest.TestCase):
    def setUp(self):
        self.original_url = database_manager.TURSO_URL
        self.original_token = database_manager.TURSO_TOKEN
        database_manager.TURSO_URL = "libsql://theoracle.example.turso.io"
        database_manager.TURSO_TOKEN = "read-only-test-token"
        database_manager._local.read_client = None
        database_manager._local.read_endpoint = None
        FakeReadPipeline.instances = []

    def tearDown(self):
        database_manager._local.read_client = None
        database_manager._local.read_endpoint = None
        database_manager.TURSO_URL = self.original_url
        database_manager.TURSO_TOKEN = self.original_token

    def test_execute_query_uses_https_pipeline_and_preserves_dataframe_contract(self):
        with patch.object(database_manager, "TursoReadPipeline", FakeReadPipeline):
            frame = database_manager.execute_query(
                "SELECT persona,date FROM capital_ledgers WHERE persona=?",
                ["BallsForBrains"],
            )
        self.assertEqual(len(FakeReadPipeline.instances), 1)
        client = FakeReadPipeline.instances[0]
        self.assertEqual(
            client.endpoint,
            "https://theoracle.example.turso.io/v2/pipeline",
        )
        self.assertEqual(
            client.calls,
            [(
                "SELECT persona,date FROM capital_ledgers WHERE persona=?",
                ["BallsForBrains"],
            )],
        )
        self.assertEqual(frame.columns.tolist(), ["persona", "date"])
        self.assertEqual(frame.iloc[0].to_dict(), {
            "persona": "BallsForBrains",
            "date": "2026-08-24",
        })

    def test_read_adapter_is_reused_per_thread_without_legacy_connection(self):
        with patch.object(database_manager, "TursoReadPipeline", FakeReadPipeline), patch.object(
            database_manager, "get_connection", side_effect=AssertionError("legacy transport used")
        ):
            database_manager.execute_query("SELECT 1")
            database_manager.execute_query("SELECT 2")
        self.assertEqual(len(FakeReadPipeline.instances), 1)
        self.assertEqual(len(FakeReadPipeline.instances[0].calls), 2)

    def test_existing_pipeline_suffix_is_not_duplicated(self):
        self.assertEqual(
            database_manager._https_pipeline_endpoint(
                "https://theoracle.example.turso.io/v2/pipeline"
            ),
            "https://theoracle.example.turso.io/v2/pipeline",
        )

    def test_invalid_or_missing_read_configuration_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "libsql:// or https://"):
            database_manager._https_pipeline_endpoint("ws://example.invalid")
        database_manager.TURSO_TOKEN = None
        with self.assertRaisesRegex(ValueError, "Missing TURSO credentials"):
            database_manager.get_read_connection()

    def test_cli_cleanup_releases_https_read_reference(self):
        database_manager._local.read_client = object()
        database_manager._local.read_endpoint = "https://example/v2/pipeline"
        database_manager.close_connection_for_cli_exit()
        self.assertIsNone(database_manager._local.read_client)
        self.assertIsNone(database_manager._local.read_endpoint)


if __name__ == "__main__":
    unittest.main()
