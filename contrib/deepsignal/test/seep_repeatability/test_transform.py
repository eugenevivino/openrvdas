"""Record, transform, and demo configuration contract tests."""

import copy
import pathlib
import unittest

import yaml

from logger.utils.das_record import DASRecord

from contrib.deepsignal.seep_repeatability.fixtures import synthetic_records
from contrib.deepsignal.seep_repeatability.transform import SeepRepeatabilityTransform


class TransformContractTest(unittest.TestCase):
    def test_none_passes_through(self):
        self.assertIsNone(SeepRepeatabilityTransform().transform(None))

    def test_dict_list_and_dasrecord_preserve_inputs(self):
        transform = SeepRepeatabilityTransform()
        rows = synthetic_records()
        inputs = [rows[0], rows, DASRecord(timestamp=12.5, fields=rows[0]["fields"])]
        for value in inputs:
            pristine = copy.deepcopy(value)
            with self.subTest(kind=type(value).__name__):
                transform.transform(value)
                self.assertEqual(pristine, value)

    def test_record_shape_and_absent_optional_channels(self):
        result = SeepRepeatabilityTransform().transform(synthetic_records())
        required = {
            "FLARE_Anchor_EN_m", "FLARE_AnchorSD_m", "FLARE_FeatureScore",
            "FLARE_NullScore", "FLARE_RepeatLines", "FLARE_Coverage",
            "FLARE_RelativeIndex", "FLARE_IndexUnits", "FLARE_HeightBand_m",
            "FLARE_Score", "FLARE_Verdict", "FLARE_Reason", "FLARE_Support",
            "FLARE_Persistence", "FLARE_SourceIds", "FLARE_Stale", "FLARE_Excluded",
        }
        self.assertTrue(required.issubset(result["fields"]))

    def test_demo_logger_chain(self):
        config_path = pathlib.Path("contrib/deepsignal/configs/seep_repeatability_demo.yaml")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            "contrib.deepsignal.seep_repeatability.transform.SeepRepeatabilityTransform",
            config["transform"]["class"],
        )
        result = SeepRepeatabilityTransform(**config["transform"]["kwargs"]).transform(
            synthetic_records())
        self.assertEqual("seep_repeatability", result["data_id"])


if __name__ == "__main__":
    unittest.main()
