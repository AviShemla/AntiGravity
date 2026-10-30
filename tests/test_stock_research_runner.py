import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import pandas as pd

from model_input_reader import InputSnapshot, StockUniverseEntry
from model_lineage import LineageError, Recommendation, RunStatus
from sampler_qa import SamplerDiagnostics
from stock_model_preflight import SnapshotApproval, StockModelPreflightEvidence
from stock_pymc_core import StockPosteriorEvidence
from stock_research_run_writer import CompletedStockResearchReceipt
from stock_research_runner import (
    FrozenStockResearchConfig,
    run_frozen_stock_research,
)


def diagnostics():
    return SamplerDiagnostics(1.01, 500.0, 300.0, 0.8, 0, 0.0, 4)


def posterior(ticker="AAA"):
    return StockPosteriorEvidence(
        ticker=ticker,
        probability_up_mean=0.72,
        probability_up_std=0.04,
        probability_up_q05=0.55,
        probability_up_q95=0.84,
        expected_return_pp_mean=1.25,
        expected_return_pp_std=0.30,
        predictive_risk_pp=2.50,
        diagnostics=diagnostics(),
    )


class Writer:
    def __init__(self):
        self.calls = []

    def persist_completed_stock_run(self, run, evidence, scorecards):
        self.calls.append((run, evidence, scorecards))
        return CompletedStockResearchReceipt(
            run.run_id,
            len(scorecards),
            evidence.market_snapshot.snapshot_id,
            evidence.universe_snapshot.snapshot_id,
            RunStatus.COMPLETED,
            datetime(2026, 8, 25, 5, 0, tzinfo=timezone.utc),
            "statistical-units-v1",
        )


class FrozenStockResearchRunnerTests(unittest.TestCase):
    source = date(2026, 8, 24)
    prediction = date(2026, 8, 25)
    cutoff = datetime(2026, 8, 25, 3, 30, tzinfo=timezone.utc)

    def setUp(self):
        market = InputSnapshot(
            "market-1", "MARKET_FEATURES", self.source,
            datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
            "YAHOO_WITH_TIINGO_FALLBACK", "market-code", 2, 2, "a" * 64,
        )
        universe = InputSnapshot(
            "universe-1", "STOCK_UNIVERSE", self.source,
            datetime(2026, 8, 25, 3, 0, tzinfo=timezone.utc),
            "PREDICTIVE_SCREENING", "universe-code", 1, 1, "b" * 64,
        )
        approval = SnapshotApproval(
            "approval-1", "APPROVED", "Avi",
            datetime(2026, 8, 25, 3, 10, tzinfo=timezone.utc),
            "b" * 64, "PREDICTIVE_SCREENING", "screen-1",
        )
        entry = StockUniverseEntry("AAA", 1, 0.61, 1, ("BBB",), (2,))
        self.preflight = StockModelPreflightEvidence(
            self.source, self.prediction, self.cutoff, market, universe,
            approval, "screen-1", (entry,), ("AAA", "BBB"), 30,
        )
        self.frame = pd.DataFrame([
            {"Ticker": "AAA", "Date": pd.Timestamp(self.source), "VIX_Close": 18.0},
            {"Ticker": "BBB", "Date": pd.Timestamp(self.source), "VIX_Close": 18.0},
        ])
        self.config = FrozenStockResearchConfig(
            run_id="stock-research-1",
            prediction_date=self.prediction,
            source_session_date=self.source,
            cutoff_utc=self.cutoff,
            code_version="code-sha",
            config_version="config-sha",
            minimum_history_sessions=30,
            round_trip_cost_bps=10.0,
        )

    def run_it(self, writer, fitter=lambda dataset: posterior()):
        with (
            patch("stock_research_runner.build_stock_model_preflight", return_value=self.preflight),
            patch("stock_research_runner.load_stock_model_market_frame", return_value=self.frame),
            patch("stock_research_runner.build_stock_model_dataset", return_value=object()),
        ):
            return run_frozen_stock_research(
                object(), writer, self.config, posterior_fitter=fitter
            )

    def test_preserves_raw_bayesian_evidence_but_persists_no_trade_only(self):
        writer = Writer()
        result = self.run_it(writer)
        self.assertEqual(result.ticker_evidence[0].posterior.probability_up_mean, 0.72)
        comparisons = dict(result.ticker_evidence[0].persona_comparisons)
        self.assertEqual(comparisons["Neutral"].raw_model_signal, Recommendation.BUY)
        self.assertTrue(all(
            item.codex_action is Recommendation.NO_TRADE
            and item.balanced_action is Recommendation.NO_TRADE
            for item in comparisons.values()
        ))
        scorecards = writer.calls[0][2]
        self.assertEqual(len(scorecards), 3)
        self.assertTrue(all(card.recommendation is Recommendation.NO_TRADE for card in scorecards))
        self.assertTrue(all(card.proposed_allocation == 0.0 for card in scorecards))

    def test_exposes_exact_input_and_unit_lineage(self):
        result = self.run_it(Writer())
        lineage = result.lineage
        self.assertEqual(lineage.market_snapshot_id, "market-1")
        self.assertEqual(lineage.market_snapshot_checksum_sha256, "a" * 64)
        self.assertEqual(lineage.universe_approval_event_id, "approval-1")
        self.assertEqual(lineage.predictive_screening_run_id, "screen-1")
        self.assertEqual(lineage.expected_return_unit, "percentage_points")
        self.assertEqual(lineage.transaction_cost_unit, "basis_points")
        self.assertEqual(lineage.action_policy, "RESEARCH_ONLY_ALL_LANES_NO_TRADE")

    def test_model_failure_writes_nothing(self):
        writer = Writer()
        def fail(_dataset):
            raise LineageError("sampler failed")
        with self.assertRaisesRegex(LineageError, "sampler failed"):
            self.run_it(writer, fail)
        self.assertEqual(writer.calls, [])

    def test_posterior_ticker_mismatch_writes_nothing(self):
        writer = Writer()
        with self.assertRaisesRegex(LineageError, "ticker differs"):
            self.run_it(writer, lambda dataset: posterior("WRONG"))
        self.assertEqual(writer.calls, [])

    def test_unknown_or_duplicate_persona_fails_before_preflight(self):
        for personas in (("Unknown",), ("Neutral", "Neutral")):
            bad = FrozenStockResearchConfig(
                **{**self.config.__dict__, "persona_names": personas}
            )
            with self.assertRaises(LineageError):
                run_frozen_stock_research(object(), Writer(), bad)


if __name__ == "__main__":
    unittest.main()
