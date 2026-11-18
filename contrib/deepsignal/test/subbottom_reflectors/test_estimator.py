"""Executable contract for the future numerical implementation."""

import copy
import importlib
from pathlib import Path
import unittest

import yaml

from contrib.deepsignal.subbottom_reflectors.contract import RESULT_FIELDS, validate_trace_shape
from contrib.deepsignal.subbottom_reflectors.estimator import estimate_reflectors
from contrib.deepsignal.test.subbottom_reflectors.fixtures import four_trace_gap, synthetic_crossing


class EstimatorContractTest(unittest.TestCase):
    def test_record_shape(self):
        self.assertEqual(set(), validate_trace_shape(synthetic_crossing(count=1)[0]))
        self.assertEqual(16, len(RESULT_FIELDS))

    def test_immutable_inputs(self):
        traces = synthetic_crossing(count=8)
        original = copy.deepcopy(traces)
        try:
            estimate_reflectors(traces)
        except NotImplementedError:
            pass
        self.assertEqual(original, traces)

    def test_replay_determinism(self):
        traces = synthetic_crossing(count=8)
        self.assertEqual(estimate_reflectors(traces), estimate_reflectors(traces))

    def test_absent_channels(self):
        trace = synthetic_crossing(count=1)[0]
        del trace["bottom_twt_s"]
        results = estimate_reflectors([trace])
        self.assertEqual("missing bottom_twt_s", results[0]["SBPH_Reason"])

    def test_demo_logger_chain(self):
        config_path = Path("contrib/deepsignal/configs/subbottom_reflectors_demo.yaml")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        declaration = config["transforms"][0]
        module = importlib.import_module(declaration["module"])
        transform = getattr(module, declaration["class"])(**declaration["kwargs"])
        result = transform.transform(synthetic_crossing(count=1)[0])
        self.assertIn("SBPH_TraceId", result)

    def test_draft_shifts_order_two_four_ms(self):
        zero = synthetic_crossing(count=1)[0]
        draft = synthetic_crossing(count=1, draft_m=3.0)[0]
        expected_zero = 2 * zero["bottom_twt_s"]
        expected_draft = 2 * draft["bottom_twt_s"] + 0.004
        self.assertAlmostEqual(0.004, expected_draft - expected_zero)

    def test_shallow_primary_is_separate(self):
        trace = synthetic_crossing(count=1, include_shallow=True)[0]
        results = estimate_reflectors([trace])
        picks = [item["SBPH_PickTWT_s"] for item in results]
        self.assertTrue(any(abs(value - 0.052) <= 0.001 for value in picks))

    def test_primary_disappears_inside_multiple_tube(self):
        results = estimate_reflectors(synthetic_crossing())
        crossing = [item for item in results if item["SBPH_TraceId"] == "T100"]
        self.assertEqual("AMBIGUOUS", crossing[0]["SBPH_Verdict"])
        self.assertIsNotNone(crossing[0]["SBPH_Alternative"])

    def test_no_pick_in_trace_gap(self):
        results = estimate_reflectors(four_trace_gap())
        gaps = {item["SBPH_TraceId"]: item for item in results}
        for trace_id in ("T004", "T005", "T006", "T007"):
            self.assertTrue(gaps[trace_id]["SBPH_Gap"])
            self.assertIsNone(gaps[trace_id]["SBPH_PickTWT_s"])

    def test_terminate_at_three_missing(self):
        results = estimate_reflectors(four_trace_gap())
        self.assertEqual("terminated", results[6]["track_state"])
        self.assertNotEqual("terminated", results[5]["track_state"])

    def test_order3_timing_sd(self):
        results = estimate_reflectors(synthetic_crossing(count=1))
        self.assertAlmostEqual(0.00075, results[0]["order3_timing_sd_s"])

    def test_repeated_positions(self):
        traces = synthetic_crossing(count=6)
        traces[2]["x_m"] = traces[1]["x_m"]
        results = estimate_reflectors(traces)
        self.assertIn(results[2]["position_status"], ("merged", "flagged"))

    def test_withheld_traces_one_footprint(self):
        traces = synthetic_crossing(count=8)
        traces[2]["withheld"] = traces[3]["withheld"] = True
        results = estimate_reflectors(traces)
        self.assertEqual(1, results[0]["withheld_independent_blocks"])


if __name__ == "__main__":
    unittest.main()
