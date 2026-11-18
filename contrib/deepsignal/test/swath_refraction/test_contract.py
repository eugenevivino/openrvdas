"""Record, replay, fixture and demo configuration contracts."""

import copy
import importlib
import pathlib
import unittest

import yaml

from contrib.deepsignal.swath_refraction.contract import RESULT_FIELDS
from contrib.deepsignal.swath_refraction.fixtures import (
    FINAL_INJECTION_SEEDS,
    constant_c_truth,
    fixture_hash,
    synthetic_records,
)
from contrib.deepsignal.swath_refraction.transform import SwathRefractionTransform
from logger.utils.das_record import DASRecord


ROOT = pathlib.Path(__file__).parents[4]


class TestContract(unittest.TestCase):
    def test_synthetic_truth_fixture(self):
        truth = constant_c_truth()
        self.assertAlmostEqual(truth["x_m"], 75.0, places=9)
        self.assertAlmostEqual(truth["z_m"], 129.90381, places=5)
        self.assertEqual(FINAL_INJECTION_SEEDS, tuple(range(27001, 27021)))

    def test_none_passes_through(self):
        self.assertIsNone(SwathRefractionTransform().transform(None))

    def test_record_shape_and_timestamp_preserved(self):
        source = DASRecord(data_id="mrz", timestamp=1234.5,
                           fields=synthetic_records()[0]["fields"],
                           metadata={"qc": 1})
        output = SwathRefractionTransform().transform(source)
        self.assertEqual(output.timestamp, source.timestamp)
        self.assertEqual(output.fields["raw"], source.fields)
        self.assertEqual(tuple(output.fields["derived"]), RESULT_FIELDS)
        self.assertEqual(source.metadata["qc"], 1)

    def test_dict_list_and_absent_channels(self):
        transform = SwathRefractionTransform()
        records = synthetic_records()[:2]
        output = transform.transform([records[0], None, records[1]])
        self.assertEqual(len(output), 3)
        self.assertEqual(output[1]["fields"]["REFR_Verdict"], "AMBIGUOUS")
        self.assertIn("missing", output[1]["fields"]["REFR_Reason"].lower())

    def test_replay_is_causal_and_deterministic(self):
        records = synthetic_records()
        first = SwathRefractionTransform().transform(copy.deepcopy(records))
        second = SwathRefractionTransform().transform(copy.deepcopy(records))
        self.assertEqual(first, second)
        self.assertTrue(all(row["timestamp"] <= records[-1]["timestamp"]
                            for row in first))

    def test_input_hash_and_timestamp_survive(self):
        records = synthetic_records()
        before_hash = fixture_hash(records)
        before_times = [row["timestamp"] for row in records]
        SwathRefractionTransform().transform(records)
        self.assertEqual(fixture_hash(records), before_hash)
        self.assertEqual([row["timestamp"] for row in records], before_times)

    def test_fit_excludes_holdout_ids(self):
        result = SwathRefractionTransform().transform(synthetic_records())
        fit_ids = set(result[-1]["metadata"]["fit_source_ids"])
        holdout_ids = set(result[-1]["metadata"]["holdout_source_ids"])
        self.assertTrue(holdout_ids)
        self.assertTrue(fit_ids.isdisjoint(holdout_ids))

    def test_malformed_partial_fan_is_excluded(self):
        malformed = synthetic_records()[0]
        del malformed["fields"]["one_way_time_s"]
        result = SwathRefractionTransform().transform(malformed)
        self.assertTrue(result["fields"]["REFR_Excluded"])
        self.assertIn("partial fan", result["fields"]["REFR_Reason"].lower())

    def test_demo_logger_chain_declarations_load(self):
        path = ROOT / "contrib/deepsignal/configs/swath_refraction_demo.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        for declaration in config["module_declarations"]:
            module = importlib.import_module(declaration["module"])
            self.assertTrue(hasattr(module, declaration["class"]))
        fixture_module = importlib.import_module(config["fixture"]["module"])
        fixture = getattr(fixture_module, config["fixture"]["function"])()
        transform = SwathRefractionTransform(**config["transform"]["kwargs"])
        self.assertTrue(transform.transform(fixture))


if __name__ == "__main__":
    unittest.main()
