"""Immutable research overlays: retained base plus compressed cell differences."""
from __future__ import annotations

import hashlib
import json
import zlib
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def make_patch(columns, baseline, source):
    """Null is a retained value, not JSON-merge deletion syntax."""
    before = {r[1]: r for r in baseline}
    after = {r[1]: r for r in source}
    if len(before) != len(baseline) or len(after) != len(source):
        raise ValueError("duplicate research keys")
    changes = {}
    for date, row in after.items():
        old = before.get(date)
        changed = {col: row[i] for i, col in enumerate(columns) if i > 1 and
                   (old is None or type(old[i]) is not type(row[i]) or old[i] != row[i])}
        if old is None or changed:
            changes[date] = changed
    payload = {"schema_version": 1, "upserts": changes, "deletes": sorted(set(before) - set(after))}
    packed = zlib.compress(canonical(payload), level=9)
    return packed, {"base_sha256": digest(baseline), "content_sha256": digest(source),
                    "rows": len(source), "base_rows": len(baseline),
                    "additions": len(set(after) - set(before)),
                    "deletions": len(set(before) - set(after)),
                    "changed_cells": sum(len(v) for k, v in changes.items() if k in before),
                    "payload_bytes": len(packed), "payload_sha256": hashlib.sha256(packed).hexdigest()}


def reconstruct(columns, ticker, baseline, packed, summary):
    if digest(baseline) != summary["base_sha256"]:
        raise ValueError("retained base content changed")
    if hashlib.sha256(packed).hexdigest() != summary["payload_sha256"]:
        raise ValueError("research patch content changed")
    payload = json.loads(zlib.decompress(packed))
    if payload["schema_version"] != 1:
        raise ValueError("unknown overlay format")
    rows = {row[1]: list(row) for row in baseline}
    if len(rows) != len(baseline):
        raise ValueError("duplicate baseline keys")
    for date in payload["deletes"]:
        del rows[date]
    for date, updates in payload["upserts"].items():
        if set(updates) - set(columns[2:]):
            raise ValueError("unknown patch column")
        if date not in rows:
            if set(updates) != set(columns[2:]):
                raise ValueError("incomplete addition")
            rows[date] = [ticker, date] + [updates[c] for c in columns[2:]]
        else:
            for name, value in updates.items():
                rows[date][columns.index(name)] = value
    result = [rows[d] for d in sorted(rows)]
    if len(result) != summary["rows"] or digest(result) != summary["content_sha256"]:
        raise ValueError("reconstructed content does not match frozen capture")
    return result


def read_version_rows(db, manifest, ticker):
    columns = manifest["columns"]
    projection = ",".join('"' + c + '"' for c in columns)
    baseline = [list(r) for r in db.execute(
        "SELECT " + projection + " FROM market_daily_features WHERE snapshot_id=? AND ticker=? AND date<=? ORDER BY date",
        [manifest["base_snapshot_id"], ticker, manifest["cutoff"]]).rows]
    result = db.execute("SELECT payload FROM oracle_w2_content_patches WHERE version_id=? AND ticker=?",
                        [manifest["version_id"], ticker]).rows
    if len(result) != 1:
        raise ValueError("missing or duplicate research patch")
    return reconstruct(columns, ticker, baseline, bytes(result[0][0]), manifest["instruments"][ticker])
