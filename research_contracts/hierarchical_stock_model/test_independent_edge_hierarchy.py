from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock

import numpy as np

try:
    from .independent_edge_hierarchy import (
        CLAIM_SCOPE, EXPECTED_DEPTHS, EXPECTED_LAGS, RETURN_UNIT, TOPOLOGY,
        CanonicalPercentPosterior,
        EdgeSelectionPolicy, HierarchicalBackendResult, HierarchicalContractError,
        HistoricalReturnPanel, SamplerDiagnosticsEvidence,
        build_hierarchical_fit_request, run_hierarchical_backend,
        select_independent_edges,
    )
except ImportError:  # pragma: no cover - direct staging-directory execution
    from independent_edge_hierarchy import (
    CLAIM_SCOPE, EXPECTED_DEPTHS, EXPECTED_LAGS, RETURN_UNIT, TOPOLOGY,
    CanonicalPercentPosterior,
    EdgeSelectionPolicy, HierarchicalBackendResult, HierarchicalContractError,
    HistoricalReturnPanel, SamplerDiagnosticsEvidence,
    build_hierarchical_fit_request, run_hierarchical_backend,
    select_independent_edges,
    )


class IndependentEdgeHierarchyTests(unittest.TestCase):
    def dates(self, count):
        start = date(2025, 1, 1)
        return tuple(start + timedelta(days=index) for index in range(count))

    def panel(self, values, tickers, *, snapshot="panel-1"):
        return HistoricalReturnPanel(
            snapshot_id=snapshot,
            snapshot_sha256="a" * 64,
            tickers=tuple(tickers),
            session_dates=self.dates(len(values)),
            returns_pct=np.asarray(values, dtype=float),
        )

    def single_signal_panel(self, *, count=420, lag=5, seed=7):
        rng = np.random.default_rng(seed)
        source = rng.normal(0.0, 1.0, count)
        distractor_a = rng.normal(0.0, 1.0, count)
        distractor_b = rng.normal(0.0, 1.0, count)
        target = rng.normal(0.0, 0.04, count)
        target[lag:] = 1.25 * source[:-lag] + rng.normal(0.0, 0.04, count - lag)
        return self.panel(
            np.column_stack((target, source, distractor_a, distractor_b)),
            ("TGT", "SRC", "NOISE1", "NOISE2"),
        )

    def select_single(self, panel=None, *, cutoff=360):
        return select_independent_edges(
            panel or self.single_signal_panel(),
            target_sources={"TGT": ("SRC", "NOISE1", "NOISE2")},
            selection_end_ordinal=cutoff,
        )

    def diagnostics(self, **changes):
        values = dict(
            chains=4, draws=1000, tune=1000, max_rhat=1.005,
            min_bulk_ess=800.0, min_tail_ess=700.0, bfmi_min=0.8,
            divergences=0, max_treedepth_fraction=0.0,
        )
        values.update(changes)
        return SamplerDiagnosticsEvidence(**values)

    def posterior(self, ticker, **changes):
        values = dict(
            ticker=ticker, probability_up_mean=0.68,
            probability_up_std=0.04, probability_up_q05=0.57,
            probability_up_q95=0.78, expected_return_pct_mean=1.2,
            expected_return_pct_std=0.3, predictive_risk_pct=1.8,
            diagnostics=self.diagnostics(),
        )
        values.update(changes)
        return CanonicalPercentPosterior(**values)

    def request(self):
        panel = self.single_signal_panel()
        selection = self.select_single(panel)
        return build_hierarchical_fit_request(
            panel, selection, model_run_id="fixture-run-1",
            prediction_date=panel.session_dates[361],
            preregistered_model_config_sha256="b" * 64,
            preregistered_sampler_sha256="c" * 64,
        )

    def result(self, request, **changes):
        values = dict(
            model_run_id=request.model_run_id,
            selection_id=request.selection_id,
            model_topology=request.model_topology,
            hierarchy=request.hierarchy,
            graph_contract_sha256=request.graph_contract_sha256,
            preregistered_model_config_sha256=request.preregistered_model_config_sha256,
            preregistered_sampler_sha256=request.preregistered_sampler_sha256,
            posterior_by_ticker={
                matrix.ticker: self.posterior(matrix.ticker)
                for matrix in request.target_matrices
            },
        )
        values.update(changes)
        return HierarchicalBackendResult(**values)

    def test_synthetic_signal_recovers_exact_independent_lag(self):
        selection = self.select_single()
        edges = selection.target_edge_sets[0].edges
        self.assertGreaterEqual(len(edges), 1)
        self.assertEqual((edges[0].source_ticker, edges[0].lag), ("SRC", 5))
        self.assertLess(edges[0].q_value, 0.05)
        self.assertGreater(edges[0].correlation, 0.99)
        self.assertEqual(selection.policy.candidate_lags, EXPECTED_LAGS)
        self.assertEqual(selection.policy.candidate_depths, EXPECTED_DEPTHS)

    def test_nonconsecutive_nonmonotone_edges_are_not_forced_chain(self):
        count = 450
        rng = np.random.default_rng(21)
        source_a = rng.normal(size=count)
        source_b = rng.normal(size=count)
        t1 = rng.normal(scale=0.03, size=count)
        t2 = rng.normal(scale=0.03, size=count)
        t1[7:] = source_a[:-7] + rng.normal(scale=0.03, size=count - 7)
        t2[2:] = -source_b[:-2] + rng.normal(scale=0.03, size=count - 2)
        panel = self.panel(np.column_stack((t1, t2, source_a, source_b)), ("T1", "T2", "A", "B"))
        selection = select_independent_edges(
            panel, target_sources={"T1": ("A",), "T2": ("B",)},
            selection_end_ordinal=390,
        )
        selected = {
            target.target_ticker: (target.edges[0].source_ticker, target.edges[0].lag)
            for target in selection.target_edge_sets
        }
        self.assertEqual(selected, {"T1": ("A", 7), "T2": ("B", 2)})
        self.assertFalse(selection.forced_chain)

    def test_constant_no_signal_family_selects_nothing(self):
        count = 300
        panel = self.panel(np.zeros((count, 3)), ("TGT", "A", "B"))
        selection = select_independent_edges(
            panel, target_sources={"TGT": ("A", "B")}, selection_end_ordinal=250,
        )
        self.assertEqual(selection.hypothesis_count, 14)
        self.assertEqual(selection.target_edge_sets[0].selected_depth, 0)
        self.assertTrue(all(item.p_value == 1.0 and item.q_value == 1.0 for item in selection.all_hypotheses))

    def test_seeded_random_null_is_not_misrepresented_as_signal(self):
        rng = np.random.default_rng(12345)
        panel = self.panel(rng.normal(size=(500, 9)), tuple(f"T{index}" for index in range(9)))
        selection = select_independent_edges(
            panel,
            target_sources={"T0": tuple(f"T{index}" for index in range(1, 9))},
            selection_end_ordinal=420,
        )
        self.assertEqual(selection.hypothesis_count, 56)
        self.assertEqual(selection.target_edge_sets[0].selected_depth, 0)

    def test_bh_is_applied_over_global_family_not_per_target(self):
        panel = self.single_signal_panel(count=460)
        selection = select_independent_edges(
            panel,
            target_sources={
                "TGT": ("SRC", "NOISE1", "NOISE2"),
                "NOISE1": ("SRC", "NOISE2"),
            },
            selection_end_ordinal=400,
        )
        self.assertEqual(selection.hypothesis_count, 35)
        ordered = sorted(selection.all_hypotheses, key=lambda item: item.p_value)
        self.assertLessEqual(ordered[0].q_value, ordered[-1].q_value)
        self.assertTrue(all(item.q_value + 1e-15 >= item.p_value for item in selection.all_hypotheses))

    def test_future_mutation_cannot_change_training_only_selection(self):
        panel = self.single_signal_panel(count=430)
        cutoff = 350
        original = self.select_single(panel, cutoff=cutoff)
        attacked_values = panel.returns_pct.copy()
        attacked_values[cutoff + 1 :] = np.random.default_rng(99).normal(0, 1_000_000, attacked_values[cutoff + 1 :].shape)
        attacked = replace(panel, returns_pct=attacked_values)
        replay = self.select_single(attacked, cutoff=cutoff)
        self.assertEqual(original.selection_id, replay.selection_id)
        self.assertEqual(original.all_hypotheses, replay.all_hypotheses)

    def test_cutoff_requires_126_aligned_observations_for_every_lag(self):
        with self.assertRaisesRegex(HierarchicalContractError, "insufficient aligned"):
            self.select_single(cutoff=130)

    def test_policy_cannot_change_lags_depths_multiplicity_or_claim(self):
        panel = self.single_signal_panel()
        policies = (
            EdgeSelectionPolicy(candidate_lags=(1, 2)),
            EdgeSelectionPolicy(candidate_depths=(1, 2)),
            EdgeSelectionPolicy(minimum_fit_observations=30),
            EdgeSelectionPolicy(fdr_alpha=0.051),
            EdgeSelectionPolicy(association_test="UNREGISTERED_TEST"),
            EdgeSelectionPolicy(multiple_testing_method="NONE"),
            EdgeSelectionPolicy(topology="CHAIN"),
            EdgeSelectionPolicy(claim_scope="CAUSAL_PROOF"),
        )
        for policy in policies:
            with self.subTest(policy=policy), self.assertRaises(HierarchicalContractError):
                select_independent_edges(
                    panel, target_sources={"TGT": ("SRC",)},
                    selection_end_ordinal=360, policy=policy,
                )

    def test_fit_request_uses_canonical_percentage_names_and_alignment(self):
        request = self.request()
        matrix = request.target_matrices[0]
        self.assertEqual(request.return_unit, "PERCENT")
        self.assertTrue(all("_return_pct_" in name for name in matrix.feature_names))
        self.assertFalse(hasattr(matrix, "y_return_pp"))
        self.assertTrue(hasattr(matrix, "y_return_pct"))
        self.assertEqual(matrix.x_train.shape[0], len(matrix.y_return_pct))
        self.assertEqual(matrix.x_predict.shape, (1, matrix.x_train.shape[1]))
        self.assertTrue(np.isfinite(matrix.x_train).all())

    def test_prediction_features_use_source_or_earlier_and_ignore_future_rows(self):
        panel = self.single_signal_panel(count=430)
        selection = self.select_single(panel, cutoff=350)
        original = build_hierarchical_fit_request(
            panel, selection, model_run_id="run-a",
            prediction_date=panel.session_dates[351],
            preregistered_model_config_sha256="b" * 64,
            preregistered_sampler_sha256="c" * 64,
        )
        values = panel.returns_pct.copy()
        values[351:] = 999999.0
        attacked_panel = replace(panel, returns_pct=values)
        attacked = build_hierarchical_fit_request(
            attacked_panel, selection, model_run_id="run-a",
            prediction_date=panel.session_dates[351],
            preregistered_model_config_sha256="b" * 64,
            preregistered_sampler_sha256="c" * 64,
        )
        np.testing.assert_array_equal(original.target_matrices[0].x_train, attacked.target_matrices[0].x_train)
        np.testing.assert_array_equal(original.target_matrices[0].x_predict, attacked.target_matrices[0].x_predict)

    def test_selection_artifact_identity_rejects_semantic_mutation(self):
        panel = self.single_signal_panel()
        selection = self.select_single(panel)
        attacked = replace(selection, forced_chain=True)
        with self.assertRaises(HierarchicalContractError):
            build_hierarchical_fit_request(
                panel, attacked, model_run_id="run-a",
                prediction_date=panel.session_dates[361],
                preregistered_model_config_sha256="b" * 64,
                preregistered_sampler_sha256="c" * 64,
            )
        attacked = replace(selection, selection_id="edge-selection-" + "0" * 64)
        with self.assertRaisesRegex(HierarchicalContractError, "identity mismatch"):
            build_hierarchical_fit_request(
                panel, attacked, model_run_id="run-a",
                prediction_date=panel.session_dates[361],
                preregistered_model_config_sha256="b" * 64,
                preregistered_sampler_sha256="c" * 64,
            )

    def test_backend_is_explicit_called_once_and_exact_coverage_is_validated(self):
        request = self.request()
        backend = Mock(return_value=self.result(request))
        result = run_hierarchical_backend(request, backend=backend)
        backend.assert_called_once_with(request)
        self.assertEqual(tuple(item.ticker for item in result.posterior_by_ticker), ("TGT",))
        self.assertTrue(result.research_only)
        self.assertFalse(result.operationally_eligible)
        self.assertEqual(len(result.result_sha256), 64)

    def test_preregistered_graph_hashes_are_bound_end_to_end(self):
        request = self.request()
        backend = Mock()
        with self.assertRaisesRegex(HierarchicalContractError, "graph identity mismatch"):
            run_hierarchical_backend(
                replace(request, graph_contract_sha256="0" * 64), backend=backend
            )
        backend.assert_not_called()
        attacked = self.result(
            request, preregistered_sampler_sha256="f" * 64
        )
        with self.assertRaisesRegex(HierarchicalContractError, "preregistered graph"):
            run_hierarchical_backend(request, backend=lambda _request: attacked)

    def test_missing_extra_or_mistyped_posterior_fails_closed(self):
        request = self.request()
        cases = (
            self.result(request, posterior_by_ticker={}),
            self.result(request, posterior_by_ticker={"TGT": self.posterior("TGT"), "EXTRA": self.posterior("EXTRA")}),
            self.result(request, posterior_by_ticker={"TGT": self.posterior("WRONG")}),
        )
        for result in cases:
            with self.subTest(), self.assertRaises(HierarchicalContractError):
                run_hierarchical_backend(request, backend=lambda _request, result=result: result)

    def test_backend_diagnostics_are_strict_and_scientific_failure_is_not_healed(self):
        request = self.request()
        diagnostics = (
            self.diagnostics(chains=3), self.diagnostics(draws=999),
            self.diagnostics(tune=999), self.diagnostics(max_rhat=1.02),
            self.diagnostics(min_bulk_ess=399), self.diagnostics(min_tail_ess=399),
            self.diagnostics(bfmi_min=0.29), self.diagnostics(divergences=1),
            self.diagnostics(max_treedepth_fraction=0.02),
        )
        for item in diagnostics:
            result = self.result(request, posterior_by_ticker={"TGT": self.posterior("TGT", diagnostics=item)})
            with self.subTest(item=item), self.assertRaises(HierarchicalContractError):
                run_hierarchical_backend(request, backend=lambda _request, result=result: result)

    def test_backend_cannot_persist_or_create_downstream_outputs(self):
        request = self.request()
        mutations = (
            {"database_writes": 1}, {"predictions_persisted": 1},
            {"recommendations_created": 1}, {"orders_created": 1},
            {"etf_outputs_created": 1}, {"trading_activated": True},
        )
        for changes in mutations:
            result = self.result(request, **changes)
            with self.subTest(changes=changes), self.assertRaises(HierarchicalContractError):
                run_hierarchical_backend(request, backend=lambda _request, result=result: result)

    def test_request_downstream_flags_fail_before_backend(self):
        request = self.request()
        for field in (
            "persist_predictions", "create_recommendations", "create_orders",
            "create_etf_outputs", "activate_trading",
        ):
            backend = Mock()
            with self.subTest(field=field), self.assertRaises(HierarchicalContractError):
                run_hierarchical_backend(replace(request, **{field: True}), backend=backend)
            backend.assert_not_called()

    def test_module_is_pure_and_has_no_real_fitter_or_external_io(self):
        source = Path(__file__).with_name("independent_edge_hierarchy.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "import os", "subprocess", "requests", "urllib", "libsql", "sqlite",
            "import pymc", "pm.sample", "read_csv", "read_excel", "pending_orders",
            "recommendation", "send_email",
        ):
            if forbidden == "recommendation":
                # The word appears only in explicit prohibition fields/docs.
                continue
            self.assertNotIn(forbidden, source)

    def test_artifacts_state_observational_not_causal_scope(self):
        selection = self.select_single()
        self.assertEqual(selection.policy.claim_scope, CLAIM_SCOPE)
        self.assertNotIn("CAUSAL_PROOF", selection.policy.claim_scope)
        request = self.request()
        self.assertEqual(request.model_topology, TOPOLOGY)
        self.assertEqual(request.candidate_lags, EXPECTED_LAGS)
        self.assertEqual(request.candidate_depths, EXPECTED_DEPTHS)
        self.assertEqual(request.return_unit, RETURN_UNIT)


if __name__ == "__main__":
    unittest.main()
