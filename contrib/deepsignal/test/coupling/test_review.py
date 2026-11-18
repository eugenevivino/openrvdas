"""One regression per ranked finding in the independent review, in review order."""

import copy
import csv
import json
import math
import os
from pathlib import Path
import random
from statistics import median
import tempfile
import unittest
from unittest.mock import patch

import yaml

from contrib.deepsignal.coupling import atlas, prep, stats
from contrib.deepsignal.coupling.bench_injectors import heading_coupled_bias
from contrib.deepsignal.coupling.transform import ShipCouplingTransform


ROOT = Path('contrib/deepsignal')
CFG = {'fields': ['temp'], 'ship_variables': ['v'], 'bootstrap_reps': 25, 'reps': 99}


def legs(seed, origin):
    rng = random.Random(seed)
    rows = []
    for site in range(360):
        earth = rng.choice([-1, 1])
        for sign in (earth, -earth):
            for _ in range(9 if sign == earth else 3):
                t = len(rows) * 300
                background = .08 * math.sin(t / 3600)
                noise = rng.gauss(0, .025)
                rows.append(dict(timestamp=origin + t, heading=0 if sign == 1 else 180,
                                 direction=0, sog=5, latitude=earth * .001,
                                 longitude=-30 + site * .003,
                                 temp=background + .5 * sign + noise,
                                 ocean=background + earth + noise))
    return rows


class ReviewTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)

    def live(self, verdict='ship_artifact', **kwargs):
        table = [dict(sector=2, speed_band=band, regime='transit', median=value, iqr=.1)
                 for band, value in [(1, .6), (2, 1.4)]]
        data = dict(parameters=dict(sectors=4, speed_bands=[1, 5]),
                    healthy_spread={'temp': 2}, polar={'temp': table},
                    hypotheses=[dict(field='temp', regime='transit', ship_variable='v',
                                     status='confirmed', invariance=verdict)])
        path = self.tmp / 'atlas.json'
        path.write_text(json.dumps(data))
        return ShipCouplingTransform(path, **kwargs)

    def test_review_1_invariance(self):
        rng = random.Random(78)
        bare = [dict(relative_heading_cos=v, temp=v, regime='transit')
                for v in (rng.random() for _ in range(100))]
        h = atlas.discover(bare, bare, dict(CFG, ship_variables=['relative_heading_cos']))[
            'hypotheses'][0]
        self.assertEqual((h['status'], h['invariance']), ('confirmed', 'cannot_tell'))
        config = dict(CFG, fields=['temp', 'ocean'], ship_variables=['relative_heading_cos'],
                      bin_seconds=300, median_minutes=1500, reciprocal_km=.15)
        first, second = legs(340, 0), legs(410, 1500000)
        result = atlas.discover(first, second, config)
        ship, ocean = result['hypotheses']
        self.assertEqual([ship['status'], ocean['status']], ['confirmed'] * 2)
        self.assertEqual([ship['invariance'], ocean['invariance']],
                         ['ship_artifact', 'environmental'])
        for shift in ('12h', '24h'):
            self.assertLess(abs(ship['time_shift'][shift]), .2)
        # Each independent split also loses the association after either physical clock shift.
        for name, rows in [('discovery', first), ('holdout', second)]:
            grid = prep.prepare(rows, config)
            for hours in (12, 24):
                offset = hours * 12  # 300 s bins
                expected = stats.spearman([r['temp_residual'] for r in grid[offset:]],
                                          [r['relative_heading_cos'] for r in grid[:-offset]])
                self.assertAlmostEqual(ship['time_shift_by_split'][name][f'{hours}h'], expected)
                self.assertLess(abs(expected), .2)
        # Enough reciprocal legs but less than a day of data cannot clear both controls.
        short = atlas.discover(first[:240], second[:240], config)['hypotheses'][0]
        self.assertEqual(short['status'], 'confirmed')
        self.assertGreaterEqual(short['reciprocal_pairs']['ship_artifact'], 2)
        self.assertIsNone(short['time_shift']['24h'])
        self.assertEqual(short['invariance'], 'cannot_tell')
        for row in first + second:
            row.pop('latitude')
        self.assertEqual(atlas.discover(first, second, config)['hypotheses'][0]['invariance'],
                         'cannot_tell')
        # Exact daily repetition keeps the 24 h control coupled.
        periodic = [dict(first[i % 288], timestamp=i * 300,
                         latitude=(i % 288 // 12) / 100) for i in range(1152)]
        h = atlas.discover(periodic, [dict(r, timestamp=r['timestamp'] + 432000)
                                      for r in periodic], config)['hypotheses'][0]
        self.assertGreater(abs(h['time_shift']['24h']), .8)
        self.assertNotEqual(h['invariance'], 'ship_artifact')

    def test_review_2_sample_splits(self):
        config = yaml.safe_load((ROOT / 'configs/ship_coupling_atlas.yaml').read_text())
        result = atlas.run(dict(config, output_dir=str(self.tmp)))
        self.assertGreaterEqual(result['parameters'].get('min_n_eff', 30), 30)
        self.assertTrue(all(h['status'] != 'confirmed' for h in result['hypotheses']))
        # Compare split counts to independent timestamps from the bundled MET stream.
        met = Path('test/NBP1406/mwx1/raw/NBP1406_mwx1-2014-08-01').read_text().splitlines()
        for name, bounds in config['splits'].items():
            bins = {int(prep.timestamp(line.split()[0]) // 10) for line in met
                    if ' MET,' in line and bounds['start'] <= line.split()[0] < bounds['end']}
            self.assertEqual(result['splits'][name]['field_bins']['air_temperature'], len(bins))
        with self.assertRaises(ValueError):
            atlas.run(dict(CFG, output_dir=str(self.tmp)))
        rows = [dict(cruise=c, timestamp=i, temp=i, v=i, regime='transit')
                for c in ('A', 'B') for i in range(5)]
        path = self.tmp / 'input.csv'
        with path.open('w') as stream:
            writer = csv.DictWriter(stream, rows[0])
            writer.writeheader()
            writer.writerows(rows)
        config = dict(CFG, input_csv=str(path), output_dir=str(self.tmp), bin_seconds=1,
                      splits={'discovery': {'cruises': ['A']}, 'holdout': {'cruises': ['B']}})
        self.assertEqual(atlas.run(config)['splits']['holdout']['field_bins']['temp'], 5)

    def test_review_3_grid_residual_regime(self):
        rows = [dict(timestamp=t, temp=a, v=b, regime='transit')
                for t, a, b in [(0, 2, 8), (1, 6, 6), (10, 8, 1), (30, 2, 2), (40, 10, 3)]]
        config = dict(CFG, median_minutes=.5, lags=[1], regimes=['transit', 'station'])
        grid = prep.prepare(rows, config)
        self.assertEqual([r.get('temp_residual') for r in grid], [-2, 2, None, -4, 4])
        self.assertEqual(grid[0]['v'], 7)
        self.assertIsNone(atlas.discover(rows, rows, config)['hypotheses'][0]['effect'])
        rows.extend(dict(timestamp=i * 10, temp=i, v=i) for i in range(5, 100))
        result = atlas.discover(rows, rows, config)
        self.assertIsNone(result['hypotheses'][1]['effect'])
        config['lags'] = [0]
        self.assertAlmostEqual(atlas.discover(rows[:5], rows[:5], config)['hypotheses'][0]
                               ['effect'], stats.spearman([-2, 2, -4, 4], [7, 1, 2, 3]))

    def test_review_4_nonfinite(self):
        self.assertIsNone(stats.spearman([float('nan')] * 3, [1, 2, 3]))
        self.assertEqual(stats._pairs([1, float('nan'), 3], [2, 3, float('inf')]), [(1, 2)])
        rows = [dict(temp=float('nan'), v=i, regime='transit') for i in range(60)]
        h = atlas.discover(rows, rows, CFG)['hypotheses'][0]
        self.assertEqual((h['p'], h['effect'], h['status']), (None, None, 'insufficient'))

    def test_review_5_effective_size(self):
        self.assertEqual(stats.acf([-1, -1, 1, 1], 1), .25)
        self.assertEqual(stats.n_eff([-1, -1, 1, 1], [-1, 1, -1, 1], 1), 6.4)
        self.assertEqual(stats.n_eff(range(40), [-1, 1] * 20, 1), 2)

    def test_review_6_winning_pairs(self):
        x = [random.Random(i).random() for i in range(80)]
        rows = [dict(x=a, y=b) for a, b in zip(x, [0] + x[:-1])]
        h = atlas._evaluate(rows, 'x', 'y', dict(CFG, lags=[0, 1], max_lag=10), 78)
        self.assertEqual((h['lag'], h['effect'], h['ci']), (1, 1, [1, 1]))
        self.assertEqual(h['n_eff'], stats.n_eff(x[:-1], x[:-1], 10))
        h = atlas._evaluate(rows, 'x', 'y', dict(CFG, lags=[78]), 78)
        self.assertIsNone(h['p'])
        self.assertIsNone(h['effect'])

    def test_review_7_family_fdr(self):
        def evaluate(rows, field, variable, config, seed):
            p = {'temp': .04, 'salt': .9, 'sound': .03 if seed == 78 else .9,
                 'gps': .02, 'course': .9}[field.removesuffix('_residual')]
            return dict(p=p, effect=.8, lag=0, n_eff=50, ci=[.7, .9], insufficient=False)
        families = dict(met_vs_ship=['temp'], ocean_vs_ship=['salt'],
                        acoustic_vs_ship=['sound'], nav_consistency=['gps', 'course'])
        with patch.object(atlas, '_evaluate', evaluate):
            for method in ['bh', 'by']:
                result = atlas.discover([], [], dict(CFG, fields=['temp', 'salt', 'sound', 'gps',
                                                                  'course'],
                                                     families=families, method=method))
                hs = result['hypotheses']
                self.assertEqual([h['family'] for h in hs], [*families, 'nav_consistency'])
                self.assertEqual([h['status'] for h in hs],
                                 ['confirmed', 'rejected', 'discovery_only',
                                  'confirmed' if method == 'bh' else 'rejected', 'rejected'])
                self.assertEqual([h['holdout']['q_pass'] for h in hs],
                                 [True, False, False, method == 'bh', False])

    def test_review_8_insufficient(self):
        for n in (2, 8):
            rows = [dict(temp=i, v=i, regime='transit') for i in range(n)]
            h = atlas.discover(rows, rows, CFG)['hypotheses'][0]
            self.assertEqual((h['status'], h['p']), ('insufficient', None))
            if n == 2:
                self.assertEqual((h['effect'], h['ci'], h['lag']), (None, None, None))

    def test_review_9_regime_units(self):
        rows = [dict(heading=h, sog=s) for h, s in [(359, 4), (2, 4), (5, 4.4),
                                                    (50, 4.4), (50, 5), (50, .5)]]
        grid = prep.prepare(rows, {'bin_seconds': 30})
        self.assertEqual([r['regime'] for r in grid],
                         ['transit', 'transit', 'transit', 'transit', 'maneuver', 'station'])
        self.assertAlmostEqual(grid[1]['heading_rate'], .1)
        self.assertEqual(prep.prepare(rows, {})[3]['regime'], 'maneuver')
        boundary = [dict(sog=3, heading=0), dict(sog=3.5, heading=60)]
        self.assertEqual(prep.prepare(boundary, {'bin_seconds': 30})[1]['regime'], 'transit')

    def test_review_10_polar_cells(self):
        rows = [dict(temp=100, temp_residual=value, relative_heading=angle, sog=s, regime='transit')
                for angle, s, value in [(1, 3, 2), (1, 3, 10), (1, 6, -2), (None, 3, 100)]]
        rows[-1].pop('relative_heading')
        hs = [dict(field='temp', status='confirmed', regime='transit')]
        table = atlas._polar(rows, hs, {'speed_bands': [1, 5], 'sectors': 4})['temp']
        self.assertEqual(sorted((r['sector'], r['speed_band'], r['median'], r['iqr'])
                                for r in table), [(0, 1, 6, 4), (0, 2, -2, 0)])

        # An abrupt turn ends at bin 50. Check its two five-minute windows and the
        # field-wide spread through the same CSV export that the CLI uses.
        rng = random.Random(221)
        track = []
        for cruise in ('A', 'B'):
            for i in range(100):
                v = rng.random()
                track.append(dict(cruise=cruise, timestamp=i * 60, temp=v, v=v, sog=3,
                                  heading=0 if i < 50 else 90, direction=180))
        path = self.tmp / 'turn.csv'
        with path.open('w') as stream:
            writer = csv.DictWriter(stream, track[0])
            writer.writeheader()
            writer.writerows(track)
        config = dict(CFG, input_csv=str(path), output_dir=str(self.tmp), sectors=4,
                      bin_seconds=60, median_minutes=300,
                      splits={'discovery': {'cruises': ['A']}, 'holdout': {'cruises': ['B']}})
        result = atlas.run(config)
        changes = [median(r['temp'] for r in track[k+50:k+55]) -
                   median(r['temp'] for r in track[k+45:k+50]) for k in (0, 100)]
        self.assertEqual(len(result['turn_events']), 2)
        with (self.tmp / 'polar_temp.csv').open() as stream:
            cells = list(csv.DictReader(stream))
        turned = next(r for r in cells if r['sector'] == '1')
        self.assertEqual(int(turned['turn_count']), 2)
        self.assertAlmostEqual(float(turned['turn_median_change']), median(changes))
        self.assertEqual(json.loads(turned['parameters']), result['parameters'])
        self.assertEqual(int(turned['holdout_seed']), result['hypotheses'][0]['holdout']['seed'])
        residuals = [r['temp'] - median(rr['temp'] for rr in track[k:k+100])
                     for k in (0, 100) for r in track[k:k+100]]
        centered = []
        for start in (0, 50):
            cell = residuals[start:start+50] + residuals[start+100:start+150]
            centered.extend(v - median(cell) for v in cell)
        centered.sort()
        # Linear quartiles lie at positions 49.75 and 149.25 in these 200 observations.
        spread = (.75 * centered[149] + .25 * centered[150] -
                  .25 * centered[49] - .75 * centered[50])
        self.assertAlmostEqual(result['healthy_spread']['temp'], spread)

    def test_review_11_live_cells(self):
        live = self.live()
        row = dict(temp=4, relative_heading=225, sog=3, regime='transit')
        for speed, score, qc in [(3, .3, 3), (5, .7, 4)]:
            out = live.transform(dict(row, sog=speed))
            self.assertEqual((out['temp_SHIP'], out['temp_SHIP_QC']), (score, qc))
        self.assertEqual(live.transform(dict(row, regime='maneuver'))['temp_SHIP_QC'], 2)
        path = self.tmp / 'atlas.json'
        calibration = json.loads(path.read_text())
        del calibration['healthy_spread']
        path.write_text(json.dumps(calibration))
        uncalibrated = ShipCouplingTransform(path).transform(row)
        self.assertEqual(uncalibrated['temp_SHIP_QC'], 2)
        self.assertNotIn('temp_SHIP', uncalibrated)

    def test_review_12_missing_live(self):
        live = self.live()
        for field, value, qc in [('temp', None, 9), ('temp', float('nan'), 9),
                                 ('relative_heading', None, 2), ('sog', None, 2)]:
            row = dict(temp=4, relative_heading=225, sog=3, regime='transit')
            row[field] = value
            out = live.transform(row)
            self.assertEqual(out['temp_SHIP_QC'], qc)
            self.assertNotIn('temp_SHIP', out)

    def test_review_13_preserve_annotations(self):
        row = dict(temp=4, relative_heading=225, sog=3, regime='transit',
                   temp_SHIP_QC=9, temp_SHIP=.123, temp_SHIP_why='upstream', raw=b'\x00\xff')
        before = copy.deepcopy(row)
        self.assertEqual(self.live().transform(row), before)
        self.assertEqual(row, before)

    def test_review_14_container_verdict(self):
        row = dict(timestamp=123, fields=dict(temp=4, relative_heading=225,
                                              sog=3, regime='transit'), raw=b'\xff')
        out = self.live().transform(row)
        self.assertEqual(out['fields']['temp_SHIP_QC'], 3)
        self.assertEqual((out['timestamp'], out['raw']), (123, b'\xff'))
        self.assertNotIn('temp_SHIP', row['fields'])
        live = self.live('environmental', min_verdict='environmental')
        self.assertNotIn('temp_SHIP', live.transform(row)['fields'])

    def test_review_15_input_collision(self):
        src = self.tmp / 'input.csv'
        raw = b'timestamp,temp,v,regime\n0,1,2,transit\n10,2,4,transit\n'
        src.write_bytes(raw)
        for name in ['atlas.json', 'atlas.md', 'polar_temp.csv']:
            target = self.tmp / name
            os.link(src, target)
            with self.assertRaises(ValueError):
                atlas.run(dict(CFG, input_csv=str(src), output_dir=str(self.tmp),
                               splits={'discovery': {'start': 0, 'end': 10},
                                       'holdout': {'start': 10, 'end': 20}}))
            self.assertEqual(src.read_bytes(), raw)
            target.unlink()

    def test_review_16_surrogate_defaults(self):
        x = [0, 4, 1, 5, 2, 6, 3, 7]
        # decorrelation lag 1, block 2, sole legal shift 4.
        y = x[4:] + x[:4]
        self.assertEqual(stats.circular_shift_pvalue(x, y, stats.pearson, reps=19), 1)
        self.assertIsNone(stats.circular_shift_pvalue(x[:-1], y[:-1], stats.pearson))
        rows = [dict(x=a, y=b) for a, b in zip(x, y)]
        with patch.object(stats, 'block_bootstrap_ci', wraps=stats.block_bootstrap_ci) as ci:
            atlas._evaluate(rows, 'x', 'y', {'min_n_eff': 2}, 78)
            self.assertEqual(ci.call_args.args[4], 1000)
        constrained = atlas._evaluate(rows, 'x', 'y', {'block': 3, 'min_n_eff': 2}, 78)
        self.assertEqual(constrained['min_shift'], 6)
        self.assertIsNone(constrained['p'])
        # Seeded vector for paired, overlapping moving blocks of length two.
        self.assertEqual(stats.block_bootstrap_ci([1, 2, 4, 8], [8, 4, 1, 2],
                                                  lambda a, b: sum(i * j for i, j in zip(a, b)),
                                                  2, 5, 1), (24, 32))

    def test_review_17_missing_and_csv(self):
        self.assertEqual(prep.rolling_median([None, None, 2], 1), [None, None, 2])
        src = self.tmp / 'input.csv'
        src.write_text('timestamp,temp,v,regime\n1970-01-01T00:00:01Z,2,3,transit\n'
                       'invalid,7,5,transit\n1970-01-01T00:01:00Z,3,5,station\n')
        with self.assertLogs(level='WARNING') as logs:
            result = atlas.run(dict(CFG, input_csv=str(src), output_dir=str(self.tmp),
                                    splits={'discovery': {'start': 0, 'end': 30},
                                            'holdout': {'start': 30, 'end': 90}}))
        self.assertEqual(result['unparseable_lines'], 1)
        self.assertIn('1', ' '.join(logs.output))
        self.assertEqual(result['splits']['discovery']['field_bins']['temp'], 1)

    def test_review_18_bench_contract(self):
        scenarios = yaml.safe_load((ROOT / 'coupling/bench_scenarios.yaml').read_text())
        self.assertEqual(set(scenarios), {'heading-coupled-bias', 'front-trap', 'smooth-turn-trap'})
        self.assertEqual(scenarios['front-trap']['trap'], 'front')
        self.assertEqual(scenarios['smooth-turn-trap']['trap'], 'turn')
        series = [(10, 1), (20, 2), (30, 3), (40, 4)]
        out, truth = heading_coupled_bias(series, [0, 0, 180, 0], 2, start=10, end=20)
        self.assertEqual(out, [(10, 1), (20, 4), (30, 1), (40, 4)])
        self.assertEqual(truth, [(20, 30, 'heading_coupled_bias')])
        self.assertEqual(series[1], (20, 2))

    def test_null_family_and_max_lag(self):
        rng = random.Random(270)
        fields = ['f%d' % i for i in range(50)]
        rows = [dict({f: rng.random() for f in fields}, v=rng.random(), regime='transit')
                for _ in range(180)]
        config = dict(CFG, fields=fields, lags=[-2, 0, 2], reps=99, bootstrap_reps=10)
        hypotheses = atlas.discover(rows[:90], rows[90:], config)['hypotheses']
        self.assertLessEqual(sum(h['q_pass'] for h in hypotheses), 2)
        self.assertTrue(all(h['p'] is not None for h in hypotheses))
        x, y = [r['f1'] for r in rows[:20]], [r['v'] for r in rows[:20]]
        lags = (-2, 0, 2)

        def maximum(b):
            return max(abs(stats.spearman(x[2:], b[:-2])), abs(stats.spearman(x, b)),
                       abs(stats.spearman(x[:-2], b[2:])))

        observed, rng = maximum(y), random.Random(78)
        offsets = [rng.choice(range(3, 18)) for _ in range(49)]
        count = sum(maximum(y[k:] + y[:k]) >= observed for k in offsets)
        self.assertEqual(stats.circular_shift_pvalue(x, y, stats.spearman, 49, 3, 78, lags),
                         (1 + count) / 50)
