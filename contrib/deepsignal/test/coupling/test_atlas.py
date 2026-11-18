import math
import unittest

from contrib.deepsignal.coupling.atlas import discover


class AtlasTest(unittest.TestCase):
    def test_synthetic_heading_bias_confirmed(self):
        rows = [{'field': .5 * math.cos(i / 12),
                 'relative_heading_cos': math.cos(i / 12),
                 'regime': 'transit'} for i in range(2400)]
        config = dict(fields=['field'], ship_variables=['relative_heading_cos'], reps=99)
        result = discover(rows[:1200], rows[1200:], config)
        self.assertEqual(result['hypotheses'][0]['status'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
