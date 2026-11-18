import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from contrib.deepsignal.catalog import (catalog, check_component,
                                        check_config_file, schema)
from contrib.deepsignal.catalog.build import build_catalog, component_sources


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog()

    def test_catalog_count_matches_source_walk(self):
        expected = sum(len(classes) for classes in component_sources().values())
        self.assertEqual(expected, len(self.catalog['components']))

    def test_udp_port_is_required(self):
        udp = self.catalog['components']['UDPReader']
        self.assertIn('port', udp['schema']['required'])

    def test_missing_dependency_marks_component_unavailable(self):
        source = 'class ExampleReader(Reader):\n    def __init__(self, token):\n        pass\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'optional_reader.py'
            path.write_text(source, encoding='utf-8')
            with mock.patch(
                    'contrib.deepsignal.catalog.build._import_component_module',
                    side_effect=ModuleNotFoundError("No module named 'optional'")):
                result = build_catalog(module_files=[
                    ('reader', 'logger.readers.optional_reader', path)])
        entry = result['components']['ExampleReader']
        self.assertFalse(entry['available'])
        self.assertIn('optional', entry['error'])

    def test_typo_kwarg_gets_suggestion(self):
        result = check_component({
            'class': 'UDPReader', 'kwargs': {'port': 6224, 'interfase': ''}})
        self.assertEqual(1, len(result['findings']))
        self.assertIn("interface", result['findings'][0])

    def test_nbp1406_cruise_checks_cleanly(self):
        result = check_config_file('test/NBP1406/NBP1406_cruise.yaml')
        self.assertEqual([], result['findings'])

    def test_schema_and_facades_are_json_serializable(self):
        udp_schema = schema('UDPReader')
        self.assertIsInstance(udp_schema['required'], list)
        json.dumps(udp_schema)
        json.dumps(self.catalog)
        json.dumps(check_component({'class': 'UDPReader',
                                    'kwargs': {'port': 6224}}))

    def test_guided_yaml_is_safe_loadable(self):
        guided = Path('contrib/deepsignal/catalog/guided.yaml')
        self.assertIsInstance(yaml.safe_load(guided.read_text()), dict)


if __name__ == '__main__':
    unittest.main()
