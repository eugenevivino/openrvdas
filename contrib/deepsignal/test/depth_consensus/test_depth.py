import copy
import unittest

from logger.utils.das_record import DASRecord

from contrib.deepsignal.depth_consensus.depth_consensus_transform import (
    DepthConsensusTransform,
)


SOURCES = {
    "mb": {"field": "MB", "offset_m": 0, "max_age_s": 10, "role": "sonar"},
    "hf": {"field": "HF", "offset_m": 5, "max_age_s": 10, "role": "sonar"},
    "grid": {"field": "GRID", "offset_m": 0, "max_age_s": 20, "role": "reference"},
}


class DepthConsensusTest(unittest.TestCase):
    def make(self, **kwargs):
        options = dict(sources=SOURCES, threshold_pct=2, persist_s=10, clear_s=10)
        options.update(kwargs)
        return DepthConsensusTransform(**options)

    @staticmethod
    def record(timestamp, **fields):
        return {"timestamp": timestamp, "fields": fields}

    def test_agreement_offset_and_odd_one(self):
        transform = self.make(persist_s=0)
        output = transform.transform(self.record(1, MB=100, HF=95, GRID=100))
        self.assertEqual(100, output["fields"]["DEPTH_Consensus"])
        self.assertEqual(0, output["fields"]["DEPTH_SpreadPct"])
        output = transform.transform(self.record(2, MB=110, HF=95, GRID=100))
        self.assertEqual("mb", output["fields"]["DEPTH_OddOne"])
        self.assertEqual(1, output["fields"]["DEPTH_Alarm"])
        self.assertIn("mb", output["fields"]["DEPTH_AlarmText"])
        self.assertIn("110.00 m", output["fields"]["DEPTH_AlarmText"])
        self.assertIn("100.00 m", output["fields"]["DEPTH_AlarmText"])
        self.assertIn("2.00%", output["fields"]["DEPTH_AlarmText"])

    def test_persistence_and_hysteresis(self):
        transform = self.make()
        expected = ((0, 110, 0), (9, 110, 0), (10, 110, 1),
                    (11, 101, 1), (20, 101, 1), (21, 101, 0))
        for timestamp, mb_depth, alarm in expected:
            output = transform.transform(self.record(timestamp, MB=mb_depth, HF=95))
            self.assertEqual(alarm, output["fields"]["DEPTH_Alarm"])

    def test_lost_bottom_step_and_stale(self):
        transform = self.make(persist_s=2)
        transform.transform(self.record(0, MB=100, HF=95))
        transform.transform(self.record(1, MB=100, HF=95))
        jumped = transform.transform(self.record(2, MB=120, HF=95))
        self.assertEqual("mb", jumped["fields"]["DEPTH_Step"])
        transform.transform(self.record(3, MB=None, HF=95))
        lost = transform.transform(self.record(5, MB=0, HF=95))
        self.assertEqual("mb", lost["fields"]["DEPTH_LostBottom"])
        stale = transform.transform(self.record(16, HF=95))
        self.assertEqual("mb,grid", stale["fields"]["DEPTH_Stale"])

    def test_reference_suspicion_and_shallow_floor(self):
        transform = self.make(persist_s=0)
        suspicious = transform.transform(self.record(1, MB=100, GRID=110))
        self.assertEqual(1, suspicious["fields"]["DEPTH_Alarm"])
        self.assertIn("suspicious", suspicious["fields"]["DEPTH_AlarmText"])
        shallow = self.make(persist_s=0).transform(self.record(2, MB=4, HF=0, GRID=20))
        self.assertEqual(0, shallow["fields"]["DEPTH_Alarm"])

    def test_invalid_values_and_input_shapes(self):
        transform = self.make(persist_s=0)
        self.assertIsNone(transform.transform(None))
        records = [self.record(1, MB=float("nan")), self.record(2, MB=float("inf"))]
        self.assertIs(records, transform.transform(records))
        das = DASRecord(timestamp=3, fields={"MB": 100, "HF": 95})
        self.assertIs(das, transform.transform(das))
        original = {"MB": 100, "HF": 95}
        record = self.record(4, **original)
        transform.transform(record)
        self.assertEqual(original, {key: record["fields"][key] for key in original})

    def test_replay_is_deterministic(self):
        stream = [self.record(t, MB=110, HF=95) for t in (0, 5, 10)]
        first = self.make().transform(copy.deepcopy(stream))
        second = self.make().transform(copy.deepcopy(stream))
        self.assertEqual(first, second)

    def test_configuration_errors_are_plain_english(self):
        with self.assertRaisesRegex(ValueError, "threshold_pct.*saw.*expected.*example"):
            DepthConsensusTransform(sources=SOURCES, threshold_pct=0)
        bad = {"mb": {"field": "MB", "role": "fish"}}
        with self.assertRaisesRegex(ValueError, "sources.mb.role.*saw.*expected.*example"):
            DepthConsensusTransform(sources=bad)


if __name__ == "__main__":
    unittest.main()
