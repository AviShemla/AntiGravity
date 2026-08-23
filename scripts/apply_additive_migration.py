"""Apply a reviewed CREATE-only Turso migration without exposing credentials."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path

ALLOWED = re.compile(r"^CREATE\s+(?:TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\b", re.IGNORECASE)


def statements_from_sql(text: str) -> list[str]:
    without_comments = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [part.strip() for part in without_comments.split(";") if part.strip()]
    if not statements:
        raise ValueError("Migration contains no statements.")
    for statement in statements:
        if not ALLOWED.match(statement):
            raise ValueError("Migration contains a non-additive statement.")
    return statements


def verify_expected_hash(raw: bytes, expected_sha256: str) -> str:
    actual = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Expected migration SHA-256 must be 64 lowercase hex characters.")
    if actual != expected_sha256:
        raise ValueError("Migration SHA-256 does not match the reviewed artifact.")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("migration")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the reviewed migration; default behavior is check-only.",
    )
    parser.add_argument(
        "--expected-sha256",
        help="Required with --apply; must match the exact reviewed file.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    migration = (root / args.migration).resolve()
    migrations_dir = (root / "migrations").resolve()
    if migration.parent != migrations_dir or not migration.name.endswith(".sql"):
        raise SystemExit("Migration must be a direct .sql file under migrations/.")
    raw = migration.read_bytes()
    statements = statements_from_sql(raw.decode("utf-8"))
    actual_hash = hashlib.sha256(raw).hexdigest()
    if not args.apply:
        print(
            f"CHECKED_CREATE_ONLY statements={len(statements)} "
            f"sha256={actual_hash} no_changes=true"
        )
        return 0
    if not args.expected_sha256:
        raise SystemExit("--apply requires --expected-sha256 from the reviewed artifact.")
    try:
        verify_expected_hash(raw, args.expected_sha256)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    import requests

    session = requests.Session()
    for statement in statements:
        response = session.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "requests": [
                    {"type": "execute", "stmt": {"sql": statement, "args": []}},
                    {"type": "close"},
                ]
            },
            timeout=30.0,
        )
        if response.status_code != 200:
            raise SystemExit(f"Migration failed with HTTP {response.status_code}.")
        payload = response.json()["results"][0]
        if payload.get("type") != "ok":
            raise SystemExit("Turso rejected an additive migration statement.")
    print(
        f"APPLIED_CREATE_ONLY statements={len(statements)} "
        f"sha256={actual_hash}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
