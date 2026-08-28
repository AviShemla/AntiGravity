import unittest
from datetime import date

import numpy as np
import pandas as pd

from scripts.rebuild_market_features_to_turso import (
    COLUMN_MAP,
    TURSO_TIMEOUT_SECONDS,
    build_controlled_universe,
    build_provider_lineage,
    provider_lineage_checksum,
    compare_provider_lineage,
    calculate_features,
    apply_symbol_lifecycle,
    apply_approved_instrument_registry,
    merge_cross_market_features,
    normalize_ohlc_envelope,
    content_checksum,
    diagnose_persisted_frame,
    missing_sessions,
    recent_nyse_sessions,
    repair_recent_session_gaps,
    require_complete_rebuild,
    resolve_lifecycle_tickers,
)


class RebuildMarketFeaturesTests(unittest.TestCase):
    def test_writer_turso_timeout_matches_guarded_preflight_contract(self):
        self.assertEqual(TURSO_TIMEOUT_SECONDS, 120.0)

    def test_persisted_field_diagnostic_identifies_exact_column(self):
        text = {"ticker": "AAA", "sector": "Tech", "ras_signal": None,
                "analyst_consensus": None, "sector_regime": None,
                "market_fear_level": None}
        values = {
            source: (pd.Timestamp("2026-08-27") if target == "date"
                     else text[target] if target in text else 1.0)
            for source, target in COLUMN_MAP
        }
        frame = pd.DataFrame([values])
        columns = [target for _, target in COLUMN_MAP]
        row = [
            ("2026-08-27" if target == "date" else text[target]
             if target in text else 1.0)
            for _, target in COLUMN_MAP
        ]
        row[columns.index("close_price")] = 2.0

        class Result:
            def __init__(self, rows): self.rows = rows

        class DB:
            def __init__(self): self.calls = 0
            def execute(self, *_args):
                self.calls += 1
                return Result([row] if self.calls == 1 else [])

        result = diagnose_persisted_frame(DB(), "snapshot", frame, page_size=1)
        self.assertEqual(result["mismatch_counts"], {"close_price": 1})

    def raw(self, ticker_shift=0.0):
        rows = 320
        dates = pd.bdate_range(end="2026-08-20", periods=rows)
        close = np.linspace(100.0 + ticker_shift, 130.0 + ticker_shift, rows)
        return pd.DataFrame({
            "Date": dates,
            "Open": close - 0.2,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Adj Close": close,
            "Volume": np.arange(rows) + 1000,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        })

    def test_calculates_required_technical_features(self):
        frame = calculate_features(self.raw(), ticker="AAA", sector="Tech")
        for column in (
            "Daily_Return_%", "RSI_14d", "ATR_14d", "Plus_DI_14d",
            "Minus_DI_14d", "ADX_14d", "Dynamic_Stop_Loss", "RAS_Signal",
        ):
            self.assertIn(column, frame.columns)
        self.assertFalse(frame[["RSI_14d", "ATR_14d", "ADX_14d"]].isna().any().any())

    def test_merges_sector_and_macro_features(self):
        first = calculate_features(self.raw(), ticker="AAA", sector="Tech")
        second = calculate_features(self.raw(10.0), ticker="BBB", sector="Finance")
        macro = self.raw()[["Date", "Open", "High", "Low", "Close", "Volume"]]
        result = merge_cross_market_features(pd.concat([first, second]), macro, macro)
        latest = result[result["Date"] == result["Date"].max()]
        self.assertEqual(len(latest), 2)
        self.assertFalse(latest[["Sector_Momentum_Score", "VIX_Close", "TNX_Close"]].isna().any().any())

    def test_rejects_noncanonical_ohlc_without_mutating_source(self):
        source = pd.DataFrame({
            "Ticker": ["DG", "ELV", "OTIS", "TPR"],
            "Date": pd.to_datetime(["2026-08-25"] * 4),
            "Open": [100.01, 200.01, 300.01, 400.01],
            "High": [100.00, 200.00, 300.00, 400.00],
            "Low": [99.50, 199.50, 299.50, 399.50],
            "Close": [99.80, 199.80, 299.80, 399.80],
        })
        original = source.copy(deep=True)

        with self.assertRaisesRegex(ValueError, "would change"):
            normalize_ohlc_envelope(source)
        pd.testing.assert_frame_equal(source, original)

    def test_accepts_canonical_high_and_low_as_noop(self):
        source = pd.DataFrame({
            "Open": [10.0, 20.0],
            "High": [12.0, 21.0],
            "Low": [9.0, 18.0],
            "Close": [12.0, 18.0],
        })

        normalized = normalize_ohlc_envelope(source)

        pd.testing.assert_frame_equal(normalized, source)
        pd.testing.assert_frame_equal(
            normalized,
            normalize_ohlc_envelope(normalized),
        )

    def test_feature_calculation_rejects_invalid_provider_ohlc_without_mutation(self):
        source = self.raw()
        position = source.index[-1]
        source.loc[position, "High"] = source.loc[position, "Open"] - 0.01
        provider_evidence = source.copy(deep=True)

        with self.assertRaisesRegex(ValueError, "would change"):
            calculate_features(source, ticker="DG", sector="Retail")
        pd.testing.assert_frame_equal(source, provider_evidence)

    def test_checksum_refuses_noncanonical_ohlc_at_normalization_gate(self):
        raw = self.raw().tail(1).copy()
        raw["Ticker"] = "DG"
        raw["Sector"] = "Retail"
        raw.loc[:, "High"] = raw["Open"] - 0.01
        for source, _ in __import__(
            "scripts.stage_market_features_to_turso",
            fromlist=["COLUMN_MAP"],
        ).COLUMN_MAP:
            if source not in raw:
                raw[source] = "N/A" if source in {
                    "RAS_Signal", "Analyst_Consensus", "Sector_Regime",
                    "Market_Fear_Level",
                } else 0.0

        with self.assertRaisesRegex(ValueError, "would change"):
            normalize_ohlc_envelope(raw)

    def test_checksum_matches_exact_clean_persisted_row_contract(self):
        from market_staging_content import digest_rows
        from scripts.stage_market_features_to_turso import COLUMN_MAP, clean

        frame = self.raw().tail(2).copy()
        frame["Ticker"] = "DG"
        frame["Sector"] = "Retail"
        text_columns = {
            "RAS_Signal", "Analyst_Consensus", "Sector_Regime",
            "Market_Fear_Level",
        }
        for source, _ in COLUMN_MAP:
            if source not in frame:
                frame[source] = "N/A" if source in text_columns else 0.0
        ordered = frame.sort_values(["Ticker", "Date"], kind="mergesort")
        persisted_rows = [
            tuple(clean(value) for value in row)
            for row in ordered[[source for source, _ in COLUMN_MAP]].itertuples(index=False, name=None)
        ]
        self.assertEqual(content_checksum(frame), digest_rows(persisted_rows))

    def test_normalization_requires_complete_ohlc_columns(self):
        with self.assertRaisesRegex(ValueError, "missing columns: Low"):
            normalize_ohlc_envelope(
                pd.DataFrame({"Open": [1.0], "High": [1.0], "Close": [1.0]})
            )

    def test_rebuild_fails_closed_on_any_universe_ingestion_failure(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            require_complete_rebuild(
                {"AAA": self.raw()}, {"BBB": "provider failed"}, ["AAA"]
            )

    def test_recent_nyse_sessions_include_source_session(self):
        sessions = recent_nyse_sessions(date(2026, 8, 21), rows=10)
        self.assertEqual(len(sessions), 10)
        self.assertEqual(sessions[-1], date(2026, 8, 21))
        self.assertNotIn(date(2026, 8, 15), sessions)

    def test_gap_repair_replaces_entire_ticker_with_tiingo(self):
        primary = self.raw()
        missing_day = primary.iloc[-5]["Date"].date()
        gapped = primary[primary["Date"].dt.date != missing_day].reset_index(drop=True)
        expected = [value.date() for value in primary.iloc[-10:]["Date"]]

        repaired, providers, failures, replacements = repair_recent_session_gaps(
            {"AAA": gapped},
            {"AAA": "YAHOO_FINANCE"},
            expected,
            lambda ticker: (primary, "TIINGO_EOD", None),
        )

        self.assertEqual(failures, {})
        self.assertEqual(replacements, ["AAA"])
        self.assertEqual(providers["AAA"], "TIINGO_EOD")
        self.assertEqual(missing_sessions(repaired["AAA"], expected), [])
        self.assertEqual(len(repaired["AAA"]), len(primary))

    def test_gap_repair_fails_closed_when_tiingo_also_has_gap(self):
        primary = self.raw()
        missing_day = primary.iloc[-5]["Date"].date()
        gapped = primary[primary["Date"].dt.date != missing_day].reset_index(drop=True)
        expected = [value.date() for value in primary.iloc[-10:]["Date"]]

        _, _, failures, replacements = repair_recent_session_gaps(
            {"AAA": gapped},
            {"AAA": "YAHOO_FINANCE"},
            expected,
            lambda ticker: (gapped, "TIINGO_EOD", None),
        )

        self.assertIn("AAA", failures)
        self.assertEqual(replacements, [])

    def test_builds_deterministic_per_ticker_provider_lineage(self):
        rows = build_provider_lineage(
            {"BBB": self.raw(10.0), "AAA": self.raw()},
            {"AAA": "YAHOO_FINANCE", "BBB": "TIINGO_EOD"},
            source_session=pd.Timestamp("2026-08-20").date(),
        )
        self.assertEqual([row[0] for row in rows], ["AAA", "BBB"])
        self.assertEqual(rows[0][1], "YAHOO_FINANCE")
        self.assertEqual(rows[1][1], "TIINGO_EOD")
        self.assertEqual(rows[0][2], "2026-08-20")
        self.assertEqual(rows[0][4], "2026-08-20")
        self.assertEqual(rows[0][5], 320)
        self.assertEqual(len(rows[0][6]), 64)

    def test_provider_lineage_refuses_mismatched_sources(self):
        with self.assertRaisesRegex(ValueError, "do not match"):
            build_provider_lineage(
                {"AAA": self.raw()},
                {"BBB": "YAHOO_FINANCE"},
                source_session=pd.Timestamp("2026-08-20").date(),
            )

    def test_provider_lineage_comparison_identifies_exact_changed_ticker(self):
        fresh = [
            ["AAA", "YAHOO_FINANCE", "2026-08-21", "2021-08-02", "2026-08-21", 10, "a" * 64],
            ["BBB", "TIINGO_EOD", "2026-08-21", "2021-08-02", "2026-08-21", 10, "b" * 64],
        ]
        stored = [
            ["AAA", "YAHOO_FINANCE", "2026-08-21", "2021-08-02", "2026-08-21", 10, "c" * 64],
            ["BBB", "TIINGO_EOD", "2026-08-21", "2021-08-02", "2026-08-21", 10, "b" * 64],
        ]
        comparison = compare_provider_lineage(fresh, stored)
        self.assertEqual(comparison["changed_ticker_count"], 1)
        self.assertEqual(comparison["changed_ticker_sample"], ["AAA"])
        self.assertEqual(comparison["missing_from_fresh_count"], 0)
        self.assertEqual(comparison["missing_from_fresh_sample"], [])
        self.assertEqual(comparison["unexpected_in_fresh_count"], 0)
        self.assertEqual(comparison["unexpected_in_fresh_sample"], [])

    def test_provider_lineage_comparison_bounds_changed_ticker_output(self):
        fresh = [
            [ticker, "YAHOO_FINANCE", "2026-08-21", "2021-08-02", "2026-08-21", 10, "a" * 64]
            for ticker in ("AAA", "BBB", "CCC")
        ]
        stored = [
            [ticker, "YAHOO_FINANCE", "2026-08-21", "2021-08-02", "2026-08-21", 10, "b" * 64]
            for ticker in ("AAA", "BBB", "CCC")
        ]
        comparison = compare_provider_lineage(fresh, stored, sample_size=2)
        self.assertEqual(comparison["changed_ticker_count"], 3)
        self.assertEqual(comparison["changed_ticker_sample"], ["AAA", "BBB"])

    def test_provider_lineage_checksum_is_order_independent(self):
        first = [
            ["BBB", "TIINGO_EOD", "2026-08-21", "2021-08-02", "2026-08-21", 10, "b" * 64],
            ["AAA", "YAHOO_FINANCE", "2026-08-21", "2021-08-02", "2026-08-21", 10, "a" * 64],
        ]
        second = list(reversed(first))
        self.assertEqual(provider_lineage_checksum(first), provider_lineage_checksum(second))

    def test_controlled_universe_includes_db_etf_evidence(self):
        universe = build_controlled_universe(
            [("AAA", "Tech")],
            [("XLK",)],
            [('{"IWD":{"units":1}}',)],
            [('{"UDOW":{"units":2}}',)],
        )
        self.assertEqual(universe["AAA"], "Tech")
        self.assertEqual(universe["XLK"], "ETF")
        self.assertEqual(universe["IWD"], "ETF")
        self.assertEqual(universe["UDOW"], "ETF")

    def test_controlled_universe_rejects_invalid_json(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            build_controlled_universe([], [], [("not-json",)], [])

    def test_lifecycle_retires_predecessors_and_retains_successor(self):
        universe, replacements = apply_symbol_lifecycle(
            {"EQR": "Real Estate", "AVB": "Real Estate", "VMRK": "Real Estate"},
            [
                ("EQR", "RETIRED", "2026-08-18", "VMRK", "Real Estate"),
                ("AVB", "RETIRED", "2026-08-18", "VMRK", "Real Estate"),
                ("VMRK", "ACTIVATED", "2026-08-18", None, "Real Estate"),
            ],
            source_session=date(2026, 8, 21),
        )
        self.assertNotIn("EQR", universe)
        self.assertNotIn("AVB", universe)
        self.assertEqual(universe["VMRK"], "Real Estate")
        self.assertEqual(replacements, {"EQR": "VMRK", "AVB": "VMRK"})
        self.assertEqual(resolve_lifecycle_tickers(["EQR", "AVB"], replacements), ["VMRK"])

    def test_future_lifecycle_event_does_not_change_prior_session(self):
        universe, replacements = apply_symbol_lifecycle(
            {"EQR": "Real Estate"},
            [("EQR", "RETIRED", "2026-08-18", "VMRK", "Real Estate")],
            source_session=date(2026, 8, 17),
        )
        self.assertIn("EQR", universe)
        self.assertEqual(replacements, {})

    def test_lifecycle_rejects_sector_conflict(self):
        with self.assertRaisesRegex(ValueError, "sector conflicts"):
            apply_symbol_lifecycle(
                {"EQR": "Real Estate", "VMRK": "Technology"},
                [("EQR", "RETIRED", "2026-08-18", "VMRK", "Real Estate")],
                source_session=date(2026, 8, 21),
            )

    def test_lifecycle_accepts_equivalent_sector_separator(self):
        universe, _ = apply_symbol_lifecycle(
            {"VMRK": "Real_Estate"},
            [("VMRK", "ACTIVATED", "2026-08-18", None, "Real Estate")],
            source_session=date(2026, 8, 21),
        )
        self.assertEqual(universe["VMRK"], "Real_Estate")

    def test_approved_registry_replaces_legacy_etf_membership(self):
        universe = apply_approved_instrument_registry(
            {"AAPL": "Technology", "XLK": "ETF", "MRVU": "ETF"},
            [("registry-1",)],
            [
                ("registry-1", "XLK", "ETF", "ETF", "MODEL_CANDIDATE", 252),
                ("registry-1", "SPY", "ETF", "ETF", "BENCHMARK", 252),
                ("registry-1", "MRVU", "ETF", "ETF", "QUARANTINED", 252),
            ],
        )
        self.assertEqual(universe, {"AAPL": "Technology", "XLK": "ETF", "SPY": "ETF"})

    def test_registry_does_not_add_inactive_valuation_only_etf(self):
        universe = apply_approved_instrument_registry(
            {"AAPL": "Technology"},
            [("registry-1",)],
            [
                ("registry-1", "XLK", "ETF", "ETF", "MODEL_CANDIDATE", 252),
                ("registry-1", "MRVU", "ETF", "ETF", "VALUATION_ONLY", 252),
            ],
        )
        self.assertEqual(universe, {"AAPL": "Technology", "XLK": "ETF"})

    def test_registry_preserves_current_valuation_only_etf(self):
        universe = apply_approved_instrument_registry(
            {"AAPL": "Technology", "MRVU": "ETF"},
            [("registry-1",)],
            [
                ("registry-1", "XLK", "ETF", "ETF", "MODEL_CANDIDATE", 252),
                ("registry-1", "MRVU", "ETF", "ETF", "VALUATION_ONLY", 252),
            ],
        )
        self.assertEqual(
            universe,
            {"AAPL": "Technology", "XLK": "ETF", "MRVU": "ETF"},
        )

    def test_registry_requires_exactly_one_approved_version(self):
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            apply_approved_instrument_registry(
                {"AAPL": "Technology"}, [], []
            )

    def test_registry_requires_etf_model_candidate(self):
        with self.assertRaisesRegex(ValueError, "no ETF model candidate"):
            apply_approved_instrument_registry(
                {"AAPL": "Technology"},
                [("registry-1",)],
                [("registry-1", "SPY", "ETF", "ETF", "BENCHMARK", 252)],
            )


if __name__ == "__main__":
    unittest.main()
