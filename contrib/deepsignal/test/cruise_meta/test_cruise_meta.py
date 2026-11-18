import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from contrib.deepsignal.cruise_meta import check, cruise_day, load
from contrib.deepsignal.cruise_meta.reader import CruiseMetaReader


VALID = {
    'cruise_id': 'RR2205',
    'ship': {'name': 'Roger Revelle', 'ices_code': None, 'call_sign': 'KAOU'},
    'start': '2022-04-01T00:00Z',
    'end': '2022-05-10T00:00Z',
    'departure_port': {'name': 'San Diego', 'unlocode': 'USSAN'},
    'arrival_port': {'name': 'Honolulu', 'unlocode': None},
    'chief_scientist': {'name': 'Example Person'},
    'participants': [],
}


class FakeClock:
    def __init__(self, values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


class CruiseMetaTest(unittest.TestCase):
    def write_meta(self, changes=None):
        data = dict(VALID)
        data.update(changes or {})
        temporary = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        with temporary:
            yaml.safe_dump(data, temporary)
        self.addCleanup(Path(temporary.name).unlink)
        return temporary.name

    def test_valid_example_loads(self):
        metadata = load(self.write_meta())
        self.assertEqual(metadata['cruise_id'], 'RR2205')
        self.assertEqual(check(metadata), [])

    def test_end_must_follow_start(self):
        path = self.write_meta({'end': '2022-03-31T23:59Z'})
        with self.assertRaisesRegex(ValueError, 'end.*2022-03-31.*after start.*2022-04-01'):
            load(path)

    def test_cruise_id_shape(self):
        path = self.write_meta({'cruise_id': 'RR 22/05'})
        message = 'cruise_id.*RR 22/05.*letters, digits, dash or underscore'
        with self.assertRaisesRegex(ValueError, message):
            load(path)

    def test_unlocode_shape(self):
        path = self.write_meta({'departure_port': {'name': 'San Diego', 'unlocode': 'US-SD'}})
        with self.assertRaisesRegex(ValueError, 'departure_port.unlocode.*US-SD.*USSAN'):
            load(path)

    def test_contact_details_are_rejected(self):
        path = self.write_meta({'participants': ['Person <person@example.org>']})
        with self.assertRaisesRegex(ValueError, 'participants.*contact details do not belong'):
            load(path)

    def test_cruise_day_at_start_mid_and_after_end(self):
        metadata = load(self.write_meta())
        self.assertEqual(cruise_day(metadata, '2022-04-01T00:00Z'), 1)
        self.assertEqual(cruise_day(metadata, '2022-04-02T12:00Z'), 2)
        self.assertEqual(cruise_day(metadata, '2022-05-11T00:00Z'), 41)

    def test_reader_interval_with_fake_clock(self):
        start = datetime(2022, 4, 1, tzinfo=timezone.utc).timestamp()
        reader = CruiseMetaReader(
            self.write_meta(), interval=60, clock=FakeClock([start, start + 30, start + 60]))
        first = reader.read()
        self.assertEqual(first.timestamp, start)
        self.assertEqual(first.fields, {
            'cruise_id': 'RR2205', 'cruise_day': 1, 'cruise_active': True})
        self.assertIsNone(reader.read())
        self.assertEqual(reader.read().timestamp, start + 60)


if __name__ == '__main__':
    unittest.main()
