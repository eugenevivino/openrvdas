import copy
import unittest

from logger.utils.das_record import DASRecord

from contrib.deepsignal.sv_consistency.sv_consistency_transform import (
    SVConsistencyTransform,
)


SOURCES = {
    'probe': {'field': 'ProbeSV', 'max_age_s': 30},
    'tsg': {'field': 'TSGSV', 'max_age_s': 120},
    'sonar': {'field': 'SonarSV', 'max_age_s': 30},
    'cast': {'field': 'CastSV', 'max_age_s': None},
}


def record(timestamp, **fields):
    return {'timestamp': timestamp, 'fields': fields}


class TestSVConsistencyTransform(unittest.TestCase):
    def make_transform(self, **kwargs):
        options = dict(sources=SOURCES, threshold_ms=2, persist_s=10,
                       clear_s=5)
        options.update(kwargs)
        return SVConsistencyTransform(**options)

    def test_agreement_and_persistent_alarm_then_hysteresis_clear(self):
        transform = self.make_transform()
        initial = transform.transform(record(
            0, ProbeSV=1500, TSGSV=1500.5, SonarSV=1500.2))
        self.assertEqual(0, initial['fields']['SV_Alarm'])
        self.assertEqual('', initial['fields']['SV_OddOne'])

        first_bad = transform.transform(record(1, SonarSV=1505))
        still_waiting = transform.transform(record(10, ProbeSV=1500.1))
        alarm = transform.transform(record(11, ProbeSV=1500.1))
        self.assertEqual(0, first_bad['fields']['SV_Alarm'])
        self.assertEqual(0, still_waiting['fields']['SV_Alarm'])
        self.assertEqual(1, alarm['fields']['SV_Alarm'])
        self.assertEqual('sonar', alarm['fields']['SV_OddOne'])
        self.assertIn('Sonar', alarm['fields']['SV_AlarmText'])
        self.assertIn('2.0 m/s limit', alarm['fields']['SV_AlarmText'])

        not_low_enough = transform.transform(record(12, SonarSV=1501.6))
        clear_started = transform.transform(record(13, SonarSV=1501.4))
        almost_clear = transform.transform(record(17, ProbeSV=1500))
        cleared = transform.transform(record(18, ProbeSV=1500))
        self.assertEqual(1, not_low_enough['fields']['SV_Alarm'])
        self.assertEqual(1, clear_started['fields']['SV_Alarm'])
        self.assertEqual(1, almost_clear['fields']['SV_Alarm'])
        self.assertEqual(0, cleared['fields']['SV_Alarm'])

    def test_odd_one_out_with_three_and_four_sources(self):
        three = self.make_transform(persist_s=0).transform(record(
            100, ProbeSV=1500, TSGSV=1500.2, SonarSV=1507))
        self.assertEqual('sonar', three['fields']['SV_OddOne'])

        four = self.make_transform(persist_s=0).transform(record(
            100, ProbeSV=1500, TSGSV=1500.2, SonarSV=1500.1,
            CastSV=1493))
        self.assertEqual('cast', four['fields']['SV_OddOne'])

    def test_two_sources_have_spread_but_no_odd_one(self):
        output = self.make_transform(persist_s=0).transform(
            record(100, ProbeSV=1500, SonarSV=1505))
        self.assertEqual(5, output['fields']['SV_Spread'])
        self.assertEqual('', output['fields']['SV_OddOne'])
        self.assertEqual(1, output['fields']['SV_Alarm'])
        self.assertEqual(5, output['fields']['SV_Diff_probe_sonar'])

    def test_stale_and_invalid_sources_are_excluded(self):
        transform = self.make_transform(persist_s=0)
        transform.transform(record(0, ProbeSV=1500, TSGSV=1501,
                                   SonarSV=1502, CastSV=1503))
        stale = transform.transform(record(40, TSGSV=1501))
        self.assertEqual(2, stale['fields']['SV_Fresh'])
        self.assertEqual('probe,sonar', stale['fields']['SV_Stale'])
        self.assertNotIn('SV_Diff_probe_tsg', stale['fields'])

        invalid = transform.transform(record(41, ProbeSV='nan'))
        self.assertEqual(2, invalid['fields']['SV_Fresh'])
        invalid = transform.transform(record(42, ProbeSV=1700))
        self.assertEqual(2, invalid['fields']['SV_Fresh'])
        invalid = transform.transform(record(43, ProbeSV='not a number'))
        self.assertEqual(2, invalid['fields']['SV_Fresh'])

    def test_cast_age_and_custom_prefix(self):
        transform = self.make_transform(prefix='CHECK')
        transform.transform(record(10, CastSV=1499))
        output = transform.transform(record(25, ProbeSV=1500))
        self.assertEqual(15, output['fields']['CHECK_CastAge_s'])

    def test_none_list_dict_and_das_record_inputs(self):
        transform = self.make_transform()
        self.assertIsNone(transform.transform(None))
        inputs = [record(1, ProbeSV=1500),
                  DASRecord(timestamp=2, fields={'TSGSV': 1500})]
        outputs = transform.transform(inputs)
        self.assertIsInstance(outputs, list)
        self.assertIsInstance(outputs[1], DASRecord)
        self.assertEqual(2, outputs[1].fields['SV_Fresh'])
        untouched = record(3, Unrelated=4)
        self.assertIs(untouched, transform.transform(untouched))
        self.assertNotIn('SV_Spread', untouched['fields'])

    def test_replay_is_deterministic_and_does_not_replace_inputs(self):
        inputs = [record(0, ProbeSV=1500, TSGSV=1500, SonarSV=1505),
                  record(10, ProbeSV=1500), record(20, ProbeSV=1500)]

        def replay():
            transform = self.make_transform()
            copied = copy.deepcopy(inputs)
            outputs = transform.transform(copied)
            for source, output in zip(copied, outputs):
                for key, value in source['fields'].items():
                    if not key.startswith('SV_'):
                        self.assertEqual(value, output['fields'][key])
            return outputs

        self.assertEqual(replay(), replay())

    def test_configuration_errors_are_plain_english(self):
        cases = [
            ({'sources': []}, 'sources'),
            ({'sources': {'probe': {'max_age_s': 2}}}, 'field'),
            ({'sources': {'probe': {'field': 'SV', 'max_age_s': -1}}},
             'max_age_s'),
            ({'threshold_ms': 0}, 'threshold_ms'),
            ({'persist_s': -1}, 'persist_s'),
            ({'clear_s': -1}, 'clear_s'),
            ({'valid_range': [1600, 1400]}, 'valid_range'),
        ]
        for changed, setting in cases:
            options = {'sources': SOURCES}
            options.update(changed)
            with self.subTest(setting=setting):
                with self.assertRaisesRegex(ValueError, setting):
                    SVConsistencyTransform(**options)


if __name__ == '__main__':
    unittest.main()
