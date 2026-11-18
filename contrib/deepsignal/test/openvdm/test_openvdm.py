import csv
import importlib.machinery
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

from contrib.deepsignal.openvdm.quality_day_writer import QualityDayWriter


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DIST = ROOT / "contrib/deepsignal/openvdm/dist"


def load_dist(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, str(DIST / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestQualityDayWriter(unittest.TestCase):
    def test_day_naming_rollover_and_append(self):
        with tempfile.TemporaryDirectory() as root:
            writer = QualityDayWriter(root=root, data_id="ctd")
            writer.write({"timestamp": "2026-11-17T23:59:00Z", "fields": {
                "temp": 10.2, "temp_QC": 1, "temp_QC_REASON": "in range"}})
            writer.write([{"timestamp": "2026-11-18T00:01:00Z", "fields": {
                "temp": 99, "temp_QC": 4, "temp_QC_REASON": "spike"}}])
            writer.write({"timestamp": "2026-11-17T23:59:30Z", "fields": {
                "salt": 35, "salt_QC": 1}})
            self.assertIsNone(writer.write(None))

            first = Path(root) / "ctd/ctd-quality-2026-11-17.csv"
            second = Path(root) / "ctd/ctd-quality-2026-11-18.csv"
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            with first.open(newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0], ["timestamp", "field", "value", "flag", "reason"])
            self.assertEqual(rows[1], ["2026-11-17T23:59:00Z", "temp", "10.2", "1", "in range"])
            self.assertEqual(rows[2], ["2026-11-17T23:59:30Z", "salt", "35", "1", ""])


class TestOpenVDMParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stub = load_dist("openvdm_stub", "../../test/openvdm/openvdm_stub.py")
        server = types.ModuleType("server")
        lib = types.ModuleType("server.lib")
        csv_module = types.ModuleType("server.lib.openvdm_csv_parser")
        plugin_module = types.ModuleType("server.lib.openvdm_plugin")
        csv_module.OpenVDMCSVParser = stub.OpenVDMCSVParser
        plugin_module.OpenVDMPlugin = stub.OpenVDMPlugin
        sys.modules.update({"server": server, "server.lib": lib,
                            "server.lib.openvdm_csv_parser": csv_module,
                            "server.lib.openvdm_plugin": plugin_module})
        cls.parser_module = load_dist(
            "deepsignal_quality_parser", "deepsignal_quality_parser.py.dist")
        sys.modules["deepsignal_quality_parser"] = cls.parser_module
        cls.plugin_module = load_dist("deepsignal_plugin", "deepsignal_plugin.py.dist")

    def parse(self, rows, options=None):
        with tempfile.NamedTemporaryFile("w", newline="", suffix=".csv") as stream:
            writer = csv.writer(stream)
            writer.writerow(["timestamp", "field", "value", "flag", "reason"])
            writer.writerows(rows)
            stream.flush()
            parser = self.parser_module.DeepSignalQualityParser(stream.name, options)
            return parser.parse()

    def test_pass_warning_fail_stats_and_visualizer(self):
        rows = []
        for hour in range(10):
            timestamp = "2026-11-18T%02d:00:00Z" % hour
            rows.extend([[timestamp, "pass", 1, 1, ""],
                         [timestamp, "warning", 1, 3 if hour == 0 else 1, "suspect"],
                         [timestamp, "fail", 1, 4 if hour == 0 else 1, "bad"]])
        output = self.parse(rows, {"fail_share": 0.01, "warn_share": 0.05})
        quality = {item["testName"]: item["results"] for item in output["qualityTests"]}
        self.assertEqual(quality, {"pass": "Passed", "warning": "Warning", "fail": "Failed"})
        self.assertEqual(output["stats"]["rowValidity"], {"valid": 30, "total": 30})
        self.assertEqual(output["stats"]["timeBounds"]["start"], 1794960000000)
        self.assertEqual(output["stats"]["timeBounds"]["end"], 1794992400000)
        series = {item["label"]: item["data"] for item in output["visualizerData"]}
        self.assertEqual(len(series["pass flag share"]), 10)
        self.assertEqual(series["fail flag share"][0], [1794960000000, 1.0])

    def test_invalid_rows_are_counted_not_guessed(self):
        output = self.parse([["bad-time", "temp", 1, 1, ""],
                             ["2026-11-18T00:00:00Z", "temp", 1, "x", ""]])
        self.assertEqual(output["stats"]["rowValidity"], {"valid": 0, "total": 2})

    def test_plugin_filter_matches_writer_names_only(self):
        plugin = self.plugin_module.DeepSignalPlugin()
        item = plugin.fileTypeFilters[0]
        import fnmatch
        self.assertTrue(fnmatch.fnmatch("ctd-quality-2026-11-18.csv", item["regex"]))
        self.assertFalse(fnmatch.fnmatch("ctd-2026-11-18.csv", item["regex"]))
        self.assertFalse(fnmatch.fnmatch("ctd-quality-2026-11-18.csv.bak", item["regex"]))


if __name__ == "__main__":
    unittest.main()
