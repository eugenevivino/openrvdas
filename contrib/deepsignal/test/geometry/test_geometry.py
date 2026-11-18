import copy
import logging
import tempfile
import unittest
from pathlib import Path

import yaml

from contrib.deepsignal.geometry.transform import LeverArmTransform, earth_radii, north_east
from contrib.deepsignal.geometry.survey import check
from logger.utils.das_record import DASRecord


VECTORS = [
    (0, 0, 0, 10, 0, 0.000090437, 0, 10, 0),
    (0, 0, 90, 10, 0, 0, 0.000089832, 0, 10),
    (0, 0, 0, 0, 10, 0, 0.000089832, 0, 10),
    (0, 0, 90, 0, 10, -0.000090437, 0, -10, 0),
    (45, -125, 30, -20, 5, 44.999821649, -125.000071910, -19.8205, -5.6699),
    (60, 10, 225, 15, -3, 59.999885758, 9.999847934, -12.7279, -8.4853),
]


def record(ts, **fields):
    return {'timestamp': ts, 'fields': fields, 'metadata': {'source': 'bridge'}}


class GeometryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'vessel_geometry.yaml'
        self.survey = {'positions': [dict(id='antenna', x=-10, y=0, z=25)]}
        self.settings = dict(geometry_file=str(self.path), antenna='antenna', lat_field='lat',
                             lon_field='lon', heading_field='hdg', prefix='Ship')
        self.write_survey()

    def write_survey(self):
        self.path.write_text(yaml.safe_dump(self.survey), encoding='utf-8')

    def transform(self, **settings):
        return LeverArmTransform(**(self.settings | settings)).transform

    def test_vectors(self):
        for lat, lon, h, dx, dy, new_lat, new_lon, dn, de in VECTORS:
            with self.subTest(lat=lat, heading=h, dx=dx, dy=dy):
                north, east = north_east(dx, dy, h)
                self.assertAlmostEqual(north, dn, delta=1e-4)
                self.assertAlmostEqual(east, de, delta=1e-4)
                self.survey['positions'][0].update(x=-dx, y=-dy)
                self.write_survey()
                result = self.transform()(record(10, lat=lat, lon=lon, hdg=h))['fields']
                self.assertAlmostEqual(result['ShipLatitude'], new_lat, delta=1e-9)
                self.assertAlmostEqual(result['ShipLongitude'], new_lon, delta=1e-9)

    def test_radii(self):
        for lat, meridian, vertical in [(0, 6335439.3273, 6378137), (45, 6367381.8156,
                                                                     6388838.2901)]:
            with self.subTest(lat=lat):
                m, n = earth_radii(lat)
                self.assertAlmostEqual(m, meridian, delta=1e-4)
                self.assertAlmostEqual(n, vertical, delta=1e-4)

    def test_wrap(self):
        fields = self.transform()(record(10, lat=0, lon=179.99995, hdg=90))['fields']
        self.assertAlmostEqual(fields['ShipLongitude'], -179.999960168, delta=1e-9)

    def test_heading_age_and_recovery(self):
        apply = self.transform()
        apply(record(10, hdg=90))
        apply(record(9, hdg=0))
        fix = record(12, lat=0, lon=0)
        self.assertAlmostEqual(apply(fix)['fields']['ShipLongitude'], 0.000089832, delta=1e-9)
        with self.assertLogs(level='WARNING') as log:
            for ts in (12.01, 13):
                fix = record(ts, lat=0, lon=0)
                self.assertEqual(apply(fix), fix)
        self.assertEqual(len(log.output), 1)
        self.assertIn('stale', log.output[0].lower())
        self.assertIn('ShipLatitude', apply(record(14, lat=0, lon=0, hdg=0))['fields'])

    def test_future_heading(self):
        apply = self.transform()
        apply(record(11, hdg=0))
        fix = record(10, lat=0, lon=0)
        with self.assertLogs(level='WARNING'):
            self.assertEqual(apply(fix), fix)

    def test_polar(self):
        apply = self.transform()
        for sign in (-1, 1):
            fix = record(10, hdg=0, lat=89.5 * sign, lon=0)
            self.assertIn('ShipLatitude', apply(fix)['fields'])
            with self.assertLogs(level='WARNING') as log:
                fix['fields']['lat'] = 89.6 * sign
                self.assertEqual(apply(fix), fix)
            self.assertEqual(len(log.output), 1)

    def test_check_findings(self):
        survey = {'positions': [dict(id='a', x=120, y=160, z=1), dict(id='b', x=0, y=0)],
                  'monuments': [dict(id='a', x=0, y=0, z=0)]}
        findings = check(survey)
        self.assertEqual(len(findings), 3)
        self.assertTrue(any(f.level == logging.WARNING and '200 m' in f.message for f in findings))
        errors = [f.message for f in findings if f.level == logging.ERROR]
        self.assertTrue(any('monuments[0].id' in e and 'unique' in e for e in errors))
        self.assertTrue(any('positions[1].z' in e and 'missing' in e for e in errors))
        survey['positions'][0]['z'] = 0
        self.assertEqual(len(check(survey)), 2)

    def test_inputs_untouched(self):
        self.survey['positions'].append(dict(id='bow', x=5, y=0, z=0))
        self.write_survey()
        apply = self.transform(target='bow')
        raw = record(20, lat=0, lon=0, hdg=0, quality='good')
        das = DASRecord(data_id='GPS', message_type='fix', **raw)
        batch = [None, raw, das]
        original = copy.deepcopy(batch)
        out = apply(batch)
        self.assertEqual(batch, original)
        self.assertIsNone(apply(None))
        self.assertIsNone(out[0])
        self.assertIsInstance(out[2], DASRecord)
        for fields in (out[1]['fields'], out[2].fields):
            self.assertEqual(fields, dict(raw['fields'], ShipLatitude=fields['ShipLatitude'],
                                          ShipLongitude=0))
            self.assertAlmostEqual(fields['ShipLatitude'], 0.000135655, delta=1e-9)
        self.assertEqual(out[1]['metadata'], raw['metadata'])
        self.assertEqual((out[2].data_id, out[2].message_type, out[2].timestamp, out[2].metadata),
                         ('GPS', 'fix', 20, raw['metadata']))

    def test_output_collision(self):
        fix = record(10, hdg=0, lat=0, lon=0, ShipLongitude=None)
        with self.assertLogs(level='WARNING'):
            self.assertEqual(self.transform()(fix), fix)

    def test_bad_inputs(self):
        for fix in (record(1, lon=0), record(1, lon=0, lat=0), record(1, hdg=float('nan')),
                    record(None, lon=0, lat=0, hdg=0), record(1, lat=True, lon=0, hdg=0)):
            with self.subTest(fix=fix), self.assertLogs(level='WARNING'):
                self.assertEqual(self.transform()(fix), fix)

    def test_bad_configuration(self):
        for key, value in [('heading_timeout', -1), ('antenna', 'typo'), ('target', 'typo'),
                           ('prefix', False), ('lat_field', ''), ('heading_field', 'lat'),
                           ('geometry_file', ''), ('unknown_setting', 12)]:
            with self.subTest(setting=key), self.assertRaises(ValueError) as error:
                self.transform(**{key: value})
            message = str(error.exception)
            for part in (key, repr(value), 'expected', 'example'):
                self.assertIn(part, message)
            self.assertEqual(len(message.splitlines()), 1)

    def test_unsafe_yaml(self):
        self.path.write_text('!!python/tuple [1, 2]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'geometry_file'):
            self.transform()
