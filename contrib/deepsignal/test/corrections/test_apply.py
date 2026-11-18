import json
import logging
import os
import unittest

from logger.utils.das_record import DASRecord

from contrib.deepsignal.corrections import CorrectionApplyTransform, Ledger

from .test_ledger import LedgerTestCase, proposal, transition, WHEN


TIMESTAMP = 1406937600.0


class ApplyTest(LedgerTestCase):
    def record(self, raw=10, timestamp=TIMESTAMP):
        return {'data_id': 'sensor', 'timestamp': timestamp,
                'fields': {'status': 'ok', 'temperature': raw}, 'metadata': {'units': 'C'}}

    def test_each_method_and_uncertainty(self):
        cases = (
            ('offset', {'value': 2}, 12),
            ('linear_drift', {'rate_per_day': -3, 't0': '2014-08-01T00:00:00Z'}, 7),
            ('polynomial', {'coefficients': [1, 2, 3]}, 321),
            ('time_shift', {'seconds': -2.5}, 10),
            ('gain_offset', {'offset': 2, 'gain': 4}, 2),
        )
        for method, parameters, expected in cases:
            with self.subTest(method=method):
                entry = proposal(method=method)
                del entry['value']
                entry.update(parameters)
                Ledger.append(self.path, entry)
                self.add_transition('approve', entry)
                transform = CorrectionApplyTransform(self.path, ['temperature'])
                result = transform.transform(self.record())['fields']
                self.assertEqual(result['temperature_corr'], expected)
                self.assertEqual(result['temperature_corr_id'], entry['id'])
                self.assertEqual(result['temperature_corr_u'], 0.25)
                if method == 'time_shift':
                    self.assertEqual(result['temperature_corr_time'], TIMESTAMP - 2.5)
                else:
                    self.assertNotIn('temperature_corr_time', result)
                self.add_transition('rollback', entry)

    def test_raw_values_timestamp_order_and_inputs_preserved(self):
        self.approve_entry()
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        record = self.record(raw=-0.0, timestamp=WHEN)
        record['extra'] = 'kept'
        before = json.dumps(record).encode()
        result = transform.transform(record)
        self.assertEqual(json.dumps(record).encode(), before)
        self.assertEqual(list(result), list(record))
        self.assertEqual(list(result['fields'])[:2], list(record['fields']))
        restored = result | {'fields': {name: result['fields'][name] for name in record['fields']}}
        self.assertEqual(json.dumps(restored).encode(), before)
        self.assertIsNot(result['fields'], record['fields'])

    def test_dasrecord_list_and_none(self):
        self.approve_entry()
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        record = DASRecord(timestamp=TIMESTAMP, data_id='sensor', message_type='sensor reading',
                           fields=self.record()['fields'], metadata={'units': 'C'})
        before = record.as_json()
        original = [record, None, self.record()]
        result = transform.transform(original)
        self.assertIsInstance(result[0], DASRecord)
        self.assertEqual(result[0].timestamp, record.timestamp)
        self.assertEqual(result[0].data_id, 'sensor')
        self.assertEqual(result[0].message_type, 'sensor reading')
        self.assertEqual(result[0].metadata, {'units': 'C'})
        self.assertEqual(result[0].fields['temperature_corr'], 12)
        self.assertIsNone(result[1])
        self.assertEqual(result[2]['fields']['temperature_corr'], 12)
        self.assertEqual(record.as_json(), before)
        self.assertEqual(original[2], self.record())
        self.assertIsNone(transform.transform(None))
        self.assertEqual(transform.transform([]), [])

    def test_epoch_zero_timestamp_preserved(self):
        self.approve_entry(start='1969-12-31T00:00:00Z', end='1970-01-02T00:00:00Z')
        record = DASRecord(timestamp=TIMESTAMP, fields={'temperature': 10})
        record.timestamp = 0
        output = CorrectionApplyTransform(self.path, ['temperature']).transform(record)
        self.assertEqual(output.timestamp, 0)
        self.assertEqual(output.fields['temperature_corr'], 12)

    def test_microsecond_windows_match_iso_records_exactly(self):
        start = '2400-01-01T00:00:00.000001Z'
        end = '2400-01-01T00:00:00.000002Z'
        self.approve_entry(start=start, end=end)
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        in_window = transform.transform(self.record(timestamp=start))
        self.assertEqual(in_window['fields']['temperature_corr'], 12)
        for timestamp in ('2400-01-01T00:00:00Z', end):
            with self.subTest(timestamp=timestamp):
                record = self.record(timestamp=timestamp)
                self.assertEqual(transform.transform(record), record)

    def test_reload_on_change_and_rollback_removes_effect(self):
        entry = self.add_proposal()
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        record = self.record()
        self.assertEqual(transform.transform(record), record)
        self.add_transition('approve', entry)
        self.assertIn('temperature_corr', transform.transform(record)['fields'])
        self.add_transition('rollback', entry)
        self.assertEqual(transform.transform(record), record)

    def test_overlap_warns_once_per_pair_and_skips_correction(self):
        entries = [self.approve_entry() for _ in range(3)]
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        record = self.record()
        with self.assertLogs(level=logging.WARNING) as logs:
            for _ in range(3):
                self.assertEqual(transform.transform(record), record)
        self.assertEqual(len(logs.output), 3)
        ids = [entry['id'] for entry in entries]
        pairs = {frozenset(entry_id for entry_id in ids if entry_id in message)
                 for message in logs.output}
        self.assertEqual(len(pairs), 3)
        self.assertTrue(all(len(pair) == 2 for pair in pairs))
        self.add_transition('rollback', entries[0])
        with self.assertNoLogs(level=logging.WARNING):
            self.assertEqual(transform.transform(record), record)

    def test_bad_reload_does_not_apply_stale_approval(self):
        self.approve_entry()
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        self.assertIn('temperature_corr', transform.transform(self.record())['fields'])
        with self.path.open('ab') as file:
            file.write(b'corruption\n')
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'line 3'):
                transform.transform(self.record())

    def test_existing_output_names_are_preserved(self):
        self.approve_entry()
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        record = self.record()
        record['fields']['temperature_corr_id'] = 'existing provenance'
        with self.assertLogs(level=logging.WARNING):
            self.assertEqual(transform.transform(record), record)

    def test_reload_replacement_with_same_mtime_and_size(self):
        entry = self.approve_entry()
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        self.assertEqual(transform.transform(self.record())['fields']['temperature_corr'], 12)
        replacement = self.path.with_suffix('.replacement')
        Ledger.append(replacement, entry | {'value': 3})
        Ledger.append(replacement, transition('approve', entry))
        stat = self.path.stat()
        self.assertEqual(replacement.stat().st_size, stat.st_size)
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replacement.replace(self.path)
        with self.assertRaisesRegex(ValueError, 'line 2.*verified'):
            transform.transform(self.record())

    def test_reload_rejects_truncated_rollback(self):
        entry = self.approve_entry()
        approved_history = self.path.read_bytes()
        self.add_transition('rollback', entry)
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        self.assertEqual(transform.transform(self.record()), self.record())
        self.path.write_bytes(approved_history)
        with self.assertRaisesRegex(ValueError, 'line 3.*verified'):
            transform.transform(self.record())

    def test_reload_accepts_replacement_with_verified_prefix(self):
        entry = self.approve_entry()
        transform = CorrectionApplyTransform(self.path, ['temperature'])
        self.assertIn('temperature_corr', transform.transform(self.record())['fields'])
        replacement = self.path.with_suffix('.replacement')
        replacement.write_bytes(self.path.read_bytes())
        Ledger.append(replacement, transition('rollback', entry))
        replacement.replace(self.path)
        self.assertEqual(transform.transform(self.record()), self.record())


if __name__ == '__main__':
    unittest.main()
