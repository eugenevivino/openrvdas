"""Regressions for the final independent review, in finding order."""

import csv
import json
import math
from pathlib import Path
import random
from statistics import median
import tempfile
import unittest
from unittest.mock import patch

from contrib.deepsignal.coupling import archive, atlas, prep, stats
from contrib.deepsignal.coupling.bench_injectors import heading_coupled_bias
from contrib.deepsignal.coupling.transform import ShipCouplingTransform
from contrib.deepsignal.test.coupling.test_review import CFG, ROOT, legs


class RoundTwoTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def live(self):
        return ShipCouplingTransform(ROOT / 'coupling/sample_atlas.json')

    def test_01_offset_tracks(self):
        a, b = legs(340, 0), legs(410, 1500000)
        for rng, rows in ((random.Random(12), a), (random.Random(17), b)):
            for i, r in enumerate(rows):
                sign = 1 if r['heading'] == 0 else -1
                sample = i % 12
                r.update(latitude=.004 * sign, heading=90 if sign == 1 else 270, direction=90,
                         longitude=-30 + sign * (sample - (4 if sample < 9 else 10)) * .0069)
                r['temp'] = 125 * r['latitude'] + .08 * math.sin(i / 12) + rng.gauss(0, .025)
        h, = atlas.discover(a, b, dict(CFG, ship_variables=['relative_heading_cos'],
                                       bin_seconds=300, median_minutes=1500))['hypotheses']
        self.assertEqual(h['status'], 'confirmed')
        self.assertEqual(h['reciprocal_pairs'].get('ship_artifact', 0), 0)
        self.assertEqual(h['invariance'], 'cannot_tell')

    def test_02_single_shift(self):
        def noise(seed):
            rng = random.Random(seed)
            return [dict(temp=rng.gauss(0, 1), v=math.sin(i * 2 * math.pi / 60), regime='transit')
                    for i in range(96)]
        h, = atlas.discover(noise(4), noise(11), dict(fields=['temp'], ship_variables=['v'])
                            )['hypotheses']
        self.assertEqual((h['min_shift'], h['holdout']['min_shift']), (48, 48))
        self.assertEqual((h['p'], h['holdout']['p'], h['status']), (.5, .5, 'rejected'))
        self.assertEqual((h['shift_reps'], h['holdout']['shift_reps']), (1, 1))

    def test_03_heading_ties(self):
        rows = [dict(relative_heading=a) for a in (90, 270, 30, 330, 150)]
        values = prep.prepare(rows, {})
        self.assertEqual([r['relative_heading_cos'] for r in values[:2]], [0, 0])
        self.assertEqual(values[2]['relative_heading_cos'], values[3]['relative_heading_cos'])
        self.assertEqual(values[2]['relative_heading_sin'], values[4]['relative_heading_sin'])

    def test_04_delayed_calibration(self):
        a, b = legs(340, 0), legs(410, 1500000)
        for rows in (a, b):
            for i in reversed(range(len(rows))):
                rows[i]['temp'] = rows[i-12]['temp'] if i >= 12 else None
        config = dict(CFG, ship_variables=['relative_heading_cos'], lags=[-12, 0],
                      bin_seconds=300, median_minutes=1500, reciprocal_km=.15)
        result = atlas.discover(a, b, config)
        h, = result['hypotheses']
        self.assertEqual((h['status'], h['invariance'], h['lag']), ('confirmed', 'ship_artifact',
                                                                    -12))
        expected = {0: [], 6: []}
        for split in (a, b):
            # Reconstruct the offline centering window and pair each value to the earlier heading.
            values = [row['temp'] for row in split]
            radius = 1500 * 60 // 300 // 2
            for i in range(12, len(values)):
                window = values[max(12, i-radius):i+radius+1]
                sector = 0 if split[i-12]['heading'] == 0 else 6
                expected[sector].append(values[i] - median(window))
        for cell in result['polar']['temp']:
            self.assertAlmostEqual(cell['median'], median(expected[cell['sector']]))
        self.assertEqual(sum(r['count'] for r in result['polar']['temp']),
                         h['pairs'] + h['holdout']['pairs'])
        path = self.tmp / 'atlas.json'
        path.write_text(json.dumps(result))
        live = ShipCouplingTransform(path)
        for i in range(13):
            out = live.transform(dict(timestamp=300*i, relative_heading=0 if i == 0 else 180,
                                      sog=5, temp=1))
            if i < 12:
                self.assertEqual(out['temp_SHIP_QC'], 2)
        self.assertEqual(out['temp_SHIP_QC'], 3)
        self.assertIn('sector 0,', out['temp_SHIP_why'])

    def test_05_effective_floor(self):
        rows = [dict(temp=.5 * math.cos(i/12), v=math.cos(i/12), regime='transit')
                for i in range(240)]
        h, = atlas.discover(rows[:120], rows[120:], dict(CFG, min_n_eff=2))['hypotheses']
        self.assertTrue(all(fit['n_eff'] < 30 for fit in (h, h['holdout'])))
        self.assertEqual((h['status'], h['p'], h['holdout']['p']), ('insufficient', None, None))

    def test_06_constant_bootstrap(self):
        x = list(range(100))
        random.Random(8).shuffle(x)
        y = [int(i in (25, 75)) for i in range(100)]
        fit = atlas._evaluate([dict(x=a, y=b) for a, b in zip(x, y)], 'x', 'y', {'max_lag': 1}, 78)
        expected = stats.circular_shift_pvalue(x, y, stats.spearman, 500, fit['min_shift'], 78)
        self.assertIsNotNone(expected)
        self.assertEqual(fit['p'], expected)
        self.assertFalse(fit['insufficient'])

    def test_07_empty_cruise(self):
        rng = random.Random(78)
        rows = [dict(cruise='A', timestamp=i*10, temp=v, v=v, regime='transit')
                for i in range(100) for v in [rng.random()]]
        a, = atlas.discover(rows, rows, CFG)['hypotheses']
        b, = atlas.discover(rows + [dict(cruise='B', timestamp=1000)], rows, CFG)['hypotheses']
        self.assertEqual(a['status'], 'confirmed')
        for key in ('effect', 'p', 'n_eff', 'ci', 'status'):
            self.assertEqual(a[key], b[key])

    def test_08_irregular_grid(self):
        for first, second, status in [(1, 4, 'confirmed'), (4, 0, 'discovery_only')]:
            fit = dict(effect=.8, p=.01, insufficient=False)
            h = dict(fit, family='met', lag=first, holdout=dict(fit, lag=second))
            atlas._correct([h], dict(method='bh', q=.05, lags=[4, 0, 1]))
            self.assertEqual(h['status'], status)

    def test_09_split_maneuver(self):
        live = self.live()
        live.transform(dict(timestamp=10, sog=3, heading=0, relative_heading=0))
        live.transform(dict(timestamp=20, sog=4))
        out = live.transform(dict(timestamp=20, heading=0, air_temperature=1))
        self.assertEqual(out['air_temperature_SHIP_QC'], 2)

    def test_10_late_heading(self):
        live = self.live()
        live.transform(dict(timestamp=30, heading=180, direction=0, sog=3))
        live.transform(dict(timestamp=20, heading=0))
        out = live.transform(dict(timestamp=40, air_temperature=1))
        self.assertEqual(out['air_temperature_SHIP_QC'], 2)
        self.assertEqual(live.state['heading'], 180)

    def test_11_sector_agreement(self):
        for fields, sector in [({'relative_heading': 240}, 8),
                               (dict(relative_heading=0, direction=180, heading=0), 0)]:
            with self.subTest(fields=fields):
                live = self.live()
                row = dict(fields, sog=3)
                offline, = prep.prepare([row], live.config)
                live.transform(row)
                self.assertEqual(prep.polar_cell(offline, live.config),
                                 prep.polar_cell(live.state, live.config))
                self.assertEqual(prep.polar_cell(offline, live.config)[0], sector)

    def test_12_pearson_shift_statistic(self):
        x = [0, 1, 2, 3, 4, 30, 3, 2, 1, 0]
        y = [3, 8, 5, 100, 4, 1, 3, 7, 1, 0]
        for lags in ([0], [-1, 0, 2]):
            def maximum(values):
                return max(abs(stats.pearson(*stats.aligned(x, values, lag)[:2])) for lag in lags)
            p = (1 + sum(maximum(y[k:] + y[:k]) >= maximum(y) for k in range(1, 10))) / 10
            self.assertEqual(stats.circular_shift_pvalue(x, y, stats.pearson, 99, 1, 78, lags), p)

    def test_13_pearson_scale(self):
        for scale in (1e100, 1e307, 1e-300):
            x = [i * scale for i in (1, 2, 3)]
            self.assertAlmostEqual(stats.pearson(x, x), 1)
            self.assertAlmostEqual(stats.pearson(x, x[::-1]), -1)

    def test_14_bounded_grid(self):
        # Catch accidental allocation before the original loop can consume gigabytes.
        with patch.object(prep, 'range', side_effect=AssertionError('started dense grid')):
            with self.assertRaisesRegex(ValueError, 'bin'):
                prep.prepare([dict(timestamp=0), dict(timestamp=365*86400)], {})

    def write(self, fields, rows, holdout):
        result = atlas.discover(rows, holdout, dict(CFG, fields=fields, output_dir=str(self.tmp)))
        result['unparseable_lines'] = 0
        archive.write_atlas(result, [])
        return result

    def coupled(self, n, cruise, sign=1):
        rng = random.Random(n)
        return [dict(timestamp=i*10, cruise=cruise, v=v, temp=sign*v, sog=3, relative_heading=0)
                for i in range(n) for v in [rng.random()]]

    def test_15_stale_polar(self):
        rows = self.coupled(120, 'A')
        path = self.tmp / 'polar_temp.csv'
        unrelated = self.tmp / 'polar_unrelated.csv'
        unrelated.write_text('external')
        for fields in (['temp'], []):
            self.write(['temp'], rows, rows)
            self.assertTrue(path.exists())
            self.write(fields, rows[:4], rows[:4])
            self.assertFalse(path.exists())
            self.assertEqual(unrelated.read_text(), 'external')

    def test_16_truth_on_changes(self):
        series = [(t, 0) for t in range(5)]
        out, truth = heading_coupled_bias(series, [0, 90, 180, 270, 0], 2)
        self.assertEqual(out, [(0, 2), (1, 0), (2, -2), (3, 0), (4, 2)])
        self.assertEqual(truth, [(t, t, 'heading_coupled_bias') for t in (0, 2, 4)])
        self.assertEqual(heading_coupled_bias(series, [0]*5, 0)[1], [])
        self.assertEqual(heading_coupled_bias([(0, 1e100)], [0], 2)[1], [])

    def test_17_reported_fits(self):
        result = self.write(['temp'], self.coupled(140, 'A'),
                            self.coupled(360, 'B') + self.coupled(80, 'C', -1))
        h, = result['hypotheses']
        self.assertEqual(h['status'], 'confirmed')
        md = (self.tmp / 'atlas.md').read_text().lower()
        self.assertIn('replicated on 1 of 2 holdout cruises', md)
        with (self.tmp / 'polar_temp.csv').open() as stream:
            cell = next(csv.DictReader(stream))
        for name, fit in [('discovery', h), ('holdout', h['holdout'])]:
            for key in ('block', 'min_shift'):
                self.assertEqual(int(cell[f'{name}_{key}']), fit[key])
                self.assertIn(f'{key} {fit[key]}', md)
