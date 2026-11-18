import datetime
import tempfile
import unittest

from contrib.deepsignal.stream_health.stream_health import (
    StreamHealthWriter,
    TransitionTracker,
    describe_chain,
    evaluate,
)


NOW = datetime.datetime(2026, 11, 18, tzinfo=datetime.timezone.utc)


class StreamHealthTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "streams": {
                "met": {
                    "logger": "met_logger",
                    "key_fields": ["wind_speed"],
                    "expected_period_s": 1,
                    "derived": ["true_wind"],
                }
            }
        }

    def test_each_failure_selects_root_and_affected_outputs(self):
        for stage in describe_chain(self.cfg)["stages"]:
            stage_facts = {name: {"state": "OK", "evidence": "test healthy"}
                           for name in describe_chain(self.cfg)["stages"]}
            stage_facts[stage] = {"state": "FAILED", "evidence": "test failure"}
            snapshot = {"met": {"stages": stage_facts}}
            result = evaluate(self.cfg, snapshot, NOW)["met"]
            self.assertEqual(stage, result["root"])
            self.assertEqual(["true_wind"], result["affected_outputs"])
            root_index = describe_chain(self.cfg)["stages"].index(stage)
            later = describe_chain(self.cfg)["stages"][root_index + 1:]
            self.assertTrue(all(result["stages"][name].get("affected")
                                for name in later))

    def test_flapping_inside_hold_and_recovery(self):
        tracker = TransitionTracker(hold_s=10)
        self.assertEqual([], tracker.update("met", "parser", "OK", 0, ""))
        self.assertEqual([], tracker.update("met", "parser", "FAILED", 1, "bad"))
        self.assertEqual([], tracker.update("met", "parser", "OK", 5, "good"))
        self.assertEqual([], tracker.update("met", "parser", "FAILED", 6, "bad"))
        failed = tracker.update("met", "parser", "FAILED", 16, "bad")
        self.assertEqual("FAILED", failed[0]["to"])
        self.assertEqual([], tracker.update("met", "parser", "OK", 17, "good"))
        recovered = tracker.update("met", "parser", "OK", 27, "good")
        self.assertEqual(("FAILED", "OK"),
                         (recovered[0]["from"], recovered[0]["to"]))

    def test_rate_cap_holds(self):
        tracker = TransitionTracker(hold_s=0, rate_cap=1, rate_window_s=60)
        tracker.update("met", "parser", "OK", 0, "")
        self.assertEqual(1, len(tracker.update(
            "met", "parser", "FAILED", 1, "bad")))
        tracker.update("met", "parser", "OK", 2, "good")
        self.assertEqual([], tracker.update(
            "met", "parser", "DEGRADED", 3, "worse"))

    def test_timeout_adds_null_and_age_without_changing_input(self):
        writer = StreamHealthWriter(self.cfg, field_timeouts={"wind_speed": 5})
        record = {"timestamp": 100, "fields": {"wind_speed": 12}}
        output = writer.transform(record, now=110)
        self.assertEqual(12, record["fields"]["wind_speed"])
        self.assertIsNone(output["fields"]["wind_speed"])
        self.assertEqual(10, output["fields"]["ds_age_s:wind_speed"])
        self.assertIsNone(writer.transform(None, now=110))

    def test_endpoint_check_never_opens_port(self):
        called = []
        cfg = {"streams": {"met": dict(
            self.cfg["streams"]["met"], endpoint="/dev/fake")}}
        result = evaluate(cfg, {"endpoint_opener": lambda path: called.append(path)},
                          NOW)
        self.assertEqual([], called)
        self.assertIn(result["met"]["stages"]["endpoint"]["state"],
                      ("OK", "UNKNOWN"))

    def test_missing_store_directory_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {"streams": {"met": dict(
                self.cfg["streams"]["met"], store=directory + "/missing")}}
            result = evaluate(cfg, {}, NOW)
        self.assertEqual("UNKNOWN",
                         result["met"]["stages"]["store"]["state"])


if __name__ == "__main__":
    unittest.main()
