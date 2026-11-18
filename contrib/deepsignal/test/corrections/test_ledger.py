import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from uuid import uuid4

from contrib.deepsignal.corrections import Ledger


START = '2014-08-01T00:00:00Z'
END = '2014-08-04T00:00:00Z'
WHEN = '2014-08-02T00:00:00Z'


def proposal(**changes):
    return {
        'event': 'propose',
        'id': str(uuid4()),
        'field': 'temperature',
        'start': START,
        'end': END,
        'method': 'offset',
        'value': 2,
        'standard_uncertainty': 0.25,
        'evidence': ['calibration.txt'],
        'author': 'Ana',
        'code_version': 'v1',
        'reason': 'Calibration check',
        'correction_state': 'CORRECTABLE',
        'model_id': 'C1',
        'fit_refs': ['fit-1'],
        'validation_refs': ['check-1'],
    } | changes


def transition(event, entry, by='Bo'):
    return {'event': event, 'id': entry['id'], 'by': by,
            'reason': 'Independent review', 'time': WHEN}


def canonical(event):
    return json.dumps(event, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        scratch = self.enterContext(TemporaryDirectory())
        self.path = Path(scratch) / 'ledger.jsonl'

    def add_proposal(self, **changes):
        entry = proposal(**changes)
        Ledger.append(self.path, entry)
        return entry

    def add_transition(self, event, entry, by='Bo'):
        Ledger.append(self.path, transition(event, entry, by))

    def approve_entry(self, **changes):
        entry = self.add_proposal(**changes)
        self.add_transition('approve', entry)
        return entry


class LedgerTest(LedgerTestCase):
    def test_every_state_transition(self):
        legal = {('proposed', 'approve'): 'approved',
                 ('proposed', 'reject'): 'rejected',
                 ('approved', 'rollback'): 'rolled_back'}
        history = {'proposed': [], 'approved': ['approve'], 'rejected': ['reject'],
                   'rolled_back': ['approve', 'rollback']}
        for state, events in history.items():
            for action in ('approve', 'reject', 'rollback'):
                with self.subTest(state=state, event=action):
                    entry = self.add_proposal()
                    for event in events:
                        self.add_transition(event, entry)
                    resulting_state = legal.get((state, action))
                    before = self.path.read_bytes()
                    if resulting_state is None:
                        with self.assertRaisesRegex(ValueError, state):
                            self.add_transition(action, entry)
                        self.assertEqual(self.path.read_bytes(), before)
                        resulting_state = state
                    else:
                        self.add_transition(action, entry)
                        self.assertTrue(self.path.read_bytes().startswith(before))
                    self.assertEqual(Ledger.load(self.path).entries[entry['id']]['status'],
                                     resulting_state)

    def test_unknown_and_duplicate_ids_rejected(self):
        entry = self.add_proposal()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            Ledger.append(self.path, entry)
        for action in ('approve', 'reject', 'rollback'):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, 'unknown'):
                    self.add_transition(action, proposal())

    def test_author_cannot_review_own_proposal(self):
        entry = self.add_proposal()
        for action in ('approve', 'reject'):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, 'author'):
                    self.add_transition(action, entry, 'Ana')
        self.add_transition('approve', entry)
        with self.assertRaisesRegex(ValueError, 'author'):
            self.add_transition('rollback', entry, 'Ana')

    def test_active_uses_half_open_utc_window(self):
        proposed = self.add_proposal()
        approved = self.approve_entry()
        rejected = self.add_proposal()
        self.add_transition('reject', rejected)
        ledger = Ledger.load(self.path)
        for instant in (START, WHEN, 1406851200):
            with self.subTest(instant=instant):
                self.assertEqual([row['id'] for row in ledger.active('temperature', instant)],
                                 [approved['id']])
        self.assertEqual(ledger.active('temperature', END), [])
        self.assertEqual(ledger.active('temperature', 1406851199), [])
        self.assertEqual(ledger.active('other', WHEN), [])
        self.assertEqual(ledger.entries[proposed['id']]['status'], 'proposed')

    def test_tampered_line_is_reported_and_never_repaired(self):
        entry = self.approve_entry(author='André')
        before = self.path.read_bytes()
        first, second = map(json.loads, before.splitlines())
        self.assertIsNone(first['prev_hash'])
        for event in (first, second):
            digest = event.pop('hash')
            self.assertEqual(digest, hashlib.sha256(canonical(event)).hexdigest())
            if event is first:
                self.assertEqual(second['prev_hash'], digest)
        tampered = before.replace(b'Independent review', b'Altered review')
        self.path.write_bytes(tampered)
        with self.assertRaisesRegex(ValueError, 'line 2.*hash'):
            Ledger.load(self.path)
        with self.assertRaisesRegex(ValueError, 'line 2.*hash'):
            self.add_transition('rollback', entry)
        self.assertEqual(self.path.read_bytes(), tampered)

    def test_invalid_chained_events_are_reported_at_the_line(self):
        entry = self.add_proposal()
        before = self.path.read_bytes()
        previous = json.loads(before)['hash']
        bad_events = (
            transition('approve', entry, by='Ana'),
            transition('rollback', entry),
            proposal(standard_uncertainty=-1),
            proposal(fit_refs=['shared'], validation_refs=['shared']),
        )
        for event in bad_events:
            with self.subTest(event=event['event']):
                event['prev_hash'] = previous
                event['hash'] = hashlib.sha256(canonical(event)).hexdigest()
                self.path.write_bytes(before + canonical(event) + b'\n')
                with self.assertRaisesRegex(ValueError, 'line 2'):
                    Ledger.load(self.path)

    def test_valid_event_hash_does_not_excuse_wrong_previous_link(self):
        entry = self.add_proposal()
        event = transition('approve', entry) | {'prev_hash': '0' * 64}
        event['hash'] = hashlib.sha256(canonical(event)).hexdigest()
        with self.path.open('ab') as file:
            file.write(canonical(event) + b'\n')
        with self.assertRaisesRegex(ValueError, 'line 2.*prev_hash'):
            Ledger.load(self.path)

    def test_malformed_lines_are_rejected(self):
        self.add_proposal()
        before = self.path.read_bytes()
        for suffix in (b'\n', b'{"event":"approve"}', b'{"id":"a","id":"b"}\n',
                       b'{"value":NaN}\n', b'\xff\n'):
            with self.subTest(suffix=suffix):
                self.path.write_bytes(before + suffix)
                with self.assertRaisesRegex(ValueError, 'line 2'):
                    Ledger.load(self.path)

    def test_legacy_uncertainty_alias_on_disk(self):
        entry = proposal()
        entry['uncertainty'] = entry.pop('standard_uncertainty')
        entry['prev_hash'] = None
        entry['hash'] = hashlib.sha256(canonical(entry)).hexdigest()
        before = canonical(entry) + b'\n'
        self.path.write_bytes(before)
        self.add_transition('approve', entry)
        result, = Ledger.load(self.path).active('temperature', WHEN)
        self.assertEqual(result['standard_uncertainty'], 0.25)
        self.assertTrue(self.path.read_bytes().startswith(before))

    def test_overlapping_refs_rejected_and_named(self):
        with self.assertRaisesRegex(ValueError, 'shared1.*shared2'):
            self.add_proposal(fit_refs=['shared1', 'shared2'],
                              validation_refs=['shared2', 'shared1'])

    def test_noncorrectable_state_rejected(self):
        with self.assertRaisesRegex(ValueError, 'must be CORRECTABLE'):
            self.add_proposal(correction_state='SUSPECT')

    def test_proposal_parameters_validated(self):
        for changes, message in (
            ({'start': '2014-08-01T00:00:00'}, 'start'),
            ({'end': START}, 'end'),
            ({'model_id': 'C6'}, 'model_id'),
            ({'independence_score': 1.1}, 'independence_score'),
            ({'coverage_interval': [2, 1]}, 'coverage_interval'),
            ({'standard_uncertainty': True}, 'standard_uncertainty'),
            ({'value': float('inf')}, 'value'),
            ({'method': 'unknown'}, 'method'),
        ):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError, message):
                    self.add_proposal(**changes)
        entry = proposal(method='gain_offset', offset=2, gain=0)
        del entry['value']
        with self.assertRaisesRegex(ValueError, 'gain'):
            Ledger.append(self.path, entry)

    def test_cli_round_trip(self):
        def cli(action, *args, check=True):
            return subprocess.run(
                [sys.executable, '-m', 'contrib.deepsignal.corrections', action,
                 '--ledger', str(self.path), *args],
                check=check, text=True, capture_output=True,
            )

        exact_offset = 2**53 + 1
        reason = 'Calibration check\n\x1b[31mSee report'
        result = cli('propose', '--author', 'Ana', '--field', 'temperature',
                     '--start', START, '--end', END, '--method', 'offset',
                     '--value', str(exact_offset),
                     '--standard-uncertainty', '.25', '--evidence', 'calibration.txt',
                     '--reason', reason, '--code-version', 'v1',
                     '--correction-state', 'CORRECTABLE', '--model-id', 'C1',
                     '--fit-refs', 'fit-1', '--validation-refs', 'check-1')
        entry_id = result.stdout.strip()
        entry = Ledger.load(self.path).entries[entry_id]
        self.assertEqual(entry['value'], exact_offset)
        self.assertEqual(entry['reason'], reason)
        review = (entry_id, '--by', 'Bo', '--reason', 'Independent review')
        missing_by = cli('approve', entry_id, '--reason', 'Independent review', check=False)
        self.assertNotEqual(missing_by.returncode, 0)
        self.assertIn('--by', missing_by.stderr)
        self.assertIn('proposed', cli('list').stdout)
        cli('approve', *review)
        listed = cli('list').stdout
        self.assertEqual(len(listed.splitlines()), 1)
        self.assertNotIn('\x1b', listed)
        for word in ('approved', entry_id, 'temperature', 'offset', 'Calibration check'):
            self.assertIn(word, listed)
        cli('rollback', *review)
        self.assertIn('rolled back', cli('list').stdout)
        self.assertIn('verified', cli('verify').stdout.lower())
        self.assertEqual(Ledger.load(self.path).active('temperature', WHEN), [])
        self.assertNotEqual(cli('reject', *review, check=False).returncode, 0)
