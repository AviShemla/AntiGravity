from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

import numpy as np

try:
    from hierarchical_model_impl.independent_edge_hierarchy import (
        HierarchicalFitRequest,
        TargetDesignMatrix,
        canonical_sha256,
    )
    from model_fit_contract_impl.execution_contract import (
        AuthorizationStatus,
        ExecutionAuthorizationArtifact,
    )
except ImportError:
    from research_contracts.hierarchical_stock_model.independent_edge_hierarchy import (
        HierarchicalFitRequest,
        TargetDesignMatrix,
        canonical_sha256,
    )
    from research_contracts.stock_model_fit_execution.execution_contract import (
        AuthorizationStatus,
        ExecutionAuthorizationArtifact,
    )

try:
    from .immutable_fixture_runner import build_fixture_run_plan
    from .pymc_hierarchical_backend import (
        FrozenBackendConfig,
        NumericModelConfig,
        PyMCBackendError,
        SamplerConfig,
        extract_posterior,
        extract_sampler_diagnostics,
        freeze_backend_config,
        make_pymc_backend,
        pack_design,
    )
except ImportError:  # isolated workspace execution
    from pymc_backend_runner_impl.immutable_fixture_runner import build_fixture_run_plan
    from pymc_backend_runner_impl.pymc_hierarchical_backend import (
        FrozenBackendConfig,
        NumericModelConfig,
        PyMCBackendError,
        SamplerConfig,
        extract_posterior,
        extract_sampler_diagnostics,
        freeze_backend_config,
        make_pymc_backend,
        pack_design,
    )


def _matrix(ticker: str, edges: tuple[tuple[str, int], ...], offset: float) -> TargetDesignMatrix:
    observations = 126
    depth = len(edges)
    x = np.arange(observations * depth, dtype=float).reshape(observations, depth) / 100 + offset
    return TargetDesignMatrix(
        ticker=ticker,
        feature_names=tuple(f"{source}_return_pct_lag{lag}" for source, lag in edges),
        edge_identities=edges,
        training_dates=tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(observations)),
        x_train=x,
        y_direction=(np.arange(observations) % 2).astype(np.int8),
        y_return_pct=np.linspace(-2, 2, observations),
        x_predict=x[-1:].copy(),
        train_mean=np.zeros(depth),
        train_scale=np.ones(depth),
    )


def _request(config: FrozenBackendConfig | None = None) -> HierarchicalFitRequest:
    config = config or freeze_backend_config()
    topology = "INDEPENDENT_TICKER_LAG_EDGES_PARTIAL_POOLING"
    hierarchy = "PARTIAL_POOLING_GLOBAL_EDGE_SCALE_AND_TARGET_INTERCEPTS"
    graph = canonical_sha256({
        "model_topology": topology,
        "hierarchy": hierarchy,
        "direction_likelihood": "BERNOULLI_LOGIT",
        "return_likelihood": "STUDENT_T_PERCENT",
        "edge_coefficients": "INDEPENDENT_EXCHANGEABLE_NO_POSITIONAL_CHAIN",
        "standardization": "TRAINING_ONLY_PER_TARGET_EDGE",
        "preregistered_model_config_sha256": config.model_config_sha256,
        "preregistered_sampler_sha256": config.sampler_sha256,
    })
    return HierarchicalFitRequest(
        model_run_id="fixture-s08-run",
        selection_id="fixture-selection",
        panel_snapshot_id="fixture-panel",
        panel_snapshot_sha256="a" * 64,
        source_session_date=date(2026, 8, 26),
        prediction_date=date(2026, 8, 27),
        model_topology=topology,
        hierarchy=hierarchy,
        graph_contract_sha256=graph,
        preregistered_model_config_sha256=config.model_config_sha256,
        preregistered_sampler_sha256=config.sampler_sha256,
        candidate_lags=tuple(range(1, 8)),
        candidate_depths=tuple(range(1, 6)),
        target_matrices=(
            _matrix("AAA", (("BBB", 7),), 0.0),
            _matrix("BBB", (("AAA", 2), ("CCC", 5)), 1.0),
        ),
    )


