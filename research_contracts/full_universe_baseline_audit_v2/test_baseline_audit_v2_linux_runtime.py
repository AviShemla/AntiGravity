from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import unittest
from unittest import mock

import baseline_audit_v2_linux_runtime as subject

OUTPUT_PATH = Path("C:/var/lib/codex/audit/evidence.json") if os.name == "nt" else Path("/var/lib/codex/audit/evidence.json")
CREDENTIAL_PATH = Path("C:/run/credentials/turso.env") if os.name == "nt" else Path("/run/credentials/turso.env")


@dataclass(frozen=True)
class Result:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


@dataclass(frozen=True)
class LiveReadback:
    observed_at_utc: str
    effective_identity: str
    database_name: str
    snapshot_id: str
    source_session_date: str
    sessions: tuple[str, ...]
    session_sha256: str
    downstream_counts: dict[str, int]
    select_statement_count: int
    database_write_count: int


class FakeVerifier:
    SNAPSHOT_ID = "market_features_2026-08-25_5b1044ee45605a3d"
    SOURCE_SESSION_DATE = "2026-08-25"
    EXPECTED_SESSIONS = 1_246
    LiveReadback = LiveReadback
    canonical_bytes = staticmethod(subject.canonical_bytes)
    sha256 = staticmethod(subject.sha256)


class FakeDB:
    def __init__(self, *, present=subject.DOWNSTREAM_TABLES, bad_count=None, fail=None):
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.write_calls = 0
        self.present = tuple(present)
        self.bad_count = bad_count
        self.fail = fail

    def execute(self, sql, args):
        self.calls.append((sql, tuple(args)))
        if self.fail and len(self.calls) == self.fail:
            raise RuntimeError("secret-token-marker")
        if len(self.calls) == 1:
            start = date(2023, 3, 29)
            dates = tuple((start + timedelta(days=i)).isoformat() for i in range(1_246))
            return Result(
                ("snapshot_id", "source_session_date", "date"),
                tuple((FakeVerifier.SNAPSHOT_ID, FakeVerifier.SOURCE_SESSION_DATE, item) for item in dates),
            )
        if len(self.calls) == 2:
            return Result(("name", "type"), tuple((name, "table") for name in self.present))
        if len(self.calls) == 3:
            values = [0 for _ in subject.DOWNSTREAM_TABLES]
            if self.bad_count is not None:
                values[subject.DOWNSTREAM_TABLES.index(self.bad_count)] = 1
            return Result(subject.DOWNSTREAM_TABLES, (tuple(values),))
        raise AssertionError("more than three database calls")


def release_fixture():
    artifacts = {
        "baseline_audit_v2_linux_runtime.py": b"runtime",
        "test_baseline_audit_v2_linux_runtime.py": b"runtime-tests",
        "audit_only_baseline_v2.py": b"verifier",
        "test_audit_only_baseline_v2.py": b"verifier-tests",
        "audit_full_universe_simple_baselines.py": b"semantic-auditor",
    }
    verifier_release = b'{"fixture":"externally-reviewed-verifier-release"}'
    runtime_release = subject.build_runtime_release_manifest(
        runtime_bytes=artifacts["baseline_audit_v2_linux_runtime.py"],
        runtime_test_bytes=artifacts["test_baseline_audit_v2_linux_runtime.py"],
        verifier_module_bytes=artifacts["audit_only_baseline_v2.py"],
        verifier_test_bytes=artifacts["test_audit_only_baseline_v2.py"],
        semantic_auditor_bytes=artifacts["audit_full_universe_simple_baselines.py"],
        verifier_release_manifest_sha256=subject.sha256(verifier_release),
        runtime_integration_git_commit="1" * 40,
    )
    pin = subject.canonical_bytes({
        "contract_id": subject.EXTERNAL_PIN_CONTRACT_ID,
        "canonical_git_commit": subject.CANONICAL_GIT_COMMIT,
        "runtime_integration_git_commit": "1" * 40,
        "runtime_release_manifest_sha256": subject.sha256(runtime_release),
        "verifier_release_manifest_sha256": subject.sha256(verifier_release),
        "scope": "EXACT_THREE_SELECTS_BASELINE_AUDIT_ONLY",
        "database_write_authorized": False,
        "producer_rerun_authorized": False,
        "model_run_authorized": False,
        "successor_authorized": False,
    })
    return artifacts, verifier_release, runtime_release, pin


