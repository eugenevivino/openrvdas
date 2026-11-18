import pathlib
import tempfile
import unittest

from logger.transforms.parse_transform import ParseTransform
from logger.utils.das_record import DASRecord

from contrib.deepsignal.seismic.p111_writer import P111Writer
from contrib.deepsignal.seismic.shot_qc_transform import ShotQCTransform


HERE = pathlib.Path(__file__).parent


def record(timestamp, **fields):
    return {'timestamp': timestamp, 'fields': fields}


class ShotQCTest(unittest.TestCase):
    def make_qc(self, **kwargs):
        return ShotQCTransform(shot_number='shot', fire_time='fire',
                               gun_errors=['gun1', 'gun2'], lat='lat', lon='lon',
                               nav_time='nav_time', **kwargs)

    def nav_pair(self, qc):
        qc.transform(record(100, nav_time=100, lat=10, lon=20))
        qc.transform(record(102, nav_time=102, lat=12, lon=24))

    def test_on_time_interpolation_clock_offset_and_input_unchanged(self):
        qc = self.make_qc()
        self.nav_pair(qc)
        incoming = record(101.2, shot=7, fire=101, gun1=0.2, gun2=-0.3)
        before = dict(incoming['fields'])
        out = qc.transform(incoming)
        self.assertEqual(before, incoming['fields'])
        self.assertEqual((out['fields']['SHOT_Lat'], out['fields']['SHOT_Lon']), (11, 22))
        self.assertAlmostEqual(out['fields']['SHOT_ClockOffset_s'], -0.2)
        self.assertEqual(out['fields']['SHOT_GunsOut'], 0)
        self.assertFalse(out['fields']['SHOT_Alarm'])

    def test_gun_missed_interval_spacing_and_alarm_text(self):
        qc = self.make_qc(interval_s=10, spacing_m=50, interval_tolerance_pct=5)
        qc.transform(record(100, nav_time=100, lat=0, lon=0))
        qc.transform(record(101, nav_time=101, lat=0, lon=0.0009))
        qc.transform(record(100, shot=10, fire=100, gun1=0, gun2=0))
        out = qc.transform(record(101, shot=12, fire=101, gun1=0, gun2=2.4))
        f = out['fields']
        self.assertEqual(f['SHOT_Missed'], 1)
        self.assertEqual(f['SHOT_GunsOut'], 1)
        self.assertEqual(f['SHOT_WorstGun_ms'], 2.4)
        self.assertTrue(f['SHOT_Alarm'])
        self.assertIn('gun 2 fired 2.4 ms late (limit 1.0 ms)', f['SHOT_AlarmText'])
        self.assertIn('interval', f['SHOT_AlarmText'])
        self.assertIn('spacing', f['SHOT_AlarmText'])

    def test_nav_gap_and_no_extrapolation(self):
        qc = self.make_qc(nav_max_gap_s=2)
        qc.transform(record(10, nav_time=10, lat=1, lon=2))
        out = qc.transform(record(20, shot=1, fire=20, gun1=0, gun2=0))
        self.assertIsNone(out['fields']['SHOT_Lat'])
        self.assertIsNone(out['fields']['SHOT_Lon'])
        self.assertTrue(out['fields']['SHOT_NavGap'])
        qc.transform(record(30, nav_time=30, lat=3, lon=4))
        out = qc.transform(record(20, shot=2, fire=20, gun1=0, gun2=0))
        self.assertTrue(out['fields']['SHOT_NavGap'])

    def test_alarm_persists_then_clears(self):
        qc = self.make_qc()
        bad = qc.transform(record(1, shot=1, fire=1, gun1=2, gun2=0))
        self.assertTrue(bad['fields']['SHOT_Alarm'])
        for number in (2, 3):
            out = qc.transform(record(number, shot=number, fire=number, gun1=0, gun2=0))
            self.assertTrue(out['fields']['SHOT_Alarm'])
        out = qc.transform(record(4, shot=4, fire=4, gun1=0, gun2=0))
        self.assertFalse(out['fields']['SHOT_Alarm'])

    def test_none_list_dasrecord_and_replay_determinism(self):
        self.assertIsNone(self.make_qc().transform(None))
        records = [record(1, shot=1, fire=1, gun1=0, gun2=0),
                   DASRecord(timestamp=2, fields={'shot': 2, 'fire': 2,
                                                  'gun1': 0, 'gun2': 0})]
        a = self.make_qc().transform(records)
        b = self.make_qc().transform(records)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1].fields, b[1].fields)

    def test_rejects_non_finite_values_and_bounds_nav_history(self):
        qc = self.make_qc()
        for value in range(500):
            qc.transform(record(value, nav_time=value, lat=1, lon=2))
        self.assertLessEqual(len(qc._nav_history), 121)
        out = qc.transform(record(500, shot=1, fire=float('nan'), gun1=0, gun2=0))
        self.assertIsNone(out['fields']['SHOT_FireTime'])

    def test_p111_writer_matches_hand_written_golden(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'line.csv'
            writer = P111Writer(filename=str(path), ship_name='R/V Test')
            writer.write(record(1001, SHOT_Number=7, SHOT_FireTime=1000.5,
                                SHOT_Lat=10.5, SHOT_Lon=-20.25))
            writer.close()
            self.assertEqual(path.read_text(), (HERE / 'p111_golden.csv').read_text())

    def test_template_parses_sample_line(self):
        path = 'contrib/deepsignal/configs/seismic_shotlog_template.yaml'
        parser = ParseTransform(definition_path=path)
        out = parser.transform(
            'shotlog 1970-01-01T00:16:40.500Z SHOT,7,1000.25,0.1,-0.2,1900')
        self.assertEqual(out['fields']['ShotNumber'], 7)
        self.assertEqual(out['fields']['Gun2Error_ms'], -0.2)


if __name__ == '__main__':
    unittest.main()
