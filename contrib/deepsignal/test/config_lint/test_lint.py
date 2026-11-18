"""Tests for the DeepSignal cruise configuration linter."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from contrib.deepsignal.config_lint import lint
from contrib.deepsignal.config_lint.__main__ import main


def component(class_name, **kwargs):
    """Return a compact OpenRVDAS component definition."""
    return {"class": class_name, "kwargs": kwargs}


def cruise(configs, modes=None, loggers=None):
    """Build the smallest useful cruise definition."""
    names = list(configs)
    return {
        "configs": configs,
        "loggers": loggers or {"one": {"configs": names}},
        "modes": modes or {"write": {"one": names[0]}},
    }


class LintTest(unittest.TestCase):
    def test_nb1406_has_no_errors_and_expected_warning_baseline(self):
        path = Path("test/NBP1406/NBP1406_cruise.yaml")
        definition = yaml.safe_load(path.read_text(encoding="utf-8"))
        findings = lint(definition)
        self.assertEqual([], [item for item in findings if item["level"] == "error"])
        warning_messages = [item["message"] for item in findings
                            if item["level"] == "warning"]
        self.assertEqual(106, len(warning_messages))
        self.assertTrue(any("CachedDataWriter" in message for message in warning_messages))
        self.assertTrue(any("timeout" in message for message in warning_messages))

    def test_duplicate_serial_and_udp_inputs_are_errors(self):
        configs = {
            "a": {"readers": [component("SerialReader", port="/dev/ttyS0")]},
            "b": {"readers": [component("SerialReader", port="/dev/ttyS0")]},
            "c": {"readers": [component("UDPReader", port=5000)]},
            "d": {"readers": [component("UDPReader", port=5000)]},
        }
        definition = cruise(
            configs,
            {"science": {"a_logger": "a", "b_logger": "b", "c_logger": "c", "d_logger": "d"}},
            {name + "_logger": {"configs": [name]} for name in configs},
        )
        messages = [item["message"] for item in lint(definition) if item["level"] == "error"]
        self.assertTrue(any("serial port /dev/ttyS0" in message
                            for message in messages))
        self.assertTrue(any("UDP port 5000" in message
                            for message in messages))

    def test_mode_reference_and_missing_logger_are_errors(self):
        definition = cruise(
            {"a": {}},
            {"science": {"one": "missing"}},
            {"one": {"configs": ["a"]}, "two": {"configs": ["a"]}},
        )
        messages = [item["message"] for item in lint(definition) if item["level"] == "error"]
        self.assertTrue(any("missing" in message and "does not exist" in message
                            for message in messages))
        self.assertTrue(any("logger two" in message and "science" in message
                            for message in messages))

    def test_writer_prefix_timeout_and_root_warnings(self):
        definition = cruise({
            "a": {
                "readers": [component("SerialReader", port="/dev/a")],
                "transforms": [component("PrefixTransform", prefix="same")],
                "writers": [component("LogfileWriter", filebase="/tmp/out")],
            },
            "b": {
                "transforms": [component("PrefixTransform", prefix="same")],
                "writers": [component("CachedDataWriter")],
            },
        }, {"write": {"one": "a", "two": "b"}},
           {"one": {"configs": ["a"]}, "two": {"configs": ["b"]}})
        messages = [item["message"] for item in lint(definition, root="/data")
                    if item["level"] == "warning"]
        self.assertTrue(any("CachedDataWriter" in message for message in messages))
        self.assertTrue(any("LogfileWriter" in message for message in messages))
        self.assertTrue(any("data id same" in message for message in messages))
        self.assertTrue(any("timeout" in message for message in messages))
        self.assertTrue(any("outside configured root /data" in message for message in messages))

    def test_unused_config_is_info(self):
        definition = cruise({"used": {}, "spare": {}}, loggers={
            "one": {"configs": ["used", "spare"]},
        })
        findings = lint(definition)
        self.assertTrue(any(item["level"] == "info" and "spare" in item["message"]
                            for item in findings))

    @mock.patch("contrib.deepsignal.config_lint._core_findings")
    def test_core_validator_findings_are_included(self, core_findings):
        core_findings.return_value = [{
            "level": "error", "where": "cruise", "message": "core says invalid",
            "fix": "repair the schema",
        }]
        self.assertIn(core_findings.return_value[0], lint(cruise({"off": {}})))

    def test_cli_exit_codes_and_plain_english_output(self):
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory, "good.yaml")
            bad = Path(directory, "bad.yaml")
            good.write_text(yaml.safe_dump(cruise({"off": {}})), encoding="utf-8")
            bad.write_text(yaml.safe_dump(cruise(
                {"off": {}}, {"science": {"one": "absent"}}
            )), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, main([str(good)]))
                self.assertEqual(1, main([str(bad)]))
            self.assertIn("ERROR", output.getvalue())
            self.assertIn("Fix:", output.getvalue())

    def test_cli_rejects_unsafe_or_non_mapping_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "bad.yaml")
            path.write_text("!!python/object:object {}", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, main([str(path)]))


if __name__ == "__main__":
    unittest.main()