class SelectBoundaryTests(unittest.TestCase):
    def test_exactly_three_selects_and_zero_writes(self):
        db = FakeDB()
        live = subject.execute_three_selects(
            db=db, subject=FakeVerifier,
            now=lambda: datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(db.calls), 3)
        self.assertEqual(db.write_calls, 0)
        self.assertEqual(live.select_statement_count, 3)
        self.assertEqual(live.database_write_count, 0)
        self.assertEqual(set(live.downstream_counts), set(subject.DOWNSTREAM_TABLES))
        self.assertTrue(all(value == 0 for value in live.downstream_counts.values()))
        for sql, _args in db.calls:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"))
            self.assertIsNone(subject._FORBIDDEN_SQL.search(sql))
            self.assertNotIn(";", sql)

    def test_dataset_query_arguments_are_exact(self):
        db = FakeDB()
        subject.execute_three_selects(
            db=db, subject=FakeVerifier,
            now=lambda: datetime.now(timezone.utc),
        )
        self.assertEqual(db.calls[0], (subject.DATASET_SESSION_SQL, (FakeVerifier.SNAPSHOT_ID,)))
        self.assertEqual(db.calls[1], (subject.SCHEMA_SQL, subject.DOWNSTREAM_TABLES))
        self.assertEqual(db.calls[2][1], ())

    def test_absent_downstream_tables_are_explicit_zero_literals(self):
        db = FakeDB(present=())
        live = subject.execute_three_selects(
            db=db, subject=FakeVerifier, now=lambda: datetime.now(timezone.utc)
        )
        self.assertTrue(all(value == 0 for value in live.downstream_counts.values()))
        self.assertNotIn("FROM model_runs", db.calls[2][0])

    def test_one_nonzero_downstream_count_fails(self):
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "downstream output exists"):
            subject.execute_three_selects(
                db=FakeDB(bad_count="model_runs"), subject=FakeVerifier,
                now=lambda: datetime.now(timezone.utc),
            )

    def test_wrong_session_count_fails_before_second_query(self):
        db = FakeDB()
        original = db.execute
        def short(sql, args):
            result = original(sql, args)
            if len(db.calls) == 1:
                return replace(result, rows=result.rows[:-1])
            return result
        db.execute = short
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "count differs"):
            subject.execute_three_selects(db=db, subject=FakeVerifier, now=lambda: datetime.now(timezone.utc))
        self.assertEqual(len(db.calls), 1)

    def test_wrong_dataset_identity_fails(self):
        db = FakeDB()
        original = db.execute
        def tamper(sql, args):
            result = original(sql, args)
            if len(db.calls) == 1:
                rows = list(result.rows)
                rows[0] = ("wrong", rows[0][1], rows[0][2])
                return replace(result, rows=tuple(rows))
            return result
        db.execute = tamper
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "identity differs"):
            subject.execute_three_selects(db=db, subject=FakeVerifier, now=lambda: datetime.now(timezone.utc))

    def test_duplicate_schema_row_fails(self):
        db = FakeDB(present=("model_runs", "model_runs"))
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "schema differs"):
            subject.execute_three_selects(db=db, subject=FakeVerifier, now=lambda: datetime.now(timezone.utc))

    def test_write_tokens_are_rejected(self):
        for sql in ("UPDATE x SET y=1", "SELECT 1; DELETE FROM x", " PRAGMA table_info(x)"):
            with self.subTest(sql=sql), self.assertRaises(subject.RuntimeBoundaryError):
                subject._assert_select(sql, sql)

    def test_arbitrary_select_is_rejected_against_allowlist(self):
        with self.assertRaises(subject.RuntimeBoundaryError):
            subject._assert_select("SELECT 1", subject.DATASET_SESSION_SQL)

    def test_database_error_is_token_redacted(self):
        with self.assertRaises(subject.RuntimeBoundaryError) as caught:
            subject.execute_three_selects(
                db=FakeDB(fail=1), subject=FakeVerifier,
                now=lambda: datetime.now(timezone.utc),
            )
        self.assertNotIn("secret-token-marker", str(caught.exception))
        self.assertEqual(str(caught.exception), "Turso SELECT failed")


