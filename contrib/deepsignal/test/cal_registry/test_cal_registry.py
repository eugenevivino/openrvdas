import os
import tempfile
import unittest

import yaml

from contrib.deepsignal.cal_registry.registry import CalibrationRegistry
from contrib.deepsignal.cal_registry.registry import RegistryError
from contrib.deepsignal.cal_registry.registry import apply_formula
from contrib.deepsignal.cal_registry.registry import check_unit_suspicion
from contrib.deepsignal.cal_registry.registry import find_affected
from contrib.deepsignal.cal_registry.calibration_transform import CalibrationTransform
from logger.utils.das_record import DASRecord


BASE = {
    'sensor_id': 'tsg1', 'serial': '123', 'field': 'Conductivity',
    'units_in': 'mS/cm', 'units_out': 'S/m', 'form': 'linear',
    'coefficients': [0, 0.1], 'valid_from': '2024-01-01T00:00:00Z',
    'certificate': '#118:cert-1', 'entered_by': 'tech', 'checked_by': 'lead',
    'note': 'bench calibration',
}


class CalibrationRegistryTest(unittest.TestCase):
    def write_registry(self, entries):
        handle = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        yaml.safe_dump({'calibrations': entries}, handle)
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name))
        return handle.name

    def test_each_formula(self):
        self.assertEqual(7, apply_formula('linear', [1, 2], 3))
        self.assertEqual(16, apply_formula('polynomial', [1, 2, 1], 3))
        self.assertEqual(5, apply_formula('table', [[0, 0], [10, 20]], 2.5))

    def test_steinhart_hart_vector(self):
        coefficients = [1.129148e-3, 2.34125e-4, 8.76741e-8]
        self.assertAlmostEqual(298.15,
                               apply_formula('steinhart_hart', coefficients, 10000),
                               delta=0.01)

    def test_effective_boundaries_and_raw_untouched(self):
        first = dict(BASE, valid_to='2024-02-01T00:00:00Z')
        second = dict(BASE, coefficients=[1, 0.1],
                      valid_from='2024-02-01T00:00:00Z', certificate='#118:cert-2')
        transform = CalibrationTransform(registry_path=self.write_registry([first, second]),
                                         sensor_id='tsg1')
        record = {'timestamp': '2024-02-01T00:00:00Z', 'fields': {'Conductivity': 40}}
        result = transform.transform(record)
        self.assertEqual(40, result['fields']['Conductivity'])
        self.assertEqual(5, result['fields']['Conductivity_cal'])
        self.assertEqual('#118:cert-2', result['fields']['Conductivity_cal_version'])

    def test_overlap_is_error(self):
        one = dict(BASE, valid_to='2024-03-01T00:00:00Z')
        two = dict(BASE, valid_from='2024-02-01T00:00:00Z')
        with self.assertRaisesRegex(RegistryError, 'overlap'):
            CalibrationRegistry(self.write_registry([one, two]))

    def test_no_entry_and_none_and_lists(self):
        transform = CalibrationTransform(registry_path=self.write_registry([BASE]),
                                         sensor_id='tsg1')
        early = DASRecord(timestamp=1, fields={'Conductivity': 40})
        self.assertIsNone(transform.transform(None))
        result = transform.transform([early])[0]
        self.assertNotIn('Conductivity_cal', result.fields)
        self.assertEqual('none', result.fields['Conductivity_cal_state'])

    def test_unit_suspicion_warning(self):
        warning = check_unit_suspicion('conductivity', 'S/m', [39, 40, 41])
        self.assertIn('look like mS/cm', warning)
        self.assertIn('units say S/m', warning)

    def test_affected_outputs_from_nbp1406(self):
        outputs = find_affected('mwx_port', ['test/NBP1406/NBP1406_cruise.yaml'],
                                sensor_fields={'mwx_port': ['MwxPortRelWindSpeed']})
        self.assertIn('PortTrueWindSpeed', outputs)

    def test_verified_requires_different_people(self):
        registry = CalibrationRegistry(self.write_registry([
            BASE, dict(BASE, sensor_id='tsg2', entered_by='same', checked_by='same')]))
        self.assertTrue(registry.entries[0].verified)
        self.assertFalse(registry.entries[1].verified)

    def test_polynomial_order_limit(self):
        bad = dict(BASE, form='polynomial', coefficients=list(range(7)))
        with self.assertRaisesRegex(RegistryError, 'coefficients'):
            CalibrationRegistry(self.write_registry([bad]))


if __name__ == '__main__':
    unittest.main()
