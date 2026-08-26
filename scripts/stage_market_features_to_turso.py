"""One-time, resumable legacy recovery import into Turso staging tables.

This is the only permitted CSV boundary: an explicitly invoked migration tool.
Production model code must never import or call this module.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from turso_read_pipeline import TursoReadPipeline, _encode_arg


COLUMN_MAP = [
    ("Ticker", "ticker"), ("Date", "date"), ("Sector", "sector"),
    ("Open", "open_price"), ("High", "high_price"), ("Low", "low_price"),
    ("Close", "close_price"), ("Adj Close", "adjusted_close"), ("Volume", "volume"),
    ("Dividends", "dividends"), ("Stock Splits", "stock_splits"),
    ("Daily_Return_%", "daily_return_pct"), ("Daily_STDEV", "daily_stdev"),
    ("STDEV_5d", "stdev_5d"), ("STDEV_10d", "stdev_10d"),
    ("STDEV_20d", "stdev_20d"), ("Max_High_20d", "max_high_20d"),
    ("Min_Low_20d", "min_low_20d"), ("RSI_14d", "rsi_14d"),
    ("ATR_14d", "atr_14d"), ("Plus_DI_14d", "plus_di_14d"),
    ("Minus_DI_14d", "minus_di_14d"), ("ADX_14d", "adx_14d"),
    ("Dynamic_Stop_Loss", "dynamic_stop_loss"), ("RAS_Signal", "ras_signal"),
    ("Analyst_Consensus", "analyst_consensus"),
    ("Analyst_Upside_%", "analyst_upside_pct"),
    ("Sector_Momentum_Score", "sector_momentum_score"),
    ("Sector_Regime", "sector_regime"), ("VIX_Close", "vix_close"),
    ("Market_Fear_Level", "market_fear_level"), ("TNX_Close", "tnx_close"),
    ("TNX_Lag1_Return", "tnx_lag1_return"), ("TNX_Trend_5d", "tnx_trend_5d"),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def post_statements(session, endpoint, token, statements):
    requests_payload = [
        {
            "type": "execute",
            "stmt": {"sql": sql, "args": [_encode_arg(clean(value)) for value in args]},
        }
        for sql, args in statements
    ]
    requests_payload.append({"type": "close"})
    response = session.post(
        endpoint,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"requests": requests_payload},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Turso staging import failed with HTTP {response.status_code}.")
    results = response.json().get("results", [])
    if len(results) < len(statements) or any(item.get("type") != "ok" for item in results[:len(statements)]):
        raise RuntimeError("Turso rejected a staging import statement.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 800:
        raise SystemExit("Batch size must be between 1 and 800.")
    path = Path(args.csv_path).resolve()
    frame = pd.read_csv(path, low_memory=False)
    missing = sorted({source for source, _ in COLUMN_MAP}.difference(frame.columns))
    if missing:
        raise SystemExit(f"Missing required migration columns: {', '.join(missing)}")
    dates = pd.to_datetime(frame["Date"], errors="coerce")
    if dates.isna().any() or frame["Ticker"].isna().any():
        raise SystemExit("Legacy migration source has null/invalid key fields.")
    if frame.duplicated(["Date", "Ticker"]).any():
        raise SystemExit("Legacy migration source has duplicate ticker-date keys.")
    frame["Date"] = dates.dt.date.astype(str)
    latest_date = dates.max().date().isoformat()
    checksum = sha256_file(path)
    snapshot_id = f"market_features_{latest_date}_{checksum[:16]}"
    expected_rows = len(frame)
    expected_tickers = int(frame["Ticker"].nunique())

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    raw_url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not raw_url or not token:
        raise SystemExit("Turso environment variables are unavailable.")
    endpoint = raw_url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    reader = TursoReadPipeline(endpoint, token, timeout_seconds=30.0)
    existing = reader.execute(
        "SELECT COUNT(*) AS n FROM market_daily_features WHERE snapshot_id = ?",
        [snapshot_id],
    ).rows[0][0]
    if int(existing) > expected_rows:
        raise SystemExit("Existing staging snapshot has more rows than its source.")

    created_at = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    snapshot_sql = """
        INSERT OR IGNORE INTO model_input_snapshots
            (snapshot_id, dataset_type, source_session_date, available_at_utc,
             provider, code_version, source_checksum_sha256, expected_row_count,
             expected_ticker_count, status, validation_notes, created_at_utc)
        VALUES (?, 'MARKET_FEATURES', ?, ?, ?, ?, ?, ?, ?, 'STAGING', ?, ?)
    """
    post_statements(session, endpoint, token, [(
        snapshot_sql,
        [snapshot_id, latest_date, created_at, "LEGACY_RECOVERY_FILE", "legacy-spy-snapshot",
         checksum, expected_rows, expected_tickers,
         "Structural import only; independent market-data QA required before validation.", created_at],
    )])

    target_columns = [target for _, target in COLUMN_MAP]
    row_placeholders = "(" + ",".join("?" for _ in range(len(target_columns) + 1)) + ")"
    insert_prefix = (
        f"INSERT OR IGNORE INTO market_daily_features "
        f"(snapshot_id,{','.join(target_columns)}) VALUES "
    )
    batch_args = []
    batch_rows = 0

    def flush_batch() -> None:
        nonlocal batch_args, batch_rows
        if not batch_rows:
            return
        sql = insert_prefix + ",".join(row_placeholders for _ in range(batch_rows))
        post_statements(session, endpoint, token, [(sql, batch_args)])
        batch_args = []
        batch_rows = 0

    for position, row in enumerate(frame.itertuples(index=False, name=None), start=1):
        source = dict(zip(frame.columns, row))
        args_row = [snapshot_id] + [clean(source[name]) for name, _ in COLUMN_MAP]
        batch_args.extend(args_row)
        batch_rows += 1
        if batch_rows >= args.batch_size:
            flush_batch()
        if position % 10000 == 0:
            print(f"staged_source_rows={position}/{expected_rows}", flush=True)
    flush_batch()

    result = reader.execute(
        "SELECT COUNT(*) AS row_count, COUNT(DISTINCT ticker) AS ticker_count, "
        "MIN(date) AS first_date, MAX(date) AS latest_date "
        "FROM market_daily_features WHERE snapshot_id = ?",
        [snapshot_id],
    )
    values = dict(zip(result.columns, result.rows[0]))
    if int(values["row_count"]) != expected_rows or int(values["ticker_count"]) != expected_tickers:
        raise SystemExit("Staged Turso counts do not match the migration source.")
    print(
        f"STAGED_NOT_VALIDATED snapshot_id={snapshot_id} row_count={values['row_count']} "
        f"ticker_count={values['ticker_count']} first_date={values['first_date']} "
        f"latest_date={values['latest_date']} sha256={checksum}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