class IdentityTests(unittest.TestCase):
    @dataclass
    class User:
        pw_name: str

    @dataclass
    class Completed:
        returncode: int = 0
        stdout: str = "avishe\n"
        stderr: str = ""

    def test_exact_codexops_and_avishe(self):
        calls = []
        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            return self.Completed()
        identity = subject.verify_effective_identity(
            effective_uid=lambda: 1234,
            user_lookup=lambda _uid: self.User("codexops"),
            command_runner=runner,
        )
        self.assertEqual(identity, "os=codexops;turso=avishe")
        self.assertEqual(calls[0][0][0], [str(subject.TURSO_CLI), "auth", "whoami"])
        self.assertEqual(calls[0][1]["timeout"], 10.0)
        self.assertFalse(calls[0][1]["shell"] if "shell" in calls[0][1] else False)

    def test_root_is_rejected_even_if_turso_identity_matches(self):
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "OS identity"):
            subject.verify_effective_identity(
                effective_uid=lambda: 0,
                user_lookup=lambda _uid: self.User("root"),
                command_runner=lambda *a, **k: self.Completed(),
            )

    def test_wrong_turso_user_is_rejected(self):
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "Turso identity differs"):
            subject.verify_effective_identity(
                effective_uid=lambda: 1234,
                user_lookup=lambda _uid: self.User("codexops"),
                command_runner=lambda *a, **k: self.Completed(stdout="someone-else\n"),
            )

    def test_identity_probe_timeout_is_redacted(self):
        def timeout(*_a, **_k):
            raise subprocess.TimeoutExpired("secret-token-marker", 10)
        import subprocess
        with self.assertRaises(subject.RuntimeBoundaryError) as caught:
            subject.verify_effective_identity(
                effective_uid=lambda: 1234,
                user_lookup=lambda _uid: self.User("codexops"),
                command_runner=timeout,
            )
        self.assertNotIn("secret-token-marker", str(caught.exception))


