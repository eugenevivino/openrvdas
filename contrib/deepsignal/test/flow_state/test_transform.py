import unittest

from logger.utils.das_record import DASRecord

from contrib.deepsignal.flow_state.transform import FlowStateTransform


ANCHOR = "2026-11-18T00:00:00Z"


def schedule_config(**overrides):
    schedule = {
        "anchor": ANCHOR,
        "open_minutes": 50,
        "closed_minutes": 10,
        "transition_seconds": 90,
        "open_content": "seawater",
        "closed_content": "filtered",
    }
    schedule.update(overrides)
    return [{"id": "filter", "tags_fields": ["TSG_Temp"],
             "mode": "schedule", "schedule": schedule}]


class FlowStateTransformTest(unittest.TestCase):
    def record(self, timestamp, fields=None):
        return {"timestamp": timestamp,
                "fields": fields if fields is not None else {"TSG_Temp": 2.1}}

    def test_schedule_boundaries_transitions_period_and_before_anchor(self):
        transform = FlowStateTransform(valves=schedule_config())
        cases = [
            ("2026-11-18T00:00:00Z", "transition", 0),
            ("2026-11-18T00:01:30Z", "seawater", 90),
            ("2026-11-18T00:50:00Z", "transition", 0),
            ("2026-11-18T00:51:00Z", "transition", 60),
            ("2026-11-18T01:00:00Z", "transition", 0),
            ("2026-11-17T23:59:00Z", "filtered", 540),
        ]
        for timestamp, state, age in cases:
            with self.subTest(timestamp=timestamp):
                fields = transform.transform(self.record(timestamp))["fields"]
                self.assertEqual(state, fields["filter_flow_state"])
                self.assertEqual(age, fields["filter_flow_state_age_s"])

    def test_records_without_tagged_fields_are_unchanged(self):
        transform = FlowStateTransform(valves=schedule_config())
        record = self.record(ANCHOR, {"Depth": 10})
        self.assertIs(record, transform.transform(record))
        self.assertEqual({"Depth": 10}, record["fields"])

    def test_field_mode_change_transition_unknown_and_no_state(self):
        valve = {"id": "filter", "tags_fields": ["TSG_Temp"],
                 "mode": "field", "state_field": "valve_state",
                 "values": {1: "seawater", 0: "filtered"},
                 "transition_seconds": 30}
        transform = FlowStateTransform(valves=[valve])
        no_state = transform.transform(self.record(ANCHOR))
        self.assertEqual("unknown", no_state["fields"]["filter_flow_state"])
        first = transform.transform(self.record(ANCHOR, {"valve_state": 1}))
        self.assertEqual({"valve_state": 1}, first["fields"])
        steady = transform.transform(self.record("2026-11-18T00:00:10Z"))
        self.assertEqual("seawater", steady["fields"]["filter_flow_state"])
        changed = transform.transform(self.record(
            "2026-11-18T00:00:20Z", {"valve_state": 0, "TSG_Temp": 2.2}))
        self.assertEqual("transition", changed["fields"]["filter_flow_state"])
        self.assertEqual(0, changed["fields"]["filter_flow_state_age_s"])
        after = transform.transform(self.record("2026-11-18T00:00:50Z"))
        self.assertEqual("filtered", after["fields"]["filter_flow_state"])
        with self.assertLogs(level="WARNING") as logs:
            transform.transform(self.record(
                "2026-11-18T00:01:00Z", {"valve_state": 7, "TSG_Temp": 2.3}))
            unknown = transform.transform(self.record("2026-11-18T00:01:01Z"))
        self.assertEqual("unknown", unknown["fields"]["filter_flow_state"])
        self.assertEqual(1, len(logs.output))

    def test_list_dasrecord_and_none(self):
        transform = FlowStateTransform(valves=schedule_config())
        das = DASRecord(timestamp=ANCHOR, fields={"TSG_Temp": 2.1})
        records = [das, self.record("2026-11-18T00:02:00Z")]
        self.assertIsNone(transform.transform(None))
        self.assertIs(records, transform.transform(records))
        self.assertEqual("transition", das.fields["filter_flow_state"])
        self.assertEqual("seawater", records[1]["fields"]["filter_flow_state"])

    def test_config_errors(self):
        invalid = [
            (schedule_config(closed_minutes=0), "closed_minutes"),
            ([{"id": "x", "tags_fields": ["x"], "mode": "manual"}], "mode"),
            (schedule_config(transition_seconds=601), "transition_seconds"),
        ]
        for valves, setting in invalid:
            with self.subTest(setting=setting):
                with self.assertRaisesRegex(ValueError, setting):
                    FlowStateTransform(valves=valves)


if __name__ == "__main__":
    unittest.main()
