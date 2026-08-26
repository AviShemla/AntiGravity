from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from model_lineage import LineageError
from scripts.audit_pinned_historical_snapshot_quality import (
    COVERAGE_SQL,
    DATES_SQL,
    DUPLICATE_SQL,
    EXTRA_LINEAGE_SQL,
    METADATA_SQL,
    MISSING_LINEAGE_SQL,
    PRIMARY_KEY_SQL,
    PROVIDER_COUNTS_SQL,
    PROVIDER_ROWS_SQL,
    PROVIDER_SUMMARY_SQL,
    QUALITY_SQL,
    SESSION_SUMMARY_SQL,
    TICKER_COVERAGE_SQL,
    HistoricalQualityContract,
    _canonical_sha,
    collect_historical_quality,
    main,
    run_audit_cli,
    write_evidence_once,
)
from scripts.audit_validated_replacement_snapshot import provider_lineage_checksum
from scripts.run_oracle_research_dataset_isolated_matrix_lifecycle import (
    WorkerError,
    _production_credentials,
)
from turso_read_pipeline import PipelineResult


SID = "market-test"
DATES = ["2026-01-02", "2026-01-05", "2026-01-06"]
TICKER_COVERAGE = [
    {"ticker": "AAA", "row_count": 3, "session_count": 3,
     "first_date": DATES[0], "last_date": DATES[-1]},
    {"ticker": "BBB", "row_count": 2, "session_count": 2,
     "first_date": DATES[0], "last_date": DATES[1]},
]
PROVIDER_ROWS = [
    ["AAA", "YAHOO_FINANCE", DATES[-1], DATES[0], DATES[-1], 3, "1" * 64],
    ["BBB", "YAHOO_FINANCE", DATES[-1], DATES[0], DATES[-1], 2, "2" * 64],
    ["^TNX", "YAHOO_FINANCE", DATES[-1], DATES[0], DATES[-1], 3, "3" * 64],
    ["^VIX", "YAHOO_FINANCE", DATES[-1], DATES[0], DATES[-1], 3, "4" * 64],
]


def contract():
    return HistoricalQualityContract(
        snapshot_id=SID,
        checksum_sha256="a" * 64,
        source_session_date=DATES[-1],
        provider="TIINGO_EOD+YAHOO_FINANCE",
        code_version="b" * 40,
        row_count=5,
        ticker_count=2,
        session_count=3,
        first_date=DATES[0],
        ticker_grid_missing_cells=1,
        full_coverage_tickers=1,
        min_ticker_sessions=2,
        max_ticker_sessions=3,
        ticker_session_distribution=((2, 1), (3, 1)),
        ticker_coverage_sha256=_canonical_sha(TICKER_COVERAGE),
        calendar_sha256=_canonical_sha(DATES),
        provider_lineage_rows=4,
        provider_lineage_sha256=provider_lineage_checksum(PROVIDER_ROWS),
        provider_summary=(("YAHOO_FINANCE", 4, 11, DATES[0], DATES[-1], 4),),
        extra_lineage_tickers=("^TNX", "^VIX"),
        min_session_tickers=1,
        max_session_tickers=2,
        full_ticker_sessions=2,
    )


def result(columns, rows):
    return PipelineResult(tuple(columns), tuple(tuple(row) for row in rows))


class Client:
    def __init__(self, mutations=None):
        self.mutations = mutations or {}
        self.calls = []

    def execute(self, sql, args):
        self.calls.append((sql, list(args)))
        if sql in self.mutations:
            return self.mutations[sql]
        mapping = {
            METADATA_SQL: result(
                ("snapshot_id","dataset_type","source_session_date","provider","code_version",
                 "source_checksum_sha256","expected_row_count","expected_ticker_count","status"),
                [[SID,"MARKET_FEATURES",DATES[-1],"TIINGO_EOD+YAHOO_FINANCE","b"*40,
                  "a"*64,5,2,"VALIDATED"]],
            ),
            COVERAGE_SQL: result(
                ("row_count","ticker_count","session_count","first_date","last_date"),
                [[5,2,3,DATES[0],DATES[-1]]],
            ),
            DUPLICATE_SQL: result(("duplicate_rows","duplicate_keys"), [[0,0]]),
            QUALITY_SQL: result(
                ("null_ticker","null_date","null_sector","null_ohlcv","nonpositive_prices",
                 "high_violations","low_violations","negative_volume","null_critical_features"),
                [[0,0,0,0,0,0,0,0,0]],
            ),
            TICKER_COVERAGE_SQL: result(
                ("ticker","row_count","session_count","first_date","last_date"),
                [[row[key] for key in ("ticker","row_count","session_count","first_date","last_date")]
                 for row in TICKER_COVERAGE],
            ),
            SESSION_SUMMARY_SQL: result(
                ("min_tickers","max_tickers","full_ticker_sessions","sessions"), [[1,2,2,3]]
            ),
            DATES_SQL: result(("date",), [[value] for value in DATES]),
            PROVIDER_ROWS_SQL: result(
                ("ticker","provider","requested_source_session_date","first_available_date",
                 "last_available_date","source_row_count","source_checksum_sha256"),
                PROVIDER_ROWS,
            ),
            PROVIDER_COUNTS_SQL: result(
                ("lineage_rows","lineage_tickers","invalid_provider","invalid_lineage",
                 "duplicate_lineage"), [[4,4,0,0,0]],
            ),
            PROVIDER_SUMMARY_SQL: result(
                ("provider","ticker_count","source_rows","first_min","last_max","checksum_count"),
                [["YAHOO_FINANCE",4,11,DATES[0],DATES[-1],4]],
            ),
            MISSING_LINEAGE_SQL: result(("count",), [[0]]),
            EXTRA_LINEAGE_SQL: result(("ticker",), [["^TNX"],["^VIX"]]),
            PRIMARY_KEY_SQL: result(("count",), [[1]]),
        }
        return mapping[sql]


