import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from contrib.deepsignal.instrument_init.api import (describe_reader_sends,
                                                    propose_init)
from contrib.deepsignal.instrument_init.profile import (ProfileError,
                                                        load_profile)
from contrib.deepsignal.instrument_init.runner import AuditLog, run


class FakeTransport:
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def readline(self, timeout):
        return self.replies.pop(0) if self.replies else None


def profile(steps, **extra):
    value = {'profile_id': 'test-v1', 'version': 1, 'reviewed_by': 'Tech',
             'reviewed_on': '2026-11-18', 'source': 'test manual',
             'instrument': 'sensor-1', 'line_ending': '\r\n', 'steps': steps}
    value.update(extra)
    return load_profile(value)


class InitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audit = AuditLog(os.path.join(self.temp.name, 'audit.jsonl'))

    def tearDown(self):
        self.temp.cleanup()

    def test_sequence_match_retry_abort_and_optional(self):
        steps = [
            {'name': 'id', 'class': 'query', 'send': 'ID?', 'expect': '^OK$'},
            {'name': 'optional', 'class': 'setup', 'send': 'OPT',
             'expect': '^OK$', 'optional': True},
            {'name': 'required', 'class': 'setup', 'send': 'SET',
             'expect': '^OK$', 'retries': 1},
            {'name': 'never', 'class': 'setup', 'send': 'GO'},
        ]
        transport = FakeTransport([b'OK\r\n', b'NO\r\n', b'NO\r\n', b'NO\r\n'])
        result = run(profile(steps), transport, 'open', self.audit)
        self.assertFalse(result['ok'])
        self.assertEqual([b'ID?\r\n', b'OPT\r\n', b'SET\r\n', b'SET\r\n'],
                         transport.writes)

    def test_clock_template_and_invalid_template(self):
        def clock():
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        transport = FakeTransport()
        run(profile([{'name': 'time', 'class': 'setup',
                      'send': 'TIME {utc:%H:%M:%S}'}]),
            transport, 'open', self.audit, clock=clock)
        self.assertEqual(b'TIME 03:04:05\r\n', transport.writes[0])
        with self.assertRaisesRegex(ProfileError, 'step time.*send'):
            profile([{'name': 'time', 'class': 'setup', 'send': '{password}'}])

    def test_review_persist_audit_and_secret(self):
        raw = {'profile_id': 'x', 'version': 1, 'reviewed_by': '',
               'reviewed_on': '2026-11-18', 'source': 'manual', 'steps': []}
        with self.assertRaisesRegex(ProfileError, 'reviewed_by'):
            load_profile(raw)
        allowed = load_profile(raw, allow_unreviewed=True)
        self.assertEqual('x', allowed['profile_id'])
        os.environ['INIT_SECRET'] = 'swordfish'
        p = profile([{'name': 'secret', 'class': 'query',
                      'secret_env': 'INIT_SECRET', 'send': 'PASS {secret}',
                      'expect': 'OK'},
                     {'name': 'save', 'class': 'persist', 'send': 'SAVE'}])
        transport = FakeTransport([b'OK\n'])
        run(p, transport, 'reconnect', self.audit)
        with open(self.audit.path, encoding='utf-8') as stream:
            text = stream.read()
        self.assertNotIn('swordfish', text)
        records = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(['send', 'reply'], [r['event'] for r in records])
        self.assertTrue(all('bytes_hex' in r for r in records))
        self.assertEqual(1, len(transport.writes))

    def test_facades_are_json_serializable_and_plan_has_no_io(self):
        raw = profile([{'name': 'id', 'class': 'query', 'send': 'ID?',
                        'expect': 'OK'},
                       {'name': 'save', 'class': 'persist', 'send': 'SAVE'}])
        proposal = propose_init(raw, {'type': 'serial', 'port': '/dev/null',
                                      'free': True})
        json.dumps(proposal)
        description = describe_reader_sends(raw)
        json.dumps(description)
        self.assertEqual('logger on this port is stopped', proposal['precondition'])
        self.assertEqual('never sent by the reader', description['persist_steps'][0]['policy'])

    def test_no_profile_means_no_writes(self):
        transport = FakeTransport()
        self.assertEqual([], transport.writes)

    def test_run_without_yes_exits_two(self):
        from contrib.deepsignal.instrument_init.__main__ import main
        with self.assertRaises(SystemExit) as raised:
            main(['run', 'unused.yaml', '--serial', '/dev/none'])
        self.assertEqual(2, raised.exception.code)

    def test_serial_exception_reopens_and_reinitializes(self):
        from contrib.deepsignal.instrument_init import serial_reader

        class FakeSerial:
            instances = []

            def __init__(self, **kwargs):
                self.timeout = kwargs.get('timeout')
                self.is_open = True
                self.writes = []
                self.fail = len(self.instances) == 0
                self.instances.append(self)

            def write(self, data):
                self.writes.append(data)

            def readline(self):
                if self.fail:
                    self.fail = False
                    raise serial_reader.serial.SerialException('power loss')
                return b'data\n'

            def close(self):
                self.is_open = False

        raw = profile([{'name': 'id', 'class': 'query', 'send': 'ID'}],
                      reinit={'on_reconnect': True, 'after_silence_s': None,
                              'max_per_hour': 2})
        clock_values = iter([0, 0, 1, 1, 1, 1])
        with mock.patch.object(serial_reader, 'load_profile', return_value=raw), \
                mock.patch.object(serial_reader.serial, 'Serial', FakeSerial):
            reader = serial_reader.InitSerialReader(
                profile_file='profile.yaml', audit_log=self.audit.path,
                port='/dev/fake', sleep=lambda seconds: None,
                clock=lambda: next(clock_values))
            self.assertIsNone(reader.read())
        self.assertEqual(2, len(FakeSerial.instances))
        self.assertEqual([b'ID\r\n'], FakeSerial.instances[1].writes)


if __name__ == '__main__':
    unittest.main()
