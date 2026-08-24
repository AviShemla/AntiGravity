#!/usr/bin/env python3
"""Select the latest completed NYSE session and stage EOD evidence only.

This runner cannot invoke models, brokers, order generation, email, or service
activation. It delegates solely to ``stage_tiingo_eod_delta.py`` after bounded
calendar, service-state, secret-permission, and code-path checks.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


PROTECTED_UNITS = (
    "ag-sniper.service",
    "antigravity-nightly.timer",
    "antigravity-qa-watchdog.timer",
)


def latest_completed_nyse_session(
    now_utc: datetime,
    *,
    grace_minutes: int = 30,
    schedule_loader: Callable[[date, date], object] | None = None,
) -> date:
    """Return the latest session whose official close plus grace has elapsed."""
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    if not 0 <= grace_minutes <= 240:
        raise ValueError("grace_minutes must be between 0 and 240")
    normalized_now = now_utc.astimezone(timezone.utc)
    start = (normalized_now - timedelta(days=21)).date()
    end = normalized_now.date()
    if schedule_loader is None:
        import pandas_market_calendars as mcal

        calendar = mcal.get_calendar("NYSE")
        schedule = calendar.schedule(start_date=start, end_date=end)
    else:
        schedule = schedule_loader(start, end)
    if schedule is None or len(schedule) == 0:
        raise RuntimeError("NYSE calendar returned no sessions")
    cutoff = normalized_now - timedelta(minutes=grace_minutes)
    completed = schedule[schedule["market_close"] <= cutoff]
    if len(completed) == 0:
        raise RuntimeError("no completed NYSE session exists before the cutoff")
    return completed.index[-1].date()


def unit_state(unit: str, verb: str = "is-active") -> str:
    result = subprocess.run(
        ["systemctl", verb, unit],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


def verify_protected_units() -> None:
    for unit in PROTECTED_UNITS:
        active_state = unit_state(unit, "is-active")
        enabled_state = unit_state(unit, "is-enabled")
        if active_state != "inactive" or enabled_state != "disabled":
            raise RuntimeError(
                f"protected unit state is unsafe: {unit} "
                f"active={active_state or 'unknown'} "
                f"enabled={enabled_state or 'unknown'}"
            )


def verify_file(path: Path, *, mode: int, owner_uid: int) -> None:
    stat = path.stat()
    actual_mode = stat.st_mode & 0o777
    if actual_mode != mode or stat.st_uid != owner_uid:
        raise RuntimeError(
            f"unsafe protected file metadata: {path} "
            f"mode={actual_mode:o} uid={stat.st_uid}"
        )


def build_command(args: argparse.Namespace, source_session: date) -> list[str]:
    command = [
        str(args.python_bin),
        str(args.stage_script),
        "--source-session",
        source_session.isoformat(),
        "--env-file",
        str(args.env_file),
        "--tiingo-token-file",
        str(args.tiingo_token_file),
    ]
    if args.apply:
        command.append("--apply")
    return command


def run_stager(
    command: list[str],
    *,
    attempts: int,
    retry_seconds: float,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run the idempotent stager with bounded whole-command retries."""
    if not 1 <= attempts <= 5:
        raise ValueError("attempts must be between 1 and 5")
    if not 0 <= retry_seconds <= 900:
        raise ValueError("retry_seconds must be between 0 and 900")
    for attempt in range(1, attempts + 1):
        print(f"STAGER_ATTEMPT attempt={attempt} max_attempts={attempts}", flush=True)
        result = run(command, check=False)
        if result.returncode == 0:
            return
        print(
            f"STAGER_ATTEMPT_FAILED attempt={attempt} "
            f"exit_code={result.returncode}",
            flush=True,
        )
        if attempt < attempts:
            sleep(retry_seconds)
    raise RuntimeError(f"EOD evidence staging failed after {attempts} attempts")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--grace-minutes", type=int, default=30)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-seconds", type=float, default=60.0)
    parser.add_argument(
        "--python-bin", type=Path, default=Path("/opt/antigravity/venv/bin/python")
    )
    parser.add_argument(
        "--stage-script",
        type=Path,
        default=Path(
            "/home/codexops/codex_git/AntiGravity/scripts/stage_tiingo_eod_delta.py"
        ),
    )
    parser.add_argument(
        "--env-file", type=Path, default=Path("/opt/antigravity/.env")
    )
    parser.add_argument(
        "--tiingo-token-file",
        type=Path,
        default=Path("/etc/antigravity/tiingo.token"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verify_protected_units()
    verify_file(args.env_file, mode=0o600, owner_uid=0)
    verify_file(args.tiingo_token_file, mode=0o640, owner_uid=0)
    if not args.python_bin.is_file() or not args.stage_script.is_file():
        raise RuntimeError("approved Python or ingestion entrypoint is missing")
    source_session = latest_completed_nyse_session(
        datetime.now(timezone.utc), grace_minutes=args.grace_minutes
    )
    mode = "APPLY" if args.apply else "PREFLIGHT"
    print(
        f"POST_CLOSE_INGESTION mode={mode} "
        f"source_session={source_session.isoformat()} grace_minutes={args.grace_minutes}",
        flush=True,
    )
    run_stager(
        build_command(args, source_session),
        attempts=args.attempts,
        retry_seconds=args.retry_seconds,
    )
    print(
        f"POST_CLOSE_INGESTION_SUCCEEDED mode={mode} "
        f"source_session={source_session.isoformat()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