def audit(client=None, **kwargs):
    return collect_historical_quality(
        client or Client(), contract=contract(), calendar_provider=lambda first, last: DATES,
        observed_at=datetime(2026, 1, 7, tzinfo=timezone.utc), **kwargs,
    )


def test_complete_select_only_contract_passes_with_exact_denominators_and_digest():
    client = Client()
    payload = audit(client)
    assert payload["status"] == "PASS"
    assert all(payload["checks"].values())
    assert payload["denominators"] == {
        "rows": 5, "tickers": 2, "sessions": 3,
        "ticker_session_cells": 6, "provider_lineage_rows": 4,
    }
    assert payload["ticker_session_grid"]["missing_cells"] == 1
    assert payload["provider_lineage"]["feature_tickers_without_lineage"] == 0
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in client.calls)
    claimed = payload.pop("evidence_sha256")
    assert claimed == _canonical_sha(payload)


@pytest.mark.parametrize(
    "sql,replacement,failed_check",
    [
        (DUPLICATE_SQL, result(("duplicate_rows","duplicate_keys"), [[1,1]]), "duplicates_zero"),
        (QUALITY_SQL, result(
            ("null_ticker","null_date","null_sector","null_ohlcv","nonpositive_prices",
             "high_violations","low_violations","negative_volume","null_critical_features"),
            [[0,0,0,0,0,1,0,0,0]]), "ohlc_valid"),
        (COVERAGE_SQL, result(
            ("row_count","ticker_count","session_count","first_date","last_date"),
            [[4,2,3,DATES[0],DATES[-1]]]), "coverage_exact"),
        (PROVIDER_COUNTS_SQL, result(
            ("lineage_rows","lineage_tickers","invalid_provider","invalid_lineage",
             "duplicate_lineage"), [[4,4,1,0,0]]), "provider_lineage_exact"),
        (MISSING_LINEAGE_SQL, result(("count",), [[1]]), "provider_lineage_exact"),
        (PRIMARY_KEY_SQL, result(("count",), [[0]]), "primary_key_exact"),
    ],
)
def test_each_quality_or_lineage_drift_fails_closed(sql, replacement, failed_check):
    payload = audit(Client({sql: replacement}))
    assert payload["status"] == "FAIL"
    assert payload["checks"][failed_check] is False


def test_ticker_session_distribution_or_digest_drift_fails_closed():
    changed = [dict(row) for row in TICKER_COVERAGE]
    changed[1]["session_count"] = 1
    replacement = result(
        ("ticker","row_count","session_count","first_date","last_date"),
        [[row[key] for key in ("ticker","row_count","session_count","first_date","last_date")]
         for row in changed],
    )
    payload = audit(Client({TICKER_COVERAGE_SQL: replacement}))
    assert payload["status"] == "FAIL"
    assert payload["checks"]["ticker_session_grid_exact"] is False


def test_missing_or_non_session_calendar_date_fails_closed():
    payload = collect_historical_quality(
        Client(), contract=contract(),
        calendar_provider=lambda first, last: DATES[:-1] + ["2026-01-07"],
        observed_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
    )
    assert payload["status"] == "FAIL"
    assert payload["calendar"]["missing_sessions"] == 1
    assert payload["calendar"]["non_session_dates"] == 1
    assert payload["checks"]["calendar_exact"] is False


def test_invalid_columns_and_naive_timestamp_raise_instead_of_emitting_evidence():
    with pytest.raises(LineageError, match="column contract"):
        audit(Client({COVERAGE_SQL: result(("wrong",), [[1]])}))
    with pytest.raises(LineageError, match="timezone-aware"):
        collect_historical_quality(
            Client(), contract=contract(), calendar_provider=lambda first, last: DATES,
            observed_at=datetime(2026, 1, 7),
        )


def test_durable_evidence_is_atomic_mode_600_and_write_once(tmp_path):
    payload = audit()
    path = tmp_path / "quality.json"
    digest = write_evidence_once(path, payload)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    with pytest.raises(LineageError, match="new absolute"):
        write_evidence_once(path, payload)


