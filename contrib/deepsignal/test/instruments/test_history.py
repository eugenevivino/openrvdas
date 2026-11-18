"""Tests for the DeepSignal instrument history registry."""

import datetime
import os
import subprocess
import sys
import tempfile
import unittest

from contrib.deepsignal.instruments.history import InstrumentHistory


UTC = datetime.timezone.utc


def event(time, event_type, **values):
    return {"time": time, "type": event_type, **values}


def instrument(identifier="tsg1", serial="0231", fields=None, events=None, **values):
    return {
        "id": identifier,
        "make": "Sea-Bird",
        "model": "SBE45",
        "serial": serial,
        "fields": fields or ["TSG_Temp"],
        "events": events or [],
        **values,
    }


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.events = [
            event("2026-03-01T00:00Z", "install", position="lab"),
            event("2026-03-01T00:00Z", "calibration", cal_id="c1",
                  coefficients={"TSG_Temp": [0.1, 1.0]}, valid_until="2027-01-01"),
            event("2026-06-01T00:00Z", "firmware", version="2.1b"),
            event("2026-09-30T00:00Z", "remove"),
        ]
        self.history = InstrumentHistory.from_dict(
            {"instruments": [instrument(events=self.events)]})

    def test_state_and_field_queries_at_boundaries(self):
        before = self.history.state_at("tsg1", "2026-02-28T23:59:59Z")
        installed = self.history.state_at("tsg1", "2026-03-01T00:00Z")
        removed = self.history.state_at("tsg1", "2026-09-30T00:00Z")
        self.assertFalse(before["installed"])
        self.assertIsNone(before["position"])
        self.assertTrue(installed["installed"])
        self.assertEqual("lab", installed["position"])
        self.assertEqual("0231", installed["serial"])
        self.assertEqual("c1", installed["calibration"]["cal_id"])
        self.assertFalse(removed["installed"])
        self.assertEqual(self.history.instrument_for_field(
            "TSG_Temp", "2026-03-01T00:00Z"), installed)
        self.assertIsNone(self.history.instrument_for_field(
            "TSG_Temp", "2026-09-30T00:00Z"))
        self.assertIsNone(self.history.calibration_for_field(
            "TSG_Temp", "2026-02-01T00:00Z"))
        self.assertEqual("c1", self.history.calibration_for_field(
            "TSG_Temp", 1772323200)["cal_id"])

    def test_bare_dates_and_serial_strings(self):
        history = InstrumentHistory.from_dict({"instruments": [instrument(
            serial="0007", events=[event("2026-03-01", "install", position="lab")])
        ]})
        self.assertEqual("0007", history.state_at("tsg1", "2026-03-01")["serial"])
        self.assertTrue(history.state_at(
            "tsg1", datetime.datetime(2026, 3, 1, tzinfo=UTC))["installed"])

    def test_segment_breaks_includes_cleaning_and_swap_sorted(self):
        history = InstrumentHistory.from_dict({"instruments": [instrument(events=[
            event("2026-03-03T00:00Z", "swap", replaces="old"),
            event("2026-03-01T00:00Z", "install", position="lab"),
            event("2026-03-02T00:00Z", "cleaning", note="rinse"),
            event("2026-03-02T12:00Z", "note", note="not a break"),
        ])]})
        self.assertEqual([
            datetime.datetime(2026, 3, 1, tzinfo=UTC),
            datetime.datetime(2026, 3, 2, tzinfo=UTC),
            datetime.datetime(2026, 3, 3, tzinfo=UTC),
        ], history.segment_breaks("TSG_Temp", "2026-03-01", "2026-03-04"))

    def test_checker_reports_all_finding_kinds(self):
        bad_events = [
            event("2026-03-02T00:00Z", "calibration", cal_id="late",
                  coefficients={"OTHER": [1]}, valid_until="2026-03-01"),
            event("2026-03-01T00:00Z", "firmware", version="1"),
            event("2026-03-03T00:00Z", "mystery"),
            event("2026-03-04T00:00Z", "install", position="lab"),
        ]
        data = {"instruments": [
            instrument(events=bad_events, shares=[{"id": "missing", "what": "intake"}]),
            instrument("tsg2", serial="0231", events=[
                event("2026-03-04T00:00Z", "install", position="deck")]),
        ]}
        messages = [finding["message"] for finding in
                    InstrumentHistory.from_dict(data).check("2026-04-01")]
        expected = ["out of time order", "while not installed", "expired",
                    "does not list", "unknown event type", "no calibration",
                    "same serial", "field TSG_Temp", "missing instrument"]
        for phrase in expected:
            self.assertTrue(any(phrase in message for message in messages), phrase)

    def test_validation_messages_are_actionable(self):
        cases = [
            ({}, "instrument <unknown>, setting instruments"),
            ({"instruments": [{}]}, "instrument <unknown>, setting id"),
            ({"instruments": [instrument(serial=231)]},
             "instrument tsg1, setting serial, saw 231, expected a string"),
            ({"instruments": [instrument(events=[{"type": "install"}])]},
             "instrument tsg1, setting event time"),
        ]
        for data, text in cases:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, text):
                InstrumentHistory.from_dict(data)

    def test_load_uses_safe_yaml(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as output:
            output.write("instruments: !!python/object:builtins.object {}\n")
            path = output.name
        try:
            with self.assertRaises(Exception):
                InstrumentHistory.load(path)
        finally:
            os.unlink(path)

    def test_cli_exit_codes(self):
        example = "contrib/deepsignal/configs/instrument_history_example.yaml"
        good = subprocess.run(
            [sys.executable, "-m", "contrib.deepsignal.instruments", "check", example],
            check=False, capture_output=True, text=True)
        at = subprocess.run(
            [sys.executable, "-m", "contrib.deepsignal.instruments", "at", example,
             "TSG_Temp", "2014-06-01T00:00Z"],
            check=False, capture_output=True, text=True)
        self.assertEqual(0, good.returncode, good.stderr)
        self.assertEqual(0, at.returncode, at.stderr)
        self.assertIn("installed", at.stdout)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as output:
            output.write("""instruments:
  - {id: bad, make: x, model: x, serial: '1', fields: [x],
     events: [{time: 2026-01-01, type: unknown}]}
""")
            bad_path = output.name
        try:
            bad = subprocess.run(
                [sys.executable, "-m", "contrib.deepsignal.instruments", "check",
                 bad_path], check=False, capture_output=True, text=True)
            self.assertEqual(1, bad.returncode)
            self.assertIn("unknown event type", bad.stdout)
        finally:
            os.unlink(bad_path)


if __name__ == "__main__":
    unittest.main()
