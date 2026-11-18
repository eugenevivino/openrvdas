import math
import random
import unittest

from contrib.deepsignal.coupling import stats


class StatsTest(unittest.TestCase):
    def test_correlations_and_acf(self):
        self.assertEqual(stats.pearson([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertAlmostEqual(stats.spearman([1, 2, 2, 4], [4, 2, 2, 1]), -1.0)
        self.assertAlmostEqual(stats.acf([1, 2, 3], 1), 0.0)
        self.assertEqual(stats.decorrelation_lag([1] * 8), 1)

    def test_nonperfect_pearson(self):
        # Three times the centered x is [-4, -1, 5]. Centered y is [0, -2, 2].
        self.assertAlmostEqual(stats.pearson([0, 1, 3], [2, 0, 4]), 12/math.sqrt(42*8))

    def test_asymmetric_spearman(self):
        # Average ranks center to [-1, -1, -1, 1, 2] and [-2, 1, -1, 2, 0].
        self.assertAlmostEqual(stats.spearman([1, 1, 1, 2, 3], [1, 4, 2, 5, 3]), 4/math.sqrt(80))

    def test_later_decorrelation_crossing(self):
        # The first three biased correlations are 17/24, 10/24 and 3/24.
        self.assertEqual(stats.decorrelation_lag(([0]*6 + [1]*6)*2), 3)

    def test_effective_sample_size_falls_with_autocorrelation(self):
        rng = random.Random(4)
        white = [rng.gauss(0, 1) for _ in range(200)]
        smooth = [0.0]
        for value in white[1:]:
            smooth.append(.95 * smooth[-1] + value)
        self.assertLess(stats.n_eff(smooth, smooth, 20), stats.n_eff(white, white, 20))

    def test_resampling_and_lags(self):
        x = list(range(20))
        y = [0, 0] + x[:-2]
        lo, hi = stats.block_bootstrap_ci(x, x, stats.pearson, 4, 50, 2)
        self.assertGreater(lo, .99)
        self.assertGreater(hi, .99)
        self.assertLessEqual(stats.circular_shift_pvalue(x, x, stats.pearson,
                                                         50, 3, 2), .1)
        self.assertEqual(stats.lagged_best(x, y, [-2, 0, 2])[0], 2)

    def test_bh_by_hand_vector(self):
        p = [.0001, .0004, .0019, .0095, .0201, .0278, .0298, .0344,
             .0459, .324, .4262, .5719, .6528, .759, 1.0]
        self.assertEqual(stats.bh(p, .05), set(range(4)))
        self.assertEqual(stats.by(p, .05), set(range(3)))
        self.assertAlmostEqual(sum(1 / i for i in range(1, 16)), 3.318228993)


if __name__ == '__main__':
    unittest.main()
