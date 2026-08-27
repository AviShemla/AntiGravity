from __future__ import annotations

import json
import os
import stat
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from . import market_ingestion_postflight_cli as cli_module
    from .market_ingestion_postflight import VisibilityPending
    from .market_ingestion_postflight_cli import (
        ALL_SELECTS,
        PostflightRuntimeError,
        PostflightVisibilityTimeout,
        build_handoff,
        load_runtime_values,
        normalize_turso_endpoint,
        read_and_reconcile_once,
        reconcile_with_bounded_retry,
        write_handoff_once,
    )
except ImportError:
    import market_ingestion_postflight_cli as cli_module  # type: ignore
    from market_ingestion_postflight import VisibilityPending  # type: ignore
    from market_ingestion_postflight_cli import (  # type: ignore
        ALL_SELECTS,
        PostflightRuntimeError,
        PostflightVisibilityTimeout,
        build_handoff,
        load_runtime_values,
        normalize_turso_endpoint,
        read_and_reconcile_once,
        reconcile_with_bounded_retry,
        write_handoff_once,
    )


class BoundedVisibilityTests(unittest.TestCase):
    def test_delayed_visibility_retries_bounded_then_succeeds(self):
        calls = 0
        sleeps: list[float] = []

        def read_once():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise VisibilityPending("not yet visible")
            return {"snapshot_id": "ready"}

        result = reconcile_with_bounded_retry(
            read_once, attempts=3, retry_seconds=2.5, sleep=sleeps.append
        )
        self.assertEqual({"snapshot_id": "ready"}, result)
        self.assertEqual(3, calls)
        self.assertEqual([2.5, 2.5], sleeps)

    def test_visibility_timeout_never_exceeds_attempt_bound(self):
        calls = 0

        def read_once():
            nonlocal calls
            calls += 1
            raise VisibilityPending("not yet visible")

        with self.assertRaises(PostflightVisibilityTimeout):
            reconcile_with_bounded_retry(
                read_once, attempts=4, retry_seconds=0, sleep=lambda _: None
            )
        self.assertEqual(4, calls)

    def test_deterministic_failure_is_not_retried(self):
        calls = 0

        def read_once():
            nonlocal calls
            calls += 1
            raise PostflightRuntimeError("bad contract")

        with self.assertRaises(PostflightRuntimeError):
            reconcile_with_bounded_retry(
                read_once, attempts=6, retry_seconds=0, sleep=lambda _: None
            )
        self.assertEqual(1, calls)


