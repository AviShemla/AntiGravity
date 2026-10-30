"""Check or apply the owner-approved quarantine fresh start.

The write path is hash-locked and append-first. It creates reset evidence,
supersedes the old ETF registry, and installs one successor registry. It never
deletes ledger, scorecard, pending-order, or model-run history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PRIOR_REGISTRY_ID = "etf_registry_20260822_v1"
REGISTRY_ID = "etf_registry_20260824_fresh_v2"
EFFECTIVE_SESSION = "2026-08-21"
MODEL_CANDIDATES = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
LEGACY_VALUATION_ONLY = ("IWD", "UDOW")
BENCHMARKS = ("SPY",)
LEGACY_QUARANTINED = ("IGV", "ITB", "IYH", "MRVU", "MSTZ", "MTUM", "MULL", "NBIL", "RDVY", "RGTZ", "SMCX", "SRTY")
OBSERVATION_ONLY = tuple(sorted(set(LEGACY_VALUATION_ONLY) | set(LEGACY_QUARANTINED)))


def evidence_payload() -> dict[str, object]:
    return {
        "prior_registry_id": PRIOR_REGISTRY_ID,
        "successor_registry_id": REGISTRY_ID,
        "effective_session_date": EFFECTIVE_SESSION,
        "stock_strike_history_preserved": True,
        "etf_strike_history_preserved": True,
        "legacy_scorecard_quarantine_preserved": True,
        "model_candidates": list(MODEL_CANDIDATES),
        "observation_only": list(OBSERVATION_ONLY),
        "benchmarks": list(BENCHMARKS),
        "legacy_quarantine_cleared_for_future_evaluation": list(LEGACY_QUARANTINED),
        "allocation_authorized_for_legacy_quarantine": False,
        "owner_instruction": "Clean stock and ETF quarantine and start fresh",
    }


def canonical_evidence() -> str:
    return json.dumps(
        evidence_payload(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def evidence_sha256() -> str:
    return hashlib.sha256(canonical_evidence().encode("utf-8")).hexdigest()


def registry_rows(created_at: str) -> list[list[object]]:
    groups = (
        (MODEL_CANDIDATES, "MODEL_CANDIDATE", "Original sector ETF model universe"),
        (
            OBSERVATION_ONLY,
            "VALUATION_ONLY",
            "Fresh-start observation and valuation; no new allocation until validated",
        ),
        (BENCHMARKS, "BENCHMARK", "Market benchmark; not allocatable"),
    )
    rows = []
    for tickers, usage, reason in groups:
        for ticker in tickers:
            rows.append([REGISTRY_ID, ticker, "ETF", "ETF", usage, 252, reason, created_at])
    return sorted(rows, key=lambda row: str(row[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-evidence-sha256")
    args = parser.parse_args()
    checksum = evidence_sha256()
    if not args.apply:
        print(
            f"CHECKED_QUARANTINE_FRESH_START registry_id={REGISTRY_ID} "
            f"instruments={len(registry_rows('CHECK'))} reset_events=2 "
            f"evidence_sha256={checksum} no_changes=true"
        )
        return 0
    if not args.expected_evidence_sha256 or not re.fullmatch(
        r"[0-9a-f]{64}", args.expected_evidence_sha256
    ):
        raise SystemExit("--apply requires a 64-character expected evidence SHA-256.")
    if args.expected_evidence_sha256 != checksum:
        raise SystemExit("Reviewed quarantine evidence SHA-256 does not match.")

    import requests
    from dotenv import load_dotenv
    from scripts.stage_market_features_to_turso import post_statements
    from turso_read_pipeline import TursoReadPipeline

    load_dotenv(ROOT / ".env")
    raw_url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    db = TursoReadPipeline(endpoint, token, timeout_seconds=30.0)
    prior = db.execute(
        "SELECT status FROM market_instrument_registry_versions WHERE registry_id=?",
        [PRIOR_REGISTRY_ID],
    )
    if prior.rows != [["APPROVED"]]:
        raise SystemExit("Expected prior ETF registry is not the sole reviewed APPROVED version.")
    if db.execute(
        "SELECT COUNT(*) FROM market_instrument_registry_versions WHERE status='APPROVED'",
        [],
    ).rows != [[1]]:
        raise SystemExit("Exactly one approved registry is required before fresh start.")
    reset_table_exists = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        ["quarantine_reset_events"],
    ).rows == [[1]]
    if reset_table_exists and db.execute(
        "SELECT COUNT(*) FROM quarantine_reset_events WHERE reset_id IN (?,?)",
        ["stock_quarantine_reset_20260821", "etf_quarantine_reset_20260821"],
    ).rows != [[0]]:
        raise SystemExit("Fresh-start reset event already exists.")

    now = datetime.now(timezone.utc).isoformat()
    rows = registry_rows(now)
    migration = (ROOT / "migrations" / "20260824_quarantine_resets_additive.sql").read_text(
        encoding="utf-8"
    )
    ddl = [part.strip() for part in migration.split(";") if part.strip()]
    statements: list[tuple[str, list[object]]] = [(sql, []) for sql in ddl]
    statements.extend(
        [
            (
                "INSERT INTO quarantine_reset_events "
                "(reset_id,asset_class,mechanism,effective_session_date,reason,"
                "approved_by,approved_at_utc,created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                [
                    "stock_quarantine_reset_20260821", "STOCK",
                    "LEGACY_STRIKE_BLACKLIST", EFFECTIVE_SESSION,
                    "Owner-approved fresh start; prior ledger evidence retained",
                    "AviShemla", now, now,
                ],
            ),
            (
                "INSERT INTO quarantine_reset_events "
                "(reset_id,asset_class,mechanism,effective_session_date,reason,"
                "approved_by,approved_at_utc,created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                [
                    "etf_quarantine_reset_20260821", "ETF",
                    "LEGACY_STRIKE_BLACKLIST", EFFECTIVE_SESSION,
                    "Owner-approved fresh start; prior ledger evidence retained",
                    "AviShemla", now, now,
                ],
            ),
            (
                "UPDATE market_instrument_registry_versions SET status='SUPERSEDED' "
                "WHERE registry_id=? AND status='APPROVED'",
                [PRIOR_REGISTRY_ID],
            ),
            (
                "INSERT INTO market_instrument_registry_versions "
                "(registry_id,status,evidence_as_of_date,source_evidence_sha256,"
                "source_evidence_json,approved_by,approved_at_utc,created_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [
                    REGISTRY_ID, "APPROVED", EFFECTIVE_SESSION, checksum,
                    canonical_evidence(), "AviShemla", now, now,
                ],
            ),
        ]
    )
    row_sql = (
        "INSERT INTO market_instrument_registry "
        "(registry_id,ticker,asset_class,sector,usage,minimum_history_rows,"
        "classification_reason,created_at_utc) VALUES "
        + ",".join("(?,?,?,?,?,?,?,?)" for _ in rows)
    )
    statements.append((row_sql, [value for row in rows for value in row]))
    post_statements(requests.Session(), endpoint, token, statements)

    approved = db.execute(
        "SELECT registry_id FROM market_instrument_registry_versions "
        "WHERE status='APPROVED' ORDER BY registry_id",
        [],
    )
    resets = db.execute(
        "SELECT asset_class,effective_session_date FROM quarantine_reset_events "
        "WHERE reset_id IN (?,?) ORDER BY asset_class",
        ["stock_quarantine_reset_20260821", "etf_quarantine_reset_20260821"],
    )
    usages = db.execute(
        "SELECT usage,COUNT(*) FROM market_instrument_registry WHERE registry_id=? "
        "GROUP BY usage ORDER BY usage",
        [REGISTRY_ID],
    )
    if approved.rows != [[REGISTRY_ID]]:
        raise SystemExit("Fresh-start approved-registry read-back failed.")
    if resets.rows != [["ETF", EFFECTIVE_SESSION], ["STOCK", EFFECTIVE_SESSION]]:
        raise SystemExit("Fresh-start reset-event read-back failed.")
    if usages.rows != [["BENCHMARK", 1], ["MODEL_CANDIDATE", 11], ["VALUATION_ONLY", 14]]:
        raise SystemExit("Fresh-start registry-usage read-back failed.")
    print(
        f"APPLIED_QUARANTINE_FRESH_START registry_id={REGISTRY_ID} "
        f"evidence_sha256={checksum} readback=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
