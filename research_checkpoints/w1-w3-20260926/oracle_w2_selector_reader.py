"""Read-only W2 selector for the user-approved Oracle research universe."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from oracle_w2_content_version import canonical, digest, read_version_rows


class W2SelectorError(RuntimeError):
    pass


_TICKER = re.compile(r"^[A-Z0-9.^-]{1,24}$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_selector(path: Path) -> dict[str, Any]:
    """Load and bind a W2 selector to its W1 membership manifest."""
    path = path.resolve()
    raw = json.loads(path.read_text(encoding="ascii"))
    required = {
        "schema_version", "record_type", "status", "membership_manifest",
        "membership_manifest_sha256", "source_table", "as_of_session_date",
        "expected_instruments", "expected_rows", "selection_rule", "forbidden",
        "version_manifest", "version_manifest_sha256", "version_id",
    }
    if set(raw) != required or raw["schema_version"] != 2 or raw["status"] != "FROZEN":
        raise W2SelectorError("W2 selector schema differs")
    if raw["record_type"] != "ORACLE_W2_RESEARCH_INPUT_SELECTOR":
        raise W2SelectorError("W2 selector identity differs")
    if raw["source_table"] != "oracle_w2_content_versions":
        raise W2SelectorError("W2 selector source differs")
    membership_path = (path.parent / raw["membership_manifest"]).resolve()
    if membership_path.parent != path.parent or _sha256(membership_path) != raw["membership_manifest_sha256"]:
        raise W2SelectorError("W1 manifest binding differs")
    membership = json.loads(membership_path.read_text(encoding="ascii"))
    members = membership.get("members")
    if not isinstance(members, list) or len(members) != raw["expected_instruments"]:
        raise W2SelectorError("W1 membership cardinality differs")
    tickers = tuple(item.get("ticker") for item in members if isinstance(item, dict))
    if len(tickers) != len(members) or len(set(tickers)) != len(tickers) or any(
        not isinstance(ticker, str) or not _TICKER.fullmatch(ticker) for ticker in tickers
    ):
        raise W2SelectorError("W1 ticker identity differs")
    manifest_path = (path.parent / raw["version_manifest"]).resolve()
    if manifest_path.parent != path.parent or _sha256(manifest_path) != raw["version_manifest_sha256"]:
        raise W2SelectorError("W2 version manifest binding differs")
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    if (manifest["version_id"] != raw["version_id"] or
        manifest["cutoff"] != raw["as_of_session_date"] or
        manifest["membership_manifest_sha256"] != raw["membership_manifest_sha256"] or
        set(manifest["instruments"]) != set(tickers) or
        manifest["rows"] != raw["expected_rows"] or
        sum(v["rows"] for v in manifest["instruments"].values()) != raw["expected_rows"] or
        manifest["verification"]["result"] != "PASS" or
        manifest["content_sha256"] != digest({t: v["content_sha256"] for t, v in manifest["instruments"].items()})):
        raise W2SelectorError("W2 version membership, cutoff, content, or cardinality differs")
    return {"selector": raw, "manifest": manifest, "tickers": frozenset(tickers), "identity_sha256": hashlib.sha256(_canonical_bytes(raw)).hexdigest()}


def _require_frozen(db: Any, bound: dict[str, Any]) -> None:
    result = db.execute(
        "SELECT state,manifest_sha256 FROM oracle_w2_content_versions WHERE version_id=?",
        [bound["selector"]["version_id"]],
    )
    if [list(r) for r in result.rows] != [["FROZEN", digest(bound["manifest"])]]:
        raise W2SelectorError("Turso version is not the bound frozen version")


def read_sessions(db: Any, bound: dict[str, Any]) -> list[str]:
    """Return the W2 calendar through its fixed terminal session."""
    _require_frozen(db, bound)
    return list(bound["manifest"]["sessions"])


def read_daily_returns(db: Any, bound: dict[str, Any], ticker: str) -> list[tuple[str, float]]:
    """Return one governed member's bounded daily returns with no write capability."""
    if ticker not in bound["tickers"]:
        raise W2SelectorError("ticker is outside the W1 manifest")
    _require_frozen(db, bound)
    result = read_version_rows(db, bound["manifest"], ticker)
    return_index = bound["manifest"]["columns"].index("daily_return_pct")
    rows = []
    for row in result:
        date, value = row[1], row[return_index]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise W2SelectorError("daily return is not finite numeric data")
        rows.append((str(date), float(value)))
    return rows