def _artifact() -> ExecutionAuthorizationArtifact:
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    return ExecutionAuthorizationArtifact(
        contract_id="codex-oracle-s08-stock-fit-execution-v1",
        status=AuthorizationStatus.AUTHORIZED_NOT_STARTED,
        artifact_id="s08-fit-auth-" + "b" * 64,
        request_sha256="c" * 64,
        created_at_utc=now,
        launch_deadline_utc=now + timedelta(hours=1),
        run_id="fixture-s08-run",
        preregistration_raw_sha256="d" * 64,
        checkpoint_identity_sha256="e" * 64,
        authorization_record_sha256="f" * 64,
        code_git_commit="1" * 40,
        release_manifest_sha256="2" * 64,
        output_root="/var/lib/codex-oracle/s08/fixture-s08-run",
        launch_argv=("python", "runner.py"),
        checkpoint_interval_seconds=60,
        max_checkpoint_age_seconds=600,
        model_fit_started=False,
        database_writes_authorized=False,
        downstream_authorized=False,
        launch_performed=False,
    )


class _Array:
    def __init__(self, value):
        self.value = np.asarray(value)

    def __array__(self, dtype=None):
        return np.asarray(self.value, dtype=dtype)

    @property
    def values(self):
        return self.value

    @property
    def shape(self):
        return self.value.shape


class _DiagnosticArray(_Array):
    def to_array(self):
        return self


class _FakeAz:
    @staticmethod
    def rhat(_idata, var_names):
        assert var_names
        return _DiagnosticArray([1.001, 1.002])

    @staticmethod
    def ess(_idata, var_names, method):
        assert var_names and method in {"bulk", "tail"}
        return _DiagnosticArray([900, 800])

    @staticmethod
    def bfmi(_idata):
        return np.asarray([0.8, 0.85, 0.82, 0.81])


class _FakeIData:
    def __init__(self, targets: int, draws: int = 1000):
        rng = np.random.default_rng(42)
        self.posterior = {
            "prediction_probability_up": _Array(rng.uniform(0.2, 0.8, (4, draws, targets))),
            "prediction_expected_return_pct": _Array(rng.normal(0, 1, (4, draws, targets))),
            "return_sigma": _Array(rng.uniform(0.5, 1.5, (4, draws, targets))),
        }
        self.sample_stats = {
            "diverging": _Array(np.zeros((4, draws), dtype=int)),
            "tree_depth": _Array(np.full((4, draws), 8, dtype=int)),
        }


class _Symbol:
    def __getitem__(self, _item):
        return self

    def __mul__(self, _other):
        return self

    __rmul__ = __mul__

    def __add__(self, _other):
        return self

    __radd__ = __add__


class _FakeModel:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @staticmethod
    def initial_point():
        return {"fixture": 0.0}

    @staticmethod
    def compile_logp():
        return lambda _point: -1.0


class _FakeMath:
    @staticmethod
    def sum(_value, axis):
        assert axis == 1
        return _Symbol()

    @staticmethod
    def sigmoid(_value):
        return _Symbol()


class _FakePM:
    math = _FakeMath()

    def __init__(self, targets=2):
        self.targets = targets
        self.sample_kwargs = None
        self.likelihoods = []

    @staticmethod
    def Model(**_kwargs):
        return _FakeModel()

    @staticmethod
    def Data(*_args, **_kwargs):
        return _Symbol()

    def Normal(self, *_args, **_kwargs):
        return _Symbol()

    def HalfNormal(self, *_args, **_kwargs):
        return _Symbol()

    def Exponential(self, *_args, **_kwargs):
        return _Symbol()

    def Bernoulli(self, name, **_kwargs):
        self.likelihoods.append(name)
        return _Symbol()

    def StudentT(self, name, **_kwargs):
        self.likelihoods.append(name)
        return _Symbol()

    @staticmethod
    def Deterministic(_name, value, **_kwargs):
        return value

    def sample(self, **kwargs):
        self.sample_kwargs = kwargs
        idata = _FakeIData(self.targets, draws=kwargs.get("draws", 1000))
        # Match the requested fixture chain count for bounded rehearsal tests.
        chains = kwargs.get("chains", 4)
        if chains != 4:
            for key, value in idata.posterior.items():
                value.value = value.value[:chains]
            for value in idata.sample_stats.values():
                value.value = value.value[:chains]
        return idata


