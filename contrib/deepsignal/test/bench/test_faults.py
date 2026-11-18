import math
import unittest

from contrib.deepsignal.bench import faults, traps


class FaultTests(unittest.TestCase):
    def setUp(self):
        self.series = [(100, 10), (110, 12), (120, 14), (130, 13), (140, 15)]
        self.window = {'start': 10, 'end': 30, 'seed': 7}

    def check_injection(self, inject, expected, **params):
        original = self.series.copy()
        output, truth = inject(self.series, **self.window, **params)
        self.assertEqual(output, expected)
        self.assertEqual(truth, [(110, 130, inject.__name__)])
        self.assertEqual(inject(self.series, **self.window, **params), (output, truth))
        self.assertEqual(self.series, original)

    def test_drift(self):
        expected = [(100, 10), (110, 12), (120, 15), (130, 15), (140, 15)]
        self.check_injection(faults.drift, expected, rate_per_hour=360)

    def test_step(self):
        expected = [(100, 10), (110, 15), (120, 17), (130, 16), (140, 15)]
        self.check_injection(faults.step, expected, bias=3)

    def test_lag_uses_elapsed_time(self):
        output, truth = faults.lag(self.series, **self.window, tau_seconds=10)
        self.assertEqual([t for t, _ in output], [100, 110, 120, 130, 140])
        first = 12 - 2 / math.e
        second = 14 + (first - 14) / math.e
        third = 13 + (second - 13) / math.e
        for (_, value), expected in zip(output, [10, first, second, third, 15]):
            self.assertAlmostEqual(value, expected)
        self.assertEqual(truth, [(110, 130, 'lag')])
        self.assertEqual(faults.lag(self.series, **self.window, tau_seconds=10),
                         (output, truth))

    def test_lag_preserves_nan_gap_without_poisoning_later_values(self):
        series = [(0, 10), (1, float('nan')), (2, 20), (3, 19)]
        output, _ = faults.lag(series, start=0, end=3, tau_seconds=1)
        self.assertTrue(math.isnan(output[1][1]))
        self.assertTrue(math.isfinite(output[2][1]))
        self.assertTrue(math.isfinite(output[3][1]))

    def test_hysteresis(self):
        self.check_injection(faults.hysteresis,
                             [(100, 10), (110, 13), (120, 15), (130, 11), (140, 15)],
                             rising_offset=1, falling_offset=-2)

    def test_clock_jump(self):
        self.check_injection(faults.clock_jump,
                             [(100, 10), (140, 12), (150, 14), (160, 13), (140, 15)],
                             seconds=30)

    def test_clock_reset(self):
        self.check_injection(faults.clock_reset,
                             [(100, 10), (80, 12), (90, 14), (100, 13), (140, 15)],
                             seconds=30)

    def test_spikes_have_seeded_point_truth(self):
        original = self.series.copy()
        expected = [(100, 10), (110, 17), (120, 19), (130, 13), (140, 15)]
        result = faults.spikes(self.series, **self.window, count=2, size=5)
        self.assertEqual(result, (expected, [(110, 110, 'spikes'), (120, 120, 'spikes')]))
        self.assertEqual(faults.spikes(self.series, **self.window, count=2, size=5), result)
        self.assertEqual(self.series, original)

    def test_flatline(self):
        expected = [(100, 10), (110, 12), (120, 12), (130, 12), (140, 15)]
        self.check_injection(faults.flatline, expected)

    def test_flatline_preserves_source_gaps(self):
        series = [(100, 10), (110, None), (120, 12)]
        output, _ = faults.flatline(series, start=0, end=20)
        self.assertEqual(output, [(100, 10), (110, None), (120, 10)])

    def test_flatline_starts_at_first_value_and_preserves_nan_gaps(self):
        series = [(100, None), (110, 12), (120, float('nan')), (130, 13)]
        output, _ = faults.flatline(series, start=0, end=30)
        self.assertIsNone(output[0][1])
        self.assertEqual(output[1][1], 12)
        self.assertTrue(math.isnan(output[2][1]))
        self.assertEqual(output[3][1], 12)

    def test_dropout(self):
        expected = [(100, 10), (110, None), (120, None), (130, None), (140, 15)]
        self.check_injection(faults.dropout, expected)

    def test_front_steps_two_fields_with_one_trap_label(self):
        companion = [(t, value + 20) for t, value in self.series]
        (primary, linked), truth = traps.front(self.series, companion, **self.window, bias=3)
        self.assertEqual(primary, [(100, 10), (110, 15), (120, 17), (130, 16), (140, 15)])
        self.assertEqual(linked, [(100, 30), (110, 35), (120, 37), (130, 36), (140, 35)])
        self.assertEqual(truth, [(110, 130, 'trap')])
        self.assertEqual(companion, [(t, value + 20) for t, value in self.series])

    def test_turn_is_smooth_and_wraps_heading(self):
        heading = [(100, 340), (110, 350), (115, 347), (120, 344), (130, 342), (140, 341)]
        output, truth = traps.turn(heading, **self.window, degrees=40)
        self.assertEqual(output, [(100, 340), (110, 350), (115, 369.5 % 360),
                                  (120, 24), (130, 342), (140, 341)])
        self.assertEqual(truth, [(110, 130, 'trap')])

    def test_turn_preserves_source_gaps_and_recovers_at_boundary(self):
        heading = [(0, 300), (1, 310), (2, None), (3, 320), (4, 318)]
        output, _ = traps.turn(heading, start=1, end=3, degrees=145)
        self.assertEqual(output[2], (2, None))
        self.assertEqual(output[3], (3, 320))
        self.assertEqual(output[4], (4, 318))
