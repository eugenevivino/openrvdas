import struct
import unittest
from datetime import datetime, timezone

import yaml

from logger.utils.das_record import DASRecord
from contrib.deepsignal.adcp_health.adcp_cross_check_transform import ADCPCrossCheckTransform
from contrib.deepsignal.adcp_health.pd0_summary_transform import PD0SummaryTransform


def make_pd0(bit=5, ranges=(1000, 1100, 1200, 1300), unknown=False):
    fixed = bytearray(10)
    struct.pack_into('<H', fixed, 0, 0)
    fixed[8:10] = bytes((4, 30))
    variable = bytearray(28)
    struct.pack_into('<H', variable, 0, 0x80)
    struct.pack_into('<H', variable, 2, 42)
    variable[4:11] = bytes((24, 1, 2, 3, 4, 5, 50))
    variable[11] = 1
    struct.pack_into('<HHHHhhHh', variable, 12, bit, 1498, 25, 35900, -123, 234, 35, 1234)
    bottom = bytearray(44)
    struct.pack_into('<H', bottom, 0, 0x600)
    struct.pack_into('<4H', bottom, 16, *ranges)
    bottom[40:44] = bytes(100 if value else 0 for value in ranges)
    blocks = [fixed, variable, bottom]
    if unknown:
        blocks.insert(1, bytearray(struct.pack('<H2s', 0x7777, b'xx')))
    count = len(blocks)
    header_size = 6 + 2 * count
    offsets = []
    cursor = header_size
    for block in blocks:
        offsets.append(cursor)
        cursor += len(block)
    ensemble = bytearray(cursor + 2)
    ensemble[:2] = b'\x7f\x7f'
    struct.pack_into('<H', ensemble, 2, cursor)
    ensemble[5] = count
    struct.pack_into('<' + 'H' * count, ensemble, 6, *offsets)
    for offset, block in zip(offsets, blocks):
        ensemble[offset:offset + len(block)] = block
    struct.pack_into('<H', ensemble, cursor, sum(ensemble[:cursor]) & 0xffff)
    return bytes(ensemble)


class PD0Test(unittest.TestCase):
    def test_layout_table_and_complete_ensemble(self):
        with open('contrib/deepsignal/adcp_health/pd0_layout.yaml', encoding='utf-8') as stream:
            layout = yaml.safe_load(stream)
        self.assertEqual(layout['header']['id'], [127, 127])
        transform = PD0SummaryTransform(beam_angle_deg=30)
        result = transform.transform(make_pd0(unknown=True))
        fields = result['fields']
        expected_time = datetime(2024, 1, 2, 3, 4, 5, 500000,
                                 tzinfo=timezone.utc).timestamp()
        self.assertEqual(fields['ADCP_Ensemble'], 65578)
        self.assertEqual(fields['ADCP_Time'], expected_time)
        self.assertEqual(fields['ADCP_Heading'], 359.0)
        self.assertEqual(fields['ADCP_Pitch'], -1.23)
        self.assertEqual(fields['ADCP_Roll'], 2.34)
        self.assertEqual(fields['ADCP_SoundSpeed'], 1498)
        self.assertEqual(fields['ADCP_XducerDepth'], 2.5)
        self.assertEqual(fields['ADCP_BIT'], 5)
        self.assertIn('bit 0', fields['ADCP_BITText'])
        self.assertIn('bit 2', fields['ADCP_BITText'])
        self.assertAlmostEqual(fields['ADCP_BTDepth'], 12.4592921)
        self.assertEqual(fields['ADCP_BTGood'], 100.0)
        self.assertEqual(fields['ADCP_ChecksumFailures'], 0)

    def test_split_concat_garbage_bad_checksum_and_interval(self):
        raw = make_pd0()
        bad = bytearray(raw)
        bad[-1] ^= 1
        transform = PD0SummaryTransform(beam_angle_deg=30)
        self.assertIsNone(transform.transform(raw[:17]))
        first = transform.transform(raw[17:])
        self.assertEqual(first['fields']['ADCP_Interval_s'], None)
        results = transform.transform(raw + b'junk' + bytes(bad) + raw)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[-1]['fields']['ADCP_ChecksumFailures'], 1)
        self.assertGreaterEqual(results[-1]['fields']['ADCP_Resyncs'], 1)
        self.assertEqual(results[-1]['fields']['ADCP_Interval_s'], 0.0)

    def test_too_few_bottom_beams_and_input_forms(self):
        transform = PD0SummaryTransform(beam_angle_deg=20)
        self.assertIsNone(transform.transform(None))
        result = transform.transform(make_pd0(ranges=(1000, 1100, 0, 0)))
        self.assertIsNone(result['fields']['ADCP_BTDepth'])
        self.assertEqual(result['fields']['ADCP_BTGood'], 50.0)
        self.assertEqual(len(PD0SummaryTransform(20).transform([make_pd0(), make_pd0()])), 2)
        record = DASRecord(timestamp=10, fields={'raw': make_pd0()})
        self.assertEqual(PD0SummaryTransform(20).transform(record).timestamp, 10)
        wrapped = {'timestamp': 11, 'fields': {'raw': make_pd0()}}
        self.assertEqual(PD0SummaryTransform(20).transform(wrapped)['timestamp'], 11)

    def test_requires_beam_angle(self):
        with self.assertRaises(TypeError):
            PD0SummaryTransform()