class FrozenConfigurationTests(unittest.TestCase):
    def test_hashes_are_stable(self):
        self.assertEqual(freeze_backend_config(), freeze_backend_config())

    def test_numeric_change_changes_hash(self):
        changed = freeze_backend_config(NumericModelConfig(return_edge_scale=0.6))
        self.assertNotEqual(changed.model_config_sha256, freeze_backend_config().model_config_sha256)

    def test_sampler_change_changes_hash(self):
        changed = freeze_backend_config(sampler=SamplerConfig(target_accept=0.96))
        self.assertNotEqual(changed.sampler_sha256, freeze_backend_config().sampler_sha256)

    def test_rejects_weakened_chains(self):
        with self.assertRaisesRegex(PyMCBackendError, "sampler counts"):
            freeze_backend_config(sampler=SamplerConfig(chains=3, random_seeds=(1, 2, 3)))

    def test_rejects_duplicate_chain_seeds(self):
        with self.assertRaisesRegex(PyMCBackendError, "unique deterministic"):
            freeze_backend_config(sampler=SamplerConfig(random_seeds=(1, 1, 2, 3)))

    def test_rejects_low_target_accept(self):
        with self.assertRaisesRegex(PyMCBackendError, "convergence controls"):
            freeze_backend_config(sampler=SamplerConfig(target_accept=0.8))

    def test_rejects_student_t_without_finite_variance(self):
        with self.assertRaisesRegex(PyMCBackendError, "finite variance"):
            freeze_backend_config(NumericModelConfig(student_t_nu_offset=1.99))

    def test_rejects_non_finite_prior_location(self):
        with self.assertRaisesRegex(PyMCBackendError, "location must be finite"):
            freeze_backend_config(NumericModelConfig(return_edge_location=float("nan")))

    def test_rejects_boolean_sampler_integer(self):
        with self.assertRaisesRegex(PyMCBackendError, "integer controls"):
            freeze_backend_config(sampler=SamplerConfig(cores=True))


class PackedDesignTests(unittest.TestCase):
    def test_ragged_edges_are_explicitly_packed(self):
        packed = pack_design(_request())
        self.assertEqual(packed.tickers, ("AAA", "BBB"))
        self.assertEqual(packed.edge_names, ("AAA<-BBB:lag7", "BBB<-AAA:lag2", "BBB<-CCC:lag5"))
        self.assertEqual(packed.x.shape, (252, 5))
        np.testing.assert_array_equal(packed.feature_mask[0], [1, 0, 0, 0, 0])
        np.testing.assert_array_equal(packed.feature_mask[-1], [1, 1, 0, 0, 0])

    def test_target_order_is_deterministic(self):
        request = _request()
        reversed_request = replace(request, target_matrices=tuple(reversed(request.target_matrices)))
        self.assertEqual(pack_design(request).edge_names, pack_design(reversed_request).edge_names)

    def test_rejects_out_of_contract_lag(self):
        request = _request()
        bad = _matrix("AAA", (("BBB", 8),), 0)
        with self.assertRaisesRegex(PyMCBackendError, "lag is outside"):
            pack_design(replace(request, target_matrices=(bad,)))

    def test_rejects_non_finite_matrix(self):
        request = _request()
        matrix = request.target_matrices[0]
        bad_x = matrix.x_train.copy()
        bad_x[0, 0] = np.nan
        with self.assertRaisesRegex(PyMCBackendError, "non-finite"):
            pack_design(replace(request, target_matrices=(replace(matrix, x_train=bad_x),)))

    def test_rejects_wrong_matrix_rank(self):
        request = _request()
        matrix = request.target_matrices[0]
        with self.assertRaisesRegex(PyMCBackendError, "rank differs"):
            pack_design(replace(request, target_matrices=(replace(matrix, x_train=matrix.x_train[:, 0]),)))

    def test_rejects_non_binary_direction(self):
        request = _request()
        matrix = request.target_matrices[0]
        bad_y = matrix.y_direction.copy()
        bad_y[0] = 2
        with self.assertRaisesRegex(PyMCBackendError, "not binary"):
            pack_design(replace(request, target_matrices=(replace(matrix, y_direction=bad_y),)))


