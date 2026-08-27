from __future__ import annotations

import json
import os
import shutil
import signal
import threading
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import stage_runner
from stage_runner import (
    StageRunnerError,
    atomic_progress_write,
    canonical_bytes,
    progress_evidence,
    supervise,
)


HERE = Path(__file__).resolve().parent


@contextmanager
def writable_directory():
    path = HERE / "_test_work" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        if os.name != "nt":
            path.chmod(0o700)
        yield path
    finally:
        shutil.rmtree(path)


def make_payload(root: Path, body: str) -> str:
    payload = root / "payload" / "run-test-impl"
    payload.parent.mkdir(mode=0o700)
    payload.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    payload.chmod(0o700)
    return "payload/run-test-impl"


class AtomicProgressTests(unittest.TestCase):
    def evidence(self, **updates):
        raw = progress_evidence(
            source_session="2026-08-27", stage="INGESTION", status="ACTIVE",
            main_pid=123, invocation_id="invocation", code_version="a" * 64,
            completed_units=0, total_units=1,
            now=datetime(2026, 8, 27, 1, tzinfo=timezone.utc),
        )
        raw.update(updates)
        return raw

    def test_atomic_marker_is_canonical_mode_0600_and_single_link(self):
        with writable_directory() as root:
            marker = root / "session" / "progress.json"
            atomic_progress_write(marker, self.evidence())
            encoded = marker.read_bytes()
            self.assertEqual(encoded, canonical_bytes(json.loads(encoded)))
            self.assertEqual(marker.stat().st_nlink, 1)
            if os.name != "nt":
                self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(marker.parent.glob(".*.tmp")), [])

    def test_atomic_marker_replaces_prior_complete_document(self):
        with writable_directory() as root:
            marker = root / "session" / "progress.json"
            atomic_progress_write(marker, self.evidence(completed_units=0))
            atomic_progress_write(marker, self.evidence(completed_units=1, status="SUCCEEDED"))
            self.assertEqual(json.loads(marker.read_text())["status"], "SUCCEEDED")

    def test_symlink_marker_rejected(self):
        with writable_directory() as root:
            session = root / "session"
            session.mkdir(mode=0o700)
            target = session / "target"
            target.write_text("x", encoding="utf-8")
            marker = session / "progress.json"
            try:
                marker.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(StageRunnerError):
                atomic_progress_write(marker, self.evidence())

    def test_invalid_progress_identity_rejected(self):
        with self.assertRaises(StageRunnerError):
            progress_evidence(
                source_session="bad", stage="INGESTION", status="ACTIVE",
                main_pid=1, invocation_id="x", code_version="a" * 64,
                completed_units=0, total_units=1,
            )


class SupervisorTests(unittest.TestCase):
    def run_payload(self, root: Path, body: str, **updates):
        args = dict(
            stage="INGESTION", relative_payload=make_payload(root, body),
            source_session="2026-08-27", progress_marker=root / "progress.json",
            code_version="a" * 64, payload_args=(), heartbeat_seconds=0.01,
            total_units=1, invocation_id="invocation", release_root=root,
        )
        args.update(updates)
        result = supervise(**args)
        return result, json.loads((root / "progress.json").read_text())

    def test_success_is_terminal_and_reconciled(self):
        with writable_directory() as root:
            result, marker = self.run_payload(root, "exit 0")
            self.assertEqual(result, 0)
            self.assertEqual((marker["status"], marker["completed_units"]), ("SUCCEEDED", 1))

    def test_failure_preserves_nonzero_exit_and_failed_marker(self):
        with writable_directory() as root:
            result, marker = self.run_payload(root, "exit 7")
            self.assertEqual(result, 7)
            self.assertEqual((marker["status"], marker["completed_units"]), ("FAILED", 0))

    def test_long_payload_refreshes_active_heartbeat(self):
        with writable_directory() as root:
            original = stage_runner.atomic_progress_write
            writes = []

            def observed(path, evidence):
                writes.append(evidence["status"])
                return original(path, evidence)

            with patch("stage_runner.atomic_progress_write", side_effect=observed):
                result, marker = self.run_payload(root, "sleep 0.06; exit 0")
            self.assertEqual(result, 0)
            self.assertGreaterEqual(writes.count("ACTIVE"), 2)
            self.assertEqual(marker["status"], "SUCCEEDED")

    def test_payload_symlink_rejected(self):
        with writable_directory() as root:
            payload_dir = root / "payload"
            payload_dir.mkdir(mode=0o700)
            target = root / "target"
            target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            target.chmod(0o700)
            payload = payload_dir / "run-test-impl"
            try:
                payload.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(StageRunnerError):
                supervise(
                    stage="INGESTION", relative_payload="payload/run-test-impl",
                    source_session="2026-08-27", progress_marker=root / "progress.json",
                    code_version="a" * 64, payload_args=(), heartbeat_seconds=1,
                    total_units=1, invocation_id="invocation", release_root=root,
                )

    def test_missing_invocation_id_fails_before_payload_launch(self):
        with writable_directory() as root:
            with self.assertRaises(StageRunnerError):
                self.run_payload(root, "touch should-not-exist", invocation_id="")
            self.assertFalse((root / "should-not-exist").exists())

    def test_shell_metacharacters_are_forwarded_without_shell(self):
        with writable_directory() as root:
            result, _ = self.run_payload(root, "exit 0", payload_args=(";touch", "escaped"))
            self.assertEqual(result, 0)
            self.assertFalse((root / "escaped").exists())

    @unittest.skipIf(os.name == "nt", "POSIX signal propagation contract")
    def test_termination_is_forwarded_and_persisted_as_failed(self):
        with writable_directory() as root:
            timer = threading.Timer(0.05, os.kill, args=(os.getpid(), signal.SIGTERM))
            timer.start()
            try:
                result, marker = self.run_payload(root, "sleep 10; exit 0")
            finally:
                timer.cancel()
            self.assertEqual(result, 128 + signal.SIGTERM)
            self.assertEqual(marker["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
