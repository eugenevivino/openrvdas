import json
from pathlib import Path
import tempfile
import unittest

from contrib.deepsignal.vocab import VocabStore, import_cf, import_csv, import_nvs

FIXTURES = Path(__file__).parent / "fixtures"


class VocabTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = VocabStore(Path(self.temp_dir.name))

    def test_importers_lookup_and_search(self):
        import_cf(FIXTURES / "cf.xml", self.store)
        import_nvs(FIXTURES / "nvs.rdf", "l22", self.store)
        import_csv(FIXTURES / "devices.csv", "r2r_device_types", "code", "name", self.store)

        self.assertEqual("K", self.store.lookup("cf", "sea_water_temperature")["units"])
        self.assertEqual("Fixture thermometer", self.store.lookup("l22", "TOOL0001")["label"])
        self.assertEqual(
            ["CTD"], [item["id"] for item in self.store.search("r2r_device_types", "temperature")]
        )

    def test_check_tags_reports_all_findings(self):
        import_cf(FIXTURES / "cf.xml", self.store)
        findings = self.store.check_tags(FIXTURES / "tags.yaml")
        messages = [finding["message"] for finding in findings]

        self.assertTrue(any("compatible" in message for message in messages))
        self.assertTrue(any("metre" in message and "expected K" in message for message in messages))
        self.assertTrue(
            any("not_a_term" in message and "unknown" in message for message in messages)
        )
        self.assertTrue(
            any("l22" in message and "import it with import_nvs" in message for message in messages)
        )

    def test_import_refuses_entity_expansion(self):
        dangerous = Path(self.temp_dir.name) / "dangerous.xml"
        dangerous.write_text(
            '<!DOCTYPE x [<!ENTITY boom "expanded">]><standard_name_table>'
            '<entry id="bad"><canonical_units>K</canonical_units>'
            "<description>&boom;</description></entry></standard_name_table>",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "DOCTYPE"):
            import_cf(dangerous, self.store)

    def test_store_format(self):
        output = import_cf(FIXTURES / "cf.xml", self.store)
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("cf_standard_names", saved["scheme"])
        self.assertIn("version", saved)
        self.assertIn("source", saved)
        self.assertTrue(saved["imported"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
