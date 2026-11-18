import json
import os
import tempfile
import unittest
from unittest import mock

from logger.utils.das_record import DASRecord

from contrib.deepsignal.shore_snapshot.shore_snapshot_writer import ShoreSnapshotWriter


FIELDS = [
    {"name": "air_temp", "label": "Air temp", "units": "degC", "decimals": 1},
    {"name": "wind", "label": "Wind", "units": "m/s", "decimals": 0},
]


class ShoreSnapshotWriterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def writer(self, **kwargs):
        options = {"fields": FIELDS, "period_s": 60, "out_dir": self.temp_dir.name,
                   "ship": "R/V Test", "max_bytes": 4096}
        options.update(kwargs)
        return ShoreSnapshotWriter(**options)

    def snapshot(self):
        with open(os.path.join(self.temp_dir.name, "snapshot.json"), encoding="utf-8") as source:
            return json.load(source)

    def test_rounding_age_and_qc_passthrough(self):
        writer = self.writer()
        writer.write({"timestamp": 100, "fields": {
            "air_temp": 21.36, "air_temp_QC": 2}})
        writer.write(DASRecord(timestamp=160, fields={"wind": 8.7}))
        fields = self.snapshot()["fields"]
        self.assertEqual(fields[0], {"n": "air_temp", "v": 21.4, "u": "degC",
                                     "age_s": 60, "q": 2})
        self.assertEqual(fields[1], {"n": "wind", "v": 9.0, "u": "m/s",
                                     "age_s": 0, "q": None})

    def test_stale_wording_and_escaped_label(self):
        writer = self.writer(fields=[{"name": "air_temp", "label": "Air <temp>",
                                      "units": "degC", "decimals": 1}])
        writer.write({"timestamp": 100, "fields": {"air_temp": 21.4}})
        writer.write({"timestamp": 300, "fields": {}})
        with open(os.path.join(self.temp_dir.name, "snapshot.svg"), encoding="utf-8") as source:
            svg = source.read()
        self.assertIn("STALE", svg)
        self.assertIn("Air &lt;temp&gt;", svg)
        self.assertNotIn("<script", svg.lower())

    def test_byte_cap_drops_trailing_fields(self):
        full_writer = self.writer()
        full_writer.write({"timestamp": 100, "fields": {"air_temp": 21.4, "wind": 9}})
        full_size = os.path.getsize(os.path.join(self.temp_dir.name, "snapshot.json"))
        writer = self.writer(max_bytes=full_size - 10)
        writer.write({"timestamp": 200, "fields": {"air_temp": 21.4, "wind": 9}})
        result = self.snapshot()
        self.assertLessEqual(os.path.getsize(os.path.join(self.temp_dir.name, "snapshot.json")),
                             full_size - 10)
        self.assertEqual(result["truncated"], 1)
        self.assertEqual([field["n"] for field in result["fields"]], ["air_temp"])

    def test_atomic_replace_hides_partial_destination(self):
        writer = self.writer()
        real_replace = os.replace
        destinations = []

        def observe_replace(source, destination):
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))
            destinations.append(os.path.basename(destination))
            real_replace(source, destination)

        with mock.patch("contrib.deepsignal.shore_snapshot.shore_snapshot_writer.os.replace",
                        side_effect=observe_replace):
            writer.write({"timestamp": 100, "fields": {"air_temp": 1}})
        self.assertCountEqual(destinations, ["snapshot.json", "snapshot.svg"])

    def test_period_boundary_uses_record_time_and_lists(self):
        writer = self.writer()
        self.assertIsNone(writer.write(None))
        writer.write([{"timestamp": 100, "fields": {"air_temp": 1}},
                      {"timestamp": 159, "fields": {"air_temp": 2}}])
        self.assertEqual(self.snapshot()["time"], 100)
        writer.write({"timestamp": 160, "fields": {"air_temp": 3}})
        self.assertEqual(self.snapshot()["time"], 160)


if __name__ == "__main__":
    unittest.main()
