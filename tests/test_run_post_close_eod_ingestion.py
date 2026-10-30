import unittest
from argparse import Namespace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.operations.run_post_close_eod_ingestion import (
    build_command,
    latest_completed_nyse_session,
    run_stager,
    verify_protected_units,
)


class PostCloseIngestionTests(unittest.TestCase):
    @staticmethod
    def schedule(_start, _end):
        return pd.DataFrame(
            {
                "market_close": pd.to_datetime(
                    ["2026-08-21T20:00:00Z", "2026-08-24T20:00:00Z"], utc=True
                )
            },
            index=pd.to_datetime(["2026-08-21", "2026-08-24"]),
        )

    def test_before_close_selects_previous_completed_session(self):
        result = latest_completed_nyse_session(
            datetime(2026, 8, 24, 19, 0, tzinfo=timezone.utc),
            schedule_loader=self.schedule,
        )
        self.assertEqual(result, date(2026, 8, 21))

    def test_grace_period_blocks_just_closed_session(self):
        result = latest_completed_nyse_session(
            datetime(2026, 8, 24, 20, 15, tzinfo=timezone.utc),
            grace_minutes=30,
            schedule_loader=self.schedule,
        )
        self.assertEqual(result, date(2026, 8, 21))
        result = latest_completed_nyse_session(
            datetime(2026, 8, 24, 20, 31, tzinfo=timezone.utc),
            grace_minutes=30,
            schedule_loader=self.schedule,
        )
        self.assertEqual(result, date(2026, 8, 24))

    def test_naive_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            latest_completed_nyse_session(
                datetime(2026, 8, 24, 21, 0), schedule_loader=self.schedule
            )

    @patch("scripts.operations.run_post_close_eod_ingestion.unit_state")
    def test_protected_units_must_be_inactive_and_disabled(self, state):
        state.side_effect = lambda _unit, verb: (
            "inactive" if verb == "is-active" else "disabled"
        )
        verify_protected_units()
        state.side_effect = lambda _unit, verb: (
            "active" if verb == "is-active" else "disabled"
        )
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            verify_protected_units()

    def test_apply_flag_is_explicit(self):
        args = Namespace(
            python_bin=Path("/python"),
            stage_script=Path("/stage.py"),
            env_file=Path("/secure.env"),
            tiingo_token_file=Path("/secure.token"),
            apply=False,
        )
        command = build_command(args, date(2026, 8, 24))
        self.assertNotIn("--apply", command)
        args.apply = True
        self.assertEqual(build_command(args, date(2026, 8, 24))[-1], "--apply")

    def test_stager_retry_is_bounded_and_recovers(self):
        outcomes = [
            type("Result", (), {"returncode": 1})(),
            type("Result", (), {"returncode": 0})(),
        ]
        calls = []
        sleeps = []

        def run(command, *, check):
            calls.append((command, check))
            return outcomes.pop(0)

        run_stager(
            ["python", "stage.py"],
            attempts=3,
            retry_seconds=5,
            run=run,
            sleep=sleeps.append,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [5])

    def test_stager_retry_fails_after_bound(self):
        result = type("Result", (), {"returncode": 7})()
        calls = []
        with self.assertRaisesRegex(RuntimeError, "after 2 attempts"):
            run_stager(
                ["python", "stage.py"],
                attempts=2,
                retry_seconds=0,
                run=lambda command, check: calls.append(command) or result,
                sleep=lambda _seconds: None,
            )
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
