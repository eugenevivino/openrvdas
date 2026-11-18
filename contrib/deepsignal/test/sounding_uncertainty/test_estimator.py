"""Executable specification for the sounding uncertainty estimator."""

import copy
import math
import random
import statistics
import unittest

from contrib.deepsignal.sounding_uncertainty.contract import RESULT_FIELDS
from contrib.deepsignal.sounding_uncertainty.estimator import (
    calibrate_vertical, compare_crossline, estimate_sounding)
from contrib.deepsignal.sounding_uncertainty.transform import (
    SoundingUncertaintyTransform)
from contrib.deepsignal.test.sounding_uncertainty.fixtures import (
    calibration_samples, packet_dict, vertical_packet)


class EstimatorTruthTest(unittest.TestCase):

    def test_common_draft_survives_per_sounding_covariance(self):
        packet = vertical_packet()
        result = estimate_sounding(packet, {"draft_sd_m": 2.0})
        self.assertAlmostEqual(result["TPU_Cov_ENZ_m2"][2][2], 4.6025, places=7)

    def test_difference_quantile_never_labels_absolute_depth(self):
        samples = [{**item, "target": "difference"}
                   for item in calibration_samples()]
        result = calibrate_vertical(samples, alpha=0.05, seed=17001,
                                    target="difference")
        self.assertEqual(result["interval_target"], "comparison")
        self.assertFalse(result["applies_to_absolute_depth"])

    def test_independent_vertical_variance(self):
        result = estimate_sounding(vertical_packet())
        self.assertAlmostEqual(result["TPU_VerticalSD_m"] ** 2, 0.6025, places=7)

    def test_correlated_vertical_variance(self):
        result = estimate_sounding(vertical_packet(correlation=0.5))
        self.assertAlmostEqual(result["TPU_VerticalSD_m"] ** 2, 0.7525, places=7)

    def test_turn_off_diagonal_sign_and_ellipse_rotation(self):
        packet = vertical_packet()
        east_turn = estimate_sounding(
            packet, {"turn_rate_rad_s": 0.02, "heading_rad": 0.0})
        north_turn = estimate_sounding(
            packet, {"turn_rate_rad_s": 0.02, "heading_rad": math.pi / 2})
        self.assertGreater(east_turn["TPU_Cov_ENZ_m2"][0][1], 0.0)
        delta = ((north_turn["TPU_HorizontalAzimuth_deg"]
                  - east_turn["TPU_HorizontalAzimuth_deg"]) % 180.0)
        self.assertAlmostEqual(delta, 90.0, places=7)

    def test_analytic_ray_derivative_matches_finite_difference(self):
        result = estimate_sounding(vertical_packet(),
                                   {"diagnostics": "jacobian"})
        analytic = result["diagnostics"]["dz_dt_mps"]
        epsilon = 1e-7
        plus = 1500.0 * (0.1 + epsilon) / 2
        minus = 1500.0 * (0.1 - epsilon) / 2
        finite_difference = (plus - minus) / (2 * epsilon)
        self.assertAlmostEqual(analytic, finite_difference, places=6)

    def test_monte_carlo_covariance_within_five_percent(self):
        result = estimate_sounding(vertical_packet())
        rng = random.Random(17001)
        depths = [1500.0 * rng.gauss(0.1, 0.001) / 2
                  + rng.gauss(0.0, 0.2) for _ in range(50000)]
        realized = statistics.variance(depths)
        propagated = result["TPU_VerticalSD_m"] ** 2
        self.assertLess(abs(realized - propagated) / propagated, 0.05)

    def test_detection_cross_term(self):
        packet = vertical_packet()
        packet = packet.__class__(
            **{**packet.__dict__, "detection_variance_m2": 0.04,
               "detection_cross_covariance": (0.0001, 0.0),
               "detection_independence_source_id": None})
        result = estimate_sounding(packet)
        self.assertAlmostEqual(result["TPU_Cov_ENZ_m2"][2][2], 0.7925, places=7)
        self.assertIn("detection_cross", result["signed_cross_terms_m2"])

    def test_heave_sign_convention(self):
        packet = vertical_packet(heave_m=-1.25)
        result = estimate_sounding(packet)
        self.assertAlmostEqual(result["depth_m"], 78.75, places=7)

    def test_deg_to_rad_covariance(self):
        result = estimate_sounding(vertical_packet(), {"angle_sd_deg": 2.0})
        self.assertAlmostEqual(result["angle_variance_rad2"],
                               4.0 * (math.pi / 180.0) ** 2, places=12)

    def test_invalid_joint_covariance(self):
        packet = vertical_packet()
        packet = packet.__class__(
            **{**packet.__dict__,
               "covariance": ((1.0, 2.0), (2.0, 1.0))})
        result = estimate_sounding(packet)
        self.assertIsNone(result["TPU_VerticalSD_m"])
        self.assertEqual(result["TPU_Reason"], "joint covariance is not PSD")

    def test_zero_sz_guard(self):
        comparison = compare_crossline(
            {"depth_m": 10.0, "covariance": [[0.0] * 3 for _ in range(3)]},
            {"depth_m": 11.0, "covariance": [[0.0] * 3 for _ in range(3)]},
            gradient_en=(0.0, 0.0), match_sd_m=0.0)
        self.assertIsNone(comparison["standardized_difference"])
        self.assertEqual(comparison["reason"], "comparison SD must be finite and positive")

    def test_calibration_order_statistic_and_support(self):
        result = calibrate_vertical(calibration_samples(), alpha=0.05, seed=17001)
        self.assertEqual(result["q"], 3.8)
        self.assertEqual(result["independent_blocks"], 39)

    def test_repeated_ping_adds_zero_support(self):
        samples = calibration_samples() + [calibration_samples()[0]] * 5
        result = calibrate_vertical(samples, alpha=0.05, seed=17001)
        self.assertEqual(result["independent_blocks"], 39)

    def test_fit_receives_no_holdout_ids(self):
        samples = calibration_samples()
        samples[0]["holdout_id"] = "site-holdout"
        result = calibrate_vertical(samples, alpha=0.05, seed=17001)
        self.assertNotIn("site-holdout", result["fit_input_ids"])

    def test_regime_shift_scores_undercoverage(self):
        result = calibrate_vertical(calibration_samples(), alpha=0.05,
                                    seed=17001)
        shifted = estimate_sounding(vertical_packet(), {
            "calibration": result, "regime": "outer-beam-new-installation"})
        self.assertEqual(shifted["TPU_Verdict"], "AMBIGUOUS")
        self.assertTrue(shifted["TPU_Excluded"])

    def test_missing_lag_uncertainty(self):
        result = estimate_sounding(vertical_packet(), {"lag_s": 0.02})
        self.assertIsNone(result["TPU_VerticalSD_m"])
        self.assertIn("lag uncertainty", result["TPU_Reason"])

    def test_calibration_class_too_small(self):
        result = calibrate_vertical(calibration_samples(38), alpha=0.05,
                                    seed=17001)
        self.assertIsNone(result["q"])
        self.assertEqual(result["reason"], "fewer than 39 independent blocks")

    def test_record_shape(self):
        result = estimate_sounding(vertical_packet())
        self.assertTrue(set(RESULT_FIELDS).issubset(result))
        self.assertEqual(len(result["TPU_Cov_ENZ_m2"]), 3)
        self.assertEqual(len(result["TPU_Vertical95_m"]), 2)

    def test_replay_determinism(self):
        packet = vertical_packet()
        self.assertEqual(estimate_sounding(packet), estimate_sounding(packet))

    def test_immutable_inputs(self):
        record = packet_dict()
        original = copy.deepcopy(record)
        try:
            SoundingUncertaintyTransform().transform(record)
        except NotImplementedError:
            pass
        self.assertEqual(record, original)

    def test_raw_fields_and_timestamp_survive(self):
        record = packet_dict()
        result = SoundingUncertaintyTransform().transform(record)
        self.assertEqual(result[0], record)
        self.assertEqual(result[0]["fields"]["raw_bytes"], "234d525a00ff")
        self.assertEqual(result[0]["fields"]["existing_qc"], {"quality": 1})

    def test_absent_channels_report_incomplete(self):
        packet = vertical_packet()
        packet = packet.__class__(
            **{**packet.__dict__, "q_names": ("travel_time",),
               "q_units": ("s",), "covariance": ((0.001 ** 2,),)})
        result = estimate_sounding(packet)
        self.assertIsNone(result["TPU_VerticalSD_m"])
        self.assertIn("heave", result["TPU_Reason"])

    def test_none_passes_through(self):
        self.assertIsNone(SoundingUncertaintyTransform().transform(None))


if __name__ == "__main__":
    unittest.main()
