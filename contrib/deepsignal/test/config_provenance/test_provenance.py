import json
import os
import tempfile
import unittest

import yaml

from contrib.deepsignal.config_provenance.provenance import ConfigHistory
from contrib.deepsignal.config_provenance.provenance import ConfigWatcher
from contrib.deepsignal.config_provenance.provenance import semantic_diff


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = os.path.join(self.temp.name, "NBP1406.yaml")
        self.store = ConfigHistory(os.path.join(self.temp.name, "history"))

    def write(self, value):
        with open(self.config, "w", encoding="utf-8") as output:
            yaml.safe_dump(value, output)

    def base(self):
        return {"loggers": {"gps": {"mode": "live", "reader": {
            "port": "/dev/ttyS1", "baud": 4800, "device_type": "NMEA"},
            "transforms": ["prefix"], "writer": {"path": "/data/gps"},
            "calibration": {"scale": 1.0}, "units": "degrees"}}}

    def test_each_semantic_diff_kind(self):
        old = self.base()
        changes = {
            "source_changed": ("reader", "port", "udp://0.0.0.0:6224"),
            "serial_setting": ("reader", "baud", 9600),
            "parser_changed": ("reader", "device_type", "Garmin"),
            "writer_changed": ("writer", "path", "/data/nav"),
            "mode_changed": (None, "mode", "paused"),
            "calibration_changed": ("calibration", "scale", 1.2),
            "units_changed": (None, "units", "radians"),
        }
        for kind, (section, key, value) in changes.items():
            new = json.loads(json.dumps(old))
            target = new["loggers"]["gps"]
            (target[section] if section else target)[key] = value
            self.assertIn(kind, {item["kind"] for item in
                                 semantic_diff(old, new)})
        new = json.loads(json.dumps(old))
        new["loggers"]["gps"]["transforms"].append("checksum")
        self.assertEqual("transform_added", semantic_diff(old, new)[0]["kind"])
        self.assertEqual("transform_removed", semantic_diff(new, old)[0]["kind"])
        new = json.loads(json.dumps(old))
        new["loggers"]["depth"] = {"reader": {"port": "/dev/ttyS2"}}
        self.assertIn("logger_added", {d["kind"] for d in semantic_diff(old, new)})
        self.assertIn("logger_removed", {d["kind"] for d in semantic_diff(new, old)})

    def test_rename_is_detected_as_rename(self):
        old = self.base()
        new = self.base()
        new["loggers"]["position"] = new["loggers"].pop("gps")
        self.assertEqual(["renamed"], [d["kind"] for d in
                                       semantic_diff(old, new)])

    def test_note_is_required_for_high_risk_change(self):
        self.write(self.base())
        self.store.snapshot([self.config], "tech", "initial import")
        value = self.base()
        value["loggers"]["gps"]["reader"]["baud"] = 9600
        self.write(value)
        with self.assertRaisesRegex(ValueError, "note.*high-risk"):
            self.store.snapshot([self.config], "tech", "")

    def test_history_is_append_only_and_content_addressing_dedupes(self):
        self.write(self.base())
        version = self.store.snapshot([self.config], "tech", "initial")
        again = self.store.snapshot([self.config], "tech", "unchanged")
        self.assertEqual(version, again)
        self.assertEqual(2, len(self.store.log()))
        snapshots = [name for name in os.listdir(self.store.directory)
                     if name.endswith(".yaml")]
        self.assertEqual(1, len(snapshots))

    def test_watch_records_external_edit(self):
        self.write(self.base())
        watcher = ConfigWatcher(self.store, [self.config])
        self.assertIsNone(watcher.poll())
        value = self.base()
        value["loggers"]["gps"]["mode"] = "paused"
        self.write(value)
        record = watcher.poll()
        self.assertEqual("unknown, detected", record["who"])
        self.assertEqual("config_provenance", record["fields"]["event"])

    def test_drift_ignores_comments_and_order_changes(self):
        first = "loggers:\n  gps:\n    mode: live\n    units: degrees\n"
        second = "# edited comment\nloggers:\n  gps:\n    units: degrees\n    mode: live\n"
        self.assertEqual([], semantic_diff(yaml.safe_load(first),
                                           yaml.safe_load(second)))


if __name__ == "__main__":
    unittest.main()