class ReleaseTests(unittest.TestCase):
    def test_external_pin_and_artifact_closure_pass(self):
        artifacts, verifier, release, pin = release_fixture()
        runtime_sha, verifier_sha = subject._validate_external_closure(
            pin_bytes=pin, runtime_release_bytes=release,
            verifier_release_bytes=verifier, artifact_bytes=artifacts,
        )
        self.assertEqual(runtime_sha, subject.sha256(release))
        self.assertEqual(verifier_sha, subject.sha256(verifier))

    def test_tampered_artifact_fails(self):
        artifacts, verifier, release, pin = release_fixture()
        artifacts["audit_only_baseline_v2.py"] += b"tamper"
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "artifact bytes differ"):
            subject._validate_external_closure(
                pin_bytes=pin, runtime_release_bytes=release,
                verifier_release_bytes=verifier, artifact_bytes=artifacts,
            )

    def test_tampered_release_fails_external_pin(self):
        artifacts, verifier, release, pin = release_fixture()
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "external release pin differs"):
            subject._validate_external_closure(
                pin_bytes=pin, runtime_release_bytes=release + b"x",
                verifier_release_bytes=verifier, artifact_bytes=artifacts,
            )

    def test_caller_cannot_enable_write_or_successor(self):
        artifacts, verifier, release, pin = release_fixture()
        payload = json.loads(pin)
        for key in ("database_write_authorized", "producer_rerun_authorized", "model_run_authorized", "successor_authorized"):
            with self.subTest(key=key):
                changed = dict(payload)
                changed[key] = True
                with self.assertRaisesRegex(subject.RuntimeBoundaryError, "boundary differs"):
                    subject._validate_external_closure(
                        pin_bytes=subject.canonical_bytes(changed),
                        runtime_release_bytes=release,
                        verifier_release_bytes=verifier,
                        artifact_bytes=artifacts,
                    )

    def test_wrong_commit_fails(self):
        artifacts, verifier, release, pin = release_fixture()
        payload = json.loads(pin)
        payload["canonical_git_commit"] = "f" * 40
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "boundary differs"):
            subject._validate_external_closure(
                pin_bytes=subject.canonical_bytes(payload), runtime_release_bytes=release,
                verifier_release_bytes=verifier, artifact_bytes=artifacts,
            )

    def test_runtime_release_cannot_claim_unintegrated_base_commit(self):
        artifacts, verifier, _release, _pin = release_fixture()
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "not yet distinct"):
            subject.build_runtime_release_manifest(
                runtime_bytes=artifacts["baseline_audit_v2_linux_runtime.py"],
                runtime_test_bytes=artifacts["test_baseline_audit_v2_linux_runtime.py"],
                verifier_module_bytes=artifacts["audit_only_baseline_v2.py"],
                verifier_test_bytes=artifacts["test_audit_only_baseline_v2.py"],
                semantic_auditor_bytes=artifacts["audit_full_universe_simple_baselines.py"],
                verifier_release_manifest_sha256=subject.sha256(verifier),
                runtime_integration_git_commit=subject.CANONICAL_GIT_COMMIT,
            )

    def test_release_binds_timeout(self):
        artifacts, verifier, release, pin = release_fixture()
        payload = json.loads(release)
        self.assertEqual(payload["timeout_seconds"], 120.0)
        payload["timeout_seconds"] = 300.0
        changed = subject.canonical_bytes(payload)
        pin_payload = json.loads(pin)
        pin_payload["runtime_release_manifest_sha256"] = subject.sha256(changed)
        with self.assertRaisesRegex(subject.RuntimeBoundaryError, "boundary differs"):
            subject._validate_external_closure(
                pin_bytes=subject.canonical_bytes(pin_payload),
                runtime_release_bytes=changed,
                verifier_release_bytes=verifier, artifact_bytes=artifacts,
            )


