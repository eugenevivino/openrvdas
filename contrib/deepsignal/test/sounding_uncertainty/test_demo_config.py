"""Offline logger declaration checks for the synthetic demonstration."""

import importlib
from pathlib import Path
import unittest

import yaml

from contrib.deepsignal.test.sounding_uncertainty.fixtures import packet_dict


ROOT = Path(__file__).parents[4]
CONFIG = ROOT / "contrib/deepsignal/configs/sounding_uncertainty_demo.yaml"


class DemoConfigTest(unittest.TestCase):

    def test_demo_logger_chain_declarations_load(self):
        document = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        config = document["configs"]["sounding_uncertainty->file"]
        declarations = [config["readers"], *config["transforms"],
                        *config["writers"]]
        for declaration in declarations:
            module = importlib.import_module(declaration["module"])
            self.assertTrue(hasattr(module, declaration["class"]))

    def test_demo_normal_record_path(self):
        module = importlib.import_module(
            "contrib.deepsignal.sounding_uncertainty.transform")
        transform = module.SoundingUncertaintyTransform()
        result = transform.transform(packet_dict())
        self.assertEqual(result[0]["timestamp"], "2026-11-18T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
