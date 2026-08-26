#!/usr/bin/env python3
"""SELECT-only quality and coverage audit for the pinned Oracle stock history."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_lineage import LineageError
from scripts.audit_validated_replacement_snapshot import provider_lineage_checksum
from scripts.run_oracle_research_dataset_isolated_matrix_lifecycle import (
    _production_credentials,
)
from turso_read_pipeline import TursoReadPipeline


EVIDENCE_CONTRACT = "oracle-pinned-historical-quality-audit-v1"
METADATA_SQL = (
    "SELECT snapshot_id,dataset_type,source_session_date,provider,code_version,"
    "source_checksum_sha256,expected_row_count,expected_ticker_count,status "
    "FROM model_input_snapshots WHERE snapshot_id=?"
)
COVERAGE_SQL = (
    "SELECT COUNT(*) AS row_count,COUNT(DISTINCT ticker) AS ticker_count,"
    "COUNT(DISTINCT date) AS session_count,MIN(date) AS first_date,MAX(date) AS last_date "
    "FROM market_daily_features WHERE snapshot_id=?"
)
DUPLICATE_SQL = (
    "SELECT COALESCE(SUM(n-1),0) AS duplicate_rows,COUNT(*) AS duplicate_keys FROM "
    "(SELECT ticker,date,COUNT(*) AS n FROM market_daily_features WHERE snapshot_id=? "
    "GROUP BY ticker,date HAVING COUNT(*)>1)"
)
QUALITY_SQL = (
    "SELECT SUM(CASE WHEN ticker IS NULL OR ticker='' THEN 1 ELSE 0 END) AS null_ticker,"
    "SUM(CASE WHEN date IS NULL OR date='' THEN 1 ELSE 0 END) AS null_date,"
    "SUM(CASE WHEN sector IS NULL OR sector='' THEN 1 ELSE 0 END) AS null_sector,"
    "SUM(CASE WHEN open_price IS NULL OR high_price IS NULL OR low_price IS NULL OR "
    "close_price IS NULL OR adjusted_close IS NULL OR volume IS NULL THEN 1 ELSE 0 END) "
    "AS null_ohlcv,SUM(CASE WHEN open_price<=0 OR high_price<=0 OR low_price<=0 OR "
    "close_price<=0 OR adjusted_close<=0 THEN 1 ELSE 0 END) AS nonpositive_prices,"
    "SUM(CASE WHEN high_price<open_price OR high_price<close_price OR high_price<low_price "
    "THEN 1 ELSE 0 END) AS high_violations,"
    "SUM(CASE WHEN low_price>open_price OR low_price>close_price OR low_price>high_price "
    "THEN 1 ELSE 0 END) AS low_violations,"
    "SUM(CASE WHEN volume<0 THEN 1 ELSE 0 END) AS negative_volume,"
    "SUM(CASE WHEN daily_return_pct IS NULL OR daily_stdev IS NULL OR stdev_5d IS NULL OR "
    "stdev_10d IS NULL OR stdev_20d IS NULL OR max_high_20d IS NULL OR min_low_20d IS NULL "
    "OR rsi_14d IS NULL OR atr_14d IS NULL OR plus_di_14d IS NULL OR minus_di_14d IS NULL "
    "OR adx_14d IS NULL OR dynamic_stop_loss IS NULL OR ras_signal IS NULL OR "
    "sector_momentum_score IS NULL OR sector_regime IS NULL OR vix_close IS NULL OR "
    "market_fear_level IS NULL OR tnx_close IS NULL OR tnx_lag1_return IS NULL OR "
    "tnx_trend_5d IS NULL THEN 1 ELSE 0 END) AS null_critical_features "
    "FROM market_daily_features WHERE snapshot_id=?"
)
TICKER_COVERAGE_SQL = (
    "SELECT ticker,COUNT(*) AS row_count,COUNT(DISTINCT date) AS session_count,"
    "MIN(date) AS first_date,MAX(date) AS last_date FROM market_daily_features "
    "WHERE snapshot_id=? GROUP BY ticker ORDER BY ticker"
)
SESSION_SUMMARY_SQL = (
    "SELECT MIN(n) AS min_tickers,MAX(n) AS max_tickers,"
    "SUM(CASE WHEN n=? THEN 1 ELSE 0 END) AS full_ticker_sessions,COUNT(*) AS sessions "
    "FROM (SELECT date,COUNT(DISTINCT ticker) AS n FROM market_daily_features "
    "WHERE snapshot_id=? GROUP BY date)"
)
DATES_SQL = "SELECT DISTINCT date FROM market_daily_features WHERE snapshot_id=? ORDER BY date"
PROVIDER_ROWS_SQL = (
    "SELECT ticker,provider,requested_source_session_date,first_available_date,"
    "last_available_date,source_row_count,source_checksum_sha256 FROM "
    "market_data_provider_lineage WHERE snapshot_id=? ORDER BY ticker"
)
PROVIDER_COUNTS_SQL = (
    "SELECT COUNT(*) AS lineage_rows,COUNT(DISTINCT ticker) AS lineage_tickers,"
    "SUM(CASE WHEN provider NOT IN ('YAHOO_FINANCE','TIINGO_EOD') THEN 1 ELSE 0 END) "
    "AS invalid_provider,SUM(CASE WHEN requested_source_session_date<>? OR "
    "last_available_date<>? OR source_checksum_sha256 IS NULL OR "
    "LENGTH(source_checksum_sha256)<>64 THEN 1 ELSE 0 END) AS invalid_lineage,"
    "COUNT(*)-COUNT(DISTINCT ticker) AS duplicate_lineage FROM "
    "market_data_provider_lineage WHERE snapshot_id=?"
)
PROVIDER_SUMMARY_SQL = (
    "SELECT provider,COUNT(*) AS ticker_count,SUM(source_row_count) AS source_rows,"
    "MIN(first_available_date) AS first_min,MAX(last_available_date) AS last_max,"
    "COUNT(DISTINCT source_checksum_sha256) AS checksum_count FROM "
    "market_data_provider_lineage WHERE snapshot_id=? GROUP BY provider ORDER BY provider"
)
MISSING_LINEAGE_SQL = (
    "SELECT COUNT(*) AS count FROM (SELECT DISTINCT f.ticker FROM market_daily_features f "
    "LEFT JOIN market_data_provider_lineage l ON l.snapshot_id=f.snapshot_id AND "
    "l.ticker=f.ticker WHERE f.snapshot_id=? AND l.ticker IS NULL)"
)
EXTRA_LINEAGE_SQL = (
    "SELECT l.ticker FROM market_data_provider_lineage l LEFT JOIN "
    "(SELECT DISTINCT ticker FROM market_daily_features WHERE snapshot_id=?) f "
    "ON f.ticker=l.ticker WHERE l.snapshot_id=? AND f.ticker IS NULL ORDER BY l.ticker"
)
PRIMARY_KEY_SQL = (
    "SELECT COUNT(*) AS count FROM sqlite_schema WHERE type='table' AND "
    "name='market_daily_features' AND sql LIKE '%PRIMARY KEY (snapshot_id, ticker, date)%'"
)


@dataclass(frozen=True)
class HistoricalQualityContract:
    snapshot_id: str
    checksum_sha256: str
    source_session_date: str
    provider: str
    code_version: str
    row_count: int
    ticker_count: int
    session_count: int
    first_date: str
    ticker_grid_missing_cells: int
    full_coverage_tickers: int
    min_ticker_sessions: int
    max_ticker_sessions: int
    ticker_session_distribution: tuple[tuple[int, int], ...]
    ticker_coverage_sha256: str
    calendar_sha256: str
    provider_lineage_rows: int
    provider_lineage_sha256: str
    provider_summary: tuple[tuple[str, int, int, str, str, int], ...]
    extra_lineage_tickers: tuple[str, ...]
    min_session_tickers: int
    max_session_tickers: int
    full_ticker_sessions: int


PINNED = HistoricalQualityContract(
    snapshot_id="market_features_2026-08-25_5b1044ee45605a3d",
    checksum_sha256="5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011",
    source_session_date="2026-08-25",
    provider="TIINGO_EOD+YAHOO_FINANCE",
    code_version="1e28786832b633c8b63163e7954e3297b0b9ec0e",
    row_count=586_710,
    ticker_count=474,
    session_count=1_246,
    first_date="2021-09-08",
    ticker_grid_missing_cells=3_894,
    full_coverage_tickers=466,
    min_ticker_sessions=358,
    max_ticker_sessions=1_246,
    ticker_session_distribution=(
        (358, 1), (478, 1), (579, 1), (583, 1), (804, 1), (899, 1),
        (1128, 1), (1245, 1), (1246, 466),
    ),
    ticker_coverage_sha256="fa0d8f75e48b7367bb8ba7b7fda2f0db5447f7f9473efa3657f002de8a52d042",
    calendar_sha256="030b17a6d94cfebdd24582b8206357b6905c58e5b3d10796b0c8ee3c87b53eeb",
    provider_lineage_rows=476,
    provider_lineage_sha256="7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a",
    provider_summary=(
        ("TIINGO_EOD", 24, 30_528, "2021-08-02", "2026-08-25", 24),
        ("YAHOO_FINANCE", 452, 571_051, "2021-08-02", "2026-08-25", 452),
    ),
    extra_lineage_tickers=("^TNX", "^VIX"),
    min_session_tickers=467,
    max_session_tickers=474,
    full_ticker_sessions=357,
)


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _rows(result, columns: tuple[str, ...], label: str) -> list[dict[str, object]]:
    if tuple(getattr(result, "columns", ())) != columns:
        raise LineageError(f"{label} column contract differs.")
    output = []
    for row in getattr(result, "rows", ()):
        if len(row) != len(columns):
            raise LineageError(f"{label} row shape differs.")
        output.append(dict(zip(columns, row)))
    return output


def _one(result, columns: tuple[str, ...], label: str) -> dict[str, object]:
    rows = _rows(result, columns, label)
    if len(rows) != 1:
        raise LineageError(f"{label} did not return exactly one row.")
    return rows[0]


def _calendar_dates(first_date: str, last_date: str) -> list[str]:
    import pandas as pd
    import pandas_market_calendars as mcal
    schedule = mcal.get_calendar("NYSE").schedule(start_date=first_date, end_date=last_date)
    return [pd.Timestamp(value).date().isoformat() for value in schedule.index]


def collect_historical_quality(
    client,
    *,
    contract: HistoricalQualityContract = PINNED,
    calendar_provider=_calendar_dates,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Collect bounded aggregate/list SELECTs and evaluate the immutable contract."""

    sid = contract.snapshot_id
    metadata = _one(client.execute(METADATA_SQL, [sid]), (
        "snapshot_id","dataset_type","source_session_date","provider","code_version",
        "source_checksum_sha256","expected_row_count","expected_ticker_count","status",
    ), "metadata")
    coverage = _one(client.execute(COVERAGE_SQL, [sid]), (
        "row_count","ticker_count","session_count","first_date","last_date",
    ), "coverage")
    duplicates = _one(client.execute(DUPLICATE_SQL, [sid]),
        ("duplicate_rows","duplicate_keys"), "duplicates")
    quality = _one(client.execute(QUALITY_SQL, [sid]), (
        "null_ticker","null_date","null_sector","null_ohlcv","nonpositive_prices",
        "high_violations","low_violations","negative_volume","null_critical_features",
    ), "quality")
    ticker_coverage = _rows(client.execute(TICKER_COVERAGE_SQL, [sid]),
        ("ticker","row_count","session_count","first_date","last_date"), "ticker coverage")
    session_summary = _one(
        client.execute(SESSION_SUMMARY_SQL, [contract.ticker_count, sid]),
        ("min_tickers","max_tickers","full_ticker_sessions","sessions"), "sessions")
    observed_dates = [row["date"] for row in _rows(
        client.execute(DATES_SQL, [sid]), ("date",), "dates")]
    expected_dates = calendar_provider(contract.first_date, contract.source_session_date)
    provider_result = client.execute(PROVIDER_ROWS_SQL, [sid])
    provider_columns = (
        "ticker","provider","requested_source_session_date","first_available_date",
        "last_available_date","source_row_count","source_checksum_sha256",
    )
    provider_rows = _rows(provider_result, provider_columns, "provider rows")
    provider_values = [[row[column] for column in provider_columns] for row in provider_rows]
    provider_counts = _one(client.execute(PROVIDER_COUNTS_SQL, [
        contract.source_session_date, contract.source_session_date, sid,
    ]), ("lineage_rows","lineage_tickers","invalid_provider","invalid_lineage",
        "duplicate_lineage"), "provider counts")
    provider_summary_rows = _rows(client.execute(PROVIDER_SUMMARY_SQL, [sid]), (
        "provider","ticker_count","source_rows","first_min","last_max","checksum_count",
    ), "provider summary")
    provider_summary = tuple(tuple(row.values()) for row in provider_summary_rows)
    missing_lineage = _one(client.execute(MISSING_LINEAGE_SQL, [sid]), ("count",),
        "missing lineage")["count"]
    extra_lineage = tuple(row["ticker"] for row in _rows(
        client.execute(EXTRA_LINEAGE_SQL, [sid, sid]), ("ticker",), "extra lineage"))
    primary_key = _one(client.execute(PRIMARY_KEY_SQL, []), ("count",), "primary key")["count"]

    distribution: dict[int, int] = {}
    for row in ticker_coverage:
        count = int(row["session_count"])
        distribution[count] = distribution.get(count, 0) + 1
    grid_cells = int(coverage["ticker_count"]) * int(coverage["session_count"])
    grid = {
        "possible_cells": grid_cells,
        "observed_cells": int(coverage["row_count"]),
        "missing_cells": grid_cells - int(coverage["row_count"]),
        "full_coverage_tickers": sum(
            int(row["session_count"]) == int(coverage["session_count"])
            for row in ticker_coverage
        ),
        "min_ticker_sessions": min(int(row["session_count"]) for row in ticker_coverage),
        "max_ticker_sessions": max(int(row["session_count"]) for row in ticker_coverage),
        "session_distribution": [[key, distribution[key]] for key in sorted(distribution)],
        "ticker_coverage_sha256": _canonical_sha(ticker_coverage),
    }
    calendar = {
        "expected_sessions": len(expected_dates),
        "observed_sessions": len(observed_dates),
        "missing_sessions": len(set(expected_dates) - set(observed_dates)),
        "non_session_dates": len(set(observed_dates) - set(expected_dates)),
        "expected_sha256": _canonical_sha(expected_dates),
        "observed_sha256": _canonical_sha(observed_dates),
    }
    checks = {
        "metadata_exact": metadata == {
            "snapshot_id": sid, "dataset_type": "MARKET_FEATURES",
            "source_session_date": contract.source_session_date, "provider": contract.provider,
            "code_version": contract.code_version, "source_checksum_sha256": contract.checksum_sha256,
            "expected_row_count": contract.row_count, "expected_ticker_count": contract.ticker_count,
            "status": "VALIDATED",
        },
        "coverage_exact": coverage == {
            "row_count": contract.row_count, "ticker_count": contract.ticker_count,
            "session_count": contract.session_count, "first_date": contract.first_date,
            "last_date": contract.source_session_date,
        },
        "duplicates_zero": duplicates == {"duplicate_rows": 0, "duplicate_keys": 0},
        "missingness_zero": all(int(quality[key]) == 0 for key in (
            "null_ticker", "null_date", "null_sector", "null_ohlcv",
            "null_critical_features",
        )),
        "ohlc_valid": all(int(quality[key]) == 0 for key in (
            "nonpositive_prices", "high_violations", "low_violations", "negative_volume",
        )),
        "ticker_session_grid_exact": (
            grid["missing_cells"] == contract.ticker_grid_missing_cells
            and grid["full_coverage_tickers"] == contract.full_coverage_tickers
            and grid["min_ticker_sessions"] == contract.min_ticker_sessions
            and grid["max_ticker_sessions"] == contract.max_ticker_sessions
            and tuple((int(a), int(b)) for a, b in grid["session_distribution"])
            == contract.ticker_session_distribution
            and grid["ticker_coverage_sha256"] == contract.ticker_coverage_sha256
        ),
        "calendar_exact": (
            calendar["expected_sessions"] == calendar["observed_sessions"] == contract.session_count
            and calendar["missing_sessions"] == calendar["non_session_dates"] == 0
            and calendar["expected_sha256"] == calendar["observed_sha256"]
            == contract.calendar_sha256
        ),
        "per_session_coverage_exact": session_summary == {
            "min_tickers": contract.min_session_tickers,
            "max_tickers": contract.max_session_tickers,
            "full_ticker_sessions": contract.full_ticker_sessions,
            "sessions": contract.session_count,
        },
        "provider_lineage_exact": (
            provider_counts == {
                "lineage_rows": contract.provider_lineage_rows,
                "lineage_tickers": contract.provider_lineage_rows,
                "invalid_provider": 0, "invalid_lineage": 0, "duplicate_lineage": 0,
            }
            and provider_lineage_checksum(provider_values) == contract.provider_lineage_sha256
            and provider_summary == contract.provider_summary
            and int(missing_lineage) == 0 and extra_lineage == contract.extra_lineage_tickers
        ),
        "primary_key_exact": int(primary_key) == 1,
    }
    timestamp = observed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise LineageError("Audit timestamp must be timezone-aware.")
    payload: dict[str, object] = {
        "evidence_contract": EVIDENCE_CONTRACT,
        "observed_at_utc": timestamp.astimezone(timezone.utc).isoformat(),
        "snapshot_id": sid,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "denominators": {
            "rows": contract.row_count, "tickers": contract.ticker_count,
            "sessions": contract.session_count,
            "ticker_session_cells": contract.ticker_count * contract.session_count,
            "provider_lineage_rows": contract.provider_lineage_rows,
        },
        "coverage": coverage,
        "duplicates": duplicates,
        "quality": quality,
        "ticker_session_grid": grid,
        "calendar": calendar,
        "per_session_coverage": session_summary,
        "provider_lineage": {
            **provider_counts, "sha256": provider_lineage_checksum(provider_values),
            "summary": provider_summary_rows, "feature_tickers_without_lineage": missing_lineage,
            "extra_lineage_tickers": list(extra_lineage),
        },
        "checks": checks,
        "read_only": True,
        "sanitization": {"credentials_included": False, "source_rows_included": False},
    }
    payload["evidence_sha256"] = _canonical_sha(payload)
    return payload


