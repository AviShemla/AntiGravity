import unittest
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from sampler_qa import SamplerDiagnostics, sampler_diagnostics, validate_sampler_diagnostics


class SamplerQATests(unittest.TestCase):
    def valid(self, **overrides):
        values = {
            "max_rhat": 1.01,
            "min_ess_bulk": 500.0,
            "min_ess_tail": 300.0,
            "min_bfmi": 0.8,
            "divergences": 0,
            "tree_depth_saturation_fraction": 0.0,
            "chains": 2,
        }
        values.update(overrides)
        return SamplerDiagnostics(**values)

    def test_valid_diagnostics_pass(self):
        validate_sampler_diagnostics(self.valid())

    def test_single_chain_fails(self):
        with self.assertRaisesRegex(ValueError, "two chains"):
            validate_sampler_diagnostics(self.valid(chains=1))

    def test_divergence_fails(self):
        with self.assertRaisesRegex(ValueError, "divergences"):
            validate_sampler_diagnostics(self.valid(divergences=1))

    def test_low_ess_fails(self):
        with self.assertRaisesRegex(ValueError, "ESS"):
            validate_sampler_diagnostics(self.valid(min_ess_bulk=80.0))

    def test_nonfinite_rhat_fails(self):
        with self.assertRaisesRegex(ValueError, "non-finite"):
            validate_sampler_diagnostics(self.valid(max_rhat=float("nan")))

    def test_bfmi_is_computed_from_explicit_energy_array(self):
        class Sizes:
            def get(self, key, default):
                return 2 if key == "chain" else default

        class Posterior:
            sizes = Sizes()

        class SampleStats(dict):
            pass

        class Trace:
            posterior = Posterior()
            sample_stats = SampleStats(
                energy=np.ones((2, 10)),
                diverging=np.zeros((2, 10), dtype=int),
                tree_depth=np.ones((2, 10), dtype=int),
            )

        summary = type(
            "Summary",
            (),
            {
                "columns": {"r_hat", "ess_bulk", "ess_tail"},
                "__getitem__": lambda self, key: {
                    "r_hat": np.asarray([1.0]),
                    "ess_bulk": np.asarray([400.0]),
                    "ess_tail": np.asarray([250.0]),
                }[key],
            },
        )()
        bfmi = MagicMock(return_value=np.asarray([0.8, 0.9]))
        fake_arviz = SimpleNamespace(summary=MagicMock(return_value=summary), bfmi=bfmi)
        with patch.dict(sys.modules, {"arviz": fake_arviz}):
            diagnostics = sampler_diagnostics(Trace())
        self.assertEqual(diagnostics.min_bfmi, 0.8)
        np.testing.assert_array_equal(bfmi.call_args.args[0], np.ones((2, 10)))


if __name__ == "__main__":
    unittest.main()
