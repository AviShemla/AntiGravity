"""Fail-closed argument adapters for immutable nightly payloads.

The adapters deliberately contain no network or database code.  They bind the
recurring systemd contract to reviewed release-local implementations and reject
unknown arguments before those implementations can run.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence


SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
TICKER_RE = re.compile(r"^[A-Z^][A-Z0-9.^-]{0,15}$")
INGESTION_ENV_FILE = "/etc/codex-oracle/market-ingestion.env"
TIINGO_TOKEN_FILE = "/etc/antigravity/tiingo.token"
HANDOFF_ROOT = Path("/var/lib/codex-oracle/market-ingestion")


class PayloadAdapterError(ValueError):
    """The immutable runtime arguments violate the reviewed payload contract."""


def _source_session(value: str) -> str:
    if not SESSION_RE.fullmatch(value):
        raise PayloadAdapterError("source session must be YYYY-MM-DD")
    return value


def _parse_required_tickers(value: str) -> tuple[str, ...]:
    tickers = tuple(part.strip() for part in value.split(",") if part.strip())
    if not tickers or len(set(tickers)) != len(tickers):
        raise PayloadAdapterError("required ticker set is empty or duplicated")
    if any(not TICKER_RE.fullmatch(ticker) for ticker in tickers):
        raise PayloadAdapterError("required ticker set contains an invalid symbol")
    return tickers


def ingestion_arguments(
    argv: Sequence[str], environ: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """Build the exact reviewed ingestion CLI without lifecycle-changing flags."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-session", required=True)
    args = parser.parse_args(argv)
    source_session = _source_session(args.source_session)
    env = os.environ if environ is None else environ
    universe = env.get("CODEX_MARKET_UNIVERSE_SNAPSHOT", "")
    if not SNAPSHOT_RE.fullmatch(universe):
        raise PayloadAdapterError("immutable universe snapshot is missing or invalid")
    tickers = _parse_required_tickers(env.get("CODEX_MARKET_REQUIRED_TICKERS", ""))
    try:
        workers = int(env.get("CODEX_MARKET_WORKERS", "8"))
    except ValueError as exc:
        raise PayloadAdapterError("worker count is not an integer") from exc
    if not 1 <= workers <= 12:
        raise PayloadAdapterError("worker count must be between 1 and 12")
    return (
        "--source-session", source_session,
        "--universe-snapshot", universe,
        "--required-tickers", *tickers,
        "--workers", str(workers),
        "--env-file", INGESTION_ENV_FILE,
        "--tiingo-token-file", TIINGO_TOKEN_FILE,
    )


def _expected_handoff(source_session: str) -> Path:
    return HANDOFF_ROOT / source_session / "postflight-handoff.json"


def postflight_arguments(argv: Sequence[str]) -> tuple[str, ...]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--expected-code-version", required=True)
    parser.add_argument("--handoff-output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, required=True)
    parser.add_argument("--retry-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    source = _source_session(args.source_session)
    if not SHA256_RE.fullmatch(args.expected_code_version):
        raise PayloadAdapterError("expected code version is not a lowercase SHA-256")
    if args.handoff_output != _expected_handoff(source):
        raise PayloadAdapterError("handoff output is outside the canonical session path")
    if not 1 <= args.attempts <= 20 or not 0 <= args.retry_seconds <= 30:
        raise PayloadAdapterError("postflight retry contract is outside bounded limits")
    return (
        "--source-session", source,
        "--expected-code-version", args.expected_code_version,
        "--handoff-output", str(args.handoff_output),
        "--attempts", str(args.attempts),
        "--retry-seconds", str(args.retry_seconds),
    )


def handoff_arguments(argv: Sequence[str]) -> tuple[str, ...]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--max-age-seconds", type=int, required=True)
    args = parser.parse_args(argv)
    source = _source_session(args.source_session)
    if args.artifact != _expected_handoff(source):
        raise PayloadAdapterError("handoff artifact is outside the canonical session path")
    if not 1 <= args.max_age_seconds <= 900:
        raise PayloadAdapterError("handoff freshness bound is outside the allowlist")
    return (
        "--source-session", source,
        "--artifact", str(args.artifact),
        "--max-age-seconds", str(args.max_age_seconds),
    )


def invoke_noarg_main(main: Callable[[], int], argv: Sequence[str]) -> int:
    """Invoke a reviewed argparse main while restoring the process argv."""
    previous = sys.argv
    try:
        sys.argv = [previous[0], *argv]
        return int(main())
    finally:
        sys.argv = previous
