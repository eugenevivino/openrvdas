#!/usr/bin/env python3

import math
import sys
import unittest

sys.path.append('.')
from logger.utils.das_record import DASRecord  # noqa: E402
from contrib.deepsignal.logger.transforms.vector_wind_average_transform import (  # noqa: E402
    VectorWindAverageTransform, vector_wind_statistics)

WIND = {'speed_field': 'WindSpeed', 'direction_field': 'WindDir'}
ALL_STATS = ['speed', 'direction', 'scalar_speed', 'max_speed',
             'steadiness', 'direction_std_dev', 'count']


def rec(timestamp, speed=None, direction=None, **extra):
    fields = dict(extra)
    if speed is not None:
        fields['WindSpeed'] = speed
    if direction is not None:
        fields['WindDir'] = direction
    return {'timestamp': timestamp, 'fields': fields}


def run(transform, records):
    """Feed records one at a time; return all output records in order."""
    out = []
    for record in records:
        result = transform.transform(record)
        if result:
            out.extend(result)
    return out


def angle_diff(a, b):
    """Smallest difference between two angles in degrees."""
    return abs((a - b + 180) % 360 - 180)


################################################################################
class TestVectorWindStatistics(unittest.TestCase):

    def stats(self, pairs, calm_speed=0):
        return vector_wind_statistics(
            [(speed, math.radians(direction)) for speed, direction in pairs], calm_speed)

    def test_359_and_1_average_to_0_not_180(self):
        s = self.stats([(10, 359), (10, 1)])
        self.assertLess(angle_diff(s['direction'], 0), 1e-9)
        self.assertAlmostEqual(s['speed'], 10 * math.cos(math.radians(1)))
        self.assertAlmostEqual(s['scalar_speed'], 10)

    def test_direction_stays_in_0_to_360(self):
        s = self.stats([(5, 350), (5, 340)])
        self.assertAlmostEqual(s['direction'], 345)
        s = self.stats([(5, -10), (5, 370)])  # out-of-range input still works
        self.assertLess(angle_diff(s['direction'], 0), 1e-9)
        self.assertGreaterEqual(s['direction'], 0)
        self.assertLess(s['direction'], 360)

    def test_speed_weighting(self):
        # A strong east wind outweighs a weak west one
        s = self.stats([(9, 90), (1, 270)])
        self.assertAlmostEqual(s['direction'], 90)
        self.assertAlmostEqual(s['speed'], 4)
        self.assertAlmostEqual(s['scalar_speed'], 5)
        self.assertAlmostEqual(s['steadiness'], 0.8)
        self.assertEqual(s['max_speed'], 9)
        self.assertEqual(s['count'], 2)

    def test_large_finite_speeds_have_finite_means(self):
        for direction in (0, 45, 90, 180, 270):
            with self.subTest(direction=direction):
                s = self.stats([(1e308, direction), (1e308, direction)])
                self.assertTrue(math.isfinite(s['speed']))
                self.assertAlmostEqual(s['speed'] / 1e308, 1)
                self.assertEqual(s['scalar_speed'], 1e308)
                self.assertAlmostEqual(s['steadiness'], 1)
                self.assertLess(angle_diff(s['direction'], direction), 1e-9)

    def test_opposing_winds_have_no_direction(self):
        s = self.stats([(10, 0), (10, 180)])
        self.assertIsNone(s['direction'])
        self.assertAlmostEqual(s['speed'], 0)
        self.assertAlmostEqual(s['steadiness'], 0)
        s = self.stats([(10, 45), (10, 225)])
        self.assertIsNone(s['direction'])

    def test_all_calm(self):
        s = self.stats([(0, 120), (0, 300)])
        self.assertIsNone(s['direction'])
        self.assertIsNone(s['steadiness'])
        self.assertIsNone(s['direction_std_dev'])  # calm samples have no direction
        self.assertEqual(s['speed'], 0)

    def test_calm_speed_threshold(self):
        pairs = [(0.3, 10), (0.1, 190)]  # mean vector 0.1 toward 10 degrees
        self.assertAlmostEqual(self.stats(pairs)['direction'], 10)
        self.assertIsNone(self.stats(pairs, calm_speed=0.5)['direction'])

    def test_steady_wind(self):
        s = self.stats([(7, 200)] * 5)
        self.assertAlmostEqual(s['direction'], 200)
        self.assertAlmostEqual(s['steadiness'], 1)
        self.assertAlmostEqual(s['direction_std_dev'], 0, places=5)

    def test_direction_std_dev_wraps(self):
        # Spread around north is as small as the same spread around south
        north = self.stats([(5, 350), (5, 10)])['direction_std_dev']
        south = self.stats([(5, 170), (5, 190)])['direction_std_dev']
        self.assertAlmostEqual(north, south)
        self.assertLess(north, 15)

    def test_yamartino_matches_known_two_and_three_angle_values(self):
        # 0, 90: mean sine = mean cosine = 1/2, epsilon = sqrt(1 - 1/2).
        # 0, 90, 180: mean sine = 1/3, mean cosine = 0, epsilon = sqrt(1 - 1/9).
        for angles, epsilon in (((0, 90), math.sqrt(0.5)),
                                ((0, 90, 180), math.sqrt(8 / 9))):
            with self.subTest(angles=angles):
                expected = math.degrees(
                    math.asin(epsilon) * (1 + (2 / math.sqrt(3) - 1) * epsilon ** 3))
                actual = self.stats([(5, angle) for angle in angles])['direction_std_dev']
                self.assertAlmostEqual(actual, expected, places=10)


