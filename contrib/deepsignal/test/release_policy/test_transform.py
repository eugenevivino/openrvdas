import contextlib
import hashlib
import io
import logging
import os
import tempfile
import unittest

import yaml

from logger.utils.das_record import DASRecord


POLICY = {
    'audience': 'science',
    'levels': {
        'priority*': 'public',
        'priority_private': 'shore_ops',
        'other*': 'shore_ops',
    },
    'default_level': 'science',
    'eez': {
        'inside_field': 'eez_inside',
        'hold_back': ['secret*', 'position*'],
        'position_fields': ['position_lat'],
        'position_rounding_deg': 0.1,
    },
}


class TestReleasePolicyTransform(unittest.TestCase):
    def setUp(self):
        self.addCleanup(logging.disable, logging.NOTSET)
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.policy_path = os.path.join(self.tempdir.name, 'policy.yaml')
        self.write_policy(POLICY)

    def write_policy(self, policy):
        with open(self.policy_path, 'w', encoding='utf-8') as policy_file:
            yaml.safe_dump(policy, policy_file, sort_keys=False)

    def make_transform(self):
        from contrib.deepsignal.release_policy.transform import ReleasePolicyTransform
        return ReleasePolicyTransform(self.policy_path)

    def test_audience_order_glob_precedence_and_default(self):
        transform = self.make_transform()
        result = transform.transform({'timestamp': 1, 'fields': {
            'eez_inside': False, 'priority_private': 1, 'other': 2,
            'unmatched': 3,
        }})
        self.assertEqual(result['fields']['priority_private'], 1)
        self.assertNotIn('other', result['fields'])
        self.assertEqual(result['fields']['unmatched'], 3)

    def test_eez_outside_inside_and_position_rounding(self):
        transform = self.make_transform()
        outside = transform.transform({'timestamp': 1, 'fields': {
            'eez_inside': False, 'secret_value': 2, 'position_lat': 12.36,
        }})
        self.assertEqual(outside['fields']['secret_value'], 2)
        inside = transform.transform({'timestamp': 2, 'fields': {
            'eez_inside': True, 'secret_value': 3, 'position_lat': 12.36,
        }})
        self.assertNotIn('secret_value', inside['fields'])
        self.assertEqual(inside['fields']['position_lat'], 12.4)

    def test_unknown_eez_fails_closed_and_warns_once(self):
        transform = self.make_transform()
        with self.assertLogs(level='WARNING') as logs:
            first = transform.transform({'timestamp': 1, 'fields': {
                'secret_a': 1, 'unmatched': 9,
            }})
            transform.transform({'timestamp': 2, 'fields': {
                'secret_b': 2, 'unmatched': 9,
            }})
        self.assertNotIn('secret_a', first['fields'])
        self.assertEqual(len(logs.records), 1)
        self.assertIn('unknown', logs.output[0].lower())

    def test_empty_record_is_dropped_and_input_unchanged(self):
        transform = self.make_transform()
        incoming = {'timestamp': 1, 'fields': {'secret_a': 1}}
        # The trace field means policy processing itself never makes a record empty;
        # a genuinely empty input still has no released data and is dropped.
        self.assertIsNone(transform.transform({'timestamp': 1, 'fields': {}}))
        transform.transform(incoming)
        self.assertEqual(incoming['fields'], {'secret_a': 1})

    def test_policy_hash_and_dasrecord_and_list_and_none(self):
        transform = self.make_transform()
        with open(self.policy_path, 'rb') as policy_file:
            expected = hashlib.sha256(policy_file.read()).hexdigest()[:12]
        record = DASRecord(timestamp=5, fields={'eez_inside': False, 'unmatched': 1})
        result = transform.transform([record, None])
        self.assertIsInstance(result[0], DASRecord)
        self.assertEqual(result[0].timestamp, 5)
        self.assertEqual(result[0].fields['release_policy'], expected)
        self.assertIsNone(result[1])
        self.assertIsNone(transform.transform(None))

    def test_explain_output(self):
        from contrib.deepsignal.release_policy.__main__ import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['explain', self.policy_path, 'secret_value']), 0)
        text = output.getvalue().lower()
        self.assertIn('science', text)
        self.assertIn('outside', text)
        self.assertIn('withheld', text)

    def test_config_errors_are_plain_english(self):
        for update, setting, saw, expected, example in [
                ({'audience': 'crew'}, 'audience', 'crew', 'public, science, or shore_ops',
                 'science'),
                ({'levels': {'[broken': 'public'}}, 'levels glob', '[broken',
                 'a valid shell-style glob', 'TSG_*')]:
            policy = dict(POLICY)
            policy.update(update)
            self.write_policy(policy)
            with self.subTest(setting=setting):
                with self.assertRaises(ValueError) as raised:
                    self.make_transform()
                message = str(raised.exception)
                self.assertEqual(len(message.splitlines()), 1)
                for phrase in (setting, saw, expected, example):
                    self.assertIn(phrase, message)


if __name__ == '__main__':
    unittest.main()
