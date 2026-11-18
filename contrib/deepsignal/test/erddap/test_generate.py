"""Tests for the DeepSignal ERDDAP dataset fragment generator."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

from contrib.deepsignal.erddap.generate import check, generate


EXAMPLE = {
    "institution": "Scripps Institution of Oceanography",
    "ship": {"name": "Roger Revelle", "call_sign": "KAOU"},
    "summary": "Meteorology from R/V Roger Revelle",
    "infoUrl": "https://example.invalid/revelle",
    "datasets": [{
        "id": "revelle_met_1min",
        "title": "R/V Revelle 1-minute meteorology",
        "directory": "/data/openrvdas/binned/met",
        "file_regex": r".*\.csv",
        "time_column": "time",
        "reload_minutes": 10,
        "variables": [
            {"column": "air_temperature", "units": "degree_C",
             "long_name": "Air temperature", "standard_name": "air_temperature",
             "ioos_category": "Meteorology"},
            {"column": "air_temperature_flag", "units": "1",
             "long_name": "Air temperature QARTOD flag", "flag_of": "air_temperature"},
        ],
    }],
}


def canonical(xml_text):
    """Return a whitespace-insensitive representation of XML."""
    root = ET.fromstring("<root>" + xml_text + "</root>")
    for element in root.iter():
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    return ET.tostring(root, encoding="unicode")


class GenerateTest(unittest.TestCase):
    def test_example_matches_golden_xml(self):
        expected = r"""<dataset type="EDDTableFromAsciiFiles" datasetID="revelle_met_1min"
          active="true">
          <reloadEveryNMinutes>10</reloadEveryNMinutes>
          <fileDir>/data/openrvdas/binned/met/</fileDir>
          <fileNameRegex>.*\.csv</fileNameRegex>
          <addAttributes>
            <att name="cdm_data_type">Other</att>
            <att name="Conventions">COARDS, CF-1.10, ACDD-1.3</att>
            <att name="institution">Scripps Institution of Oceanography</att>
            <att name="title">R/V Revelle 1-minute meteorology</att>
            <att name="summary">Meteorology from R/V Roger Revelle</att>
            <att name="platform">ship</att>
            <att name="infoUrl">https://example.invalid/revelle</att>
            <att name="license">See ship data policy</att>
          </addAttributes>
          <dataVariable>
            <sourceName>time</sourceName><destinationName>time</destinationName>
            <dataType>String</dataType><addAttributes>
              <att name="units">yyyy-MM-dd'T'HH:mm:ssZ</att>
            </addAttributes>
          </dataVariable>
          <dataVariable>
            <sourceName>air_temperature</sourceName>
            <destinationName>air_temperature</destinationName><dataType>double</dataType>
            <addAttributes><att name="units">degree_C</att>
              <att name="long_name">Air temperature</att>
              <att name="standard_name">air_temperature</att>
              <att name="ioos_category">Meteorology</att></addAttributes>
          </dataVariable>
          <dataVariable>
            <sourceName>air_temperature_flag</sourceName>
            <destinationName>air_temperature_flag</destinationName><dataType>double</dataType>
            <addAttributes><att name="units">1</att>
              <att name="long_name">Air temperature QARTOD flag</att>
              <att name="flag_values">1 2 3 4 9</att>
              <att name="flag_meanings">pass not_evaluated suspect fail missing</att>
            </addAttributes>
          </dataVariable>
        </dataset>"""
        self.assertEqual(canonical(expected), canonical(generate(EXAMPLE)))

    def test_xml_parses_and_escapes_special_characters(self):
        config = dict(EXAMPLE)
        config["datasets"] = [dict(EXAMPLE["datasets"][0], title="Wind & waves < underway")]
        output = generate(config)
        self.assertIn("Wind &amp; waves &lt; underway", output)
        ET.fromstring("<root>" + output + "</root>")

    def test_time_and_flag_attributes(self):
        root = ET.fromstring("<root>" + generate(EXAMPLE) + "</root>")
        variables = {node.findtext("sourceName"): node for node in root.iter("dataVariable")}
        time = variables["time"]
        self.assertEqual("time", time.findtext("destinationName"))
        self.assertEqual("yyyy-MM-dd'T'HH:mm:ssZ",
                         time.find("addAttributes/att[@name='units']").text)
        flag = variables["air_temperature_flag"]
        self.assertEqual("1 2 3 4 9", flag.find("addAttributes/att[@name='flag_values']").text)
        self.assertEqual("pass not_evaluated suspect fail missing",
                         flag.find("addAttributes/att[@name='flag_meanings']").text)


class CheckTest(unittest.TestCase):
    def test_reports_each_required_finding(self):
        config = {"datasets": [
            {"id": "bad-id", "variables": [{"column": "flag", "flag_of": "missing"}]},
            {"id": "bad-id", "variables": []},
        ]}
        findings = check(config)
        joined = "\n".join(findings)
        self.assertIn("dataset id saw 'bad-id'; expected letters, digits, or underscore", joined)
        self.assertIn("dataset id saw duplicate 'bad-id'; expected a unique id", joined)
        self.assertIn("variable flag units saw missing; expected a units value", joined)
        self.assertIn("variable flag flag_of saw 'missing'; expected an existing column", joined)

    def test_unknown_standard_name_warning_only_when_vocab_is_supplied(self):
        config = {"cf_standard_names": ["air_temperature"], "datasets": [{
            "id": "valid", "variables": [
                {"column": "x", "units": "1", "standard_name": "not_a_cf_name"}]}]}
        self.assertIn("WARNING: variable x standard_name saw 'not_a_cf_name'",
                      "\n".join(check(config)))


class CliTest(unittest.TestCase):
    def run_cli(self, command, config):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as stream:
            yaml.safe_dump(config, stream)
            path = stream.name
        try:
            return subprocess.run(
                [sys.executable, "-m", "contrib.deepsignal.erddap", command, path],
                cwd=os.getcwd(), text=True, capture_output=True, check=False)
        finally:
            os.unlink(path)

    def test_generate_cli_succeeds(self):
        result = self.run_cli("generate", EXAMPLE)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("<dataset", result.stdout)

    def test_check_cli_exit_codes(self):
        good = self.run_cli("check", EXAMPLE)
        self.assertEqual(0, good.returncode, good.stdout + good.stderr)
        bad = self.run_cli("check", {"datasets": [{"id": "bad-id", "variables": []}]})
        self.assertEqual(1, bad.returncode)
        self.assertIn("ERROR:", bad.stdout)

    def test_cli_rejects_unsafe_or_malformed_yaml_plainly(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as stream:
            stream.write("!!python/object/apply:os.system ['echo unsafe']")
            path = stream.name
        try:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = subprocess.run(
                    [sys.executable, "-m", "contrib.deepsignal.erddap", "check", path],
                    text=True, capture_output=True, check=False)
            self.assertEqual(1, result.returncode)
            self.assertIn("configuration YAML saw invalid content", result.stderr)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