def test_evidence_excludes_source_rows_credentials_and_endpoints():
    serialized = json.dumps(audit(), sort_keys=True).lower()
    assert "libsql://" not in serialized
    assert "https://" not in serialized
    assert "auth_token" not in serialized
    assert "bearer " not in serialized
    assert '"source_rows_included": true' not in serialized


def _cli_args(tmp_path, *, evidence_name="quality.json"):
    env_path = tmp_path / "production.env"
    env_path.write_text("unused=test-only\n", encoding="utf-8")
    env_path.chmod(0o600)
    return [
        "--env-file", str(env_path.resolve()),
        "--evidence-json", str((tmp_path / evidence_name).resolve()),
    ]


def _secure_env(tmp_path):
    path = tmp_path / "production.env"
    path.write_text(
        "TURSO_DATABASE_URL=libsql://theoracle-test.turso.io\n"
        "TURSO_AUTH_TOKEN=test-only-secret\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path.resolve()


def test_production_credentials_requires_single_link_mode_and_owner(tmp_path, monkeypatch):
    target = _secure_env(tmp_path)
    assert _production_credentials(target) == (
        "libsql://theoracle-test.turso.io",
        "test-only-secret",
        "https://theoracle-test.turso.io/v2/pipeline",
    )

    symlink = tmp_path / "linked.env"
    symlink.symlink_to(target)
    with pytest.raises(WorkerError):
        _production_credentials(symlink.absolute())

    hardlink = tmp_path / "hardlinked.env"
    os.link(target, hardlink)
    with pytest.raises(WorkerError):
        _production_credentials(target)
    hardlink.unlink()

    target.chmod(0o640)
    with pytest.raises(WorkerError):
        _production_credentials(target)

    target.chmod(0o600)
    actual_uid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: actual_uid + 1)
    with pytest.raises(WorkerError):
        _production_credentials(target)


def test_cli_secure_loader_failure_is_fail_closed_and_redacted(tmp_path, capsys):
    args = _cli_args(tmp_path)
    secret = "test-only-token"
    endpoint = "libsql://theoracle-private.turso.io"

    def fail_loader(_):
        raise RuntimeError(f"credential failure {secret} {endpoint}")

    assert main(
        args,
        credentials_loader=fail_loader,
        effective_uid=lambda: 0,
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Historical quality audit failed; inspect only redacted operational evidence.\n"
    )
    assert secret not in captured.err
    assert endpoint not in captured.err
    assert "Traceback" not in captured.err


def test_cli_uses_exact_credentials_directly_without_environment_mutation(tmp_path):
    args = _cli_args(tmp_path)
    before = dict(os.environ)
    calls = []

    def factory(endpoint, token, timeout):
        calls.append((endpoint, token, timeout))
        return object()

    assert run_audit_cli(
        args,
        credentials_loader=lambda _: ("theoracle", "exact-token", "libsql://theoracle-exact.turso.io"),
        client_factory=factory,
        collector=lambda client: {"status": "PASS", "client_seen": client is not None},
        evidence_writer=lambda path, payload: calls.append((path, payload)),
        effective_uid=lambda: 0,
    ) == 0
    assert calls[0] == ("libsql://theoracle-exact.turso.io", "exact-token", 120.0)
    assert calls[1][1] == {"status": "PASS", "client_seen": True}
    assert dict(os.environ) == before


def test_cli_output_is_write_once_and_runtime_error_stays_generic(tmp_path, capsys):
    args = _cli_args(tmp_path)
    injected = {
        "credentials_loader": lambda _: (
            "theoracle", "test-token", "libsql://theoracle-test.turso.io"
        ),
        "client_factory": lambda endpoint, token, timeout: object(),
        "collector": lambda client: {"status": "PASS", "safe": True},
        "effective_uid": lambda: 0,
    }
    assert main(args, **injected) == 0
    evidence_path = Path(args[3])
    original = evidence_path.read_bytes()
    assert stat.S_IMODE(evidence_path.stat().st_mode) == 0o600

    assert main(args, **injected) == 1
    assert evidence_path.read_bytes() == original
    captured = capsys.readouterr()
    assert captured.err == (
        "Historical quality audit failed; inspect only redacted operational evidence.\n"
    )


def test_cli_requires_root_and_absolute_credential_path_before_loading(tmp_path):
    args = _cli_args(tmp_path)
    called = False

    def loader(_):
        nonlocal called
        called = True
        return "theoracle", "token", "libsql://theoracle-test.turso.io"

    with pytest.raises(LineageError, match="run as root"):
        run_audit_cli(args, credentials_loader=loader, effective_uid=lambda: 1)
    assert called is False

    relative_args = list(args)
    relative_args[1] = "production.env"
    with pytest.raises(LineageError, match="must be absolute"):
        run_audit_cli(relative_args, credentials_loader=loader, effective_uid=lambda: 0)
    assert called is False
