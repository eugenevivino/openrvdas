import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from logger.utils.das_record import DASRecord
from contrib.deepsignal.bench.run import main, run, score_flags
from contrib.deepsignal.bench.stub import StubThresholdDetector


MODULE = __name__
SAMPLE_LAYOUTS = ('mwx1/raw', 'data/mwx1/raw')
ROW_START = datetime(2014, 8, 1, tzinfo=timezone.utc).timestamp()


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


def plugin(series, *, start, end, seed, offset):
    injected = [(timestamp, value + offset + seed if index == 1 else value)
                for index, (timestamp, value) in enumerate(series)]
    origin = series[0][0]
    return injected, [(origin + start, origin + end, 'custom')]


class ScoringTests(unittest.TestCase):
    def test_stub_reports_nan_and_unconfigured_range_as_missing(self):
        detector = StubThresholdDetector()
        record = DASRecord(timestamp=0, fields={'MwxAirTemp': float('nan'),
                                                'MwxBarometer': 1023})
        result = detector.transform(record)
        self.assertEqual(result.fields['MwxAirTemp_QC'], 9)
        self.assertEqual(result.fields['MwxBarometer_QC'], 9)

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

    def test_point_fault_does_not_remove_following_exposure(self):
        result = score_flags([(0, 1), (1, 4), (100, 1)], [(1, 1, 'spikes')])
        self.assertEqual(result['outside_fault_seconds'], 100)

    def test_duplicate_timestamp_uses_injected_sample_identity(self):
        result = score_flags([(0, 1), (1, 4), (1, 1), (2, 1)],
                             [(1, 1, 'spikes')], truth_samples=[[2]])
        self.assertEqual(result['missed'], 1)
        self.assertEqual(result['false_flags'], 1)


class ReplayTests(unittest.TestCase):
    def fixture(self):
        scratch = Path(__file__).resolve().parents[5]
        tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def sample(self, root, layout):
        raw = root / layout
        raw.mkdir(parents=True)
        sample = raw / 'NBP1406_mwx1-2014-08-01'
        sample.write_text(
            '2014-08-01T00:00:00.000000Z MET,12,22,19,64,7,0,0,295,294,1023\n'
            '2014-08-01T00:00:01.000000Z MET,12,22,20,64,7,0,0,295,294,1023\n'
            '2014-08-01T00:00:02.000000Z MET,12,22,19,64,7,0,0,295,294,1023\n',
            encoding='utf-8')
        return sample

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

    def test_buffered_output_is_scored_at_returned_record_source_time(self):
        root = self.fixture()
        self.sample(root, SAMPLE_LAYOUTS[0])
        scenario = {'field': 'MwxAirTemp', 'fault': 'step',
                    'params': {'start': 1, 'end': 1, 'bias': 5}}
        result = run(scenario, MODULE, 'BufferedDetector', {}, sample_root=root)
        self.assertEqual(result['faults'][0]['latency_seconds'], 0)
        self.assertEqual(result['missing_flag_samples'], 1)

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
