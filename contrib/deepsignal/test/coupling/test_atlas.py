import unittest

from contrib.deepsignal.coupling.atlas import discover


class AtlasTest(unittest.TestCase):
    def test_synthetic_heading_bias_confirmed(self):
        rows = [{'field': .5 * __import__('math').cos(i / 12),
                 'relative_heading_cos': __import__('math').cos(i / 12),
                 'regime': 'transit'} for i in range(240)]
        result = discover(rows[:120], rows[120:], {'fields': ['field'],
                                                   'ship_variables':
                                                   ['relative_heading_cos'],
                                                   'reps': 99, 'min_n_eff': 2})
        self.assertEqual(result['hypotheses'][0]['status'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
