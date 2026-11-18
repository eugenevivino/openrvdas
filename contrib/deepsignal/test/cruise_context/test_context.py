"""Tests for cruise context import and runtime tagging."""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock


from contrib.deepsignal.cruise_context import (CruiseContextReader, from_openvdm,
                                               from_sealog)
from contrib.deepsignal.cruise_context.__main__ import main


# shape from OpenVDM 2.17 source, verify on a live system
OPENVDM = {
    "cruise_id": "EN700", "cruise_name": "Deep Test", "cruise_description": "Survey",
    "chief_scientist": "A. PI", "start_date": "2026-11-01T00:00:00Z",
    "end_date": "2026-11-20T00:00:00Z", "start_port": "Woods Hole",
    "end_port": "Reykjavik", "cruise_location": "North Atlantic",
    "vessel": {"name": "Endeavor", "operator": "URI", "r2r_vessel_id": "EN",
               "r2r_operator_id": "URI", "r2r_scheduler_id": "EN"},
    "lowering_id": "J2-1700", "lowering_start_date": "2026-11-02T00:00:00Z",
    "lowering_end_date": None,
}


class ContextTest(unittest.TestCase):
    def test_openvdm_maps_cruise_meta(self):
        value = from_openvdm(OPENVDM)
        self.assertEqual(value["cruise"]["id"], "EN700")
        self.assertEqual(value["cruise"]["ports"]["start"], "Woods Hole")
        self.assertEqual(value["vessel"]["r2r"]["vessel_id"], "EN")
        self.assertEqual(value["lowering"]["id"], "J2-1700")

    def test_sealog_maps_and_missing_values_are_null(self):
        value = from_sealog({"cruise_id": "EN700", "start_ts": "start", "stop_ts": "stop",
                             "cruise_location": "Atlantic",
                             "cruise_additional_meta": {"lowering_id": "J2-1700"}})
        self.assertEqual(value["cruise"]["id"], "EN700")
        self.assertEqual(value["lowering"]["id"], "J2-1700")
        self.assertIsNone(value["cruise"]["name"])

    def test_cli_refuses_overwrite_and_prints_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "cruise.yaml")
            with open(output, "w", encoding="utf-8") as stream:
                stream.write("cruise: old\n")
            with mock.patch("contrib.deepsignal.cruise_context.__main__.fetch",
                            return_value=OPENVDM):
                with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                    main(["pull", "--openvdm", "http://vdm", "--out", output])
                text = io.StringIO()
                with redirect_stdout(text):
                    main(["pull", "--openvdm", "http://vdm", "--diff", output])
                self.assertIn("-cruise: old", text.getvalue())

    def test_reader_keeps_last_value_and_marks_stale(self):
        reader = CruiseContextReader("openvdm", "http://vdm", fetcher=mock.Mock(
            side_effect=[OPENVDM, OSError("offline")]))
        record = {"timestamp": 1, "fields": {"temperature": 2}}
        first = reader.transform(record)
        second = reader.transform(record, force=True)
        self.assertEqual(second["fields"]["cruise_id"], first["fields"]["cruise_id"])
        self.assertTrue(second["fields"]["cruise_context_stale"])

    def test_none_list_and_token_not_logged(self):
        os.environ["SECRET_TOKEN"] = "do-not-print"
        reader = CruiseContextReader("sealog", "http://sealog", token_env="SECRET_TOKEN",
                                     fetcher=mock.Mock(return_value={"cruise_id": "x"}))
        self.assertIsNone(reader.transform(None))
        self.assertEqual(len(reader.transform([{"timestamp": 1, "fields": {}}])), 1)
        self.assertNotIn("do-not-print", repr(reader))


if __name__ == "__main__":
    unittest.main()
