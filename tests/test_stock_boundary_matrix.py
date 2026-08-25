"""Cross-boundary fail-closed QA for the frozen stock research path.

These tests are pure: no network, database mutation, model fitting, recommendation
promotion, order creation, or service activation.
"""

import unittest
from datetime import date, datetime, timezone

from model_input_reader import InputSnapshot, StockUniverseEntry
from model_lineage import AssetClass, LineageError, ModelRun, Recommendation, RunStatus
from model_run_writer import ModelRunWriter
from sampler_qa import SamplerDiagnostics
from statistical_units import (
    basis_points_to_percentage_points,
    percentage_points_to_fraction,
)
from stock_model_preflight import SnapshotApproval, StockModelPreflightEvidence
from stock_posterior_bridge import compare_research_only_posterior
from stock_prediction_eligibility import (
    DecisionContext,
    PredictionEvidence,
    compare_stock_prediction,
)
from stock_pymc_core import StockPosteriorEvidence
from stock_scorecard_reader import load_stock_evidence_for_etf


class Result:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = list(rows)


def decision_context(**changes):
    values = {
        "snapshot_validated": True,
        "universe_approved": True,
        "source_date_aligned": True,
        "model_run_completed": True,
        "sampler_qa_passed": True,
        "research_promotion_approved": True,
        "available_capital": 10_000.0,
        "vix_close": 18.0,
        "round_trip_cost_bps": 10.0,
    }
    values.update(changes)
    return DecisionContext(**values)


def posterior():
    return StockPosteriorEvidence(
        ticker="NDAQ",
        probability_up_mean=0.72,
        probability_up_std=0.04,
        probability_up_q05=0.55,
        probability_up_q95=0.84,
        expected_return_pp_mean=1.25,
        expected_return_pp_std=0.30,
        predictive_risk_pp=2.50,
        diagnostics=SamplerDiagnostics(1.01, 500.0, 300.0, 0.8, 0, 0.0, 4),
    )


def writer_fixture():
    source = date(2026, 8, 24)
    prediction = date(2026, 8, 25)
    cutoff = datetime(2026, 8, 25, 3, 30, tzinfo=timezone.utc)
    run = ModelRun(
        "stock-run-boundary", "STOCK_PYMC", AssetClass.STOCK,
        prediction, source, cutoff, "code-1", "config-1", RunStatus.STARTED,
    )
    market = InputSnapshot(
        "market-1", "MARKET_FEATURES", source,
        datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
        "CANONICAL_EOD", "code-1", 1000, 10, "a" * 64,
    )
    universe = InputSnapshot(
        "universe-1", "STOCK_UNIVERSE", source,
        datetime(2026, 8, 25, 3, 0, tzinfo=timezone.utc),
        "PREDICTIVE_SCREENING", "code-1", 1, 1, "b" * 64,
    )
    approval = SnapshotApproval(
        "approval-1", "APPROVED", "Avi",
        datetime(2026, 8, 25, 3, 10, tzinfo=timezone.utc),
        "b" * 64, "PREDICTIVE_SCREENING", "screen-1",
    )
    evidence = StockModelPreflightEvidence(
        source, prediction, cutoff, market, universe, approval, "screen-1",
        (StockUniverseEntry("AAPL", 1, 0.6, 1, ("MSFT",), (2,)),),
        ("AAPL", "MSFT"), 30,
    )
    return run, evidence


class FakeReadback:
    columns = [
        "run_id", "model_name", "asset_class", "prediction_date",
        "source_session_date", "as_of_timestamp_utc", "code_version",
        "config_version", "status", "input_role", "snapshot_id",
        "snapshot_checksum_sha256",
    ]

    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query, _args):
        return Result(self.columns, self.rows)


class MissingETFLineageDB:
    def execute(self, query, _args):
        if "FROM model_runs" in query:
            return Result(
                ["run_id", "source_session_date", "completed_at_utc"],
                [["stock-run", "2026-08-24", "2026-08-25T04:00:00+00:00"]],
            )
        if "FROM model_run_inputs" in query:
            return Result(
                [
                    "input_role", "snapshot_id", "snapshot_checksum_sha256",
                    "source_checksum_sha256", "source_session_date",
                    "available_at_utc", "status",
                ],
                [[
                    "MARKET_FEATURES", "market-1", "a" * 64, "a" * 64,
                    "2026-08-24", "2026-08-25T03:00:00+00:00", "VALIDATED",
                ]],
            )
        raise AssertionError("Scorecards must not be queried after incomplete lineage.")


