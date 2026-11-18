"""Executable numerical contract for the future weighted-depth estimator."""

import copy
import unittest

from contrib.deepsignal.test.weighted_depth.fixtures import (
    PAIR_VARIANCES, PRIVATE_VARIANCES, fixture_hash, moment_fixture,
    observations, synthetic_epochs,
)
from contrib.deepsignal.weighted_depth.estimator import (
    FamilyContrastEstimator, WeightedDepthEstimator,
)
from contrib.deepsignal.weighted_depth.factors import solve_linear
from contrib.deepsignal.weighted_depth.records import Observation


class EstimatorContractTest(unittest.TestCase):
    def test_pair_contrasts_recover_private_variances(self):
        result = FamilyContrastEstimator().fit(PAIR_VARIANCES, {})
        self.assertEqual(result["status"], "IDENTIFIED")
        for family, expected in PRIVATE_VARIANCES.items():
            self.assertAlmostEqual(result["private_variance_m2"][family], expected, places=9)

    def test_duplicate_head_cannot_outvote_two_families(self):
        estimator = WeightedDepthEstimator({"huber_cutoff": 1000.0})
        plain = estimator.estimate(observations(), 10.0)
        copied = estimator.estimate(observations(duplicate_first=True), 10.0)
        self.assertAlmostEqual(plain["WDEP_Depth_m"], 100.12244897959184, places=9)
        self.assertAlmostEqual(copied["WDEP_Depth_m"], plain["WDEP_Depth_m"], places=12)
        self.assertAlmostEqual(copied["WDEP_SD_m"], plain["WDEP_SD_m"], places=12)

    def test_row_permutation_invariance(self):
        import numpy as np

        y = np.array([4.0, 0.0])
        H = np.ones((2, 1))
        R = np.array([[1.0, 0.8], [0.8, 1.0]])
        forward = solve_linear(y, H, R, np.zeros(1), np.eye(1) * 1e12)[0]
        reverse = solve_linear(y[::-1], H[::-1], R[::-1, ::-1],
                               np.zeros(1), np.eye(1) * 1e12)[0]
        self.assertAlmostEqual(float(forward[0]), float(reverse[0]), places=9)

    def test_hidden_correlation_withholds(self):
        pairs = {("f1", "f2"): 0.4, ("f1", "f3"): 2.0,
                 ("f2", "f3"): 2.0}
        result = FamilyContrastEstimator(prior_variances={"f1": 1, "f2": 1,
                                                          "f3": 1}).fit(pairs)
        self.assertEqual(result["status"], "UNIDENTIFIED")
        self.assertNotEqual(tuple(result["private_variance_m2"].values()), (0.2, 0.2, 1.8))

    def test_known_residual_covariance_in_fusion(self):
        source = [
            Observation("s1", "f1", 10.0, 100.0, 1.0, (1.0, 1.0),
                        ("raw-1",)),
            Observation("s2", "f2", 10.0, 100.0, 1.0, (1.0, 1.0),
                        ("raw-2",)),
        ]
        estimator = WeightedDepthEstimator({
            "huber_cutoff": 1000.0,
            "residual_covariance_m2": {("f1", "f2"): 0.8},
        })
        result = estimator.estimate(source, 10.0)
        self.assertAlmostEqual(result["WDEP_SD_m"] ** 2, 0.9, places=9)

    def test_inconsistent_moments_gate(self):
        pairs = {("f1", "f2"): 1.0, ("f1", "f3"): 1.0,
                 ("f2", "f3"): 4.0}
        blocks = moment_fixture(pairs, block_count=400,
                                standard_error_m2=0.1)
        result = FamilyContrastEstimator(
            bootstrap_resamples=999,
            bootstrap_minimum_blocks=30,
            bootstrap_seed=17001,
        ).fit(blocks, {})
        self.assertEqual(result["verdict"], "AMBIGUOUS")
        self.assertIn("misfit", result["reason"].lower())

    def test_noisy_moments_no_gate(self):
        pairs = {("f1", "f2"): 1.0, ("f1", "f3"): 1.0,
                 ("f2", "f3"): 4.0}
        blocks = moment_fixture(pairs, block_count=30,
                                standard_error_m2=2.0)
        result = FamilyContrastEstimator(
            bootstrap_resamples=999,
            bootstrap_minimum_blocks=30,
            bootstrap_seed=17001,
        ).fit(blocks, {})
        self.assertNotEqual(result["verdict"], "AMBIGUOUS")
        self.assertEqual(result["status"], "IDENTIFIED")
        self.assertTrue(result["intervals_wide"])

    def test_uniform_noise_variance(self):
        import numpy as np

        rng = np.random.default_rng(17001)
        blocks = rng.uniform(0.0, 1.0, size=(20000, 3))
        result = FamilyContrastEstimator(minimum_blocks=20).fit(blocks, {})
        for variance in result["private_variance_m2"].values():
            self.assertAlmostEqual(variance, 1.0 / 12.0, delta=(1.0 / 12.0) * 0.02)

    def test_uncalibrated_trim_refused(self):
        import numpy as np

        rng = np.random.default_rng(17001)
        blocks = rng.uniform(0.0, 1.0, size=(20000, 3))
        estimator = FamilyContrastEstimator(trim=0.5)
        with self.assertRaisesRegex(ValueError, "consistency"):
            estimator.fit(blocks, {})

    def test_even_cycle_unidentified(self):
        pairs = {("f1", "f2"): 2, ("f2", "f3"): 2,
                 ("f3", "f4"): 2, ("f4", "f1"): 2}
        result = FamilyContrastEstimator().fit(pairs, {})
        self.assertEqual(result["status"], "UNIDENTIFIED")

    def test_relative_and_anchored_bias_are_distinct(self):
        estimator = WeightedDepthEstimator()
        shifted = observations((100.0, 102.0, 100.0))
        relative = estimator.estimate(shifted, 10.0)
        anchored = estimator.estimate(
            shifted, 10.0, anchor={"depth_m": 100.0, "id": "check-1"})
        self.assertIsNone(relative["WDEP_AnchorId"])
        self.assertEqual(anchored["WDEP_AnchorId"], "check-1")
        self.assertNotEqual(relative["WDEP_RelativeBias_m"],
                            anchored["WDEP_RelativeBias_m"])

    def test_fit_receives_no_holdout_ids(self):
        fixture = synthetic_epochs()
        self.assertFalse(set(fixture["fit_ids"]) & set(fixture["holdout_ids"]))

    def test_fixture_input_hash_survives(self):
        fixture = synthetic_epochs(100)
        before = fixture_hash(fixture)
        WeightedDepthEstimator().estimate(observations(), 10.0)
        self.assertEqual(fixture_hash(fixture), before)

    def test_observation_inputs_are_immutable(self):
        source = observations()
        before = copy.deepcopy(source)
        WeightedDepthEstimator().estimate(source, 10.0)
        self.assertEqual(source, before)

    def test_two_family_tie_is_ambiguous(self):
        result = WeightedDepthEstimator().estimate(observations()[:2], 10.0)
        self.assertEqual(result["WDEP_Verdict"], "AMBIGUOUS")

    def test_single_source_uses_prior_uncertainty(self):
        result = WeightedDepthEstimator().estimate(observations()[:1], 10.0)
        self.assertEqual(result["WDEP_Support"], 1)
        self.assertGreater(result["WDEP_SD_m"], 0.0)


if __name__ == "__main__":
    unittest.main()
