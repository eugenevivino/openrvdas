"""Record and logger-chain contract tests."""

import copy
import unittest

from logger.utils.das_record import DASRecord
from logger.utils.read_config import read_config

from contrib.deepsignal.weighted_depth.records import Observation
from contrib.deepsignal.weighted_depth.transform import WeightedDepthTransform


class TransformContractTest(unittest.TestCase):
    def test_none_passes_through(self):
        self.assertIsNone(WeightedDepthTransform().transform(None))

    def test_observation_ancestry_is_immutable(self):
        with self.assertRaises(TypeError):
            Observation("s", "f", 1.0, 2.0, 0.1, (1.0, 1.0), ["mutable"])

    def test_record_shape_timestamp_fields_and_qc_survive(self):
        original = DASRecord(data_id="raw-1", timestamp=123.5,
                             fields={"MB_NadirDepth": 100.0, "QC": 1},
                             metadata={"parents": ["frame-1"]})
        frozen = copy.deepcopy(original)
        output = WeightedDepthTransform(sources=[]).transform(original)
        self.assertEqual(original, frozen)
        self.assertEqual(output.timestamp, original.timestamp)
        self.assertEqual(output.fields["MB_NadirDepth"], 100.0)
        self.assertEqual(output.fields["QC"], 1)
        self.assertIn("WDEP_Depth_m", output.fields)

    def test_dict_list_replay_is_deterministic(self):
        records = [{"timestamp": 1.0, "fields": {"MB_NadirDepth": 100.0}},
                   {"timestamp": 2.0, "fields": {"MB_NadirDepth": 101.0}}]
        one = WeightedDepthTransform().transform(copy.deepcopy(records))
        two = WeightedDepthTransform().transform(copy.deepcopy(records))
        self.assertEqual(one, two)

    def test_absent_channels_report_single_source(self):
        record = {"timestamp": 1.0,
                  "fields": {"ADCP_BTDepth": 100.0, "ADCP_BTGood": 90.0}}
        output = WeightedDepthTransform().transform(record)
        self.assertEqual(output["fields"]["WDEP_Support"], 1)
        self.assertTrue(output["fields"]["WDEP_Excluded"])

    def test_demo_logger_chain_declarations_load(self):
        config = read_config("contrib/deepsignal/configs/weighted_depth_demo.yaml")
        self.assertEqual(config["transforms"][0]["module"],
                         "contrib.deepsignal.weighted_depth.transform")
        record = {"timestamp": 1.0, "fields": {"MB_NadirDepth": 100.0}}
        output = WeightedDepthTransform(**config["transforms"][0]["kwargs"]).transform(record)
        self.assertIn("WDEP_Reason", output["fields"])


if __name__ == "__main__":
    unittest.main()