class ExtractionTests(unittest.TestCase):
    def test_extracts_full_diagnostics(self):
        config = SamplerConfig()
        evidence = extract_sampler_diagnostics(_FakeAz(), _FakeIData(2), config)
        self.assertEqual(evidence.chains, 4)
        self.assertEqual(evidence.divergences, 0)
        self.assertLess(evidence.max_rhat, 1.01)
        self.assertGreater(evidence.min_bulk_ess, 400)

    def test_extracts_canonical_percent_posteriors(self):
        packed = pack_design(_request())
        diagnostics = extract_sampler_diagnostics(_FakeAz(), _FakeIData(2), SamplerConfig())
        posterior = extract_posterior(_FakeIData(2), packed, diagnostics)
        self.assertEqual(set(posterior), {"AAA", "BBB"})
        self.assertGreater(posterior["AAA"].predictive_risk_pct, 0)
        self.assertLessEqual(posterior["AAA"].probability_up_q95, 1)

    def test_rejects_posterior_coverage_shape(self):
        packed = pack_design(_request())
        diagnostics = extract_sampler_diagnostics(_FakeAz(), _FakeIData(2), SamplerConfig())
        with self.assertRaisesRegex(PyMCBackendError, "coordinates"):
            extract_posterior(_FakeIData(1), packed, diagnostics)


class BackendAndRunnerGateTests(unittest.TestCase):
    def test_concrete_backend_builds_both_heads_and_samples_exactly(self):
        config = freeze_backend_config()
        pm = _FakePM()
        importer = lambda name: pm if name == "pymc" else _FakeAz()
        result = make_pymc_backend(config, importer=importer)(_request(config))
        self.assertEqual(pm.likelihoods, ["direction_observed", "return_observed_pct"])
        self.assertEqual(pm.sample_kwargs["chains"], 4)
        self.assertEqual(pm.sample_kwargs["draws"], 1000)
        self.assertEqual(pm.sample_kwargs["tune"], 1000)
        self.assertEqual(pm.sample_kwargs["nuts"], {"max_treedepth": 12})
        self.assertEqual(set(result.posterior_by_ticker), {"AAA", "BBB"})
        self.assertEqual(result.database_writes, 0)
        self.assertFalse(result.trading_activated)

    def test_concrete_backend_uses_deterministic_chain_seeds(self):
        config = freeze_backend_config()
        pm = _FakePM()
        importer = lambda name: pm if name == "pymc" else _FakeAz()
        make_pymc_backend(config, importer=importer)(_request(config))
        self.assertEqual(pm.sample_kwargs["random_seed"], [1729, 2718, 3141, 5772])

    def test_lazy_dependency_failure_is_typed(self):
        config = freeze_backend_config()
        backend = make_pymc_backend(config, importer=lambda name: (_ for _ in ()).throw(ImportError(name)))
        with self.assertRaisesRegex(PyMCBackendError, "dependency closure"):
            backend(_request(config))

    def test_hash_mismatch_fails_before_import(self):
        config = freeze_backend_config()
        called = []
        backend = make_pymc_backend(config, importer=lambda name: called.append(name))
        with self.assertRaisesRegex(PyMCBackendError, "not the preregistered identity"):
            backend(replace(_request(config), preregistered_model_config_sha256="0" * 64))
        self.assertEqual(called, [])

    def test_tampered_config_rejected(self):
        config = freeze_backend_config()
        bad = replace(config, model_config_sha256="0" * 64)
        with self.assertRaisesRegex(PyMCBackendError, "not content-addressed"):
            make_pymc_backend(bad)

    def test_builds_content_addressed_fixture_plan(self):
        config = freeze_backend_config()
        plan = build_fixture_run_plan(_artifact(), _request(config), config)
        self.assertTrue(plan.fixture_only)
        self.assertEqual(plan.database_write_scope, "NONE")
        self.assertFalse(plan.downstream_authorized)
        self.assertEqual(len(plan.plan_sha256), 64)

    def test_runner_rejects_started_artifact(self):
        config = freeze_backend_config()
        with self.assertRaisesRegex(PyMCBackendError, "already records a launch"):
            build_fixture_run_plan(replace(_artifact(), model_fit_started=True), _request(config), config)

    def test_runner_rejects_database_authority(self):
        config = freeze_backend_config()
        with self.assertRaisesRegex(PyMCBackendError, "research-only"):
            build_fixture_run_plan(replace(_artifact(), database_writes_authorized=True), _request(config), config)

    def test_runner_rejects_run_mismatch(self):
        config = freeze_backend_config()
        with self.assertRaisesRegex(PyMCBackendError, "run IDs differ"):
            build_fixture_run_plan(replace(_artifact(), run_id="different-run"), _request(config), config)


if __name__ == "__main__":
    unittest.main()
