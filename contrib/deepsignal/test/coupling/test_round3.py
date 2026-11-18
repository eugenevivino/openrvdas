"""Regressions from the re-review of cf7afd9."""

import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

from contrib.deepsignal.coupling import archive, atlas, prep, stats
from contrib.deepsignal.coupling.transform import ShipCouplingTransform
from contrib.deepsignal.test.coupling.test_review import CFG, ROOT, legs


class RoundThreeTest(unittest.TestCase):
    def live(self):
        return ShipCouplingTransform(ROOT / 'coupling/sample_atlas.json')

    def heading_fit(self, a, b, **settings):
        cfg = dict(CFG, ship_variables=['relative_heading_cos'], bootstrap_reps=3)
        cfg.update(settings)
        h, = atlas.discover(a, b, cfg)['hypotheses']
        self.assertEqual(h['status'], 'confirmed')
        return h

    def test_earth_fixed_crossing(self):
        def cruise(seed):
            rng = random.Random(seed)
            rows = []
            for leg in range(200):
                sign = (-1)**leg
                for k in range(-rng.randrange(6, 14), rng.randrange(6, 14) + 1):
                    lat = -sign * .0002 * min(1, abs(k))
                    heading = (90 if sign == 1 else 270) + sign * 5 * ((k == 0) - (k == 1))
                    rows.append(dict(timestamp=len(rows)*180, latitude=lat,
                                     longitude=-70 + .002*sign*k, heading=heading,
                                     direction=heading if sign == 1 else heading-180,
                                     sog=2.4, temp=1000*lat))
            return rows
        a, b = cruise(12), cruise(37)
        h = self.heading_fit(a, b, bin_seconds=180, median_minutes=15)
        self.assertTrue(all(abs(v) < .2 for v in h['time_shift'].values()))
        self.assertEqual(h['reciprocal_pairs'].get('ship_artifact', 0), 0)
        self.assertEqual(h['invariance'], 'environmental')

        # Nearby but distinct raw readings differ by only the spatial gradient.
        # Different rolling backgrounds still account for almost the entire flip.
        for row in a + b:
            row['latitude'] += 1e-8 if row['heading'] < 180 else -1e-8
            row['temp'] = 1000*row['latitude']
        h = self.heading_fit(a, b, bin_seconds=180, median_minutes=15)
        self.assertEqual(h['reciprocal_pairs'].get('ship_artifact', 0), 0)

    def test_constant_cruise_null(self):
        def cruise(seed):
            rng = random.Random(seed)
            main = [dict(temp=rng.gauss(0, 1), v=math.sin(i*2*math.pi/60), cruise='main',
                         regime='transit') for i in range(96)]
            return main + [dict(temp=0, v=0, cruise='flat', regime='transit') for _ in range(145)]
        h, = atlas.discover(cruise(4), cruise(11), dict(fields=['temp'], ship_variables=['v'])
                            )['hypotheses']
        self.assertEqual(h['status'], 'rejected')
        for fit in (h, h['holdout']):
            self.assertEqual((fit['min_shift'], fit['p'], fit['shift_reps']), (48, .5, 1))

    def test_flat_field_null_family(self):
        fields = [f'f{i}' for i in range(50)]
        q = .05

        def cruise(seed):
            rng = random.Random(seed)
            main = [dict({f: rng.gauss(0, 1) for f in fields}, v=math.sin(i*2*math.pi/60),
                         cruise='main', regime='transit') for i in range(96)]
            # At lag zero rotating this cruise permutes identical field readings.
            return main + [dict(dict.fromkeys(fields, 0), v=i % 3, cruise='flat', regime='transit')
                           for i in range(145)]

        seeds = ((4, 11), (27, 38), (81, 95))
        total = 0
        for a, b in seeds:
            cfg = dict(fields=fields, ship_variables=['v'], min_shift=48, bootstrap_reps=2, q=q)
            fits = atlas.discover(cruise(a), cruise(b), cfg)['hypotheses']
            total += sum(h['status'] == 'confirmed' for h in fits)
            with self.subTest(seed=a):
                support = {fit['shift_reps'] for h in fits for fit in (h, h['holdout'])}
                self.assertEqual(support, {1})
        self.assertLessEqual(total, len(seeds)*len(fields)*q*q)

    def test_periodic_shift_support(self):
        # The missing bin is part of each period. Equal absolute effects can still
        # come from different rotated vectors and count as separate surrogates.
        x = [2, 9, 1, 3, 6, 4, 8, 7, 5, 0, 2, 7]
        y = [2, None, 1] * 4
        observed = abs(stats.spearman(x, y))
        count = sum(abs(stats.spearman(x, y[k:] + y[:k])) >= observed for k in (1, 2, 3))
        self.assertEqual(stats.circular_shift_test(x, y, stats.spearman, 50, 1, 78, [0], None),
                         ((1 + count)/4, 3))

    def test_unreversed_relative_heading(self):
        def cruise(seed):
            rng = random.Random(seed)
            rows = []
            for site in range(250):
                angle = rng.choice([0, 180])
                for head in (0, 180):
                    for _ in range(3):
                        rows.append(dict(timestamp=len(rows)*300, relative_heading=angle,
                                         heading=head, sog=5, latitude=0, longitude=site*.003,
                                         temp=.5*math.cos(math.radians(angle))))
            return rows
        h = self.heading_fit(cruise(12), cruise(37), bin_seconds=300, median_minutes=1500,
                             reciprocal_km=.15)
        self.assertEqual(h['reciprocal_pairs'].get('environmental', 0), 0)
        self.assertEqual(h['invariance'], 'cannot_tell')

    def test_lagged_bin_sector(self):
        data = json.loads((ROOT / 'coupling/sample_atlas.json').read_text())
        data['hypotheses'][0]['lag'] = -1
        cell, = data['polar']['air_temperature']
        cell['lag'] = -1
        data['polar']['air_temperature'].append(dict(cell, sector=1, median=0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'atlas.json')
            path.write_text(json.dumps(data))
            live = ShipCouplingTransform(path)
        rows = [dict(timestamp=t, relative_heading=a, sog=3) for t, a in [(0, 320), (3, 40)]]
        offline, = prep.prepare(rows, {})
        self.assertEqual(prep.polar_cell(offline, {}), (0, 1))
        live.transform(rows)
        current = self.live()
        current.transform(rows)
        self.assertEqual(current.transform(dict(timestamp=4, air_temperature=4))
                         ['air_temperature_SHIP_QC'], 3)
        out = live.transform(dict(timestamp=10, air_temperature=4))
        self.assertEqual(out['air_temperature_SHIP_QC'], 3)
        self.assertIn('sector 0,', out['air_temperature_SHIP_why'])

    def test_acf_scale(self):
        for scale in (1e-200, 1e200):
            with self.subTest(scale=scale):
                x = [v*scale for v in range(100)]
                fit = atlas._evaluate([dict(x=a, y=a) for a in x], 'x', 'y', CFG, 78)
                self.assertAlmostEqual(fit['n_eff'], 4.729002781454743)
                self.assertTrue(fit['insufficient'])
                self.assertIsNone(fit['p'])
                self.assertAlmostEqual(stats.acf(x, 1), .97)

    def test_disjoint_cruise(self):
        def cruise(seed):
            rng = random.Random(seed)
            return [dict(temp=v, v=v, cruise='main', regime='transit')
                    for v in (rng.random() for _ in range(100))]
        gap = [dict(temp=1, cruise='extra', regime='transit'),
               dict(v=1, cruise='extra', regime='transit')]
        base, = atlas.discover(cruise(7), cruise(1), CFG)['hypotheses']
        h, = atlas.discover(cruise(7)+gap, cruise(1)+gap, CFG)['hypotheses']
        self.assertEqual(base['status'], 'confirmed')
        for name in ('status', 'effect', 'p', 'shift_reps', 'n_eff', 'ci', 'holdout'):
            self.assertEqual(h[name], base[name], name)
        # This cruise does contribute at lag +1.
        fit = atlas._evaluate(gap, 'temp', 'v', dict(CFG, lags=[1]), 78)
        self.assertIsNone(fit['effect'])  # only one pair
        many = [dict(r, cruise=i) for i in range(40)
                for r in (dict(temp=i), dict(v=i))]
        self.assertEqual(atlas._evaluate(many, 'temp', 'v', dict(CFG, lags=[1]), 78)['pairs'], 40)

    def test_late_channel(self):
        live = self.live()
        live.transform(dict(timestamp=10, sog=3, relative_heading=0))
        live.transform(dict(timestamp=30, air_temperature=42))
        live.transform(dict(timestamp=20, relative_heading=180))
        self.assertEqual(live.transform(dict(timestamp=40, air_temperature=42))
                         ['air_temperature_SHIP_QC'], 2)

    def test_bad_timestamp(self):
        live = self.live()
        live.transform(dict(timestamp=10, sog=3, relative_heading=180))
        for stamp in ('invalid', None, float('nan')):
            bad = live.transform(dict(timestamp=stamp, relative_heading=0, air_temperature=42))
            good = live.transform(dict(timestamp=30, air_temperature=42))
            self.assertEqual((bad['air_temperature_SHIP_QC'], good['air_temperature_SHIP_QC']),
                             (2, 2), stamp)

    def test_measured_regime(self):
        live = self.live()
        a = dict(timestamp=0, sog=3, relative_heading=0)
        b = dict(timestamp=10, sog=4, regime='transit', air_temperature=42)
        self.assertEqual(prep.prepare([a, b], {})[-1]['regime'], 'maneuver')
        live.transform(a)
        self.assertEqual(live.transform(b)['air_temperature_SHIP_QC'], 2)

    def test_bin_maneuver(self):
        live = self.live()
        rows = [dict(timestamp=t, sog=s, relative_heading=0, regime='transit', air_temperature=1)
                for t, s in [(0, 3), (11, 4), (12, 4)]]
        self.assertEqual(prep.prepare(rows, {})[-1]['regime'], 'maneuver')
        self.assertEqual(live.transform(rows)[-1]['air_temperature_SHIP_QC'], 2)

    def test_late_maneuver_state(self):
        live = self.live()
        live.transform(dict(timestamp=10, sog=3, heading=0, relative_heading=0))
        live.transform(dict(timestamp=20, sog=3, heading=90))
        live.transform(dict(timestamp=10, heading_rate=0))
        self.assertEqual(live.transform(dict(timestamp=30, air_temperature=1))
                         ['air_temperature_SHIP_QC'], 2)
        live = self.live()
        live.transform(dict(timestamp=20, sog=4, relative_heading=0))
        live.transform(dict(timestamp=10, sog=3))
        self.assertEqual(live.transform(dict(timestamp=30, air_temperature=1))
                         ['air_temperature_SHIP_QC'], 2)

    def test_configured_source(self):
        cfg = dict(relative_heading_field='intended')
        for extra, expected in [({}, None), (dict(direction=30, heading=15), 15)]:
            row = dict(extra, sog=3, intended=None, relative_heading=0, relative_heading_cos=1)
            grid, = prep.prepare([row], cfg)
            self.assertEqual(grid.get('relative_heading'), expected)
            self.assertEqual(grid.get('relative_heading_cos'),
                             None if expected is None else prep.sine_degrees(expected+90))
            live = self.live()
            live.config.update(cfg)
            live.transform(row)
            self.assertEqual(live.state['relative_heading'], expected)

    def test_gps_jitter(self):
        a, b = legs(340, 0), legs(410, 1500000)
        for row in a + b:
            if row['heading'] == 180:
                row['latitude'] += 1e-8
        h = self.heading_fit(a, b, bin_seconds=300, median_minutes=1500, reciprocal_km=.15)
        self.assertEqual(h['invariance'], 'ship_artifact')

    def test_interrupted_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            result = atlas.discover([], [], dict(CFG, output_dir=tmp))
            names = ('atlas.json', 'atlas.md', 'polar_temp.csv')
            table = [dict(regime='transit', ship_variable='v', sector=0, speed_band=0, median=1)]
            result.update(unparseable_lines=0, polar={'temp': table}, healthy_spread={'temp': 1})
            archive.write_atlas(result, [])
            old = tuple((path/name).read_bytes() for name in names)
            result.update(unparseable_lines=1, polar={})
            replace = os.replace

            def interrupt_after_visible_change(src, dest, *args, **kwargs):
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(descriptor)
                replace(src, dest, *args, **kwargs)
                if (path/'atlas.md').read_bytes() != old[1]:
                    raise KeyboardInterrupt

            with patch.object(os, 'replace', side_effect=interrupt_after_visible_change):
                with self.assertRaises(KeyboardInterrupt):
                    archive.write_atlas(result, [])
            self.assertEqual(json.loads((path/'atlas.json').read_bytes())['unparseable_lines'], 1)
            self.assertFalse((path/'polar_temp.csv').exists())
            archive.write_atlas(result, [])
            self.assertFalse((path/'polar_temp.csv').is_symlink())

    def test_core_record_dispatch(self):
        live = self.live()
        with (patch.object(live, 'can_process_record', return_value=False, create=True),
              patch.object(live, 'digest_record', return_value={'decoded': True},
                           create=True) as digest):
            self.assertEqual(live.transform('{"temp": 4}'), {'decoded': True})
            digest.assert_called_once_with('{"temp": 4}')

    def test_packaged_core_imports(self):
        module = sys.modules[ShipCouplingTransform.__module__]
        spec = importlib.util.spec_from_file_location(module.__name__, module.__file__)
        packaged = importlib.util.module_from_spec(spec)
        imports = {}
        for name in ('logger.transforms.transform', 'logger.utils.das_record'):
            imports['openrvdas.' + name] = sys.modules[name]
            imports[name] = None
        with patch.dict(sys.modules, imports):
            spec.loader.exec_module(packaged)
            live = packaged.ShipCouplingTransform(ROOT / 'coupling/sample_atlas.json')
        self.assertEqual(live.transform(dict(air_temperature=1, relative_heading=0, sog=3))
                         ['air_temperature_SHIP_QC'], 3)
