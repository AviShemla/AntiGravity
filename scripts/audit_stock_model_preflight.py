"""Read-only proof of the stock-model input preflight against Turso."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from stock_model_preflight import build_stock_model_preflight
from turso_read_pipeline import TursoReadPipeline


def _load_local_secret_env(path: Path) -> None:
    """Load the ignored local secret file without logging any value."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session-date", required=True)
    parser.add_argument("--prediction-date", required=True)
    parser.add_argument("--cutoff-utc", required=True)
    parser.add_argument("--minimum-history-sessions", type=int, default=252)
    args = parser.parse_args()

    source = date.fromisoformat(args.source_session_date)
    prediction = date.fromisoformat(args.prediction_date)
    cutoff = datetime.fromisoformat(args.cutoff_utc.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise SystemExit("--cutoff-utc must be timezone-aware.")

    _load_local_secret_env(ROOT / ".env")
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    db = TursoReadPipeline(endpoint, token, timeout_seconds=30.0)
    try:
        evidence = build_stock_model_preflight(
            db,
            source_session_date=source,
            prediction_date=prediction,
            cutoff_utc=cutoff,
            minimum_history_sessions=args.minimum_history_sessions,
        )
    except LineageError as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "mode": "READ_ONLY_PREFLIGHT",
            "source_session_date": source.isoformat(),
            "prediction_date": prediction.isoformat(),
            "reason": str(exc),
            "model_started": False,
            "recommendation_created": False,
            "order_created": False,
        }, sort_keys=True))
        return 2

    print(json.dumps({
        "status": "PASS",
        "mode": "READ_ONLY_PREFLIGHT",
        "source_session_date": source.isoformat(),
        "prediction_date": prediction.isoformat(),
        "market_snapshot_id": evidence.market_snapshot.snapshot_id,
        "universe_snapshot_id": evidence.universe_snapshot.snapshot_id,
        "approval_event_id": evidence.universe_approval.event_id,
        "screening_run_id": evidence.screening_run_id,
        "candidate_count": len(evidence.universe),
        "required_market_ticker_count": len(evidence.required_market_tickers),
        "model_started": False,
        "recommendation_created": False,
        "order_created": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