def write_evidence_once(path: Path, payload: dict[str, object]) -> str:
    """Atomically create one mode-600 evidence file; never replace or follow links."""
    path = Path(path)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise LineageError("Evidence target must be a new absolute path.")
    parent = path.parent.resolve(strict=True)
    if parent != path.parent or not parent.is_dir():
        raise LineageError("Evidence parent identity is not exact.")
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = parent / f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
        getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise LineageError("Evidence write did not make progress.")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise LineageError("Evidence target was created concurrently.") from exc
    finally:
        os.unlink(temporary)
    directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise LineageError("Evidence file metadata is not exact.")
    return hashlib.sha256(raw).hexdigest()


def run_audit_cli(
    argv: list[str] | None = None,
    *,
    credentials_loader=_production_credentials,
    client_factory=None,
    collector=collect_historical_quality,
    evidence_writer=write_evidence_once,
    effective_uid=os.geteuid,
) -> int:
    """Run the audit through injectable seams without mutating process environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not 10 <= args.timeout_seconds <= 300:
        raise LineageError("Timeout is outside the allowed range.")
    if effective_uid() != 0:
        raise LineageError("Historical quality audit must run as root.")
    if not args.env_file.is_absolute():
        raise LineageError("Production credential path must be absolute.")
    _, token, endpoint = credentials_loader(args.env_file)
    factory = client_factory or (
        lambda value, secret, timeout: TursoReadPipeline(
            value, secret, timeout_seconds=timeout
        )
    )
    client = factory(endpoint, token, args.timeout_seconds)
    payload = collector(client)
    evidence_writer(args.evidence_json, payload)
    return 0 if payload["status"] == "PASS" else 1


def main(argv: list[str] | None = None, **injected) -> int:
    try:
        return run_audit_cli(argv, **injected)
    except Exception:
        print(
            "Historical quality audit failed; inspect only redacted operational evidence.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
