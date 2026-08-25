import unittest
from datetime import date, datetime, timezone

from etf_model_preflight import build_etf_model_preflight
from model_lineage import LineageError


class Result:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class FakeDB:
    def __init__(
        self,
        *,
        constituent_rows=None,
        constituent_status_rows=True,
        stock_run=True,
        stock_market_snapshot="market-1",
        etf_latest="2026-08-21",
    ):
        self.constituent_rows = constituent_rows if constituent_rows is not None else [
            ["AAPL", 1, 0.35, "2026-08-21"],
            ["MSFT", 2, 0.30, "2026-08-21"],
        ]
        self.constituent_status_rows = constituent_status_rows
        self.stock_run = stock_run
        self.stock_market_snapshot = stock_market_snapshot
        self.etf_latest = etf_latest

    def execute(self, query, args):
        compact = " ".join(query.split())
        if "FROM model_input_snapshots" in compact:
            return Result(
                ["snapshot_id", "dataset_type", "source_session_date", "available_at_utc",
                 "provider", "code_version", "expected_row_count", "expected_ticker_count",
                 "source_checksum_sha256"],
                [["market-1", "MARKET_FEATURES", "2026-08-21",
                  "2026-08-22T03:00:00+00:00", "YAHOO", "market-v1", 1512, 3, "m" * 64]],
            )
        if "COUNT(*) AS row_count" in compact and "market_daily_features" in compact and "ticker=?" not in compact:
            return Result(["row_count", "ticker_count"], [[1512, 3]])
        if "FROM etf_constituent_snapshots" in compact:
            rows = [] if not self.constituent_status_rows else [[
                "constituents-1", "2026-08-21", "2026-08-22T03:10:00+00:00",
                "PROVIDER", "const-v1", "c" * 64, 2, 1,
            ]]
            return Result(
                ["snapshot_id", "source_session_date", "available_at_utc", "provider",
                 "code_version", "source_checksum_sha256", "expected_row_count", "expected_etf_count"],
                rows,
            )
        if "COUNT(DISTINCT etf_ticker)" in compact:
            return Result(["row_count", "etf_count"], [[2, 1]])
        if "FROM etf_constituent_weights" in compact:
            return Result(
                ["constituent_ticker", "constituent_rank", "constituent_weight", "effective_date"],
                self.constituent_rows,
            )
        if "FROM market_daily_features" in compact and "ticker=?" in compact:
            return Result(
                ["row_count", "latest_date", "bad_close_rows", "bad_volume_rows"],
                [[504, self.etf_latest, 0, 0]],
            )
        if "FROM model_runs" in compact:
            rows = [["stock-run", "2026-08-21", "2026-08-22T04:00:00+00:00"]] if self.stock_run else []
            return Result(["run_id", "source_session_date", "completed_at_utc"], rows)
        if "FROM model_run_inputs" in compact:
            return Result(
                ["input_role", "snapshot_id", "snapshot_checksum_sha256",
                 "source_checksum_sha256", "source_session_date", "available_at_utc", "status"],
                [
                    ["MARKET_FEATURES", self.stock_market_snapshot, "m" * 64, "m" * 64,
                     "2026-08-21", "2026-08-22T03:00:00+00:00", "VALIDATED"],
                    ["STOCK_UNIVERSE", "universe-1", "u" * 64, "u" * 64,
                     "2026-08-21", "2026-08-22T03:30:00+00:00", "VALIDATED"],
                ],
            )
        if "FROM model_scorecards" in compact:
            return Result(
                ["ticker", "posterior_probability", "posterior_probability_std",
                 "expected_return", "expected_return_std", "created_at_utc"],
                [
                    ["AAPL", 0.65, 0.04, 0.012, 0.006, "2026-08-22T04:01:00+00:00"],
                    ["MSFT", 0.58, 0.05, 0.008, 0.005, "2026-08-22T04:01:00+00:00"],
                ],
            )
        raise AssertionError(f"Unexpected query: {compact}")


class ETFModelPreflightTests(unittest.TestCase):
    kwargs = dict(
        run_id="etf-run",
        etf_ticker="XLK",
        etf_persona="ETF_Neutral",
        source_session_date=date(2026, 8, 21),
        prediction_date=date(2026, 8, 24),
        cutoff_utc=datetime(2026, 8, 22, 5, 0, tzinfo=timezone.utc),
        code_version="code-v1",
        config_version="config-v1",
        minimum_history_sessions=252,
        minimum_weight_coverage=0.60,
        calibrated_sigma_floor=0.20,
    )

    def test_exact_db_lineage_passes_without_writing(self):
        evidence = build_etf_model_preflight(FakeDB(), **self.kwargs)
        self.assertEqual(evidence.market_snapshot.snapshot_id, "market-1")
        self.assertEqual(evidence.constituent_snapshot.snapshot_id, "constituents-1")
        self.assertEqual(evidence.prepared_stock_prior.stock_batch.run_id, "stock-run")
        self.assertEqual(len(evidence.prepared_stock_prior.lineage_records), 6)

    def test_missing_constituent_snapshot_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "No validated ETF constituent"):
            build_etf_model_preflight(FakeDB(constituent_status_rows=False), **self.kwargs)

    def test_insufficient_constituent_coverage_fails_closed(self):
        rows = [["AAPL", 1, 0.35, "2026-08-21"]]
        with self.assertRaisesRegex(LineageError, "coverage .* below"):
            build_etf_model_preflight(FakeDB(constituent_rows=rows), **self.kwargs)

    def test_missing_completed_stock_run_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "No completed stock model run"):
            build_etf_model_preflight(FakeDB(stock_run=False), **self.kwargs)

    def test_stock_and_etf_market_snapshot_must_match(self):
        with self.assertRaisesRegex(LineageError, "different market snapshots"):
            build_etf_model_preflight(
                FakeDB(stock_market_snapshot="other-market"), **self.kwargs
            )

    def test_stale_etf_market_history_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "market history is stale"):
            build_etf_model_preflight(FakeDB(etf_latest="2026-08-20"), **self.kwargs)


if __name__ == "__main__":
    unittest.main()
