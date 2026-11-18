"""Synthetic acceptance contract for the future numerical estimator."""

import copy
import unittest

from contrib.deepsignal.seep_repeatability.estimator import (
    estimate_repeatability,
    fit_amplitude,
    heading_separation,
    null_p_value,
)
from contrib.deepsignal.seep_repeatability.fixtures import (
    missing_coverage_records,
    record_hash,
    synthetic_records,
)


class EstimatorContractTest(unittest.TestCase):
    def test_repeat_anchor_beats_beam_fixed_ghost(self):
        result = estimate_repeatability(synthetic_records())
        self.assertEqual("REPEAT", result["FLARE_Verdict"])
        self.assertEqual([0.0, 0.0], result["FLARE_Anchor_EN_m"])
        self.assertGreater(result["FLARE_FeatureScore"], result["FLARE_NullScore"])
        self.assertAlmostEqual(2.0, result["FLARE_RelativeIndex"], places=6)

    def test_missing_coverage_is_missing_strength(self):
        result = estimate_repeatability(missing_coverage_records())
        self.assertIsNone(result["FLARE_RelativeIndex"])
        self.assertEqual("INSUFFICIENT_COVERAGE", result["FLARE_Reason"])
        self.assertNotEqual(0.0, result["FLARE_RelativeIndex"])

    def test_correlated_voxel_gain(self):
        covariance = [[1.0, 0.5], [0.5, 1.0]]
        amplitude, gain = fit_amplitude([2.0, 2.0], [1.0, 1.0], covariance)
        self.assertAlmostEqual(2.0, amplitude)
        self.assertAlmostEqual(8.0 / 3.0, gain)

    def test_heading_wrap(self):
        self.assertAlmostEqual(20.0, heading_separation(350.0, 10.0))
        self.assertLess(heading_separation(350.0, 10.0), 30.0)

    def test_null_p_value(self):
        self.assertAlmostEqual(0.05, null_p_value(10.0, [10.0] * 9 + [0.0] * 190))
        self.assertAlmostEqual(0.055, null_p_value(10.0, [10.0] * 10 + [0.0] * 189))

    def test_zero_template_support(self):
        result = estimate_repeatability([], window_id="empty")
        self.assertIsNone(result["FLARE_Score"])
        self.assertEqual("ZERO_TEMPLATE_SUPPORT", result["FLARE_Reason"])

    def test_near_zero_first_pass(self):
        rows = synthetic_records()
        for row in rows:
            if row["fields"]["line_id"] == "discovery":
                row["fields"]["linear_excess"] = 1e-15
        result = estimate_repeatability(rows)
        self.assertIsNone(result["FLARE_RelativeIndex"])
        self.assertEqual("UNDEFINED_NEAR_ZERO_BASELINE", result["FLARE_Reason"])

    def test_fit_holdout_ids_are_disjoint(self):
        result = estimate_repeatability(synthetic_records(), debug_partition=True)
        self.assertTrue(set(result["fit_ids"]).isdisjoint(result["holdout_ids"]))

    def test_replay_determinism_and_immutable_inputs(self):
        rows = synthetic_records()
        before = record_hash(rows)
        first = estimate_repeatability(rows)
        second = estimate_repeatability(copy.deepcopy(rows))
        self.assertEqual(first, second)
        self.assertEqual(before, record_hash(rows))


if __name__ == "__main__":
    unittest.main()
