import json
import copy
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

from logger.utils.das_record import DASRecord
from contrib.deepsignal.bench import faults
from contrib.deepsignal.bench.run import main, run, score_flags
from contrib.deepsignal.bench.stub import StubThresholdDetector


MODULE = __name__
SAMPLE_LAYOUTS = ('mwx1/raw', 'data/mwx1/raw')
ROW_START = datetime(2014, 8, 1, tzinfo=timezone.utc).timestamp()
SCRATCH = Path('/private/tmp/deepsignal/fault-bench')


class TimingDetector:
    def __init__(self):
        self.previous = None

    def transform(self, record):
        if not isinstance(record, DASRecord):
            raise TypeError('Expected DASRecord')
        backwards = self.previous is not None and record.timestamp < self.previous
        self.previous = record.timestamp
        record.fields['MwxAirTemp_DG'] = 4 if backwards else 3
        return record


class PairedFieldDetector:
    def transform(self, record):
        case_temp = record.fields['MwxPIRCaseTemp']
        dome_temp = record.fields['MwxPIRDomeTemp']
        record.fields['MwxPIRCaseTemp_QC'] = 4 if abs(case_temp - dome_temp - 1) > 0.1 else 1
        return record


class BufferedDetector:
    def __init__(self):
        self.pending = None

    def transform(self, record):
        result, self.pending = self.pending, record
        if result is not None:
            result.fields['MwxAirTemp_QC'] = 4
        return result


class CopiedBufferedDetector(BufferedDetector):
    def transform(self, record):
        result = super().transform(record)
        return copy.deepcopy(result) if result is not None else None


class StatusDetector:
    def transform(self, record):
        record.fields['MwxPortStatus_QC'] = 4 if record.fields['MwxPortStatus'] & 1 else 1
        return record


class FirstAlarmDetector:
    def __init__(self):
        self.alarmed = False

    def transform(self, record):
        alarm = not self.alarmed and record.fields['MwxAirTemp'] > 20
        self.alarmed = self.alarmed or alarm
        record.fields['MwxAirTemp_QC'] = 4 if alarm else 1
        return record


class AlwaysAlarmDetector:
    def transform(self, record):
        record.fields['MwxAirTemp_QC'] = 4
        return record


class TimestampChangeDetector:
    def __init__(self):
        self.previous = None

    def transform(self, record):
        changed = self.previous is not None and record.timestamp - self.previous != 1
        self.previous = record.timestamp
        record.fields['MwxAirTemp_DG'] = 4 if changed else 1
        return record


class NoFlagDetector:
    def transform(self, record):
        return record


class RepeatVerdictDetector:
    def __init__(self):
        self.first = None

    def transform(self, record):
        if self.first is None:
            self.first = record
            self.first.fields['MwxAirTemp_QC'] = 4
        else:
            self.first.fields['MwxAirTemp_QC'] = 1
        return self.first


class RebuiltBufferedDetector:
    def __init__(self):
        self.pending = None

    def transform(self, record):
        result = self.pending
        self.pending = DASRecord(timestamp=record.timestamp, fields={
            'MwxAirTemp_QC': 4 if record.fields['MwxAirTemp'] > 21 else 1})
        return result


class PermutedVerdictDetector:
    def __init__(self, order):
        self.order = iter(order)
        self.buffer = []

    def transform(self, record):
        self.buffer.append(record)
        if len(self.buffer) < 3:
            return None
        result = self.buffer[next(self.order)]
        result.fields['MwxAirTemp_QC'] = 4
        return result


def overlapping_steps(series, *, intervals, seed):
    injected = series
    truth = []
    for start, end in intervals:
        injected, labels = faults.step(injected, start=start, end=end, bias=5, seed=seed)
        truth.extend(labels)
    return injected, truth


def plugin(series, *, start, end, seed, offset):
    injected = [(timestamp, value + offset + seed if index == 1 else value)
                for index, (timestamp, value) in enumerate(series)]
    origin = series[0][0]
    return injected, [(origin + start, origin + end, 'custom')]


