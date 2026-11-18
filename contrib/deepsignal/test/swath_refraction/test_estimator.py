"""Executable numerical contract for the sequential estimator lane."""

import copy
import math
import unittest

from contrib.deepsignal.swath_refraction.estimator import (
    SwathRefractionEstimator,
    projected_information,
)
from contrib.deepsignal.swath_refraction.fixtures import solve_rows


class TestEstimator(unittest.TestCase):
    def setUp(self):
        self.estimator = SwathRefractionEstimator()

    def test_profile_mode_survives_nuisance_projection(self):
        result = self.estimator.solve(**solve_rows())
        self.assertAlmostEqual(result.mode_amplitude_mps, 2.0, delta=0.05)

    def test_duplicate_crossing_prior_refused(self):
        result = self.estimator.solve(
            crossing_ids=("line-a/line-b",),
            prior_source_ids=("line-a/line-b",),
        )
        self.assertEqual(result.verdict, "AMBIGUOUS")
        self.assertIn("same crossing evidence", result.reason.lower())

    def test_constant_c_ray_port_symmetry_and_angle_units(self):
        starboard = self.estimator.trace_constant_layer(
            sound_speed_mps=1500.0, angle_deg=30.0, one_way_time_s=0.1)
        port = self.estimator.trace_constant_layer(
            sound_speed_mps=1500.0, angle_rad=math.radians(-30.0),
            one_way_time_s=0.1)
        self.assertAlmostEqual(starboard.x_m, 75.0, places=6)
        self.assertAlmostEqual(starboard.z_m, 129.90381, places=5)
        self.assertAlmostEqual(port.x_m, -starboard.x_m, places=9)
        self.assertAlmostEqual(port.z_m, starboard.z_m, places=9)

    def test_rank_vs_visible(self):
        result = projected_information(
            residual_m=(0.0,), jacobian=((0.5,),), nuisance=((),),
            covariance=((1.0,),), prior_covariance=((1.0,),))
        self.assertEqual(result.data_rank, 1)
        self.assertEqual(result.visible_modes, 0)

    def test_hidden_mode_positive_rank(self):
        result = projected_information(
            residual_m=(0.2, -0.2), jacobian=((0.4,), (-0.4,)),
            nuisance=((1.0,), (1.0,)), covariance=((1.0, 0.0), (0.0, 1.0)),
            prior_covariance=((1.0,),))
        self.assertGreater(result.data_rank, 0)
        self.assertEqual(result.visible_modes, 0)
        self.assertEqual(result.retained_mode_vectors, ())

    def test_mode_in_nuisance_span_has_zero_data_rank(self):
        result = projected_information(
            residual_m=(-0.4, 0.4, 0.0),
            jacobian=((1.0,), (1.0,), (1.0,)),
            nuisance=((1.0,), (1.0,), (1.0,)),
            covariance=((0.0001, 0.0, 0.0), (0.0, 0.0001, 0.0),
                        (0.0, 0.0, 0.0001)),
            prior_covariance=((25.0,),))
        self.assertEqual(result.data_rank, 0)

    def test_turning_ray(self):
        ray = self.estimator.trace_constant_layer(
            sound_speed_mps=1500.0, ray_parameter_s_per_m=1.0 / 1500.0,
            layer_thickness_m=10.0)
        self.assertTrue(ray.turned)
        self.assertTrue(ray.excluded)
        self.assertEqual(ray.reason, "turning depth reached")

    def test_sloping_crossing_sign(self):
        common = dict(residual_m=(-0.4, 0.4), row_sd_m=0.01,
                      prior_sd_mps=5.0)
        full = self.estimator.solve(
            **common, depth_jacobian=(0.1, -0.1),
            horizontal_jacobian=(0.3, -0.3), terrain_gradient=1.0)
        flat = self.estimator.solve(
            **common, depth_jacobian=(0.1, -0.1),
            horizontal_jacobian=(0.0, 0.0), terrain_gradient=0.0)
        self.assertLess(full.mode_amplitude_mps * flat.mode_amplitude_mps, 0.0)

    def test_inputs_are_immutable(self):
        observations = {"crossing_ids": ["a/b"], **solve_rows()}
        before = copy.deepcopy(observations)
        self.estimator.solve(**observations)
        self.assertEqual(observations, before)


if __name__ == "__main__":
    unittest.main()
