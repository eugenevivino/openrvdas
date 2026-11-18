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


def plugin(series, *, start, end, seed, offset):
    injected = [(timestamp, value + offset + seed if index == 1 else value)
                for index, (timestamp, value) in enumerate(series)]
    origin = series[0][0]
    return injected, [(origin + start, origin + end, 'custom')]


class ScoringTests(unittest.TestCase):
    def test_latency_misses_false_flag_rates_and_traps(self):
        flags = list(zip(range(0, 3601, 600), [3, 1, 4, 9, 3, 4, 2]))
        truth = [(600, 1200, 'step'), (1800, 1800, 'spikes'), (3000, 3000, 'trap')]
        result = score_flags(flags, truth)
        self.assertEqual([event['latency_seconds'] for event in result['faults']], [600, None])
        self.assertEqual(result['missed'], 1)
        self.assertEqual(result['trap_flags'], 1)
        self.assertEqual(result['false_flags'], 3)
        self.assertEqual(result['false_flags_per_hour'], 6)
        self.assertEqual(result['trap_flags_per_hour'], 6)
        self.assertEqual(result['false_alarms_per_ship_day'], 144)

    def test_threshold_missing_verdict_and_boundaries(self):
        flags = [(0, 3), (20, 9), (30, None), (40, 4), (41, 4)]
        truth = [(0, 30, 'dropout'), (40, 40, 'spikes')]
        result = score_flags(flags, truth, threshold=4)
        self.assertEqual([event['latency_seconds'] for event in result['faults']], [None, 0])
        self.assertEqual(result['missed'], 1)
        self.assertEqual(result['missing_flag_samples'], 1)
        self.assertEqual(result['false_flags'], 1)
        self.assertIsNone(result['false_flags_per_hour'])
        self.assertIsNone(result['trap_flags_per_hour'])
        self.assertIsNone(result['false_alarms_per_ship_day'])


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
