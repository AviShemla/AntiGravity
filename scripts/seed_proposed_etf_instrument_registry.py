"""Check or seed the hash-locked 2026-08-22 ETF instrument registry proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.stage_market_features_to_turso import post_statements
from turso_read_pipeline import TursoReadPipeline


REGISTRY_ID = "etf_registry_20260822_v1"
MODEL_CANDIDATES = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
VALUATION_ONLY = ("IWD", "UDOW")
BENCHMARKS = ("SPY",)
QUARANTINED = ("IGV", "ITB", "IYH", "MRVU", "MSTZ", "MTUM", "MULL", "NBIL", "RDVY", "RGTZ", "SMCX", "SRTY")


def evidence_payload() -> dict[str, object]:
    return {
        "evidence_as_of_date": "2026-08-21",
        "legacy_etf_scorecard_distinct_tickers": 26,
        "model_candidates": list(MODEL_CANDIDATES),
        "valuation_only": list(VALUATION_ONLY),
        "benchmarks": list(BENCHMARKS),
        "quarantined": list(QUARANTINED),
        "short_history_rows": {"MRVU": 133, "NBIL": 220, "RGTZ": 218},
        "minimum_model_history_rows": 252,
        "source": "Turso audit plus bounded Yahoo/Tiingo provider validation",
    }


def canonical_evidence() -> str:
    return json.dumps(evidence_payload(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def evidence_sha256() -> str:
    return hashlib.sha256(canonical_evidence().encode("utf-8")).hexdigest()


def proposed_instruments(created_at: str) -> list[list[object]]:
    rows: list[list[object]] = []
    groups = (
        (MODEL_CANDIDATES, "MODEL_CANDIDATE", "Original sector ETF model universe"),
        (VALUATION_ONLY, "VALUATION_ONLY", "Required for existing-holding valuation; no new allocation"),
        (BENCHMARKS, "BENCHMARK", "Market benchmark; not an allocatable model candidate"),
        (QUARANTINED, "QUARANTINED", "Historical experiment or insufficient approved model-use evidence"),
    )
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
            f"CHECKED_REGISTRY_PROPOSAL registry_id={REGISTRY_ID} instruments=26 "
            f"evidence_sha256={checksum} no_changes=true"
        )
        return 0
    if not args.expected_evidence_sha256 or not re.fullmatch(
        r"[0-9a-f]{64}", args.expected_evidence_sha256
    ):
        raise SystemExit("--apply requires a 64-character expected evidence SHA-256.")
    if args.expected_evidence_sha256 != checksum:
        raise SystemExit("Registry evidence SHA-256 does not match the reviewed proposal.")

    load_dotenv(ROOT / ".env")
    raw_url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    timestamp = datetime.now(timezone.utc).isoformat()
    rows = proposed_instruments(timestamp)
    statements = [(
        "INSERT OR IGNORE INTO market_instrument_registry_versions "
        "(registry_id,status,evidence_as_of_date,source_evidence_sha256,source_evidence_json,"
        "approved_by,approved_at_utc,created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
        [
            REGISTRY_ID, "APPROVED", "2026-08-21", checksum, canonical_evidence(),
            "AviShemla", timestamp, timestamp,
        ],
    )]
    statement = (
        "INSERT OR IGNORE INTO market_instrument_registry "
        "(registry_id,ticker,asset_class,sector,usage,minimum_history_rows,"
        "classification_reason,created_at_utc) VALUES "
        + ",".join("(?,?,?,?,?,?,?,?)" for _ in rows)
    )
    statements.append((statement, [value for row in rows for value in row]))
    post_statements(requests.Session(), endpoint, token, statements)

    db = TursoReadPipeline(endpoint, token, timeout_seconds=30.0)
    version = db.execute(
        "SELECT status,evidence_as_of_date,source_evidence_sha256,approved_by "
        "FROM market_instrument_registry_versions WHERE registry_id=?",
        [REGISTRY_ID],
    )
    instruments = db.execute(
        "SELECT ticker,usage,minimum_history_rows FROM market_instrument_registry "
        "WHERE registry_id=? ORDER BY ticker",
        [REGISTRY_ID],
    )
    if version.rows != [["APPROVED", "2026-08-21", checksum, "AviShemla"]]:
        raise SystemExit("Registry version read-back does not match the approved payload.")
    expected_rows = [[row[1], row[4], row[5]] for row in rows]
    if instruments.rows != expected_rows:
        raise SystemExit("Registry instrument read-back does not match the approved payload.")
    print(
        f"SEEDED_APPROVED_REGISTRY registry_id={REGISTRY_ID} instruments={len(rows)} "
        f"evidence_sha256={checksum} readback=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
