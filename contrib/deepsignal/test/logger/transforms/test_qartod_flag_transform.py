import unittest
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import re
from statistics import median
import time
from unittest.mock import patch

from logger.transforms.parse_transform import ParseTransform
from logger.utils.das_record import DASRecord
from contrib.deepsignal.logger.transforms import qartod_flag_transform
from contrib.deepsignal.logger.transforms.qartod_flag_transform import QartodFlagTransform


def record(timestamp=100, **fields):
    return {'timestamp': timestamp, 'fields': fields}


def transform_for(**tests):
    return QartodFlagTransform(fields={'SeaTemp': tests}, per_test_flags=True)


class QartodFlagTransformTest(unittest.TestCase):
    def test_gross_range(self):
        transform = transform_for(gross_range={'fail_span': [-2, 40], 'suspect_span': [0, 32]})
        for value, flag in [(15, 1), (0, 1), (32, 1), (-2, 3), (40, 3), (33, 3), (-3, 4), (41, 4)]:
            with self.subTest(value=value):
                flags = transform.transform(record(SeaTemp=value))['fields']
                self.assertEqual(flags['SeaTemp_QC_gross_range'], flag)
                self.assertEqual(flags['SeaTemp_QC'], flag)
        transform = transform_for(gross_range={'fail_span': [-2, 40]})
        self.assertEqual(transform.transform(record(SeaTemp=-2))['fields']['SeaTemp_QC'], 1)

    def test_climatology_static_and_utc_months(self):
        transform = transform_for(climatology={'suspect_span': [0, 32]})
        for value, expected in [(32, 1), (33, 3)]:
            fields = transform.transform(record(SeaTemp=value))['fields']
            self.assertEqual(fields['SeaTemp_QC_climatology'], expected)

        transform = transform_for(climatology={'months': [
            {'months': [1, 2], 'suspect_span': [0, 10]},
            {'months': [3], 'suspect_span': [10, 20]},
        ]})
        for month, flag in [(2, 1), (3, 3), (4, 2)]:
            timestamp = datetime(2024, month, 1, tzinfo=timezone.utc).timestamp()
            fields = transform.transform(record(timestamp, SeaTemp=5))['fields']
            self.assertEqual(fields['SeaTemp_QC_climatology'], flag)

    def test_spike_uses_prior_median_and_default_window(self):
        for value, expected in [(11, 1), (12, 3), (13, 4)]:
            with self.subTest(value=value):
                transform = transform_for(spike={'suspect': 1, 'fail': 2})
                for timestamp, sample in enumerate([10, 15, 9], start=100):
                    fields = transform.transform(record(timestamp, SeaTemp=sample))['fields']
                    self.assertEqual(fields['SeaTemp_QC_spike'], 2)
                fields = transform.transform(record(103, SeaTemp=value))['fields']
                self.assertEqual(fields['SeaTemp_QC_spike'], expected)

    def test_rate_of_change_uses_seconds_and_checks_positive_step(self):
        transform = transform_for(rate_of_change={'max_rate': 2})
        for timestamp, value, flag in [(100, 10, 2), (102, 14, 1), (103, 17, 3),
                                       (103, 18, 2), (102, 18, 2)]:
            fields = transform.transform(record(timestamp, SeaTemp=value))['fields']
            self.assertEqual(fields['SeaTemp_QC_rate_of_change'], flag)

    def test_flat_line_duration_and_current_value_tolerance(self):
        transform = transform_for(flat_line={'tolerance': 0.5, 'suspect_seconds': 2,
                                             'fail_seconds': 4})
        for timestamp, value, flag in [(100, 5, 2), (101, 5.5, 1), (102, 5, 3),
                                       (104, 5.5, 4), (107, 6, 3), (111, 7, 1),
                                       (112, 7, 1), (115, 7, 4)]:
            with self.subTest(timestamp=timestamp):
                fields = transform.transform(record(timestamp, SeaTemp=value))['fields']
                self.assertEqual(fields['SeaTemp_QC_flat_line'], flag)

    def test_timing_order_gap_future_and_unusable_timestamp(self):
        transform = transform_for(timing={'max_gap_seconds': 10})
        with patch('time.time', return_value=120):
            for timestamp, expected in [(100, 1), (110, 1), (121, 3), (121, 4),
                                        (120, 4), (180, 3), (181, 4), (None, 2)]:
                with self.subTest(timestamp=timestamp):
                    fields = transform.transform(record(timestamp, SeaTemp=10))['fields']
                    self.assertEqual(fields['SeaTemp_QC_timing'], expected)

    def test_timing_uses_previous_record_even_if_field_absent(self):
        transform = QartodFlagTransform(fields={
            'SeaTemp': {'timing': {'max_gap_seconds': 10}},
            'Salt': {'timing': {'max_gap_seconds': 10}},
        })
        transform.transform(record(100, Other=5))
        fields = transform.transform(record(112, SeaTemp=10, Salt=31))['fields']
        self.assertEqual((fields['SeaTemp_QC'], fields['Salt_QC']), (3, 3))

    def test_timing_checks_present_missing_values_without_overriding_missing(self):
        transform = transform_for(timing={}, gross_range={'fail_span': [0, 40]})
        transform.transform(record(100, SeaTemp=10))
        fields = transform.transform(record(100, SeaTemp=None))['fields']
        self.assertEqual(fields['SeaTemp_QC'], 9)
        self.assertEqual(fields['SeaTemp_QC_timing'], 4)
        self.assertEqual(fields['SeaTemp_QC_gross_range'], 2)

    def test_aggregate_priority_and_per_test_flags(self):
        transform = transform_for(gross_range={'fail_span': [0, 50], 'suspect_span': [5, 30]},
                                  spike={'suspect': 1, 'fail': 2, 'window': 1})
        for value, expected in [(10, 1), (31, 4), (32, 3), (51, 4), (None, 9)]:
            fields = transform.transform(record(SeaTemp=value))['fields']
            self.assertEqual(fields['SeaTemp_QC'], expected)
            if value is not None:
                self.assertIn('SeaTemp_QC_gross_range', fields)
                self.assertIn('SeaTemp_QC_spike', fields)
                if expected == 4 and value == 31:
                    self.assertIn('spike', fields['SeaTemp_QC_reason'])

        transform = QartodFlagTransform(fields={'SeaTemp': {'spike': {'suspect': 1, 'fail': 2}}},
                                        flag_suffix='_quality')
        output = transform.transform(record(SeaTemp=10))['fields']
        self.assertEqual(output, {'SeaTemp': 10, 'SeaTemp_quality': 2})

    def test_missing_absent_and_syntax(self):
        transform = transform_for(gross_range={'fail_span': [-2, 40]})
        for value in [None, float('nan'), '']:
            fields = transform.transform(record(SeaTemp=value))['fields']
            self.assertIs(fields['SeaTemp'], value)
            self.assertEqual(fields['SeaTemp_QC'], 9)
            self.assertNotIn('SeaTemp_QC_reason', fields)
        for value in ['10', False, True, float('inf')]:
            fields = transform.transform(record(SeaTemp=value))['fields']
            self.assertIs(fields['SeaTemp'], value)
            self.assertEqual(fields['SeaTemp_QC'], 4)
            self.assertIn('syntax', fields['SeaTemp_QC_reason'])
        self.assertEqual(transform.transform(record(Salt=30))['fields'], {'Salt': 30})

    def test_history_skips_syntax_and_gross_range_failures(self):
        transform = transform_for(
            gross_range={'fail_span': [0, 20]},
            spike={'suspect': 1, 'fail': 2, 'window': 2},
            rate_of_change={'max_rate': 1},
            flat_line={'tolerance': 1, 'suspect_seconds': 2, 'fail_seconds': 4},
        )
        for timestamp, value in enumerate([10, 99, '10', 11], start=100):
            transform.transform(record(timestamp, SeaTemp=value))
        fields = transform.transform(record(104, SeaTemp=10))['fields']
        self.assertEqual(fields['SeaTemp_QC_spike'], 1)
        self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 1)
        self.assertEqual(fields['SeaTemp_QC_flat_line'], 4)
        transform.transform(record(105, SeaTemp=99))
        fields = transform.transform(record(106, SeaTemp=12))['fields']
        self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 1)

    def test_rejected_repeated_timestamp_preserves_flat_line_history(self):
        settings = dict(gross_range={'fail_span': [0, 20]},
                        flat_line={'tolerance': 1, 'suspect_seconds': 1,
                                   'fail_seconds': 1})
        transform = transform_for(**settings)
        for timestamp, value in [(100, 10), (100, 99)]:
            transform.transform(record(timestamp, SeaTemp=value))
        fields = transform.transform(record(101, SeaTemp=10))['fields']
        self.assertEqual(fields['SeaTemp_QC'], 4)
        self.assertEqual(fields['SeaTemp_QC_flat_line'], 4)

        transform = transform_for(**settings)
        for timestamp, value in [(100, 10), (100, 20)]:
            transform.transform(record(timestamp, SeaTemp=value))
        fields = transform.transform(record(101, SeaTemp=10))['fields']
        self.assertEqual(fields['SeaTemp_QC_flat_line'], 1)

    def test_preserves_record_type_timestamp_field_order_and_input(self):
        transform = transform_for(gross_range={'fail_span': [-2, 40]})
        timestamp = 100.123456789
        values = {'Other': [1, 2], 'SeaTemp': 10.0123456789, 'Salt': 32}
        das = DASRecord(data_id='mwx1', message_type='MET', timestamp=timestamp,
                        fields=values.copy(), metadata={'unit': 'C'})
        # A DASRecord constructor may replace zero with wall time.
        das.timestamp = 0
        mapping = {'timestamp': timestamp, 'fields': values.copy(), 'source': 'sample'}
        inputs = [das, mapping]
        result = transform.transform(inputs)

        self.assertIsNot(result, inputs)
        self.assertIsInstance(result[0], DASRecord)
        self.assertIsInstance(result[1], dict)
        self.assertIsNot(result[0], das)
        self.assertIsNot(result[1], mapping)
        self.assertIs(result[0].timestamp, das.timestamp)
        self.assertIs(result[1]['timestamp'], timestamp)
        self.assertEqual(result[0].data_id, 'mwx1')
        self.assertEqual(result[0].message_type, 'MET')
        self.assertEqual(result[0].metadata, {'unit': 'C'})
        self.assertEqual(result[1]['source'], 'sample')
        for output in [result[0].fields, result[1]['fields']]:
            self.assertEqual(list(output)[:len(values)], list(values))
            for name, value in values.items():
                self.assertIs(output[name], value)
            self.assertEqual(output['SeaTemp_QC'], 1)
        self.assertEqual(das.fields, values)
        self.assertEqual(mapping['fields'], values)
        self.assertIsNone(transform.transform(None))
        self.assertEqual(transform.transform([]), [])

    def test_existing_qc_field_is_preserved(self):
        transform = transform_for(gross_range={'fail_span': [0, 40]})
        original = record(SeaTemp=50, SeaTemp_QC='original', SeaTemp_QC_reason='original reason')
        snapshot = deepcopy(original)
        with self.assertRaisesRegex(ValueError, 'SeaTemp_QC'):
            transform.transform(original)
        self.assertEqual(list(original['fields'].items()), list(snapshot['fields'].items()))
        retry = QartodFlagTransform(fields={'SeaTemp': {'gross_range': {'fail_span': [0, 40]}}},
                                    flag_suffix='_quality', per_test_flags=True)
        fields = retry.transform(original)['fields']
        self.assertEqual(list(fields.items())[:3], list(snapshot['fields'].items()))
        self.assertEqual(fields['SeaTemp_quality_gross_range'], 4)

    def test_raw_string_passes_through_with_one_warning(self):
        transform = transform_for()
        raw = '2014-08-01 MET,12.1'
        with self.assertLogs(level='WARNING') as messages:
            self.assertIs(transform.transform(raw), raw)
            self.assertEqual(transform.transform([raw, raw]), [raw, raw])
        self.assertEqual(len(messages.output), 1)
        self.assertIn('put a parse transform before', messages.output[0].lower())

    def test_front_moving_flat_missing_bad_and_without_prior_value(self):
        scenarios = [
            (31, 30, 3, 'AMBIGUOUS: jump matches a change in Salt; '
             'may be a real front, check before trusting or discarding'),
            (30, 30, 4, 'FAIL: spike 4.0 over limit 2.0'),
            (None, 30, 4, 'FAIL: spike 4.0 over limit 2.0; Salt missing'),
            (50, 30, 4, 'FAIL: spike 4.0 over limit 2.0; Salt bad'),
            ('31', 30, 4, 'FAIL: spike 4.0 over limit 2.0; Salt bad'),
            (31, None, 4, 'FAIL: spike 4.0 over limit 2.0; '
             'Salt has no previous good value in the jump window'),
        ]
        for salt, prior, flag, reason in scenarios:
            with self.subTest(salt=salt, prior=prior):
                transform = QartodFlagTransform(fields={
                    'Salt': {'gross_range': {'fail_span': [0, 40]}},
                    'SeaTemp': {
                        'spike': {'suspect': 0.5, 'fail': 2.0, 'window': 1},
                        'front_check': {'companions': ['Salt'], 'min_change': {'Salt': 0.2}},
                    },
                }, per_test_flags=True)
                transform.transform(record(100, SeaTemp=10.0, Salt=prior))
                sample = record(101, SeaTemp=14.0)
                if salt is not None:
                    sample['fields']['Salt'] = salt
                fields = transform.transform(sample)['fields']
                self.assertEqual(fields['SeaTemp_QC_spike'], flag)
                self.assertEqual(fields['SeaTemp_QC'], flag)
                self.assertEqual(fields['SeaTemp_QC_reason'], reason)

    def test_front_rate_and_hard_failures_take_priority(self):
        transform = QartodFlagTransform(fields={
            'SeaTemp': {
                'gross_range': {'fail_span': [0, 20]},
                'rate_of_change': {'max_rate': 2},
                'timing': {},
                'front_check': {'companions': ['Salt'], 'min_change': {'Salt': 0.2}},
            },
            'Salt': {},
        }, per_test_flags=True)
        with patch('time.time', return_value=100):
            transform.transform(record(100, SeaTemp=10, Salt=30))
            fields = transform.transform(record(101, SeaTemp=14, Salt=31))['fields']
            self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 3)
            self.assertEqual(fields['SeaTemp_QC_reason'],
                             'AMBIGUOUS: jump matches a change in Salt; '
                             'may be a real front, check before trusting or discarding')
            fields = transform.transform(record(102, SeaTemp=25, Salt=32))['fields']
            self.assertEqual(fields['SeaTemp_QC'], 4)
            self.assertIn('gross_range', fields['SeaTemp_QC_reason'])
            fields = transform.transform(record(170, SeaTemp=16, Salt=33))['fields']
            self.assertEqual(fields['SeaTemp_QC'], 4)
            self.assertIn('timing', fields['SeaTemp_QC_reason'])
            fields = transform.transform(record(171, SeaTemp='16', Salt=34))['fields']
            self.assertEqual(fields['SeaTemp_QC'], 4)
            self.assertIn('syntax', fields['SeaTemp_QC_reason'])

    def test_front_ignores_companion_history_older_than_jump_window(self):
        transform = QartodFlagTransform(fields={
            'SeaTemp': {
                'spike': {'window': 1, 'suspect': 1, 'fail': 2},
                'front_check': {'companions': ['Salt'], 'min_change': {'Salt': 0.2}},
            },
            'Salt': {},
        })
        transform.transform(record(100, Salt=30))
        transform.transform(record(101, SeaTemp=10))
        fields = transform.transform(record(102, SeaTemp=15, Salt=31))['fields']
        self.assertEqual(fields['SeaTemp_QC'], 4)
        self.assertIn('Salt has no previous good value', fields['SeaTemp_QC_reason'])

    def test_ambiguous_verdict_constant(self):
        self.assertEqual(qartod_flag_transform.VERDICT_AMBIGUOUS, 'AMBIGUOUS')

    def test_front_uses_previous_good_companion_in_jump_window(self):
        for salt, expected in [(30, 4), (31, 3)]:
            with self.subTest(salt=salt):
                transform = QartodFlagTransform(fields={
                    'SeaTemp': {
                        'spike': {'window': 2, 'suspect': 1, 'fail': 2},
                        'front_check': {'companions': ['Salt'], 'min_change': {'Salt': 1}},
                    },
                    'Salt': {'timing': {}},
                })
                transform.transform(record(100, SeaTemp=10, Salt=30))
                bad = transform.transform(record(99, SeaTemp=10, Salt=31))['fields']
                self.assertEqual(bad['Salt_QC'], 4)
                fields = transform.transform(record(101, SeaTemp=15, Salt=salt))['fields']
                self.assertEqual(fields['SeaTemp_QC'], expected)
                if expected == 3:
                    self.assertIn('AMBIGUOUS: jump matches a change in Salt',
                                  fields['SeaTemp_QC_reason'])
                else:
                    self.assertIn('FAIL: spike', fields['SeaTemp_QC_reason'])

    def test_front_reason_keeps_missing_companion_when_suspect_checks_tie(self):
        transform = QartodFlagTransform(fields={
            'SeaTemp': {
                'climatology': {'suspect_span': [0, 10]},
                'spike': {'window': 1, 'suspect': 1, 'fail': 5},
                'front_check': {'companions': ['Salt'], 'min_change': {'Salt': 0.2}},
            },
            'Salt': {},
        })
        transform.transform(record(100, SeaTemp=10, Salt=30))
        fields = transform.transform(record(101, SeaTemp=13))['fields']
        self.assertEqual(fields['SeaTemp_QC'], 3)
        self.assertEqual(fields['SeaTemp_QC_reason'], 'SUSPECT: spike 3 over limit 1; Salt missing')

    def test_configuration_errors_explain_setting_value_expectation_and_example(self):
        with self.assertRaisesRegex(ValueError, r'fields.*got missing.*expected.*Good example'):
            QartodFlagTransform()
        cases = [
            ({'range': {}}, 'range', 'range'),
            ({'gross_range': {}}, 'gross_range.fail_span', 'missing'),
            ({'gross_range': {'fail_span': [40, -2]}}, 'gross_range.fail_span', '[40, -2]'),
            ({'spike': {'suspect': 0, 'fail': 2}}, 'spike.suspect', '0'),
            ({'spike': {'suspect': 1}}, 'spike.fail', 'missing'),
            ({'spike': {'suspect': 1, 'fail': 2, 'window': 1.5}}, 'spike.window', '1.5'),
            ({'spike': {'suspect': 2, 'fail': 1}}, 'spike.fail', '1'),
            ({'rate_of_change': {}}, 'rate_of_change.max_rate', 'missing'),
            ({'rate_of_change': {'max_rate': -1}}, 'rate_of_change.max_rate', '-1'),
            ({'flat_line': {'tolerance': 0.01, 'suspect_seconds': 1}},
             'flat_line.fail_seconds', 'missing'),
            ({'timing': {'max_future_seconds': False}}, 'timing.max_future_seconds', 'False'),
            ({'timing': {'max_gap_seconds': 0}}, 'timing.max_gap_seconds', '0'),
            ({'climatology': {'months': [{'months': [13], 'suspect_span': [0, 32]}]}},
             'climatology.months', '13'),
            ({'climatology': {'months': [{'months': [True], 'suspect_span': [0, 32]}]}},
             'climatology.months', 'True'),
            ({'climatology': {'months': [{'months': [1], 'suspect_span': [0, 0]}]}},
             'climatology.months.suspect_span', '[0, 0]'),
            ({'front_check': {'companions': ['Unknown'], 'min_change': {'Unknown': 0.2}}},
             'front_check.companions', 'Unknown'),
            ({'front_check': {'companions': ['Salt'], 'min_change': {}}},
             'front_check.min_change', 'missing'),
        ]
        for config, setting, value in cases:
            with self.subTest(setting=setting, value=value):
                with self.assertRaises(ValueError) as error:
                    QartodFlagTransform(fields={'SeaTemp': config, 'Salt': {}})
                message = str(error.exception)
                for text in ['SeaTemp', setting, value, 'expected', 'example']:
                    self.assertIn(text, message)
                self.assertEqual(len(message.splitlines()), 1)

    def test_review_1_output_collision(self):
        fields = {
            'T': {'spike': {'suspect': 1, 'fail': 2, 'window': 1},
                  'timing': {'max_gap_seconds': 10},
                  'front_check': {'companions': ['S'], 'min_change': {'S': 1}}},
            'S': {},
        }
        for name, collision in [('T_QC', record(110, T=None, T_QC=1, T_QC_2=1)),
                                ('S_QC', record(110, T=14, S=31, S_QC=4)),
                                ('T_QC_reason', record(110, T=None, T_QC_reason='raw')),
                                ('T_QC_spike', record(110, T=None, T_QC_spike=1))]:
            with self.subTest(name=name):
                transform = QartodFlagTransform(fields=fields, per_test_flags=True)
                transform.transform(record(100, T=10, S=30))
                snapshot = deepcopy(collision)
                with self.assertRaisesRegex(ValueError, name) as error:
                    transform.transform([record(105, T=11, S=29), collision])
                self.assertEqual(collision, snapshot)
                self.assertEqual(list(collision['fields']), list(snapshot['fields']))
                suffix = re.search(r"flag_suffix: '([^']+)'", str(error.exception))[1]
                retry = QartodFlagTransform(fields=fields, flag_suffix=suffix, per_test_flags=True)
                output = retry.transform(collision)['fields']
                if collision['fields']['T'] is None:
                    self.assertEqual(output['T' + suffix], 9)
                output = transform.transform(record(112, T=14, S=30))['fields']
                self.assertEqual(output['T_QC_timing'], 3)
                self.assertEqual(output['T_QC_spike'], 4)

    def test_review_2_decimal_values(self):
        transform = transform_for(gross_range={'fail_span': [0, 40]},
                                  spike={'suspect': 1, 'fail': 2, 'window': 2},
                                  rate_of_change={'max_rate': 1},
                                  flat_line={'tolerance': 1, 'suspect_seconds': 4,
                                             'fail_seconds': 6})
        transform.transform(record(98, SeaTemp=1.5))
        transform.transform(record(99, SeaTemp=1.6))
        for timestamp, value, flag in [(100, Decimal('NaN'), 9), (101, Decimal('1.5'), 1)]:
            with self.subTest(value=value):
                sample = record(timestamp, SeaTemp=value)
                fields = transform.transform(sample)['fields']
                self.assertIs(fields['SeaTemp'], value)
                self.assertIs(sample['fields']['SeaTemp'], value)
                self.assertEqual(fields['SeaTemp_QC'], flag)
                for test in ('gross_range', 'spike', 'rate_of_change', 'flat_line'):
                    self.assertEqual(fields['SeaTemp_QC_' + test], 1 if flag == 1 else 2)

    def test_review_3_rate_overflow(self):
        transform = transform_for(gross_range={'fail_span': [0, 40]},
                                  rate_of_change={'max_rate': 1})
        transform.transform(record(100, SeaTemp=1))
        value = 10**400
        fields = transform.transform(record(101, SeaTemp=value))['fields']
        self.assertIs(fields['SeaTemp'], value)
        self.assertEqual(fields['SeaTemp_QC_gross_range'], 4)
        self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 3)
        self.assertTrue(fields['SeaTemp_QC_reason'].startswith('FAIL: gross_range'))

    def test_review_4_roundoff_boundaries(self):
        for baseline, current, expected in [(30.0, 30.2, 3), (30.2, 30.0, 3),
                                            (30.0, 30.1999999999, 4)]:
            with self.subTest(companion=(baseline, current)):
                transform = QartodFlagTransform(fields={
                    'T': {'spike': {'suspect': 1, 'fail': 2, 'window': 1},
                          'front_check': {'companions': ['S'], 'min_change': {'S': 0.2}}},
                    'S': {},
                })
                transform.transform(record(100, T=10, S=baseline))
                fields = transform.transform(record(101, T=14, S=current))['fields']
                self.assertEqual(fields['T_QC'], expected)
                if expected == 3:
                    self.assertIn('AMBIGUOUS: jump matches a change in S;', fields['T_QC_reason'])
        for baseline, current, expected in [(1.0, 1.1, 1), (1.1, 1.0, 1),
                                            (1.0, 1.1000000001, 3)]:
            with self.subTest(rate=(baseline, current)):
                transform = transform_for(rate_of_change={'max_rate': 0.1})
                transform.transform(record(100, SeaTemp=baseline))
                fields = transform.transform(record(101, SeaTemp=current))['fields']
                self.assertEqual(fields['SeaTemp_QC_rate_of_change'], expected)
        transform = transform_for(rate_of_change={'max_rate': 0.1})
        transform.transform(record(100.1, SeaTemp=1))
        fields = transform.transform(record(Decimal('100.1'), SeaTemp=2))['fields']
        self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 2)

    def test_review_5_even_median(self):
        for values in [(1e308, 1e308, 1e308), (-1e308, 1e308, 0)]:
            with self.subTest(values=values):
                transform = transform_for(spike={'suspect': 1, 'fail': 2, 'window': 2})
                for timestamp, value in enumerate(values, start=100):
                    fields = transform.transform(record(timestamp, SeaTemp=value))['fields']
                self.assertEqual(fields['SeaTemp_QC_spike'], 1)
                self.assertNotIn('SeaTemp_QC_reason', fields)

    def test_review_6_unusable_timestamp_breaks_baseline(self):
        transform = transform_for(timing={'max_gap_seconds': 10})
        with patch('time.time', return_value=120):
            for timestamp, expected in [(100, 1), (None, 2), (120, 1), (None, 2), (181, 4)]:
                with self.subTest(timestamp=timestamp):
                    fields = transform.transform(record(timestamp, SeaTemp=10))['fields']
                    self.assertEqual(fields['SeaTemp_QC_timing'], expected)
        self.assertIn('ahead of wall time', fields['SeaTemp_QC_reason'])

    def test_review_7_companion_chains_and_cycles(self):
        cases = [(['C'], 1, (3, 3)), (['A'], 1, (4, 4)),
                 (['A', 'C'], 1, (3, 3)), (['A', 'C'], 0, (4, 4))]
        for b_companions, c_change, expected in cases:
            for as_configured in ('ABC', 'CBA'):
                with self.subTest(companions=b_companions, change=c_change, order=as_configured):
                    settings = {}
                    for name, companions in [('A', ['B']), ('B', b_companions)]:
                        settings[name] = {
                            'spike': {'suspect': 1, 'fail': 2, 'window': 1},
                            'front_check': {'companions': companions,
                                            'min_change': dict.fromkeys(companions, 1)},
                        }
                    settings['C'] = {}
                    transform = QartodFlagTransform(fields={n: settings[n] for n in as_configured})
                    transform.transform(record(100, A=0, B=0, C=0))
                    flags = transform.transform(record(101, A=4, B=4, C=c_change))['fields']
                    self.assertEqual((flags['A_QC'], flags['B_QC']), expected)
                    if expected == (3, 3):
                        self.assertIn('matches a change in B;', flags['A_QC_reason'])
                        self.assertIn('matches a change in C;', flags['B_QC_reason'])
                        flags = transform.transform(record(102, A=0, B=3, C=c_change))['fields']
                        self.assertEqual(flags['A_QC'], 3)

    def test_review_8_hard_failure_reason(self):
        transform = QartodFlagTransform(fields={
            'T': {'gross_range': {'fail_span': [0, 20]},
                  'spike': {'suspect': 1, 'fail': 2, 'window': 1},
                  'front_check': {'companions': ['S'], 'min_change': {'S': 1}}},
            'S': {'gross_range': {'fail_span': [0, 40]}},
        })
        transform.transform(record(100, T=10, S=30))
        for timestamp, companion, expected in [(101, {}, 'S missing'), (102, {'S': 50}, 'S bad')]:
            with self.subTest(companion=companion):
                fields = transform.transform(record(timestamp, T=25, **companion))['fields']
                self.assertEqual(fields['T_QC'], 4)
                self.assertEqual(fields['T_QC_reason'], f'FAIL: gross_range 25 outside [0, 20]; '
                                 f'{expected}')

    def test_review_9_configuration_diagnostics(self):
        for fields, kwargs, setting, example in [
            ({'T': {}}, {'per_test_flag': True}, 'per_test_flag', 'per_test_flags: true'),
            ({'T': {}}, {'per_test\nflag': True}, r'per_test\nflag', 'per_test_flags: true'),
            ({'T': {'typo\nname': {}}}, {}, r'typo\nname', 'gross_range:'),
            ({'T': {'spike': {'odd\nkey': 2}}}, {}, r'spike.odd\nkey', 'window: 3'),
            ({'T': {}, 'T_QC': {}, 'T_QC_2': {}}, {}, 'flag_suffix', 'flag_suffix:'),
            ({'T': {'spike': {'window': 1, 'suspect': 1, 'fail': 2}}, 'T_alt_spike': {}},
             {'flag_suffix': '_alt', 'per_test_flags': True}, 'flag_suffix', 'flag_suffix:'),
        ]:
            with self.subTest(fields=fields, kwargs=kwargs):
                with self.assertRaises(ValueError) as error:
                    QartodFlagTransform(fields=fields, **kwargs)
                message = str(error.exception)
                self.assertEqual(len(message.splitlines()), 1)
                for part in (setting, 'got', 'expected', 'Good example', example):
                    self.assertIn(part, message)
                if setting == 'flag_suffix':
                    suffix = re.search(r"flag_suffix: '([^']+)'", message)[1]
                    QartodFlagTransform(fields=fields, **dict(kwargs, flag_suffix=suffix))

    def test_review_10_full_input_snapshot(self):
        values = {'Z': [1, 2], 'SeaTemp': 10.125, 'Salt': 32}
        inputs = [DASRecord(data_id='mwx1', message_type='MET', timestamp=100.125,
                            fields=deepcopy(values), metadata={'unit': 'C'}),
                  {'source': 'sample', 'fields': deepcopy(values), 'timestamp': 101.125}]
        transform = transform_for(gross_range={'fail_span': [0, 40]})
        for sample in inputs:
            with self.subTest(record_type=type(sample)):
                source = vars(sample) if isinstance(sample, DASRecord) else sample
                snapshot = deepcopy(source)
                result = transform.transform(sample)
                output = vars(result) if isinstance(result, DASRecord) else result
                self.assertEqual(list(source.items()), list(snapshot.items()))
                self.assertEqual(list(source['fields'].items()), list(snapshot['fields'].items()))
                self.assertEqual(output['timestamp'], snapshot['timestamp'])
                self.assertEqual(list(output['fields'].items())[:len(values)], list(values.items()))

    def test_review_11_history_and_config_guards(self):
        transform = transform_for(flat_line={'tolerance': 1, 'suspect_seconds': 2,
                                             'fail_seconds': 4})
        for timestamp in range(100, 120):
            transform.transform(record(timestamp, SeaTemp=10))
        self.assertEqual([stamp for stamp, _ in transform.flat_history['SeaTemp']],
                         [115, 116, 117, 118, 119])

        transform = QartodFlagTransform(fields={
            'T': {'spike': {'suspect': 1, 'fail': 2, 'window': 3},
                  'rate_of_change': {'max_rate': 1},
                  'front_check': {'companions': ['S'], 'min_change': {'S': 1}}},
            'S': {},
        })
        transform.transform(record(100, T=10, S=30))
        transform.transform(record(101, T=10))
        output = transform.transform(record(102, T=14, S=31))['fields']
        self.assertEqual(output['T_QC_reason'],
                         'SUSPECT: rate_of_change 4 per second over limit 1; '
                         'S has no previous good value in the jump window')

        transform = QartodFlagTransform(fields={
            'T': {'spike': {'suspect': 1, 'fail': 2, 'window': 1},
                  'rate_of_change': {'max_rate': 1},
                  'flat_line': {'tolerance': 1, 'suspect_seconds': 1, 'fail_seconds': 2},
                  'front_check': {'companions': ['S'], 'min_change': {'S': 1}}},
            'S': {},
        }, per_test_flags=True)
        transform.transform(record(100, T=10, S=30))
        for timestamp, flat_flag in [(101, 3), (102, 4)]:
            output = transform.transform(record(timestamp, T=10, S=30 + timestamp - 100))['fields']
            self.assertEqual((output['T_QC_spike'], output['T_QC_rate_of_change']), (1, 1))
            self.assertEqual(output['T_QC_flat_line'], flat_flag)
            self.assertEqual(output['T_QC'], flat_flag)
            self.assertIn('flat_line', output['T_QC_reason'])

        with self.assertRaisesRegex(ValueError, 'distinct months'):
            transform_for(climatology={'months': [
                {'months': [1], 'suspect_span': [0, 10]},
                {'months': [1], 'suspect_span': [10, 20]},
            ]})
        with self.assertRaisesRegex(ValueError, 'distinct months'):
            transform_for(climatology={'months': [{'months': [1, 1], 'suspect_span': [0, 10]}]})
        with self.assertRaisesRegex(ValueError, 'flag_suffix.*nonempty string'):
            QartodFlagTransform(fields={'T': {}}, flag_suffix='')

    def test_review_12_quickstart_and_worked_error(self):
        guide = Path(qartod_flag_transform.__file__).parents[2] / 'docs' / 'qartod_flags.md'
        content = guide.read_text(encoding='utf-8')
        with self.subTest(section='quickstart'):
            self.assertIn('test/NBP1406/data/mwx1', content)
            self.assertLess(content.index('test/NBP1406/data/mwx1'),
                            content.index('python logger/listener/listen.py'))
        with self.subTest(section='worked error'):
            with self.assertRaises(ValueError) as error:
                transform_for(rate_of_change={'max_rate': 0})
            self.assertIn(str(error.exception), content)
            self.assertRegex(content, r'(?m)^ +max_rate: 0\.5$')

    def test_review_13_utc_conversion_diagnostic(self):
        transform = transform_for(
            climatology={'months': [{'months': [1], 'suspect_span': [0, 10]}]}, timing={})
        timestamp = -10**20
        with (patch('time.monotonic', side_effect=[0, 1, 59, 60]),
              self.assertLogs(level='WARNING') as messages):
            for _ in range(4):
                outcome = transform.transform(record(timestamp, SeaTemp=5))
                self.assertIs(outcome['timestamp'], timestamp)
                self.assertEqual(outcome['fields']['SeaTemp_QC_climatology'], 2)
        self.assertEqual(len(messages.output), 2)
        self.assertIn('UTC', messages.output[0])
        self.assertIn(str(timestamp), messages.output[0])

    def test_fix2_mixed_decimal_float_boundaries(self):
        for span, value, expected in [([0.1, 1], Decimal('0.1'), 1),
                                      ([0, 0.1], Decimal('0.100000000000000003'), 4),
                                      ([Decimal('0.1'), 1.0], 0.1, 1)]:
            with self.subTest(span=span, value=value):
                transform = transform_for(gross_range={'fail_span': span})
                fields = transform.transform(record(SeaTemp=value))['fields']
                self.assertEqual(fields['SeaTemp_QC_gross_range'], expected)

    def test_fix2_extreme_values_reach_caller(self):
        for value in (10**4300, Decimal('1e5000')):
            with self.subTest(value_type=type(value)):
                transform = transform_for(gross_range={'fail_span': [0, 40]},
                                          rate_of_change={'max_rate': 1})
                transform.transform(record(100, SeaTemp=1))
                fields = transform.transform(record(101, SeaTemp=value))['fields']
                self.assertEqual(fields['SeaTemp_QC'], 4)
                self.assertEqual(fields['SeaTemp_QC_gross_range'], 4)
                self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 3)
                self.assertLess(len(fields['SeaTemp_QC_reason']), 200)

    def test_fix2_fraction_reasons_are_compatible_and_precise(self):
        transform = transform_for(spike={'suspect': 1, 'fail': 2, 'window': 1})
        transform.transform(record(100, SeaTemp=0))
        fields = transform.transform(record(101, SeaTemp=3))['fields']
        self.assertEqual(fields['SeaTemp_QC_reason'], 'FAIL: spike 3 over limit 2')

        transform = transform_for(rate_of_change={'max_rate': 0.1})
        transform.transform(record(100, SeaTemp=1.0))
        fields = transform.transform(record(101, SeaTemp=1.1000000001))['fields']
        self.assertEqual(fields['SeaTemp_QC_reason'],
                         'SUSPECT: rate_of_change 0.1000000001 per second over limit 0.1')

    def test_fix2_front_evidence_cannot_return_to_source(self):
        transform = QartodFlagTransform(fields={
            'A': {'spike': {'suspect': 1, 'fail': 2, 'window': 1},
                  'front_check': {'companions': ['B'], 'min_change': {'B': 1}}},
            'B': {'spike': {'suspect': 1, 'fail': 2, 'window': 1},
                  'front_check': {'companions': ['A'], 'min_change': {'A': 1}}},
        })
        transform.transform(record(100, A=0, B=0))
        fields = transform.transform(record(101, A=4, B=2))['fields']
        self.assertEqual((fields['A_QC'], fields['B_QC']), (3, 3))
        self.assertIn('matches a change in B', fields['A_QC_reason'])
        self.assertNotIn('AMBIGUOUS', fields['B_QC_reason'])

    def test_fix2_flat_line_failure_wins_jump_tie(self):
        transform = QartodFlagTransform(fields={
            'T': {'flat_line': {'tolerance': 1, 'suspect_seconds': 1, 'fail_seconds': 2},
                  'spike': {'suspect': 0.1, 'fail': 0.2, 'window': 1},
                  'front_check': {'companions': ['S'], 'min_change': {'S': 1}}},
            'S': {},
        })
        transform.transform(record(100, T=10, S=0))
        transform.transform(record(101, T=10.1, S=0))
        fields = transform.transform(record(102, T=10.3))['fields']
        self.assertEqual(fields['T_QC'], 4)
        self.assertIn('FAIL: flat_line', fields['T_QC_reason'])
        self.assertIn('S missing', fields['T_QC_reason'])

    def test_fix2_flat_line_sustained_throughput(self):
        transform = QartodFlagTransform(fields={
            name: {'flat_line': {'tolerance': 1, 'suspect_seconds': 300,
                                 'fail_seconds': 600}}
            for name in ('A', 'B')
        })
        for index in range(12000):
            transform.transform(record(index / 20, A=10.0, B=20.0))
        started = time.monotonic()
        for index in range(100):
            transform.transform(record(600 + index / 20, A=10.0, B=20.0))
        self.assertLess(time.monotonic() - started, 5)

    def test_fix2_configuration_guards_and_future_allowance(self):
        transform = transform_for(timing={'max_future_seconds': 5})
        with patch('time.time', return_value=100):
            fields = transform.transform(record(106, SeaTemp=1))['fields']
        self.assertEqual(fields['SeaTemp_QC_timing'], 4)

        invalid = [
            {'flat_line': {'tolerance': 1, 'suspect_seconds': 2, 'fail_seconds': 1}},
            {'climatology': {'suspect_span': [0, 1],
                             'months': [{'months': [1], 'suspect_span': [0, 1]}]}},
            {'front_check': {'companions': ['T'], 'min_change': {'T': 1}}},
        ]
        for tests in invalid:
            with self.subTest(tests=tests), self.assertRaises(ValueError):
                QartodFlagTransform(fields={'T': tests})
        with self.assertRaises(ValueError) as error:
            QartodFlagTransform(fields={'T': {}}, **{'self': True})
        self.assertIn('self', str(error.exception))
        self.assertEqual(len(str(error.exception).splitlines()), 1)

    def test_fix3_flat_line_spread_and_cutoff(self):
        transform = transform_for(flat_line={'tolerance': 1, 'suspect_seconds': 2,
                                             'fail_seconds': 4})
        for timestamp, value, flag in [(0, 0, 2), (1, 2, 1), (2, 1, 1), (3, 2, 3),
                                       (5, 1, 4), (8, 2.01, 1), (13, 1.01, 4)]:
            with self.subTest(timestamp=timestamp):
                fields = transform.transform(record(timestamp, SeaTemp=value))['fields']
                self.assertEqual(fields['SeaTemp_QC_flat_line'], flag)

    def test_fix3_flat_line_alternating_throughput(self):
        medians = []
        for window in (100, 10000):
            transform = transform_for(flat_line={'tolerance': 1, 'suspect_seconds': window / 40,
                                                 'fail_seconds': window / 20})
            for index in range(window):
                transform.transform(record(index / 20, SeaTemp=10.0))
            timings = []
            for index in range(window, window + 5000):
                sample = record(index / 20, SeaTemp=10.01 if index % 2 else 10.0)
                start = time.perf_counter_ns()
                fields = transform.transform(sample)['fields']
                timings.append(time.perf_counter_ns() - start)
                self.assertEqual(fields['SeaTemp_QC_flat_line'], 4)
            medians.append(median(timings) / 1e6)
        self.assertLess(max(medians), 5, medians)
        self.assertLessEqual(max(medians), 2 * min(medians), medians)

    def test_fix3_stock_csv_missing_timestamp(self):
        parser = ParseTransform(record_format='{timestamp:of},{field_string}',
                                field_patterns=['{SeaTemp:of}'])
        transform = transform_for(flat_line={'tolerance': 1, 'suspect_seconds': 1,
                                             'fail_seconds': 2},
                                  timing={}, rate_of_change={'max_rate': 1})
        transform.transform(parser.transform('100,10'))
        sample = parser.transform(',10')
        self.assertEqual(sample, record(None, SeaTemp=10.0))
        result = transform.transform(sample)
        self.assertIsNone(result['timestamp'])
        self.assertIs(result['fields']['SeaTemp'], sample['fields']['SeaTemp'])
        for suffix in ('', '_flat_line', '_timing', '_rate_of_change'):
            self.assertEqual(result['fields']['SeaTemp_QC' + suffix], 2)
        fields = transform.transform(parser.transform('103,10'))['fields']
        self.assertEqual(fields['SeaTemp_QC_flat_line'], 2)
        self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 2)

    def test_stock_parse_record_without_timestamp_passes_through(self):
        parser = ParseTransform(record_format='{field_string}',
                                field_patterns=['{T:of},{S:of}'])
        transform = QartodFlagTransform(fields={
            'T': {'flat_line': {'tolerance': 1, 'suspect_seconds': 1,
                                'fail_seconds': 2},
                  'timing': {}, 'rate_of_change': {'max_rate': 1}},
        }, per_test_flags=True)
        sample = parser.transform('10,30')
        self.assertEqual(sample, {'fields': {'T': 10.0, 'S': 30.0}})

        result = transform.transform(sample)

        self.assertNotIn('timestamp', result)
        self.assertIs(result['fields']['T'], sample['fields']['T'])
        self.assertIs(result['fields']['S'], sample['fields']['S'])
        self.assertEqual((result['fields']['T'], result['fields']['S']), (10.0, 30.0))
        for suffix in ('', '_flat_line', '_timing', '_rate_of_change'):
            self.assertEqual(result['fields']['T_QC' + suffix], 2)

    def test_fix3_stock_csv_extreme_spike(self):
        parser = ParseTransform(record_format='{timestamp:of},{field_string}',
                                field_patterns=['{SeaTemp:of}'])
        transform = transform_for(spike={'window': 1, 'suspect': 1, 'fail': 2})
        transform.transform(parser.transform('100,-1e308'))
        sample = parser.transform('101,1e308')
        fields = transform.transform(sample)['fields']
        self.assertIs(fields['SeaTemp'], sample['fields']['SeaTemp'])
        self.assertEqual((fields['SeaTemp_QC_spike'], fields['SeaTemp_QC']), (4, 4))
        reason = re.fullmatch(r'FAIL: spike (\S+) over limit 2', fields['SeaTemp_QC_reason'])
        self.assertIsNotNone(reason)
        self.assertEqual(Decimal(reason[1]), Decimal('2e308'))

    def test_fix3_rate_reason_precision(self):
        transform = transform_for(rate_of_change={'max_rate': 0.1})
        transform.transform(record(100, SeaTemp=1.0))
        fields = transform.transform(record(101, SeaTemp=1.1000000000000003))['fields']
        self.assertEqual(fields['SeaTemp_QC_rate_of_change'], 3)
        self.assertEqual(fields['SeaTemp_QC_reason'],
                         'SUSPECT: rate_of_change 0.1000000000000003 per second over limit 0.1')
        transform = transform_for(rate_of_change={'max_rate': 0.1})
        transform.transform(record(100, SeaTemp=-1e-40))
        fields = transform.transform(record(101, SeaTemp=0.1))['fields']
        rate = fields['SeaTemp_QC_reason'].split()[2]
        self.assertGreater(Decimal(rate), Decimal('0.1'))

    def test_fix3_companion_cycle_at_load(self):
        fields = {field: {'spike': {'window': 1, 'suspect': 1, 'fail': 2},
                          'front_check': {'companions': [other], 'min_change': {other: 1}}}
                  for field, other in zip('ABC', 'BCA')}
        with self.assertRaisesRegex(ValueError, r'front_check\.companions.*A -> B -> C -> A'):
            QartodFlagTransform(fields=fields)

    def test_fix3_oversized_spike_window(self):
        with self.assertLogs(level='WARNING') as messages:
            transform = transform_for(spike={'window': 10**4300, 'suspect': 1, 'fail': 2},
                                      gross_range={'fail_span': [0, 5]})
            for index, value in enumerate((1, 5, 10)):
                fields = transform.transform(record(index, SeaTemp=value))['fields']
                self.assertEqual(fields['SeaTemp'], value)
                self.assertEqual(fields['SeaTemp_QC_spike'], 2)
                self.assertEqual(fields['SeaTemp_QC'], 4 if value > 5 else 1)
        self.assertEqual(len(messages.output), 1)
        for part in ('SeaTemp', 'spike.window', 'NOT_EVALUATED'):
            self.assertIn(part, messages.output[0])


if __name__ == '__main__':
    unittest.main()
