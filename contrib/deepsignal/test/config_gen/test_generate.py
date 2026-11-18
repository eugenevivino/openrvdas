import subprocess
import sys
import tempfile
import unittest
import warnings

import yaml

from contrib.deepsignal.config_gen import generate, render
from logger.utils.read_config import read_config


EXAMPLE = "contrib/deepsignal/configs/config_gen_example.yaml"


class GenerateTest(unittest.TestCase):
    def setUp(self):
        with open(EXAMPLE, encoding="utf-8") as source:
            self.acquisition = yaml.safe_load(source)

    def test_example_generates_loggers_modes_and_loadable_stable_yaml(self):
        result = generate(self.acquisition)
        self.assertEqual(["s330", "mwx1"], list(result["loggers"]))
        self.assertEqual(["s330-off", "s330-net", "s330-net+file"],
                         result["loggers"]["s330"]["configs"])
        self.assertEqual(["mwx1-off"], result["loggers"]["mwx1"]["configs"])
        self.assertEqual("s330-net", result["modes"]["monitor"]["s330"])
        self.assertEqual("s330-net+file", result["modes"]["log"]["s330"])
        self.assertNotIn("mwx1", result["modes"]["monitor"])
        first = render(generate(self.acquisition))
        self.assertEqual(first, render(generate(self.acquisition)))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as output:
            output.write(first)
            output.flush()
            self.assertEqual(result, read_config(output.name))

    def test_history_warns_both_ways(self):
        history = {"instruments": [
            {"id": "s330", "installed": False},
            {"id": "orphan", "installed": True},
        ]}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            generate(self.acquisition, history)
        messages = "\n".join(str(item.message) for item in caught)
        self.assertIn("s330", messages)
        self.assertIn("orphan", messages)

    def test_unknown_device_type_names_nearest_type(self):
        self.acquisition["instruments"][0]["device_type"] = "Seapath33O"
        with self.assertRaisesRegex(ValueError, "Seapath33O.*Seapath330"):
            generate(self.acquisition)

    def test_cli_refuses_to_overwrite(self):
        with tempfile.NamedTemporaryFile() as output:
            result = subprocess.run(
                [sys.executable, "-m", "contrib.deepsignal.config_gen",
                 EXAMPLE, "--out", output.name], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("already exists", result.stderr)


if __name__ == "__main__":
    unittest.main()
