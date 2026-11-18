import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from logger.utils.das_record import DASRecord
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
        fields = transform.transform(original)['fields']
        self.assertEqual(list(fields.items())[:3], list(original['fields'].items()))
        self.assertEqual(fields['SeaTemp_QC_gross_range'], 4)

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
            (31, 30, 3, 'UNDECIDED: jump matches a change in Salt; '
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
            self.assertIn('UNDECIDED', fields['SeaTemp_QC_reason'])
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


if __name__ == '__main__':
    unittest.main()