################################################################################
class TestVectorWindAverageTransform(unittest.TestCase):

    def test_fractional_interval_epoch_boundaries_do_not_drift(self):
        t = VectorWindAverageTransform(winds=[WIND], window=1, interval=0.1)
        first_k = 17000000000
        self.assertIsNone(t.transform(rec(1700000000 - 0.05, 10, 0)))
        for k in range(first_k, first_k + 200):
            boundary = round(k * 0.1, 9)
            with self.subTest(k=k):
                self.assertIsNone(t.transform(rec(math.nextafter(boundary, -math.inf), 10, 0)))
                self.assertIsNone(t.transform(rec(boundary, 10, 0)))
                out = t.transform(rec(math.nextafter(boundary, math.inf), 10, 0))
                self.assertIsNotNone(out)
                self.assertEqual([r['timestamp'] for r in out], [boundary])

    def test_block_average(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10)
        out = run(t, [rec(100, 10, 359), rec(105, 10, 1), rec(110, 10, 3),
                      rec(115, 10, 5), rec(120.5, 4, 90)])
        # Windows end on multiples of 10: (90, 100], (100, 110], (110, 120]
        self.assertEqual([r['timestamp'] for r in out], [100, 110, 120])
        self.assertLess(angle_diff(out[0]['fields']['AvgWindDir'], 359), 1e-9)
        self.assertAlmostEqual(out[1]['fields']['AvgWindDir'], 2)  # 1 and 3
        self.assertAlmostEqual(out[2]['fields']['AvgWindDir'], 5)
        self.assertEqual(set(out[1]['fields']), {'AvgWindSpeed', 'AvgWindDir'})

    def test_waits_for_window_to_close(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10)
        self.assertIsNone(t.transform(rec(101, 10, 0)))
        self.assertIsNone(t.transform(rec(110, 10, 0)))  # sample at 110 belongs to (100, 110]
        out = t.transform(rec(110.1, 10, 0))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['timestamp'], 110)
        stats = VectorWindAverageTransform(winds=[dict(WIND, statistics=['count'])], window=10)
        out = run(stats, [rec(101, 10, 0), rec(110, 10, 0), rec(110.1, 10, 0)])
        self.assertEqual(out[0]['fields'], {'AvgWindSpeedCount': 2})

    def test_running_average(self):
        t = VectorWindAverageTransform(winds=[dict(WIND, statistics=['count'])],
                                       window=10, interval=5)
        out = run(t, [rec(ts, 5, 90) for ts in range(100, 131)])
        # Every 5 s, each covering 10 one-second samples once warmed up
        self.assertEqual([r['timestamp'] for r in out], [100, 105, 110, 115, 120, 125])
        self.assertEqual([r['fields']['AvgWindSpeedCount'] for r in out],
                         [1, 6, 10, 10, 10, 10])

    def test_min_count_reports_thin_window_as_missing(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10, min_count=3)
        out = run(t, [rec(101, 5, 10), rec(102, 5, 10), rec(103, 5, 10),
                      rec(111, 5, 20),
                      rec(121, 5, 30), rec(122, 5, 30), rec(123, 5, 30), rec(131, 1, 0)])
        self.assertEqual([r['timestamp'] for r in out], [110, 130])

    def test_per_wind_min_count(self):
        winds = [dict(WIND, min_count=1),
                 {'speed_field': 'S2', 'direction_field': 'D2', 'min_count': 2}]
        t = VectorWindAverageTransform(winds=winds, window=10, min_count=5)
        out = run(t, [rec(101, 5, 10, S2=3, D2=50), rec(111, 1, 0)])
        self.assertEqual(set(out[0]['fields']), {'AvgWindSpeed', 'AvgWindDir'})

    def test_missing_and_bad_values_are_skipped_not_filled(self):
        t = VectorWindAverageTransform(winds=[dict(WIND, statistics=['count', 'speed'])],
                                       window=10)
        records = [rec(101, 10, 90),
                   rec(102, None, 90),             # speed missing
                   rec(103, 10, None),             # direction missing
                   rec(104, float('nan'), 90),
                   rec(105, 10, float('inf')),
                   rec(106, -3, 90),               # negative speed
                   rec(107, '10', 90),             # string
                   rec(108, True, 90),             # bool
                   rec(109, 20, 90),
                   rec(111, 1, 1)]
        out = run(t, records)
        self.assertEqual(out[0]['fields'], {'AvgWindSpeedCount': 2, 'AvgWindSpeed': 15})

    def test_speed_and_direction_must_share_a_record(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10)
        out = run(t, [rec(101, speed=10), rec(102, direction=90), rec(111, 1, 1)])
        self.assertEqual(out, [])

    def test_gap_produces_no_records(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10)
        out = run(t, [rec(101, 10, 90), rec(102, 10, 90),
                      rec(100000.5, 10, 180), rec(100011, 10, 180)])
        self.assertEqual([r['timestamp'] for r in out], [110, 100010])
        self.assertAlmostEqual(out[1]['fields']['AvgWindDir'], 180)

    def test_unrelated_records_advance_time(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10)
        out = run(t, [rec(101, 10, 90), rec(115, Temp=12.5)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['timestamp'], 110)
        self.assertNotIn('Temp', out[0]['fields'])

    def test_late_record_lands_in_open_window_only(self):
        t = VectorWindAverageTransform(winds=[dict(WIND, statistics=['count'])],
                                       window=10, interval=5)
        out = run(t, [rec(101, 1, 0), rec(106, 1, 0),
                      rec(104, 1, 0),   # late: (95, 105] already went out, (100, 110] is open
                      rec(89, 1, 0),    # too old for any open window: dropped
                      rec(111, 1, 0)])
        counts = {r['timestamp']: r['fields']['AvgWindSpeedCount'] for r in out}
        self.assertEqual(counts, {105: 1, 110: 3})

    def test_late_sample_logs_exclusion_from_closed_windows(self):
        t = VectorWindAverageTransform(winds=[dict(WIND, statistics=['count'])],
                                       window=10, interval=5)
        out = run(t, [rec(101, 1, 0), rec(106, 1, 0)])
        self.assertEqual(out[0]['timestamp'], 105)
        self.assertEqual(out[0]['fields'], {'AvgWindSpeedCount': 1})
        with self.assertLogs(level='DEBUG') as logs:
            self.assertIsNone(t.transform(rec(104, 1, 0)))
        self.assertTrue(all(entry.levelname == 'DEBUG' for entry in logs.records))
        self.assertIn('104', ' '.join(logs.output))
        self.assertIn('105', ' '.join(logs.output))
        self.assertIn('left out of closed window(s)', ' '.join(logs.output))
        out = t.transform(rec(111))
        self.assertEqual(out[0]['timestamp'], 110)
        self.assertEqual(out[0]['fields'], {'AvgWindSpeedCount': 3})

    def test_timestamps_never_rewritten_and_record_type_kept(self):
        t = VectorWindAverageTransform(winds=[WIND], window=60, data_id='met_avg')
        records = [DASRecord(data_id='mwx1', timestamp=ts, fields={'WindSpeed': 5, 'WindDir': 270})
                   for ts in (1700000001.5, 1700000030.25, 1700000061)]
        out = run(t, records)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], DASRecord)
        self.assertEqual(out[0].timestamp, 1700000040)  # whole minute, from the data clock
        self.assertEqual(out[0].data_id, 'met_avg')
        self.assertAlmostEqual(out[0].fields['AvgWindDir'], 270)
        # Inputs untouched
        self.assertEqual(records[0].timestamp, 1700000001.5)

    def test_list_and_none_input(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10)
        self.assertIsNone(t.transform(None))
        out = t.transform([rec(101, 10, 0), rec(105, 10, 0), rec(111, 1, 1)])
        self.assertEqual(len(out), 1)
        self.assertIsNone(t.transform({'fields': {'WindSpeed': 1, 'WindDir': 1}}))

    def test_two_winds_and_custom_names(self):
        winds = [dict(WIND, prefix='Avg1m', statistics=ALL_STATS),
                 {'speed_field': 'StbdSpeed', 'direction_field': 'StbdDir',
                  'names': {'speed': 'StbdMean', 'direction': 'StbdMeanDir'}}]
        t = VectorWindAverageTransform(winds=winds, window=10)
        out = run(t, [rec(101, 10, 350, StbdSpeed=4, StbdDir=10),
                      rec(102, 10, 10, StbdSpeed=4, StbdDir=10),
                      rec(111, 1, 1)])
        self.assertEqual(set(out[0]['fields']), {
            'Avg1mWindSpeed', 'Avg1mWindDir', 'Avg1mWindSpeedScalar',
            'Avg1mWindSpeedMax', 'Avg1mWindSpeedSteadiness', 'Avg1mWindDirStdDev',
            'Avg1mWindSpeedCount', 'StbdMean', 'StbdMeanDir'})
        self.assertAlmostEqual(out[0]['fields']['StbdMeanDir'], 10)

    def test_calm_window_reports_speed_without_direction(self):
        t = VectorWindAverageTransform(winds=[WIND], window=10)
        out = run(t, [rec(101, 0, 45), rec(102, 0, 300), rec(111, 1, 1)])
        self.assertEqual(out[0]['fields'], {'AvgWindSpeed': 0})

    def test_bad_configs_fail_at_load(self):
        bad = [dict(winds=[]),
               dict(winds=[{'speed_field': 'S'}]),
               dict(winds=[dict(WIND, statistics=['median'])]),
               dict(winds=[dict(WIND, names={'gust': 'G'})]),
               dict(winds=[dict(WIND, colour='red')]),
               dict(winds=[dict(WIND, names={'speed': 'X', 'direction': 'X'})]),
               dict(winds=[dict(WIND, min_count=0)]),
               dict(winds=[WIND], window=0),
               dict(winds=[WIND], interval=-1),
               dict(winds='WindSpeed')]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    VectorWindAverageTransform(**kwargs)

    def test_output_names_must_be_unique_across_winds(self):
        other = {'speed_field': 'OtherSpeed', 'direction_field': 'OtherDir'}
        for second in (WIND, dict(other, direction_field='WindDir'),
                       dict(other, names={'speed': 'AvgWindDir'})):
            with self.subTest(second=second):
                with self.assertRaises(ValueError):
                    VectorWindAverageTransform(winds=[WIND, second])

    def test_window_and_interval_reject_nonfinite_and_bool(self):
        for key in ('window', 'interval'):
            for value in (float('nan'), float('inf'), -float('inf'), True, False):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        VectorWindAverageTransform(winds=[WIND], **{key: value})

    def test_calm_speed_requires_finite_nonnegative_number(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, False,
                      -1, -0.1, '1', None, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    VectorWindAverageTransform(winds=[WIND], calm_speed=value)
        for value in (0, 0.0, 0.1, 1):
            with self.subTest(valid_value=value):
                t = VectorWindAverageTransform(winds=[WIND], calm_speed=value, window=10)
                out = run(t, [rec(101, value, 90), rec(111)])
                self.assertEqual(out[0]['fields'], {'AvgWindSpeed': value})

    def test_names_values_must_be_nonempty_strings(self):
        for stat in ('speed', 'count'):  # Check selected and unselected overrides.
            for value in ('', None, 0, 1.5, True, [], {}):
                with self.subTest(stat=stat, value=value):
                    with self.assertRaises(ValueError):
                        VectorWindAverageTransform(winds=[dict(WIND, names={stat: value})])


if __name__ == '__main__':
    unittest.main()