class CrossCheckTest(unittest.TestCase):
    def make_transform(self):
        return ADCPCrossCheckTransform(
            roles={'adcp_heading': 'ah', 'gyro_heading': 'gh', 'gnss_heading': 'nh',
                   'adcp_sv': 'asv', 'tsg_sv': 'tsv', 'probe_sv': 'psv',
                   'adcp_bt_depth': 'bt', 'mb_depth': 'mb', 'adcp_time': 'at',
                   'mb_ping_time': 'mt', 'ek_ping_time': 'et'},
            persistence_s=2, clear_s=2, stale_s=10, overlap_window_s=0.2,
            heading_threshold=999)

    def test_checks_wrap_offsets_depth_overlap_and_no_mutation(self):
        transform = self.make_transform()
        fields = {'ah': 359, 'gh': 1, 'nh': 358, 'asv': 1490, 'tsv': 1495,
                  'psv': 1489, 'bt': 103, 'mb': 100, 'at': 100.1, 'mt': 100,
                  'et': 99.95}
        result = transform.transform({'timestamp': 100, 'fields': fields})
        out = result['fields']
        expected_keys = {'ah', 'gh', 'nh', 'asv', 'tsv', 'psv', 'bt', 'mb',
                         'at', 'mt', 'et'}
        self.assertEqual(fields.keys(), expected_keys)
        self.assertEqual(out['ADCPX_HeadingDiff_gyro'], -2.0)
        self.assertEqual(out['ADCPX_HeadingDiff_gnss'], 1.0)
        self.assertEqual(out['ADCPX_SVDiff_tsg'], -5.0)
        self.assertEqual(out['ADCPX_SVDiff_probe'], 1.0)
        self.assertEqual(out['ADCPX_BTvsMB_pct'], 3.0)
        self.assertEqual(out['ADCPX_PingOverlap'], 2)

    def test_frozen_alarm_persistence_clear_stale_and_determinism(self):
        records = [
            {'timestamp': 0.1, 'fields': {'ah': 212.4, 'gh': 10}},
            {'timestamp': 61, 'fields': {'ah': 212.4, 'gh': 28}},
            {'timestamp': 63, 'fields': {'ah': 212.4, 'gh': 29}},
            {'timestamp': 64, 'fields': {'ah': 215, 'gh': 30}},
            {'timestamp': 66, 'fields': {'ah': 215, 'gh': 30}},
            {'timestamp': 80, 'fields': {}},
        ]
        one = self.make_transform()
        two = self.make_transform()
        outputs = [one.transform(record) for record in records]
        self.assertEqual(outputs, [two.transform(record) for record in records])
        self.assertTrue(outputs[1]['fields']['ADCPX_HeadingFrozen'])
        self.assertFalse(outputs[1]['fields']['ADCPX_Alarm'])
        self.assertTrue(outputs[2]['fields']['ADCPX_Alarm'])
        self.assertIn('Check the heading feed into UHDAS',
                      outputs[2]['fields']['ADCPX_AlarmText'])
        self.assertFalse(outputs[4]['fields']['ADCPX_Alarm'])
        self.assertTrue(outputs[5]['fields']['ADCPX_Stale'])

    def test_none_list_and_das_record(self):
        transform = self.make_transform()
        self.assertIsNone(transform.transform(None))
        self.assertEqual(len(transform.transform([{'timestamp': 1, 'fields': {}}])), 1)
        result = transform.transform(DASRecord(timestamp=2, fields={'ah': 10, 'gh': 11}))
        self.assertIsInstance(result, DASRecord)


if __name__ == '__main__':
    unittest.main()