class RuntimeBoundaryTests(unittest.TestCase):
    class Result:
        def __init__(self, rows):
            self.rows = rows

    class ExactReader:
        def __init__(self, *, snapshot_visible=True):
            self.snapshot_visible = snapshot_visible
            self.queries: list[str] = []
            self.tickers = tuple(f"T{i:03d}" for i in range(474))

        def execute(self, query, args):
            self.queries.append(query)
            if query == ALL_SELECTS[0]:
                if not self.snapshot_visible:
                    return RuntimeBoundaryTests.Result([])
                return RuntimeBoundaryTests.Result(
                    [["snapshot", "STAGING", 587_184, 474, "a" * 64, "b" * 64]]
                )
            if query == ALL_SELECTS[1]:
                return RuntimeBoundaryTests.Result(
                    [[587_184, 474, "2021-09-08", "2026-08-26"]]
                )
            if query == ALL_SELECTS[2]:
                return RuntimeBoundaryTests.Result([[ticker] for ticker in self.tickers])
            if query == ALL_SELECTS[3]:
                return RuntimeBoundaryTests.Result(
                    [
                        [ticker, "2026-08-26"]
                        for ticker in sorted(set(self.tickers) | {"^TNX", "^VIX"})
                    ]
                )
            if query in (ALL_SELECTS[4], ALL_SELECTS[5]):
                return RuntimeBoundaryTests.Result([[0]])
            raise AssertionError(f"unexpected query: {query}")

    def test_select_only_reader_reconciles_exact_contract(self):
        reader = self.ExactReader()
        result = read_and_reconcile_once(
            reader,
            source_session="2026-08-26",
            expected_code_version="b" * 64,
            expected_snapshot_id="snapshot",
        )
        self.assertEqual(474, result["feature_tickers"])
        self.assertEqual(476, result["provider_lineage_rows"])
        self.assertEqual(list(ALL_SELECTS), reader.queries)

    def test_invisible_snapshot_is_retryable_visibility_only(self):
        reader = self.ExactReader(snapshot_visible=False)
        with self.assertRaises(VisibilityPending):
            read_and_reconcile_once(
                reader,
                source_session="2026-08-26",
                expected_code_version="b" * 64,
            )
        self.assertEqual([ALL_SELECTS[0]], reader.queries)

    def test_all_database_statements_are_select_only(self):
        self.assertTrue(ALL_SELECTS)
        for query in ALL_SELECTS:
            self.assertTrue(query.lstrip().upper().startswith("SELECT"))
            self.assertNotRegex(query.upper(), r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|REPLACE)\b")

    def test_endpoint_normalizer_prevents_bare_endpoint_regression(self):
        self.assertEqual(
            "https://example.turso.io/v2/pipeline",
            normalize_turso_endpoint("libsql://example.turso.io"),
        )
        self.assertEqual(
            "https://example.turso.io/v2/pipeline",
            normalize_turso_endpoint("https://example.turso.io/v2/pipeline"),
        )

    def test_non_https_endpoint_fails_closed(self):
        with self.assertRaises(PostflightRuntimeError):
            normalize_turso_endpoint("http://example.invalid")

    def test_env_file_requires_root_owned_mode_0600_on_posix(self):
        info = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o640,
            st_nlink=1,
            st_uid=0,
            st_gid=0,
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(cli_module.os, "name", "posix"),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "stat", return_value=info),
            patch.object(
                Path,
                "read_text",
                return_value="TURSO_DATABASE_URL=libsql://example.turso.io\n"
                "TURSO_AUTH_TOKEN=not-a-real-token\n",
            ),
        ):
            with self.assertRaisesRegex(PostflightRuntimeError, "mode must be 0600"):
                load_runtime_values(
                    endpoint_env="TURSO_DATABASE_URL",
                    token_env="TURSO_AUTH_TOKEN",
                    env_file=Path("ignored"),
                )

    def test_handoff_is_hash_bound_and_uses_create_once_mode_0600(self):
        result = {
            "snapshot_id": "snapshot",
            "status": "STAGING",
            "rows": 10,
            "feature_tickers": 2,
            "provider_lineage_rows": 4,
        }
        artifact = build_handoff(result, observed_at="2026-08-27T00:00:00+00:00")
        path = Path("handoff.json")
        handle = MagicMock()
        handle.__enter__.return_value = handle
        handle.__exit__.return_value = False
        handle.fileno.return_value = 123
        with (
            patch("pathlib.Path.mkdir"),
            patch("os.open", return_value=123) as open_mock,
            patch("os.fdopen", return_value=handle),
            patch("os.fsync") as fsync_mock,
        ):
            write_handoff_once(path, artifact)
        flags = open_mock.call_args.args[1]
        self.assertTrue(flags & os.O_CREAT)
        self.assertTrue(flags & os.O_EXCL)
        self.assertEqual(0o600, open_mock.call_args.args[2])
        written = handle.write.call_args.args[0]
        self.assertEqual(artifact, json.loads(written.decode("utf-8")))
        fsync_mock.assert_called_once_with(123)

    def test_existing_handoff_is_never_overwritten(self):
        artifact = build_handoff(
            {"snapshot_id": "snapshot"},
            observed_at="2026-08-27T00:00:00+00:00",
        )
        with patch("pathlib.Path.mkdir"), patch(
            "os.open", side_effect=FileExistsError("exists")
        ):
            with self.assertRaises(FileExistsError):
                write_handoff_once(Path("handoff.json"), artifact)


if __name__ == "__main__":
    unittest.main()
