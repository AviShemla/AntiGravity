"""Deterministic NYSE session-calendar artifact builder and validator.

The builder consumes a hash-pinned, explicit exchange ruleset. It performs no
network access and uses an embedded implementation of the post-2007 United
States DST law, avoiding dependence on mutable host tzdata for the covered
horizon.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence


CONTRACT_ID = "codex-nyse-session-calendar-v1"
RULESET_CONTRACT_ID = "codex-nyse-explicit-ruleset-v1"
BUILDER_VERSION = "codex-nyse-calendar-builder-v1"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OFFICIAL_2026_CLOSURES = frozenset(
    {
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-11-26",
        "2026-12-25",
    }
)
OFFICIAL_2026_EARLY_CLOSES = frozenset({"2026-11-27", "2026-12-24"})
OFFICIAL_SOURCE_URLS = frozenset(
    {
        "https://www.nyse.com/trade/hours-calendars",
        "https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf",
    }
)


class CalendarContractError(RuntimeError):
    """Calendar evidence is malformed, incomplete, or contradictory."""


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _parse_date(value: object, label: str) -> date:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise CalendarContractError(f"{label} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CalendarContractError(f"{label} is not a real date") from exc
    if parsed.isoformat() != value:
        raise CalendarContractError(f"{label} is not canonical")
    return parsed


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (ordinal - 1))


def _dst_bounds(year: int) -> tuple[date, date]:
    # U.S. Energy Policy Act rules in force since 2007: second Sunday in March
    # through the first Sunday in November.
    return _nth_weekday(year, 3, 6, 2), _nth_weekday(year, 11, 6, 1)


def _utc_offset_hours(session_date: date) -> int:
    start, end = _dst_bounds(session_date.year)
    return -4 if start <= session_date < end else -5


def _local_to_utc(session_date: date, local_value: time) -> datetime:
    offset = timezone(timedelta(hours=_utc_offset_hours(session_date)))
    return datetime.combine(session_date, local_value, tzinfo=offset).astimezone(
        timezone.utc
    )


def load_ruleset(path: Path, expected_sha256: str) -> Mapping[str, object]:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise CalendarContractError("ruleset SHA-256 is invalid")
    encoded = path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise CalendarContractError("ruleset SHA-256 mismatch")
    raw = json.loads(encoded.decode("utf-8"))
    if encoded != canonical_bytes(raw):
        raise CalendarContractError("ruleset is not canonical JSON")
    if raw.get("contract_id") != RULESET_CONTRACT_ID:
        raise CalendarContractError("ruleset contract identity mismatch")
    if raw.get("timezone") != "America/New_York":
        raise CalendarContractError("ruleset timezone mismatch")
    if raw.get("regular_open_local") != "09:30:00" or raw.get(
        "regular_close_local"
    ) != "16:00:00":
        raise CalendarContractError("regular session hours mismatch")
    start = _parse_date(raw.get("valid_from"), "ruleset valid_from")
    end = _parse_date(raw.get("valid_through"), "ruleset valid_through")
    if start > end:
        raise CalendarContractError("ruleset validity interval is inverted")
    provenance = raw.get("provenance")
    if not isinstance(provenance, Mapping):
        raise CalendarContractError("ruleset provenance is missing")
    if provenance.get("publisher") != "NYSE":
        raise CalendarContractError("ruleset publisher must be NYSE")
    for key in ("title", "url", "retrieval_status"):
        if not isinstance(provenance.get(key), str) or not provenance[key]:
            raise CalendarContractError(f"ruleset provenance {key} is missing")
    if provenance.get("retrieval_status") != "VERIFIED_PRIMARY_NYSE_2026":
        raise CalendarContractError("ruleset primary-source verification is incomplete")
    supporting = provenance.get("supporting_sources")
    if not isinstance(supporting, list) or {
        item.get("url")
        for item in supporting
        if isinstance(item, Mapping) and isinstance(item.get("url"), str)
    } != OFFICIAL_SOURCE_URLS:
        raise CalendarContractError("ruleset official source set mismatch")
    verified_at = provenance.get("verified_at_utc")
    if not isinstance(verified_at, str):
        raise CalendarContractError("ruleset verified_at_utc is missing")
    try:
        parsed_verified = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalendarContractError("ruleset verified_at_utc is invalid") from exc
    if parsed_verified.tzinfo is None:
        raise CalendarContractError("ruleset verified_at_utc must be timezone-aware")
    closures = _normalized_exception_map(raw, "full_closures")
    early_closes = _normalized_exception_map(raw, "early_closes")
    if {item.isoformat() for item in closures} != OFFICIAL_2026_CLOSURES:
        raise CalendarContractError("2026 NYSE full-closure set mismatch")
    if {item.isoformat() for item in early_closes} != OFFICIAL_2026_EARLY_CLOSES:
        raise CalendarContractError("2026 NYSE early-close set mismatch")
    return raw


def _normalized_exception_map(
    raw: Mapping[str, object], key: str
) -> dict[date, Mapping[str, object]]:
    values = raw.get(key)
    if not isinstance(values, list):
        raise CalendarContractError(f"{key} must be an array")
    result: dict[date, Mapping[str, object]] = {}
    for item in values:
        if not isinstance(item, Mapping):
            raise CalendarContractError(f"{key} entry must be an object")
        session_date = _parse_date(item.get("date"), f"{key} date")
        if session_date in result:
            raise CalendarContractError(f"{key} repeats a date")
        if not isinstance(item.get("reason"), str) or not item["reason"]:
            raise CalendarContractError(f"{key} reason is missing")
        if key == "early_closes" and item.get("close_local") != "13:00:00":
            raise CalendarContractError("early close must be 13:00:00 local")
        result[session_date] = item
    return result


def build_calendar_artifact(
    ruleset: Mapping[str, object],
    *,
    ruleset_sha256: str,
    valid_from: date | None = None,
    valid_through: date | None = None,
) -> dict[str, object]:
    if not SHA256_RE.fullmatch(ruleset_sha256):
        raise CalendarContractError("ruleset SHA-256 is invalid")
    ruleset_start = _parse_date(ruleset.get("valid_from"), "ruleset valid_from")
    ruleset_end = _parse_date(ruleset.get("valid_through"), "ruleset valid_through")
    start = valid_from or ruleset_start
    end = valid_through or ruleset_end
    if start < ruleset_start or end > ruleset_end or start > end:
        raise CalendarContractError("requested horizon escapes the ruleset")
    closures = _normalized_exception_map(ruleset, "full_closures")
    early = _normalized_exception_map(ruleset, "early_closes")
    if set(closures) & set(early):
        raise CalendarContractError("a date cannot be both closed and early-close")
    sessions: list[dict[str, object]] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in closures:
            early_row = early.get(cursor)
            close_local = time(13, 0) if early_row else time(16, 0)
            open_utc = _local_to_utc(cursor, time(9, 30))
            close_utc = _local_to_utc(cursor, close_local)
            sessions.append(
                {
                    "session_date": cursor.isoformat(),
                    "open_utc": open_utc.isoformat().replace("+00:00", "Z"),
                    "close_utc": close_utc.isoformat().replace("+00:00", "Z"),
                    "utc_offset_minutes": _utc_offset_hours(cursor) * 60,
                    "close_type": "EARLY" if early_row else "REGULAR",
                    "exception_reason": early_row["reason"] if early_row else None,
                }
            )
        cursor += timedelta(days=1)
    if not sessions:
        raise CalendarContractError("calendar horizon has no sessions")
    artifact: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "builder_version": BUILDER_VERSION,
        "timezone": "America/New_York",
        "valid_from_utc": f"{start.isoformat()}T00:00:00Z",
        "valid_through_utc": f"{end.isoformat()}T23:59:59Z",
        "ruleset_contract_id": RULESET_CONTRACT_ID,
        "ruleset_sha256": ruleset_sha256,
        "dependency_pins": {
            "calendar_algorithm": BUILDER_VERSION,
            "dst_rule": "US_ENERGY_POLICY_ACT_POST_2007_V1",
            "external_runtime_packages": [],
        },
        "data_provenance": ruleset["provenance"],
        "sessions": sessions,
    }
    validate_calendar_artifact(
        artifact, ruleset=ruleset, ruleset_sha256=ruleset_sha256
    )
    return artifact


def validate_calendar_artifact(
    raw: Mapping[str, object],
    *,
    ruleset: Mapping[str, object],
    ruleset_sha256: str,
) -> None:
    if raw.get("contract_id") != CONTRACT_ID or raw.get(
        "builder_version"
    ) != BUILDER_VERSION:
        raise CalendarContractError("calendar contract/builder identity mismatch")
    if raw.get("timezone") != "America/New_York":
        raise CalendarContractError("calendar timezone mismatch")
    if raw.get("ruleset_contract_id") != RULESET_CONTRACT_ID or raw.get(
        "ruleset_sha256"
    ) != ruleset_sha256:
        raise CalendarContractError("calendar ruleset lineage mismatch")
    pins = raw.get("dependency_pins")
    if not isinstance(pins, Mapping) or pins != {
        "calendar_algorithm": BUILDER_VERSION,
        "dst_rule": "US_ENERGY_POLICY_ACT_POST_2007_V1",
        "external_runtime_packages": [],
    }:
        raise CalendarContractError("calendar dependency pins mismatch")
    if raw.get("data_provenance") != ruleset.get("provenance"):
        raise CalendarContractError("calendar data provenance mismatch")
    from_text, through_text = raw.get("valid_from_utc"), raw.get("valid_through_utc")
    if not isinstance(from_text, str) or not from_text.endswith("T00:00:00Z"):
        raise CalendarContractError("valid_from_utc is invalid")
    if not isinstance(through_text, str) or not through_text.endswith("T23:59:59Z"):
        raise CalendarContractError("valid_through_utc is invalid")
    start = _parse_date(from_text[:10], "calendar valid_from")
    end = _parse_date(through_text[:10], "calendar valid_through")
    expected = build_calendar_artifact_unchecked(
        ruleset, ruleset_sha256=ruleset_sha256, start=start, end=end
    )
    if raw != expected:
        raise CalendarContractError("calendar sessions or metadata differ from deterministic rebuild")


def build_calendar_artifact_unchecked(
    ruleset: Mapping[str, object], *, ruleset_sha256: str, start: date, end: date
) -> dict[str, object]:
    """Internal rebuild used by validation without recursive validation."""

    ruleset_start = _parse_date(ruleset.get("valid_from"), "ruleset valid_from")
    ruleset_end = _parse_date(ruleset.get("valid_through"), "ruleset valid_through")
    if start < ruleset_start or end > ruleset_end or start > end:
        raise CalendarContractError("calendar horizon escapes ruleset")
    closures = _normalized_exception_map(ruleset, "full_closures")
    early = _normalized_exception_map(ruleset, "early_closes")
    if set(closures) & set(early):
        raise CalendarContractError("a date cannot be both closed and early-close")
    sessions: list[dict[str, object]] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in closures:
            early_row = early.get(cursor)
            close_local = time(13) if early_row else time(16)
            sessions.append(
                {
                    "session_date": cursor.isoformat(),
                    "open_utc": _local_to_utc(cursor, time(9, 30)).isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "close_utc": _local_to_utc(cursor, close_local).isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "utc_offset_minutes": _utc_offset_hours(cursor) * 60,
                    "close_type": "EARLY" if early_row else "REGULAR",
                    "exception_reason": early_row["reason"] if early_row else None,
                }
            )
        cursor += timedelta(days=1)
    if not sessions:
        raise CalendarContractError("calendar horizon has no sessions")
    return {
        "contract_id": CONTRACT_ID,
        "builder_version": BUILDER_VERSION,
        "timezone": "America/New_York",
        "valid_from_utc": f"{start.isoformat()}T00:00:00Z",
        "valid_through_utc": f"{end.isoformat()}T23:59:59Z",
        "ruleset_contract_id": RULESET_CONTRACT_ID,
        "ruleset_sha256": ruleset_sha256,
        "dependency_pins": {
            "calendar_algorithm": BUILDER_VERSION,
            "dst_rule": "US_ENERGY_POLICY_ACT_POST_2007_V1",
            "external_runtime_packages": [],
        },
        "data_provenance": ruleset["provenance"],
        "sessions": sessions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ruleset", type=Path, required=True)
    parser.add_argument("--ruleset-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--valid-from")
    parser.add_argument("--valid-through")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise CalendarContractError("output already exists")
        ruleset = load_ruleset(args.ruleset, args.ruleset_sha256)
        artifact = build_calendar_artifact(
            ruleset,
            ruleset_sha256=args.ruleset_sha256,
            valid_from=_parse_date(args.valid_from, "valid_from")
            if args.valid_from
            else None,
            valid_through=_parse_date(args.valid_through, "valid_through")
            if args.valid_through
            else None,
        )
        args.output.write_bytes(canonical_bytes(artifact))
        print(
            "NYSE_CALENDAR_WRITTEN "
            f"sha256={hashlib.sha256(canonical_bytes(artifact)).hexdigest()} "
            f"sessions={len(artifact['sessions'])}"
        )
        return 0
    except (CalendarContractError, OSError, ValueError, UnicodeError) as exc:
        print(f"NYSE_CALENDAR_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
