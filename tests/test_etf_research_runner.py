import inspect
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import etf_research_runner
from etf_research_runner import FrozenETFResearchConfig, run_frozen_etf_research
from model_lineage import LineageError


def config():
    return FrozenETFResearchConfig(
        run_id="etf-run",
        etf_ticker="xlk",
        etf_persona="ETF_Neutral",
        source_session_date=date(2026, 8, 21),
        prediction_date=date(2026, 8, 24),
        cutoff_utc=datetime(2026, 8, 22, 5, tzinfo=timezone.utc),
        code_version="code-v1",
        config_version="config-v1",
        lookback_sessions=30,
        minimum_history_sessions=252,
        minimum_weight_coverage=0.60,
        calibrated_sigma_floor=0.20,
    )


class ETFResearchRunnerTests(unittest.TestCase):
    @patch("etf_research_runner.build_frozen_etf_research_evidence")
    @patch("etf_research_runner.build_etf_model_dataset")
    @patch("etf_research_runner.load_stock_model_market_frame")
    @patch("etf_research_runner.build_etf_model_preflight")
    def test_wires_exact_db_preflight_prior_and_inert_bridge(
        self,
        build_preflight,
        load_market,
        build_dataset,
        build_bridge,
    ):
        prepared_prior = object()
        etf_run = object()
        market_snapshot = object()
        preflight = SimpleNamespace(
            prepared_stock_prior=prepared_prior,
            etf_run=etf_run,
            market_snapshot=market_snapshot,
        )
        build_preflight.return_value = preflight
        market_frame = object()
        load_market.return_value = market_frame
        dataset = object()
        build_dataset.return_value = dataset
        posterior = SimpleNamespace(ticker="XLK")
        fitter = Mock(return_value=posterior)
        research_evidence = object()
        build_bridge.return_value = research_evidence

        result = run_frozen_etf_research(None, config(), posterior_fitter=fitter)

        self.assertIs(result.preflight, preflight)
        self.assertIs(result.research_evidence, research_evidence)
        load_market.assert_called_once_with(
            None, market_snapshot, required_tickers=("XLK",)
        )
        fitter.assert_called_once_with(dataset, prepared_prior)
        build_bridge.assert_called_once_with(
            etf_run=etf_run,
            prepared_stock_prior=prepared_prior,
            posterior=posterior,
            persona_name="ETF_Neutral",
        )

    def test_mismatched_posterior_ticker_fails_closed(self):
        preflight = SimpleNamespace(
            prepared_stock_prior=object(),
            etf_run=object(),
            market_snapshot=object(),
        )
        with (
            patch("etf_research_runner.build_etf_model_preflight", return_value=preflight),
            patch("etf_research_runner.load_stock_model_market_frame", return_value=object()),
            patch("etf_research_runner.build_etf_model_dataset", return_value=object()),
        ):
            with self.assertRaisesRegex(LineageError, "ticker differs"):
                run_frozen_etf_research(
                    None,
                    config(),
                    posterior_fitter=Mock(return_value=SimpleNamespace(ticker="XLE")),
                )

    def test_rejects_naive_cutoff_before_any_read(self):
        invalid = FrozenETFResearchConfig(
            **{**config().__dict__, "cutoff_utc": datetime(2026, 8, 22, 5)}
        )
        db = Mock()
        with self.assertRaisesRegex(LineageError, "timezone-aware"):
            run_frozen_etf_research(db, invalid)
        db.assert_not_called()

    def test_canonical_runner_has_no_forbidden_production_data_dependency(self):
        source = inspect.getsource(etf_research_runner).lower()
        for forbidden in ("read_csv", "read_excel", "sqlite3", "streamlit"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