class StockBoundaryMatrixTests(unittest.TestCase):
    def test_percentage_points_cost_and_fraction_boundary_are_not_rescaled(self):
        self.assertEqual(basis_points_to_percentage_points(20.0), 0.2)
        self.assertEqual(percentage_points_to_fraction(1.0), 0.01)
        result = compare_stock_prediction(
            PredictionEvidence(0.70, 0.55, 0.82, 0.15, 2.0),
            decision_context(round_trip_cost_bps=20.0),
            persona_name="Neutral",
        )
        self.assertEqual(result.raw_model_signal, Recommendation.BUY)
        self.assertEqual(result.codex_action, Recommendation.HOLD)
        self.assertEqual(result.balanced_action, Recommendation.HOLD)
        self.assertEqual(result.shadow_allocation_fraction, 0.0)

    def test_frozen_bridge_never_authorizes_action_but_preserves_bayesian_output(self):
        result = compare_research_only_posterior(
            posterior(), decision_context(), persona_name="Neutral"
        )
        self.assertEqual(result.raw_model_signal, Recommendation.BUY)
        self.assertEqual(result.codex_action, Recommendation.NO_TRADE)
        self.assertEqual(result.balanced_action, Recommendation.NO_TRADE)
        self.assertEqual(result.shadow_allocation_fraction, 0.0)
        self.assertIn("RESEARCH_PROMOTION_NOT_APPROVED", result.hard_gate_failures)

    def test_every_missing_hard_boundary_is_reported_fail_closed(self):
        result = compare_stock_prediction(
            PredictionEvidence(0.72, 0.55, 0.84, 1.2, 2.0),
            decision_context(
                snapshot_validated=False,
                universe_approved=False,
                source_date_aligned=False,
                model_run_completed=False,
                sampler_qa_passed=False,
                research_promotion_approved=False,
                quarantined=True,
            ),
            persona_name="Neutral",
        )
        self.assertEqual(result.codex_action, Recommendation.NO_TRADE)
        self.assertEqual(result.balanced_action, Recommendation.NO_TRADE)
        self.assertEqual(
            result.hard_gate_failures,
            (
                "SNAPSHOT_NOT_VALIDATED",
                "UNIVERSE_NOT_APPROVED",
                "SOURCE_DATE_MISMATCH",
                "MODEL_RUN_NOT_COMPLETED",
                "SAMPLER_QA_FAILED",
                "RESEARCH_PROMOTION_NOT_APPROVED",
                "ACTIVE_EVIDENCE_QUARANTINE",
            ),
        )

    def test_lag_chain_supports_repeated_sources_and_independent_horizons(self):
        entry = StockUniverseEntry(
            ticker="TARGET",
            selection_rank=1,
            oos_accuracy=0.61,
            causal_depth=3,
            lag_tickers=("A", "A", "B"),
            lag_sessions=(7, 2, 6),
        )
        self.assertEqual(entry.lag_tickers, ("A", "A", "B"))
        self.assertEqual(entry.lag_sessions, (7, 2, 6))
        with self.assertRaisesRegex(LineageError, "must agree"):
            StockUniverseEntry(
                "TARGET", 1, 0.61, 3, ("A", "B"), (7, 2)
            )

    def test_duplicate_or_incomplete_atomic_readback_is_rejected(self):
        run, evidence = writer_fixture()
        common = [
            run.run_id, run.model_name, run.asset_class.value,
            run.prediction_date.isoformat(), run.source_session_date.isoformat(),
            run.as_of_timestamp_utc.isoformat(), run.code_version,
            run.config_version, run.status.value,
        ]
        market = common + ["MARKET_FEATURES", "market-1", "a" * 64]
        universe = common + ["STOCK_UNIVERSE", "universe-1", "b" * 64]
        writer = ModelRunWriter(
            "https://example.turso.io/v2/pipeline", "fake", session=object()
        )
        for rows in ([market], [market, market, universe]):
            with self.subTest(row_count=len(rows)):
                writer.reader = FakeReadback(rows)
                with self.assertRaisesRegex(
                    LineageError, "exactly the two approved inputs"
                ):
                    writer._reconcile(
                        run, evidence, datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)
                    )

    def test_etf_handoff_aborts_before_scorecards_when_input_lineage_is_incomplete(self):
        with self.assertRaisesRegex(
            LineageError, "lacks exact market/universe input lineage"
        ):
            load_stock_evidence_for_etf(
                MissingETFLineageDB(),
                etf_persona="ETF_Neutral",
                prediction_date=date(2026, 8, 25),
                etf_cutoff_utc=datetime(2026, 8, 25, 5, 0, tzinfo=timezone.utc),
                expected_market_snapshot_id="market-1",
                constituent_weights={"AAPL": 0.35},
            )


if __name__ == "__main__":
    unittest.main()
