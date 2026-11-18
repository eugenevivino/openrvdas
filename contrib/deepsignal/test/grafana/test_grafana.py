import json
import tempfile
import unittest
from pathlib import Path

import yaml

from contrib.deepsignal.grafana import alerts, build, generate


class GrafanaTest(unittest.TestCase):
    def setUp(self):
        self.cruise = {
            "cruise": {"id": "TEST"},
            "loggers": {"weather": {"configs": ["weather-on"]}},
            "logger_configs": {
                "weather-on": {
                    "writers": [{
                        "class": "InfluxDBWriter",
                        "kwargs": {
                            "bucket_name": "science",
                            "measurement_name": "weather",
                        },
                    }],
                },
            },
        }
        self.options = {
            "fields": {"weather": ["AirTemp", "HeadingTrue", "TrueWindSpeed"]},
            "stale_after_s": 90,
        }

    def test_panels_queries_qc_and_compass_are_exact(self):
        dashboard = generate(self.cruise, self.options)
        self.assertEqual(39, dashboard["schemaVersion"])
        panels = dashboard["panels"]
        self.assertEqual(7, len(panels))
        value = panels[0]
        self.assertEqual("AirTemp", value["title"])
        self.assertEqual(
            [
                {"options": {"color": "green", "text": "good"}, "value": 1},
                {"options": {"color": "orange", "text": "suspect"}, "value": 3},
                {"options": {"color": "red", "text": "fail"}, "value": 4},
                {"options": {"color": "gray", "text": "missing"}, "value": 9},
            ],
            value["fieldConfig"]["defaults"]["mappings"][0]["options"],
        )
        self.assertEqual(
            [{"color": "green", "value": 1}, {"color": "orange", "value": 3},
             {"color": "red", "value": 4}, {"color": "gray", "value": 9}],
            value["fieldConfig"]["defaults"]["thresholds"]["steps"],
        )
        query = value["targets"][0]["query"]
        self.assertIn('from(bucket: "science")', query)
        self.assertIn('r._measurement == "weather"', query)
        self.assertIn('r._field == "AirTemp" or r._field == "AirTemp_QC"', query)
        self.assertEqual("oceandatatools-compass-panel", panels[-1]["type"])
        self.assertTrue(panels[-1]["optional"])

    def test_no_heading_means_no_compass(self):
        self.options["fields"] = {"weather": ["AirTemp", "TrueWindSpeed"]}
        dashboard = generate(self.cruise, self.options)
        self.assertNotIn("oceandatatools-compass-panel",
                         [panel["type"] for panel in dashboard["panels"]])

    def test_alert_rules_shape(self):
        rules = alerts(self.cruise, self.options)
        self.assertEqual({"fail", "stale"}, {rule["kind"] for rule in rules})
        self.assertTrue(all(rule["for"] == "5m" for rule in rules if rule["kind"] == "fail"))
        self.assertTrue(all(rule["stale_after_s"] == 90
                            for rule in rules if rule["kind"] == "stale"))

    def test_output_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            build(self.cruise, Path(first), self.options)
            build(self.cruise, Path(second), self.options)
            first_files = {p.name: p.read_bytes() for p in Path(first).iterdir()}
            second_files = {p.name: p.read_bytes() for p in Path(second).iterdir()}
            self.assertEqual(first_files, second_files)

    def test_nbp1406_cruise_builds_valid_json(self):
        path = Path("test/NBP1406/NBP1406_cruise.yaml")
        cruise = yaml.safe_load(path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as output:
            files = build(cruise, Path(output), {"base_dir": Path.cwd()})
            dashboards = [json.loads(path.read_text(encoding="utf-8"))
                          for path in files if path.name.endswith("dashboard.json")]
            self.assertTrue(dashboards)
            self.assertTrue(all(dashboard["schemaVersion"] == 39
                                for dashboard in dashboards))
            titles = {panel["title"] for panel in dashboards[0]["panels"]}
            self.assertIn("MwxAirTemp", titles)
            self.assertIn("Gyr1HeadingTrue", titles)


if __name__ == "__main__":
    unittest.main()