class ScoringTests(unittest.TestCase):
    def test_stub_reports_nan_as_missing_and_unconfigured_as_not_checked(self):
        detector = StubThresholdDetector()
        record = DASRecord(timestamp=0, fields={'MwxAirTemp': float('nan'),
                                                'MwxBarometer': 1023})
        result = detector.transform(record)
        self.assertEqual(result.fields['MwxAirTemp_QC'], 9)
        self.assertEqual(result.fields['MwxBarometer_QC'], 2)

    def test_stub_accepts_one_bound_and_rejects_invalid_configuration(self):
        detector = StubThresholdDetector(maximum=21)
        result = detector.transform(DASRecord(timestamp=1, fields={'MwxAirTemp': 40}))
        self.assertEqual(result.fields['MwxAirTemp_QC'], 4)
        with self.assertRaisesRegex(ValueError, 'maximum must be a finite number'):
            StubThresholdDetector(maximum=float('nan'))
        with self.assertRaisesRegex(ValueError, 'flag_suffix must be a nonempty string'):
            StubThresholdDetector(flag_suffix='')

    def test_latency_misses_false_flag_rates_and_traps(self):
        flags = list(zip(range(0, 3601, 600), [3, 1, 4, 9, 3, 4, 2]))
        truth = [(600, 1200, 'step'), (1800, 1800, 'spikes'), (3000, 3000, 'trap')]
        result = score_flags(flags, truth)
        self.assertEqual([event['latency_seconds'] for event in result['faults']], [600, None])
        self.assertEqual(result['missed'], 1)
        self.assertEqual(result['trap_flags'], 1)
        self.assertEqual(result['false_flags'], 3)
        self.assertEqual(result['false_flags_per_hour'], 4.5)
        self.assertIsNone(result['trap_flags_per_hour'])
        self.assertEqual(result['false_alarms_per_ship_day'], 108)

    def test_threshold_missing_verdict_and_boundaries(self):
        flags = [(0, 3), (20, 9), (30, None), (40, 4), (41, 4)]
        truth = [(0, 30, 'dropout'), (40, 40, 'spikes')]
        result = score_flags(flags, truth, threshold=4)
        self.assertEqual([event['latency_seconds'] for event in result['faults']], [None, 0])
        self.assertEqual(result['missed'], 1)
        self.assertEqual(result['missing_flag_samples'], 2)
        self.assertEqual(result['false_flags'], 1)
        self.assertEqual(result['false_flags_per_hour'], 3600)
        self.assertIsNone(result['trap_flags_per_hour'])
        self.assertEqual(result['false_alarms_per_ship_day'], 86400)

    def test_missing_suffix_has_no_reported_rate(self):
        result = score_flags([(0, None), (10, None)], [(0, 0, 'spikes')])
        self.assertEqual(result['missing_flag_samples'], 2)
        self.assertIsNone(result['false_flags_per_hour'])

    def test_suffix_does_not_turn_qartod_missing_into_alarm(self):
        result = score_flags([(0, 9), (10, 1)], [(0, 0, 'dropout')],
                             flag_suffix='_DG')
        self.assertEqual(result['missed'], 1)
        self.assertEqual(result['missing_flag_samples'], 1)

    def test_invalid_qartod_code_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'Invalid QARTOD verdict code'):
            score_flags([(0, 7)], [(0, 0, 'spikes')])
        with self.assertRaisesRegex(ValueError, 'Invalid QARTOD verdict code'):
            score_flags([(0, float('inf'))], [(0, 0, 'spikes')])

    def test_not_checked_verdict_has_no_evaluated_exposure(self):
        result = score_flags([(0, 2), (3600, 2)], [(0, 0, 'spikes')])
        self.assertEqual(result['missing_flag_samples'], 2)
        self.assertEqual(result['outside_fault_seconds'], 0)
        self.assertIsNone(result['false_flags_per_hour'])

    def test_one_alarm_detects_only_one_overlapping_event(self):
        result = score_flags([(0, 4), (1, 1)],
                             [(0, 0, 'spikes'), (0, 0, 'spikes')],
                             truth_samples=[[0], [0]])
        self.assertEqual(result['missed'], 1)

    def test_overlapping_traps_count_union_exposure(self):
        result = score_flags([(0, 4), (10, 1)],
                             [(0, 8, 'trap'), (4, 10, 'trap')])
        self.assertEqual(result['trap_seconds'], 10)
        self.assertEqual(result['trap_flags_per_hour'], 360)

    def test_point_fault_does_not_remove_following_exposure(self):
        result = score_flags([(0, 1), (1, 4), (100, 1)], [(1, 1, 'spikes')])
        self.assertEqual(result['outside_fault_seconds'], 100)

    def test_ignored_recovery_alarm_keeps_following_exposure(self):
        result = score_flags([(0, 1), (10, 4), (900, 1)], [(0, 0, 'clock_jump')],
                             ignored_samples=[1])
        self.assertEqual(result['outside_fault_seconds'], 900)

    def test_duplicate_timestamp_uses_injected_sample_identity(self):
        result = score_flags([(0, 1), (1, 4), (1, 1), (2, 1)],
                             [(1, 1, 'spikes')], truth_samples=[[2]])
        self.assertEqual(result['missed'], 1)
        self.assertEqual(result['false_flags'], 1)


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)

    def fixture(self):
        tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def sample(self, root, layout, readings=(19, 20, 19)):
        raw = root / layout
        raw.mkdir(parents=True)
        sample = raw / 'NBP1406_mwx1-2014-08-01'
        sample.write_text(
            ''.join(f'2014-08-01T00:00:{i:02}.000000Z MET,12,22,{v},64,7,0,0,295,294,1023\n'
                    for i, v in enumerate(readings)),
            encoding='utf-8')
        return sample

    def status_sample(self, root):
        raw = root / SAMPLE_LAYOUTS[0]
        raw.mkdir(parents=True)
        (raw / 'NBP1406_mwx1-2014-08-01').write_text(
            '2014-08-01T00:00:00.000000Z PUS,0,10,5,0,1500,20,1,0\n',
            encoding='utf-8')

    def duplicate_sample(self, root):
        raw = root / SAMPLE_LAYOUTS[0]
        raw.mkdir(parents=True)
        (raw / 'NBP1406_mwx1-2014-08-01').write_text(
            '2014-08-01T00:00:00.000000Z MET,12,22,19,64,7,0,0,295,294,1023\n'
            '2014-08-01T00:00:01.000000Z MET,12,22,19,64,7,0,0,295,294,1023\n'
            '2014-08-01T00:00:01.000000Z MET,12,22,19,64,7,0,0,295,294,1023\n'
            '2014-08-01T00:00:02.000000Z MET,12,22,19,64,7,0,0,295,294,1023\n',
            encoding='utf-8')

    def test_stub_end_to_end_both_sample_layouts(self):
        for layout in SAMPLE_LAYOUTS:
            with self.subTest(layout=layout):
                root = self.fixture()
                sample = self.sample(root, layout)
                original = sample.read_bytes()
                scenario = {'field': 'MwxAirTemp', 'fault': 'step',
                            'params': {'start': 1, 'end': 1, 'bias': 5}, 'seed': 7}
                result = run(scenario, StubThresholdDetector.__module__,
                             StubThresholdDetector.__name__, {'minimum': 18, 'maximum': 21},
                             sample_root=root)
                self.assertEqual(result['faults'][0]['latency_seconds'], 0)
                self.assertEqual(result['truth'], [(ROW_START + 1, ROW_START + 1, 'step')])
                self.assertEqual(result['false_flags'], 0)
                self.assertEqual(result['missing_flag_samples'], 0)
                self.assertEqual(sample.read_bytes(), original)

    def test_custom_suffix_and_replay_keeps_clock_reset_visible(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'clock_reset',
                    'params': {'start': 1, 'end': 2, 'seconds': 5}, 'seed': 7}
        result = run(scenario, MODULE, 'TimingDetector', {}, sample_root=root,
                     flag_suffix='_DG', threshold=4)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)
        self.assertEqual(result['false_flags'], 0)
        self.assertEqual(result['missing_flag_samples'], 0)

    def test_clock_jump_recovery_flag_is_not_scored(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'clock_jump',
                    'params': {'start': 1, 'end': 1, 'seconds': 90}}
        result = run(scenario, MODULE, 'TimingDetector', {}, sample_root=root,
                     flag_suffix='_DG', threshold=4)
        self.assertEqual(result['false_flags'], 0)

    def test_clock_reset_recovery_flag_is_not_scored(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'clock_reset',
                    'params': {'start': 1, 'end': 1, 'seconds': 5}}
        result = run(scenario, MODULE, 'TimestampChangeDetector', {}, sample_root=root,
                     flag_suffix='_DG', threshold=4)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)
        self.assertEqual(result['false_flags'], 0)

    def test_drift_truth_includes_unchanged_onset_sample(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'drift',
                    'params': {'start': 0, 'end': 2, 'rate_per_hour': 3600}}
        result = run(scenario, MODULE, 'AlwaysAlarmDetector', {}, sample_root=root)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)

    def test_duplicate_timestamp_spikes_are_distinct_truth_events(self):
        root = self.fixture()
        self.duplicate_sample(root)
        scenario = {'field': 'MwxAirTemp', 'fault': 'spikes',
                    'params': {'start': 1, 'end': 1, 'count': 2, 'size': 5}}
        result = run(scenario, MODULE, 'FirstAlarmDetector', {}, sample_root=root)
        self.assertEqual(len(result['faults']), 2)
        self.assertEqual(result['missed'], 1)

    def test_buffered_output_is_scored_at_returned_record_source_time(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'step',
                    'params': {'start': 1, 'end': 1, 'bias': 5}}
        result = run(scenario, MODULE, 'BufferedDetector', {}, sample_root=root)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)
        self.assertEqual(result['missing_flag_samples'], 1)

    def test_buffered_copied_output_retains_source_attribution(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'step',
                    'params': {'start': 1, 'end': 1, 'bias': 5}}
        result = run(scenario, MODULE, 'CopiedBufferedDetector', {}, sample_root=root)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)
        self.assertEqual(result['missing_flag_samples'], 1)

    def test_status_fields_remain_integers(self):
        root = self.fixture()
        self.status_sample(root)
        scenario = {'field': 'MwxPortStatus', 'fault': 'step',
                    'params': {'start': 0, 'end': 0, 'bias': 0}}
        result = run(scenario, MODULE, 'StatusDetector', {}, sample_root=root)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)

    def test_front_replays_two_linked_fields_on_one_record(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxPIRCaseTemp', 'trap': 'front',
                    'companion_field': 'MwxPIRDomeTemp',
                    'params': {'start': 1, 'end': 1, 'bias': 5}, 'seed': 7}
        result = run(scenario, MODULE, 'PairedFieldDetector', {}, sample_root=root)
        self.assertEqual(result['truth'], [(ROW_START + 1, ROW_START + 1, 'trap')])
        self.assertEqual(result['trap_flags'], 0)
        self.assertEqual(result['false_flags'], 0)

    def test_plugin_injector_and_cli_output_directory(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[1])
        scenarios = root / 'scenarios.yaml'
        scenarios.write_text(
            'custom:\n'
            '  field: MwxAirTemp\n'
            f'  injector: {MODULE}:plugin\n'
            '  params: {start: 1, end: 1, offset: 3}\n'
            '  seed: 2\n', encoding='utf-8')
        output = root / 'reports'
        main(['run', '--scenarios', str(scenarios),
              '--detector', f'{StubThresholdDetector.__module__}:StubThresholdDetector',
              '--kwargs', '{}', '--sample-root', str(root), '--output-dir', str(output)])
        results = json.loads((output / 'results.json').read_text(encoding='utf-8'))
        self.assertEqual(results['custom']['truth'], [[ROW_START + 1, ROW_START + 1, 'custom']])
        self.assertEqual(results['custom']['faults'][0]['latency_seconds'], 0)
        self.assertIn('| custom |', (output / 'summary.md').read_text(encoding='utf-8'))

    def test_duplicate_scenario_names_are_rejected(self):
        root = self.fixture()
        scenarios = root / 'scenarios.yaml'
        scenarios.write_text('same: {}\nsame: {}\n', encoding='utf-8')
        with self.assertRaisesRegex(SystemExit, '2'):
            main(['run', '--scenarios', str(scenarios), '--detector',
                  f'{MODULE}:TimingDetector', '--sample-root', str(root)])

    def test_yaml_merge_scenarios_are_accepted(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenarios = root / 'scenarios.yaml'
        scenarios.write_text(
            'defaults: &defaults\n'
            '  field: MwxAirTemp\n'
            '  fault: step\n'
            '  params: {start: 1, end: 1, bias: 5}\n'
            'merged:\n'
            '  <<: *defaults\n', encoding='utf-8')
        output = root / 'reports'
        main(['run', '--scenarios', str(scenarios), '--detector',
              f'{StubThresholdDetector.__module__}:StubThresholdDetector',
              '--sample-root', str(root), '--output-dir', str(output)])
        self.assertTrue((output / 'results.json').is_file())

    def test_empty_flag_suffix(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0], readings=(4,))
        scenarios = root / 'scenarios.yaml'
        scenarios.write_text('step: {field: MwxAirTemp, fault: step, params: {bias: 0}}\n')
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit):
            main(['run', '--scenarios', str(scenarios), '--detector', f'{MODULE}:NoFlagDetector',
                  '--sample-root', str(root), '--output-dir', str(root), '--flag-suffix', ''])
        self.assertIn('nonempty', errors.getvalue())

    def test_step_covers_duplicate_rows(self):
        root = self.fixture()
        self.duplicate_sample(root)
        scenario = {'field': 'MwxAirTemp', 'fault': 'step',
                    'params': {'start': 1, 'end': 1, 'bias': 5}}
        result = run(scenario, StubThresholdDetector.__module__, 'StubThresholdDetector', {},
                     sample_root=root)
        self.assertEqual(result['false_flags'], 0)
        self.assertEqual([event['latency_seconds'] for event in result['faults']], [0])

    def test_overlapping_faults_match_both_alarms(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        for intervals in permutations([(0, 1), (0, 0)]):
            scenario = {'field': 'MwxAirTemp', 'injector': f'{MODULE}:overlapping_steps',
                        'params': {'intervals': intervals}}
            result = run(scenario, StubThresholdDetector.__module__, 'StubThresholdDetector', {},
                         sample_root=root)
            self.assertEqual(result['missed'], 0)
            by_end = {event['end']: event['latency_seconds'] for event in result['faults']}
            self.assertEqual(by_end, {ROW_START: 0, ROW_START + 1: 1})

    def test_permuted_truth_and_verdicts(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0], readings=(19,) * 5)
        for intervals in permutations([(0, 1), (0, 0), (4, 4)]):
            scenario = {'field': 'MwxAirTemp', 'injector': f'{MODULE}:overlapping_steps',
                        'params': {'intervals': intervals}}
            for order in permutations(range(3)):
                result = run(scenario, MODULE, 'PermutedVerdictDetector', {'order': order},
                             sample_root=root)
                detected = sum(event['latency_seconds'] is not None for event in result['faults'])
                self.assertEqual((result['missed'], detected, result['false_flags']), (1, 2, 1),
                                 (intervals, order))

    def test_plugin_clock_reset_recovery(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'injector': f'{faults.__name__}:clock_reset',
                    'params': {'start': 1, 'end': 1, 'seconds': 5}}
        result = run(scenario, MODULE, 'TimestampChangeDetector', {}, flag_suffix='_DG',
                     sample_root=root)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)
        self.assertEqual(result['false_flags'], 0)

    def test_duplicate_verdict_rejected(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'step',
                    'params': {'start': 0, 'end': 0, 'bias': 5}}
        with self.assertRaisesRegex(ValueError, '(?i)duplicate verdict'):
            run(scenario, MODULE, 'RepeatVerdictDetector', {}, sample_root=root)

    def test_rebuilt_buffered_verdict(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0], readings=(19, 24, 19))
        scenario = {'field': 'MwxAirTemp', 'fault': 'clock_reset',
                    'params': {'start': 1, 'end': 1, 'seconds': 5}}
        result = run(scenario, MODULE, 'RebuiltBufferedDetector', {}, sample_root=root)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)
        self.assertEqual(result['missing_flag_samples'], 1)
        self.assertEqual(result['false_flags'], 0)

    def test_nonfinite_step_bias(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'step', 'params': {'bias': float('nan')}}
        with self.assertRaisesRegex(ValueError, 'bias.*finite'):
            run(scenario, StubThresholdDetector.__module__, 'StubThresholdDetector', {},
                sample_root=root)

    def test_duplicate_in_inline_merge(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenarios = root / 'scenarios.yaml'
        scenarios.write_text('<<: {same: {field: MwxAirTemp, fault: flatline}, '
                             'same: {field: MwxAirTemp, fault: dropout}}\n')
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit):
            main(['run', '--scenarios', str(scenarios), '--detector', f'{MODULE}:NoFlagDetector',
                  '--sample-root', str(root), '--output-dir', str(root)])
        self.assertIn("Duplicate scenario name 'same'", errors.getvalue())

    def test_fixture_ignores_system_tempdir(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as system_temp:
            with patch.object(tempfile, 'tempdir', system_temp):
                fixture = self.fixture().resolve()
                self.assertTrue(fixture.is_relative_to(SCRATCH))
                self.assertFalse(fixture.is_relative_to(system_temp))

    def test_guide_counts_unchecked_as_missing(self):
        guide = Path(__file__).resolve().parents[2] / 'docs' / 'fault_bench.md'
        summary = guide.read_text().split('**Missing flag samples**', 1)[1].split('\n\n', 1)[0]
        self.assertRegex(summary, r'\b2\b')
