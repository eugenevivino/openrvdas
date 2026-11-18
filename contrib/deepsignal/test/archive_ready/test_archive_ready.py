import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from contrib.deepsignal.archive_ready.archive_ready import generate_expected, scan


class ArchiveReadyTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.expected = {
            "datasets": [{
                "name": "met",
                "glob": "met/NBP1406_met-*",
                "cadence_seconds": 60,
                "time_field": 0,
                "filename_date_pattern": r"(\d{4}-\d{2}-\d{2})$",
                "required": True,
                "parser": "delimited",
            }]
        }
        self.meta = {
            "cruise_id": "NBP1406",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T00:10:00Z",
            "ports": ["Lyttelton", "McMurdo"],
            "now": "2024-01-01T00:10:00Z",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def write_data(self, name, times):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{value} value\n" for value in times), encoding="utf-8")
        return path

    def test_expected_generated_from_nbp1406(self):
        cruise_path = Path("test/NBP1406/NBP1406_cruise.yaml")
        cruise = yaml.safe_load(cruise_path.read_text(encoding="utf-8"))
        result = generate_expected(cruise)
        names = {dataset["name"] for dataset in result["datasets"]}
        self.assertIn("PCOD", names)
        pcod = next(item for item in result["datasets"] if item["name"] == "PCOD")
        self.assertEqual("/var/tmp/log/PCOD/raw/NBP1406_PCOD-*", pcod["glob"])

    def test_coverage_and_gap_math(self):
        self.write_data("met/NBP1406_met-2024-01-01", [
            "2024-01-01T00:00:00Z", "2024-01-01T00:01:00Z",
            "2024-01-01T00:05:00Z", "2024-01-01T00:10:00Z",
        ])
        result = scan(self.root, self.expected, self.meta)
        dataset = result["datasets"][0]
        self.assertEqual(100.0, dataset["coverage_percent"])
        self.assertEqual(2, len(dataset["files"][0]["gaps"]))
        self.assertEqual(4, dataset["files"][0]["record_count"])

    def test_changed_closed_file_is_error(self):
        path = self.write_data("met/NBP1406_met-2024-01-01", ["2024-01-01T00:00:00Z"])
        scan(self.root, self.expected, self.meta)
        path.write_text("2024-01-01T00:00:00Z changed\n", encoding="utf-8")
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 2))
        result = scan(self.root, self.expected, self.meta)
        self.assertIn("checksum_changed", {check["code"] for check in result["checks"]})

    def test_out_of_dates_and_naming_inconsistency(self):
        self.write_data("met/NBP1406_met-2023-12-31", ["2023-12-31T23:59:00Z"])
        self.write_data("met/badname", ["2024-01-01T00:01:00Z"])
        self.expected["datasets"][0]["glob"] = "met/*"
        result = scan(self.root, self.expected, self.meta)
        codes = {check["code"] for check in result["checks"]}
        self.assertIn("outside_cruise_dates", codes)
        self.assertIn("inconsistent_naming", codes)

    def test_cache_avoids_rehashing(self):
        self.write_data("met/NBP1406_met-2024-01-01", ["2024-01-01T00:00:00Z"])
        scan(self.root, self.expected, self.meta)
        with mock.patch("hashlib.sha256", side_effect=AssertionError("rehash")):
            scan(self.root, self.expected, self.meta)

    def test_manifest_is_append_only(self):
        self.write_data("met/NBP1406_met-2024-01-01", ["2024-01-01T00:00:00Z"])
        scan(self.root, self.expected, self.meta)
        before = (self.root / "manifest.jsonl").read_bytes()
        scan(self.root, self.expected, self.meta)
        after = (self.root / "manifest.jsonl").read_bytes()
        self.assertTrue(after.startswith(before))
        lines = [json.loads(line) for line in after.splitlines()]
        self.assertEqual(2, len(lines))


if __name__ == "__main__":
    unittest.main()
