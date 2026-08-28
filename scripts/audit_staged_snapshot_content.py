"""SELECT-only independent content readback for one guarded STAGING snapshot."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_staging_content import ENCODING, STAGING_COLUMNS, StagingContentDigester, StagingContentError
from turso_read_pipeline import TursoReadPipeline


SHA256 = re.compile(r"[0-9a-f]{64}")


class StagedSnapshotAuditError(ValueError):
    pass


def audit_staged_snapshot(client, *, source_session: str, page_size: int = 2000):
    if type(source_session) is not str:
        raise StagedSnapshotAuditError("source session must be canonical text")
    try:
        parsed_session = date.fromisoformat(source_session)
    except ValueError as exc:
        raise StagedSnapshotAuditError("source session must be canonical YYYY-MM-DD") from exc
    if parsed_session.isoformat() != source_session:
        raise StagedSnapshotAuditError("source session must be canonical YYYY-MM-DD")
    if type(page_size) is not int or not 1 <= page_size <= 5000:
        raise StagedSnapshotAuditError("page size differs from bounded contract")
    metadata = client.execute(
        "SELECT snapshot_id,status,source_checksum_sha256,expected_row_count,expected_ticker_count,"
        "code_version,validation_notes "
        "FROM model_input_snapshots WHERE dataset_type='MARKET_FEATURES' AND source_session_date=? ORDER BY snapshot_id",
        [source_session],
    ).rows
    if len(metadata) != 1:
        raise StagedSnapshotAuditError("source session must have exactly one snapshot")
    snapshot_id, status, expected_sha, expected_rows, expected_tickers, code_version, notes = metadata[0]
    rebuild_hash = hashlib.sha256((ROOT / "scripts" / "rebuild_market_features_to_turso.py").read_bytes()).hexdigest()
    if type(expected_sha) is not str or SHA256.fullmatch(expected_sha) is None:
        raise StagedSnapshotAuditError("content checksum metadata is not canonical SHA-256")
    if type(snapshot_id) is not str or snapshot_id != f"market_features_{source_session}_{expected_sha[:16]}":
        raise StagedSnapshotAuditError("snapshot id differs from deterministic content identity")
    if type(status) is not str or status != "STAGING":
        raise StagedSnapshotAuditError("snapshot is not STAGING")
    if type(expected_rows) is not int or expected_rows <= 0:
        raise StagedSnapshotAuditError("expected row count metadata is invalid")
    if type(expected_tickers) is not int or expected_tickers <= 0:
        raise StagedSnapshotAuditError("expected ticker count metadata is invalid")
    if type(code_version) is not str or code_version != rebuild_hash:
        raise StagedSnapshotAuditError("snapshot code version differs from deployed writer")
    marker = f"checksum_encoding={ENCODING}; "
    if type(notes) is not str or not notes.startswith(marker) or notes.count("checksum_encoding=") != 1:
        raise StagedSnapshotAuditError("snapshot is legacy or checksum encoding is unbound")
    digester = StagingContentDigester()
    last_ticker = ""
    last_date = ""
    query = (
        "SELECT " + ",".join(STAGING_COLUMNS) + " FROM market_daily_features "
        "WHERE snapshot_id=? AND (ticker>? OR (ticker=? AND date>?)) "
        "ORDER BY ticker,date LIMIT ?"
    )
    while True:
        page = client.execute(
            query, [str(snapshot_id), last_ticker, last_ticker, last_date, page_size]
        ).rows
        if not page:
            break
        try:
            digester.update(tuple(tuple(row) for row in page))
        except StagingContentError as exc:
            raise StagedSnapshotAuditError("persisted canonical stream differs") from exc
        last_ticker = str(page[-1][0])
        last_date = str(page[-1][1])
        if digester.row_count % 50000 < page_size:
            print(f"postflight_rows_read={digester.row_count}/{expected_rows}", flush=True)
    audit = digester.finalize()
    if (
        audit.content_sha256 != str(expected_sha)
        or audit.row_count != expected_rows
        or audit.ticker_count != expected_tickers
        or audit.last_date != source_session
    ):
        raise StagedSnapshotAuditError("persisted content readback differs from snapshot contract")
    return str(snapshot_id), audit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=2000)
    args = parser.parse_args(argv)
    load_dotenv(args.env_file, override=True)
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise StagedSnapshotAuditError("Turso credentials unavailable")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    snapshot_id, audit = audit_staged_snapshot(
        TursoReadPipeline(endpoint, token, timeout_seconds=120.0),
        source_session=args.source_session,
        page_size=args.page_size,
    )
    values = asdict(audit)
    print(
        "POSTFLIGHT_CANONICAL_CONTENT_VERIFIED "
        f"snapshot_id={snapshot_id} rows={values['row_count']} tickers={values['ticker_count']} "
        f"sessions={values['session_count']} first_date={values['first_date']} "
        f"last_date={values['last_date']} checksum={values['content_sha256']} "
        f"ticker_sha256={values['ticker_sha256']} calendar_sha256={values['calendar_sha256']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
