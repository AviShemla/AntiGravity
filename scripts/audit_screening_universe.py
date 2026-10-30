"""Read-only proof of the candidates authorized by one validated screening run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from screening_universe_reader import load_screening_universe
from turso_read_pipeline import TursoReadPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screening-run-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--source-session", required=True)
    parser.add_argument("--maximum-candidates", type=int, default=10)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    db = TursoReadPipeline(
        raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline",
        token,
        timeout_seconds=30.0,
    )
    universe = load_screening_universe(
        db,
        screening_run_id=args.screening_run_id,
        expected_market_snapshot_id=args.snapshot_id,
        expected_source_session_date=args.source_session,
        maximum_candidates=args.maximum_candidates,
    )
    print(json.dumps({
        "status": "PASS",
        "screening_run_id": universe.screening_run_id,
        "market_snapshot_id": universe.market_snapshot_id,
        "source_session_date": universe.source_session_date,
        "disposition": universe.disposition,
        "candidate_count": len(universe.candidates),
        "candidates": [asdict(item) for item in universe.candidates],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
