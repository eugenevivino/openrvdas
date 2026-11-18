import hashlib
import json
import math
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import yaml

from contrib.deepsignal.sv_manager.ingest import ingest
from contrib.deepsignal.sv_manager.profile import clean, extend, thin
from contrib.deepsignal.sv_manager.files import export, load_export, replay
from contrib.deepsignal.sv_manager.watch import SVManagerReader, SVMonitorTransform
from logger.utils.das_record import DASRecord

HERE = Path(__file__).parent
FIX = HERE / 'fixtures'
T0 = 1794960000  # 2026-11-18 00:00:00 UTC


class TestManager(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=HERE)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cast = ingest(FIX / 'cast.csv')

    def samples(self, z, sv):
        return replace(self.cast, depth_m=z, sv_ms=sv)

    def test_cnv(self):
        p = ingest(FIX / 'ctd017.cnv')
        self.assertEqual((p.time, p.lat, p.lon), (T0, 33.2, -118.9))
        self.assertIsNone(p.sv_ms[1])
        p = clean(p)
        self.assertEqual(p.depth_m, [0, 10, 1000])
        self.assertEqual(p.sv_ms, [1500, 1501, 1520])
        self.assertEqual((p.t_c, p.s_psu), ([12, 11, 3], [35, 35, 36]))

    def test_sondes_and_mapping(self):
        for name, depth, sv in [('aml', 79, 1501), ('valeport', 9.8, 1492), ('mvp', 30, 1499)]:
            with self.subTest(name=name):
                p = ingest(FIX / (name + '.csv'))
                self.assertEqual((p.depth_m[0], p.sv_ms[0]), (depth, sv))
        path = self.tmp / 'custom.txt'
        path.write_text('velocity;z\n1500;3\n')
        mapping = self.tmp / 'custom.yaml'
        mapping.write_text("delimiter: ';'\ncolumns: {depth_m: [z], sv_ms: [velocity]}\n")
        self.assertEqual(ingest(path, mapping=mapping).sv_ms, [1500])

    def test_xbt(self):
        path = FIX / 'xbt.EDF'
        with patch.dict(sys.modules, {'logger.utils.met_formulas': None}):
            p = ingest(path, surface_salinity=35)
        self.assertIn('needs SV conversion', p.reasons)
        self.assertEqual((p.time, p.lat, p.lon), (T0, 33.2, -118.9))
        self.assertEqual((p.depth_m, p.t_c, p.sv_ms), ([1000], [25], [None]))
        module = ModuleType('logger.utils.met_formulas')
        calls = []

        def converter(t, s, z):
            calls.append((t, s, z))
            return 1550.744

        module.sound_speed_mackenzie = converter
        with patch.dict(sys.modules, {'logger.utils.met_formulas': module}):
            self.assertEqual(ingest(path, surface_salinity=35).sv_ms, [1550.744])
            sal = self.tmp / 'sal.csv'
            sal.write_text('depth_m,s_psu\n0,33\n2000,37\n')
            self.assertEqual(ingest(path, salinity_profile=sal).s_psu, [35])
            self.assertEqual(ingest(path).sv_ms, [None])
        self.assertEqual(calls, [(25, 35, 1000)] * 2)
        try:
            from logger.utils.met_formulas import sound_speed_mackenzie
        except ModuleNotFoundError:
            return
        self.assertAlmostEqual(ingest(path, surface_salinity=35).sv_ms[0],
                               sound_speed_mackenzie(25, 35, 1000))

    def test_downcast(self):
        p = clean(self.samples([0, 2, 4, 4, 2], [1500]*5))
        self.assertEqual(p.depth_m, [0, 2, 4])

    def test_range(self):
        p = clean(self.samples([0, 2, 4, 6], [1400, 1399, 1651, 1650]))
        self.assertEqual(p.sv_ms, [1400, 1650])

    def test_spikes(self):
        p = clean(self.samples([0, 1, 2, 7], [1500, 1512, 1501, 1512]))
        self.assertEqual(p.sv_ms, [1500, 1501, 1512])

    def test_bins(self):
        z = [0, 2.1, 2.3, 100, 102, 105, 1000, 1024, 1025, 1040]
        p = clean(self.samples(z, [1500]*len(z)))
        self.assertEqual(len(p.depth_m), 7)
        self.assertEqual((p.depth_m[0], p.depth_m[-1], p.max_cast_depth_m), (0, 1040, 1040))
        self.assertGreater(len(clean(self.samples(z, [1500]*len(z)),
                                     bin_m=(0.1, 1, 1)).depth_m), len(p.depth_m))

    def test_surface(self):
        p = self.samples([5, 15], [1500, 1501])
        self.assertEqual(clean(p).depth_m, [5, 15])
        for role in ('probe', 'TSG'):
            q = clean(p, **{role.lower() + '_sv': 1499})
            self.assertEqual(q.sv_ms, [1499, 1500, 1501])
            self.assertIn('surface filled from ' + role, str(q.history))
        with self.assertRaises(ValueError):
            export(extend(clean(p)), 'asvp', self.tmp)

    def test_extensions(self):
        p = clean(self.cast)
        c = extend(p, climatology=FIX / 'climate.csv')
        self.assertEqual(c.sv_ms[c.depth_m.index(1000)], 1510)
        self.assertAlmostEqual(c.sv_ms[c.depth_m.index(1200)], 1494 + 20/math.e)
        self.assertAlmostEqual(c.sv_ms[-1], 1670 + 20*math.exp(-55))
        q = extend(clean(self.samples([0, 500], [1500, 1505])))
        self.assertAlmostEqual(q.sv_ms[q.depth_m.index(1000)], 1510)
        self.assertAlmostEqual(q.sv_ms[-1], 1697)
        self.assertLess(q.quality, c.quality)
        for profile in (c, q):
            self.assertEqual(profile.depth_m[-1], 12000)
            self.assertEqual(sorted(set(profile.depth_m)), profile.depth_m)
        with self.assertRaises(ValueError):
            extend(p, climatology=FIX / 'cast.csv')

    def test_thinning(self):
        z = [0, 1, 2, 3, 4, 5]
        p = self.samples(z, [1500, 1501, 1506, 1504, 1501, 1500])
        q = thin(p, max_points=3)
        self.assertEqual(q.depth_m, [0, 2, 5])
        self.assertEqual(q.thinning_error_ms, 2)
        dense = extend(clean(self.cast), climatology=FIX / 'climate.csv')
        out = thin(dense, max_points=3)
        self.assertIn(dense.max_cast_depth_m, out.depth_m)
        j = 0
        errors = []
        for x, v in zip(dense.depth_m, dense.sv_ms):
            if x > out.depth_m[j+1]:
                j += 1
            f = (x-out.depth_m[j])/(out.depth_m[j+1]-out.depth_m[j])
            errors.append(abs(v - (out.sv_ms[j] + f*(out.sv_ms[j+1]-out.sv_ms[j]))))
        self.assertAlmostEqual(max(errors), out.thinning_error_ms)

    def test_exports_and_replay(self):
        p = thin(extend(clean(self.cast)), max_points=3)
        for fmt in ('asvp', 'csv', 'template'):
            path = export(p, fmt, self.tmp, template=FIX / 'sample.tpl')
            if fmt == 'template':
                expected = ('Cast cast at 2026-11-18T00:00:00Z\n0.00 1500.000\n'
                            '1000.00 1510.000\n12000.00 1697.000\n')
                self.assertEqual(path.read_text(), expected)
            else:
                self.assertEqual(path.read_bytes(), (FIX / ('golden.' + fmt)).read_bytes())
            side = Path(str(path) + '.json')
            manifest = json.loads(side.read_text())
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(manifest['output_sha256'], checksum)
            self.assertEqual(load_export(side), p)
            self.assertEqual(asdict(replay(manifest['profile']['history'])), asdict(p))
            self.assertEqual(export(p, fmt, self.tmp, template=FIX / 'sample.tpl'), path)
            path.write_text('tampered')
            with self.assertRaises(ValueError):
                load_export(side)

    def test_untrusted(self):
        src = self.tmp / 'bad.csv'
        for data in ('depth_m,sv_ms\n1,nan\n', 'sv_ms,sv_ms\n1,2\n',
                     'pressure,sv_ms\n10,1500\n'):
            src.write_text(data)
            with self.assertRaises(ValueError):
                ingest(src)
        with src.open('wb') as f:
            f.truncate(9*1024*1024)
        with self.assertRaises(ValueError):
            ingest(src)
        p = thin(extend(clean(self.cast)), max_points=3)
        bad = replace(p, source={'id': '../../outside', 'type': 'csv'})
        with self.assertRaises(ValueError):
            export(bad, 'asvp', self.tmp)

    def test_reader(self):
        r = SVManagerReader(self.tmp)
        self.assertIsNone(r.read())
        path = self.tmp / 'cast.csv'
        path.write_text('bad input')
        with self.assertLogs(level='WARNING'):
            self.assertIsNone(r.read())
        path.write_bytes((FIX / 'cast.csv').read_bytes())
        event = r.read()
        self.assertEqual(event['timestamp'], T0)
        self.assertEqual(event['fields']['SVM_CastId'], 'cast')
        self.assertEqual(event['fields']['SVM_NewCast'], 1)
        self.assertIsNone(r.read())

    def test_advice(self):
        profile = extend(clean(self.cast), climatology=FIX / 'climate.csv')
        fields = dict(Latitude=33.2, Longitude=-118.9, SV_Probe=1500,
                      SV_Alarm=0, WaterDepth=900)
        cases = [(dict(), 13, 'old'), ({'Latitude': 34.2}, 0, 'km'),
                 ({'SV_Probe': 1503}, 0, 'moved'), ({'SV_Alarm': 1}, 0, 'alarm'),
                 ({'WaterDepth': 1100}, 0, 'climatology'),
                 ({'Latitude': 34.2, 'SV_Probe': 1503, 'SV_Alarm': 1, 'WaterDepth': 1100},
                  13, 'all')]
        for changes, h, reason in cases:
            m = SVMonitorTransform(profile=profile)
            start = T0 + h*3600
            records = [dict(timestamp=start+i, fields=fields | changes) for i in range(0, 601, 60)]
            first, *_, last = m.transform(records)
            out = last['fields']
            self.assertEqual(out['SVM_CastAdvice'], 1)
            for word in ('old', 'km', 'moved', 'alarm', 'climatology'):
                self.assertEqual(word in out['SVM_CastAdviceText'], reason in (word, 'all'))
            if reason == 'moved':
                self.assertEqual(first['fields']['SVM_CastAdvice'], 0)
            self.assertEqual(out['SVM_Age_h'], h+1/6)
            self.assertEqual(out['SVM_SurfaceDiff_ms'], abs(changes.get('SV_Probe', 1500)-1500))
            if 'Latitude' in changes:
                self.assertAlmostEqual(out['SVM_Distance_km'], 111.195, places=2)
            self.assertEqual(m.transform(None), None)
            self.assertEqual(SVMonitorTransform(profile=profile).transform(records)[-1], last)

    def test_missing_gap_and_selection(self):
        m = SVMonitorTransform(export_dir=self.tmp)
        rec = DASRecord(timestamp=T0, fields={'SV_TSG': 1503})
        self.assertIsNone(m.transform(rec).fields['SVM_Quality'])
        p = thin(extend(clean(self.cast)), max_points=3)
        path = export(p, 'csv', self.tmp)
        self.assertEqual(m.transform(rec).fields['SVM_SurfaceDiff_ms'], 3)
        rec.timestamp += 601
        self.assertEqual(m.transform(rec).fields['SVM_CastAdvice'], 0)
        self.assertEqual(rec.fields, {'SV_TSG': 1503})
        pinned = SVMonitorTransform(profile=str(path) + '.json')
        missing = pinned.transform({'timestamp': T0, 'fields': {}})['fields']
        self.assertIsNone(missing['SVM_SurfaceDiff_ms'])
        self.assertIsNone(missing['SVM_Distance_km'])
        self.assertIn('missing', missing['SVM_CastAdviceText'].lower())

    def test_demo(self):
        from importlib import import_module
        config = HERE.parents[1] / 'configs/sv_manager_demo.yaml'
        pipeline = yaml.safe_load(config.read_text())
        r = pipeline['readers']
        reader = getattr(import_module(r['module']), r['class'])(**r['kwargs'])
        self.assertEqual(reader.read()['fields']['SVM_NewCast'], 1)
