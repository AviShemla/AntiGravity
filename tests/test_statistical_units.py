import unittest

from model_lineage import LineageError
from statistical_units import (
    basis_points_to_percentage_points,
    fraction_to_percentage_points,
    percentage_points_to_fraction,
)


class StatisticalUnitTests(unittest.TestCase):
    def test_one_percent_has_one_unambiguous_representation_per_boundary(self):
        self.assertEqual(fraction_to_percentage_points(0.01), 1.0)
        self.assertEqual(percentage_points_to_fraction(1.0), 0.01)

    def test_ten_basis_points_is_one_tenth_percentage_point(self):
        self.assertEqual(basis_points_to_percentage_points(10.0), 0.1)

    def test_known_price_move_round_trips_without_scale_loss(self):
        return_fraction = (102.0 / 101.0) - 1.0
        return_pp = fraction_to_percentage_points(return_fraction)
        self.assertAlmostEqual(return_pp, 0.990099009900991)
        self.assertAlmostEqual(percentage_points_to_fraction(return_pp), return_fraction)

    def test_nonfinite_and_negative_cost_fail_closed(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(LineageError):
                    percentage_points_to_fraction(value)
        with self.assertRaisesRegex(LineageError, "cannot be negative"):
            basis_points_to_percentage_points(-1.0)


if __name__ == "__main__":
    unittest.main()