class FilesystemTests(unittest.TestCase):
    def test_credentials_are_codexops_owned_0400_and_exact(self):
        metadata = mock.Mock(st_uid=777, st_mode=stat.S_IFREG | 0o400, st_nlink=1)
        raw = b"TURSO_DATABASE_URL=libsql://theoracle.example\nTURSO_AUTH_TOKEN=secret-token-marker\n"
        with (
            mock.patch.object(subject, "_os_effective_uid", return_value=777),
            mock.patch.object(subject, "_O_NOFOLLOW", 0x20000),
            mock.patch.object(subject.os, "open", return_value=9),
            mock.patch.object(subject.os, "fstat", return_value=metadata),
            mock.patch.object(subject.os, "read", side_effect=[raw, b""]),
            mock.patch.object(subject.os, "close"),
        ):
            endpoint, token = subject.read_codexops_credentials(CREDENTIAL_PATH)
        self.assertEqual(endpoint, "libsql://theoracle.example")
        self.assertEqual(token, "secret-token-marker")

    def test_root_owned_credential_is_rejected_for_codexops_service(self):
        metadata = mock.Mock(st_uid=0, st_mode=stat.S_IFREG | 0o400, st_nlink=1)
        with (
            mock.patch.object(subject, "_os_effective_uid", return_value=777),
            mock.patch.object(subject, "_O_NOFOLLOW", 0x20000),
            mock.patch.object(subject.os, "open", return_value=9),
            mock.patch.object(subject.os, "fstat", return_value=metadata),
            mock.patch.object(subject.os, "close"),
            self.assertRaisesRegex(subject.RuntimeBoundaryError, "ownership or mode differs"),
        ):
            subject.read_codexops_credentials(CREDENTIAL_PATH)

    def test_credential_duplicate_or_extra_key_is_rejected_without_echo(self):
        metadata = mock.Mock(st_uid=777, st_mode=stat.S_IFREG | 0o400, st_nlink=1)
        raw = b"TURSO_DATABASE_URL=x\nTURSO_AUTH_TOKEN=secret-token-marker\nEXTRA=y\n"
        with (
            mock.patch.object(subject, "_os_effective_uid", return_value=777),
            mock.patch.object(subject, "_O_NOFOLLOW", 0x20000),
            mock.patch.object(subject.os, "open", return_value=9),
            mock.patch.object(subject.os, "fstat", return_value=metadata),
            mock.patch.object(subject.os, "read", side_effect=[raw, b""]),
            mock.patch.object(subject.os, "close"),
            self.assertRaises(subject.RuntimeBoundaryError) as caught,
        ):
            subject.read_codexops_credentials(CREDENTIAL_PATH)
        self.assertNotIn("secret-token-marker", str(caught.exception))

    def test_append_once_uses_exclusive_nofollow_and_fsync(self):
        metadata = mock.Mock(st_uid=777, st_mode=stat.S_IFDIR | 0o700)
        with (
            mock.patch.object(subject, "_os_effective_uid", return_value=777),
            mock.patch.object(subject, "_O_NOFOLLOW", 0x20000),
            mock.patch.object(subject.os, "lstat", return_value=metadata),
            mock.patch.object(subject.os, "open", return_value=9) as opened,
            mock.patch.object(subject.os, "write", return_value=3) as wrote,
            mock.patch.object(subject.os, "fsync") as fsync,
            mock.patch.object(subject.os, "close") as close,
        ):
            digest = subject._append_once(OUTPUT_PATH, {"safe": True})
        flags = opened.call_args.args[1]
        self.assertTrue(flags & os.O_EXCL)
        self.assertTrue(flags & 0x20000)
        self.assertTrue(flags & os.O_CREAT)
        self.assertEqual(opened.call_args.args[2], 0o600)
        wrote.assert_called_once()
        fsync.assert_called_once_with(9)
        close.assert_called_once_with(9)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_append_refuses_wrong_owner(self):
        metadata = mock.Mock(st_uid=0, st_mode=stat.S_IFDIR | 0o700)
        with (
            mock.patch.object(subject, "_os_effective_uid", return_value=777),
            mock.patch.object(subject, "_O_NOFOLLOW", 0x20000),
            mock.patch.object(subject.os, "lstat", return_value=metadata),
            self.assertRaisesRegex(subject.RuntimeBoundaryError, "ownership or mode differs"),
        ):
            subject._append_once(OUTPUT_PATH, {"safe": True})

    def test_append_does_not_truncate_existing_file(self):
        metadata = mock.Mock(st_uid=777, st_mode=stat.S_IFDIR | 0o700)
        with (
            mock.patch.object(subject, "_os_effective_uid", return_value=777),
            mock.patch.object(subject, "_O_NOFOLLOW", 0x20000),
            mock.patch.object(subject.os, "lstat", return_value=metadata),
            mock.patch.object(subject.os, "open", side_effect=FileExistsError),
            self.assertRaises(FileExistsError),
        ):
            subject._append_once(OUTPUT_PATH, {"safe": True})


class StaticBoundaryTests(unittest.TestCase):
    def test_no_local_database_or_fallback_import(self):
        raw = Path(subject.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import sqlite3", raw)
        self.assertNotIn("import pandas", raw)
        self.assertNotIn(".csv", raw.lower())
        self.assertNotIn("openpyxl", raw.lower())

    def test_three_queries_are_select_only(self):
        self.assertEqual(subject.EXPECTED_SELECT_COUNT, 3)
        for sql in (subject.DATASET_SESSION_SQL, subject.SCHEMA_SQL, subject._count_sql(set(subject.DOWNSTREAM_TABLES))):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"))
            self.assertIsNone(subject._FORBIDDEN_SQL.search(sql))
            self.assertNotIn(";", sql)

    def test_bytecode_writes_are_disabled(self):
        self.assertTrue(subject.sys.dont_write_bytecode)


if __name__ == "__main__":
    unittest.main()
