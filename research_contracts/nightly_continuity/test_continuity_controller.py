from __future__ import annotations

import hashlib
import json
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from continuity_controller import (
    Action,
    ContractError,
    Session,
    SnapshotState,
    PriorityState,
    UnitState,
    append_event,
    assess_capacity,
    assess_liveness,
    canonical_bytes,
    decide,
    foreign_pipeline_units,
    latest_fully_completed_session,
    load_calendar,
    validate_snapshot_evidence,
    validate_priority,
    verify_handoff,
    verify_progress_marker,
    _secure_regular,
    _verify_installed_ingestion_priority,
)


IDLE = UnitState("loaded", "inactive", "dead", "success", 0, "")
ACTIVE = UnitState("loaded", "active", "running", "success", 1234, "abc")
FAILED = UnitState("loaded", "failed", "failed", "failed", 0, "def")
HERE = Path(__file__).resolve().parent


@contextmanager
def writable_directory():
    path = HERE / "_test_work" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path)


def snapshot(count=0, status=None, approvals=0, screenings=0):
    return SnapshotState(
        "2026-08-26", count, "snap-1" if count else None, status,
        approvals, screenings, 0, "SELECT_ONLY",
    )


class CalendarTests(unittest.TestCase):
    def test_latest_completed_uses_close_instants(self):
        sessions = (
            Session("2026-03-06", datetime(2026, 3, 6, 21, tzinfo=timezone.utc)),
            Session("2026-03-09", datetime(2026, 3, 9, 20, tzinfo=timezone.utc)),
        )
        chosen = latest_fully_completed_session(
            sessions, datetime(2026, 3, 10, 1, 30, tzinfo=timezone.utc),
            settlement_delay=timedelta(minutes=15),
        )
        self.assertEqual(chosen.session_date, "2026-03-09")

    def test_weekend_selects_friday(self):
        sessions = (Session("2026-08-28", datetime(2026, 8, 28, 20, tzinfo=timezone.utc)),)
        chosen = latest_fully_completed_session(
            sessions, datetime(2026, 8, 30, 0, tzinfo=timezone.utc),
            settlement_delay=timedelta(),
        )
        self.assertEqual(chosen.session_date, "2026-08-28")

    def test_settlement_delay_blocks_too_recent_close(self):
        sessions = (Session("2026-08-27", datetime(2026, 8, 27, 20, tzinfo=timezone.utc)),)
        with self.assertRaises(ContractError):
            latest_fully_completed_session(
                sessions, datetime(2026, 8, 27, 20, 5, tzinfo=timezone.utc),
                settlement_delay=timedelta(minutes=15),
            )

    def test_naive_now_rejected(self):
        with self.assertRaises(ContractError):
            latest_fully_completed_session([], datetime(2026, 1, 1), settlement_delay=timedelta())

    def test_negative_delay_rejected(self):
        with self.assertRaises(ContractError):
            latest_fully_completed_session([], datetime.now(timezone.utc), settlement_delay=timedelta(seconds=-1))

    def test_calendar_hash_and_contract(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "calendar.json"
            raw = {"contract_id": "codex-nyse-session-calendar-v1", "valid_through_utc": "2026-12-31T23:59:59Z", "sessions": [
                {"session_date": "2026-08-26", "close_utc": "2026-08-26T20:00:00Z"}
            ]}
            path.write_bytes(canonical_bytes(raw))
            rows = load_calendar(path, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(rows[0].session_date, "2026-08-26")

    def test_calendar_hash_mismatch_rejected(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "calendar.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ContractError):
                load_calendar(path, "0" * 64)

    def test_duplicate_calendar_session_rejected(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "calendar.json"
            row = {"session_date": "2026-08-26", "close_utc": "2026-08-26T20:00:00Z"}
            raw = {"contract_id": "codex-nyse-session-calendar-v1", "valid_through_utc": "2026-12-31T23:59:59Z", "sessions": [row, row]}
            path.write_bytes(canonical_bytes(raw))
            with self.assertRaises(ContractError):
                load_calendar(path, hashlib.sha256(path.read_bytes()).hexdigest())


class EvidenceTests(unittest.TestCase):
    def evidence(self, **updates):
        raw = {
            "contract_id": "codex-market-ingestion-idempotency-preflight-v1",
            "source_session": "2026-08-26", "query_mode": "SELECT_ONLY",
            "database_writes": 0, "statements": ["SELECT snapshot_id FROM x"],
            "snapshot_count": 0, "snapshot_id": None, "status": None,
            "approval_count": 0, "screening_count": 0,
        }
        raw.update(updates)
        return raw

    def test_empty_snapshot_evidence(self):
        self.assertEqual(validate_snapshot_evidence(self.evidence(), source_session="2026-08-26").snapshot_count, 0)

    def test_unique_staging_evidence(self):
        value = self.evidence(snapshot_count=1, snapshot_id="s", status="STAGING")
        self.assertEqual(validate_snapshot_evidence(value, source_session="2026-08-26").status, "STAGING")

    def test_non_select_rejected(self):
        with self.assertRaises(ContractError):
            validate_snapshot_evidence(self.evidence(statements=["UPDATE x SET y=1"]), source_session="2026-08-26")

    def test_declared_write_rejected(self):
        with self.assertRaises(ContractError):
            validate_snapshot_evidence(self.evidence(database_writes=1), source_session="2026-08-26")

    def test_duplicate_snapshot_rejected(self):
        with self.assertRaises(ContractError):
            validate_snapshot_evidence(self.evidence(snapshot_count=2), source_session="2026-08-26")

    def test_session_mismatch_rejected(self):
        with self.assertRaises(ContractError):
            validate_snapshot_evidence(self.evidence(source_session="2026-08-25"), source_session="2026-08-26")

    def test_absent_snapshot_with_id_rejected(self):
        with self.assertRaises(ContractError):
            validate_snapshot_evidence(self.evidence(snapshot_id="contradiction"), source_session="2026-08-26")

    def test_handoff_readback(self):
        with writable_directory() as tmp:
            evidence = {
                "source_session": "2026-08-26", "status": "STAGING",
                "approval_events": 0, "screening_runs": 0,
                "snapshot_id": "snap-1", "checksum": "a" * 64,
                "code_version": "b" * 64, "rows": 100,
                "feature_tickers": 474, "provider_lineage_rows": 476,
                "last_date": "2026-08-26",
            }
            artifact = {
                "contract_id": "codex-market-ingestion-postflight-handoff-v1",
                "evidence": evidence,
                "evidence_sha256": hashlib.sha256(canonical_bytes(evidence)).hexdigest(),
                "snapshot_lifecycle_unchanged": True,
                "successor_authorized": True,
                "observed_at": "2026-08-27T01:00:00+00:00",
            }
            path = Path(tmp) / "handoff.json"
            path.write_bytes(canonical_bytes(artifact))
            path.chmod(0o600)
            self.assertTrue(verify_handoff(
                path, source_session="2026-08-26",
                now=datetime(2026, 8, 27, 1, 1, tzinfo=timezone.utc),
                max_age_seconds=300,
            ))

    def test_handoff_hash_mismatch_rejected(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "handoff.json"
            path.write_text(json.dumps({"contract_id": "codex-market-ingestion-postflight-handoff-v1", "evidence": {}, "evidence_sha256": "0" * 64}), encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises(ContractError):
                verify_handoff(
                    path, source_session="2026-08-26",
                    now=datetime(2026, 8, 27, 1, 1, tzinfo=timezone.utc),
                    max_age_seconds=300,
                )

    def test_stale_handoff_rejected(self):
        with writable_directory() as tmp:
            evidence = {
                "source_session": "2026-08-26", "status": "STAGING",
                "approval_events": 0, "screening_runs": 0,
                "snapshot_id": "snap-1", "checksum": "a" * 64,
                "code_version": "b" * 64, "rows": 100,
                "feature_tickers": 474, "provider_lineage_rows": 476,
                "last_date": "2026-08-26",
            }
            artifact = {
                "contract_id": "codex-market-ingestion-postflight-handoff-v1",
                "evidence": evidence,
                "evidence_sha256": hashlib.sha256(canonical_bytes(evidence)).hexdigest(),
                "snapshot_lifecycle_unchanged": True,
                "successor_authorized": True,
                "observed_at": "2026-08-27T01:00:00+00:00",
            }
            path = Path(tmp) / "handoff.json"
            path.write_bytes(canonical_bytes(artifact))
            path.chmod(0o600)
            with self.assertRaises(ContractError):
                verify_handoff(
                    path, source_session="2026-08-26",
                    now=datetime(2026, 8, 27, 2, 0, tzinfo=timezone.utc),
                    max_age_seconds=300,
                )

    def test_calendar_horizon_exhaustion_rejected(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "calendar.json"
            raw = {
                "contract_id": "codex-nyse-session-calendar-v1",
                "valid_through_utc": "2026-08-27T23:59:59Z",
                "sessions": [{"session_date": "2026-08-26", "close_utc": "2026-08-26T20:00:00Z"}],
            }
            path.write_bytes(canonical_bytes(raw))
            with self.assertRaises(ContractError):
                load_calendar(
                    path, hashlib.sha256(path.read_bytes()).hexdigest(),
                    now=datetime(2026, 8, 27, tzinfo=timezone.utc),
                    minimum_future_horizon=timedelta(days=7),
                )

    def test_progress_marker_binds_live_pid_invocation_and_stage(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "progress.json"
            raw = {
                "contract_id": "codex-market-ingestion-progress-v1",
                "source_session": "2026-08-26", "stage": "INGESTION",
                "status": "ACTIVE", "main_pid": 1234, "invocation_id": "abc",
                "code_version": "a" * 64, "completed_units": 20,
                "total_units": 474, "observed_at": "2026-08-27T01:00:00Z",
            }
            path.write_bytes(canonical_bytes(raw))
            path.chmod(0o600)
            marker = verify_progress_marker(
                path, source_session="2026-08-26", stage="INGESTION",
                unit=ACTIVE, now=datetime(2026, 8, 27, 1, 1, tzinfo=timezone.utc),
                max_age_seconds=300,
            )
            self.assertEqual((marker.completed_units, marker.total_units), (20, 474))

    def test_progress_marker_pid_mismatch_rejected(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "progress.json"
            raw = {
                "contract_id": "codex-market-ingestion-progress-v1",
                "source_session": "2026-08-26", "stage": "INGESTION",
                "status": "ACTIVE", "main_pid": 9999, "invocation_id": "abc",
                "code_version": "a" * 64, "completed_units": 20,
                "total_units": 474, "observed_at": "2026-08-27T01:00:00Z",
            }
            path.write_bytes(canonical_bytes(raw))
            path.chmod(0o600)
            with self.assertRaises(ContractError):
                verify_progress_marker(
                    path, source_session="2026-08-26", stage="INGESTION",
                    unit=ACTIVE, now=datetime(2026, 8, 27, 1, 1, tzinfo=timezone.utc),
                    max_age_seconds=300,
                )

    def test_noncanonical_progress_marker_rejected(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "progress.json"
            path.write_text(json.dumps({
                "contract_id": "codex-market-ingestion-progress-v1",
                "source_session": "2026-08-26", "stage": "INGESTION",
                "status": "ACTIVE", "main_pid": 1234, "invocation_id": "abc",
                "code_version": "a" * 64, "completed_units": 1,
                "total_units": 2, "observed_at": "2026-08-27T01:00:00Z",
            }, indent=2), encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises(ContractError):
                verify_progress_marker(
                    path, source_session="2026-08-26", stage="INGESTION",
                    unit=ACTIVE, now=datetime(2026, 8, 27, 1, 1, tzinfo=timezone.utc),
                    max_age_seconds=300,
                )


class DecisionTests(unittest.TestCase):
    def call(self, snap, **updates):
        args = dict(
            source_session="2026-08-26", snapshot=snap,
            ingestion=IDLE, postflight=IDLE, handoff=IDLE,
            handoff_verified=False, forbidden_safe=True,
        )
        args.update(updates)
        return decide(**args)

    def test_no_snapshot_starts_ingestion(self):
        result = self.call(snapshot())
        self.assertEqual(result.action, Action.START_INGESTION)
        self.assertEqual(result.unit, "codex-market-ingestion@2026-08-26.service")

    def test_staging_resumes_postflight_without_duplicate_write(self):
        result = self.call(snapshot(1, "STAGING"))
        self.assertEqual(result.action, Action.START_POSTFLIGHT)

    def test_verified_handoff_is_noop(self):
        result = self.call(snapshot(1, "STAGING"), handoff_verified=True)
        self.assertEqual(result.action, Action.NOOP_VERIFIED)

    def test_active_ingestion_is_noop(self):
        result = self.call(snapshot(), ingestion=ACTIVE)
        self.assertEqual(result.action, Action.NOOP_ACTIVE)

    def test_active_postflight_is_noop(self):
        result = self.call(snapshot(1, "STAGING"), postflight=ACTIVE)
        self.assertEqual(result.action, Action.NOOP_ACTIVE)

    def test_multiple_active_rejected(self):
        with self.assertRaises(ContractError):
            self.call(snapshot(), ingestion=ACTIVE, postflight=ACTIVE)

    def test_failed_unit_prevents_retry(self):
        with self.assertRaises(ContractError):
            self.call(snapshot(), ingestion=FAILED)

    def test_nonstaging_snapshot_rejected(self):
        with self.assertRaises(ContractError):
            self.call(snapshot(1, "VALIDATED"))

    def test_downstream_outputs_rejected(self):
        with self.assertRaises(ContractError):
            self.call(snapshot(1, "STAGING", approvals=1))

    def test_unsafe_legacy_unit_rejected(self):
        with self.assertRaises(ContractError):
            self.call(snapshot(), forbidden_safe=False)


class LivenessTests(unittest.TestCase):
    def call(self, **updates):
        args = dict(
            units={"ingestion": ACTIVE, "ingestion-postflight": IDLE, "ingestion-handoff": IDLE},
            handoff_verified=False, checkpoint_exists=True,
            checkpoint_age_seconds=10, max_checkpoint_age_seconds=300,
        )
        args.update(updates)
        return assess_liveness(**args)

    def test_live_pid_and_fresh_marker_active(self):
        self.assertEqual(self.call().status, "ACTIVE")

    def test_verified_handoff_terminal(self):
        self.assertEqual(self.call(units={"ingestion": IDLE}, handoff_verified=True).status, "VERIFIED")

    def test_no_unit_stalled(self):
        self.assertEqual(self.call(units={"ingestion": IDLE}).status, "STALLED")

    def test_no_pid_stalled(self):
        no_pid = UnitState("loaded", "active", "running", "success", 0, "x")
        self.assertEqual(self.call(units={"ingestion": no_pid}).status, "STALLED")

    def test_missing_marker_stalled(self):
        self.assertEqual(self.call(checkpoint_exists=False, checkpoint_age_seconds=None).status, "STALLED")

    def test_stale_marker_stalled(self):
        self.assertEqual(self.call(checkpoint_age_seconds=301).status, "STALLED")

    def test_failed_unit_failed(self):
        self.assertEqual(self.call(units={"ingestion": FAILED}).status, "FAILED")

    def test_two_active_contradictory(self):
        self.assertEqual(self.call(units={"ingestion": ACTIVE, "ingestion-postflight": ACTIVE}).status, "CONTRADICTORY")

    def test_bad_max_age_rejected(self):
        with self.assertRaises(ContractError):
            self.call(max_checkpoint_age_seconds=0)


class CapacityTests(unittest.TestCase):
    def test_capacity_passes(self):
        result = assess_capacity(
            load_1m=2, cpu_count=4, available_memory_mb=4096,
            free_disk_mb=10000, max_load_per_cpu=1.5,
            min_memory_mb=1024, min_disk_mb=4096,
        )
        self.assertTrue(result.safe)

    def test_cpu_capacity_fails(self):
        self.assertFalse(assess_capacity(
            load_1m=8, cpu_count=4, available_memory_mb=4096,
            free_disk_mb=10000, max_load_per_cpu=1.5,
            min_memory_mb=1024, min_disk_mb=4096,
        ).safe)

    def test_memory_capacity_fails(self):
        self.assertFalse(assess_capacity(
            load_1m=1, cpu_count=4, available_memory_mb=100,
            free_disk_mb=10000, max_load_per_cpu=1.5,
            min_memory_mb=1024, min_disk_mb=4096,
        ).safe)

    def test_disk_capacity_fails(self):
        self.assertFalse(assess_capacity(
            load_1m=1, cpu_count=4, available_memory_mb=4096,
            free_disk_mb=100, max_load_per_cpu=1.5,
            min_memory_mb=1024, min_disk_mb=4096,
        ).safe)

    def test_invalid_capacity_policy_rejected(self):
        with self.assertRaises(ContractError):
            assess_capacity(
                load_1m=1, cpu_count=0, available_memory_mb=4096,
                free_disk_mb=10000, max_load_per_cpu=1.5,
                min_memory_mb=1024, min_disk_mb=4096,
            )

    def test_foreign_source_session_is_detected(self):
        self.assertEqual(
            foreign_pipeline_units(
                [
                    "codex-market-ingestion@2026-08-26.service",
                    "codex-market-ingestion-postflight@2026-08-25.service",
                ],
                source_session="2026-08-26",
            ),
            ("codex-market-ingestion-postflight@2026-08-25.service",),
        )

    def test_same_session_pipeline_is_allowed(self):
        self.assertEqual(
            foreign_pipeline_units(
                ["codex-market-ingestion@2026-08-26.service"],
                source_session="2026-08-26",
            ),
            (),
        )

    def test_guarded_priority_exact_contract_passes(self):
        validate_priority(PriorityState(900, 900, -5, 2, 0))

    def test_guarded_priority_downgrade_rejected(self):
        for state in (
            PriorityState(899, 900, -5, 2, 0),
            PriorityState(900, 899, -5, 2, 0),
            PriorityState(900, 900, -4, 2, 0),
            PriorityState(900, 900, -5, 3, 0),
            PriorityState(900, 900, -5, 2, 1),
        ):
            with self.subTest(state=state), self.assertRaises(ContractError):
                validate_priority(state)

    @patch("continuity_controller.subprocess.run")
    def test_installed_priority_readback_passes(self, run):
        run.return_value = Mock(
            returncode=0,
            stdout=(
                "CPUWeight=900\nIOWeight=900\nNice=-5\n"
                "IOSchedulingClass=2\nIOSchedulingPriority=0\n"
            ),
        )
        _verify_installed_ingestion_priority(
            "/usr/bin/systemctl", "codex-market-ingestion@2026-08-26.service"
        )

    @patch("continuity_controller.subprocess.run")
    def test_installed_priority_readback_downgrade_fails(self, run):
        run.return_value = Mock(
            returncode=0,
            stdout=(
                "CPUWeight=20\nIOWeight=100\nNice=10\n"
                "IOSchedulingClass=3\nIOSchedulingPriority=7\n"
            ),
        )
        with self.assertRaises(ContractError):
            _verify_installed_ingestion_priority(
                "/usr/bin/systemctl", "codex-market-ingestion@2026-08-26.service"
            )


class JournalTests(unittest.TestCase):
    def test_append_event_is_append_only(self):
        with writable_directory() as tmp:
            root = Path(tmp)
            append_event(root, {"sequence": 1})
            append_event(root, {"sequence": 2})
            rows = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
            self.assertEqual(rows, [{"sequence": 1}, {"sequence": 2}])

    def test_symlink_journal_rejected_when_supported(self):
        with writable_directory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("", encoding="utf-8")
            journal = root / "events.jsonl"
            try:
                journal.symlink_to(target)
            except OSError:
                self.skipTest("symlinks are unavailable")
            with self.assertRaises(ContractError):
                append_event(root, {"sequence": 1})


class SecureArtifactModeTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX ownership/mode contract")
    def test_preflight_executable_requires_0700_not_0600(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "preflight"
            path.write_bytes(b"#!/bin/sh\nexit 0\n")
            path.chmod(0o700)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            _secure_regular(path, digest, expected_mode=0o700)
            with self.assertRaises(ContractError):
                _secure_regular(path, digest)

    def test_unapproved_secure_mode_policy_is_rejected(self):
        with writable_directory() as tmp:
            path = Path(tmp) / "artifact"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(ContractError):
                _secure_regular(path, expected_mode=0o755)


if __name__ == "__main__":
    unittest.main()
