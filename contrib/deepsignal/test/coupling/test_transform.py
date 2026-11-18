import json
import os
import tempfile
import unittest

from contrib.deepsignal.coupling.transform import ShipCouplingTransform
from logger.utils.das_record import DASRecord


class TransformTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, 'atlas.json')
        atlas = {'parameters': {'sectors': 12, 'speed_bands': [1, 5, 10]},
                 'healthy_spread': {'temp': 1},
                 'hypotheses': [{'field': 'temp', 'ship_variable': 'relative_heading',
                                 'status': 'confirmed', 'regime': 'transit',
                                 'invariance': 'ship_artifact'}],
                 'polar': {'temp': [{'sector': 3, 'speed_band': 1, 'regime': 'transit',
                                     'median': 2, 'iqr': 1}]}}
        with open(self.path, 'w', encoding='utf-8') as stream:
            json.dump(atlas, stream)
        self.transform = ShipCouplingTransform(self.path, ['temp'])

    def tearDown(self):
        self.temp.cleanup()

    def test_dict_copy_and_missing_state(self):
        original = {'temp': 10}
        result = self.transform.transform(original)
        self.assertEqual(original, {'temp': 10})
        self.assertEqual(result['temp_SHIP_QC'], 2)

    def test_state_score_and_containers(self):
        self.transform.transform({'relative_heading': 100, 'sog': 4})
        result = self.transform.transform({'temp': 10})
        self.assertEqual(result['temp_SHIP'], 1.0)
        self.assertEqual(result['temp_SHIP_QC'], 4)
        record = DASRecord(timestamp=1, fields={'temp': 3, 'relative_heading': 100})
        self.assertIsInstance(self.transform.transform(record), DASRecord)
        self.assertEqual(len(self.transform.transform([{'temp': 1}])), 1)
        self.assertIsNone(self.transform.transform(None))


if __name__ == '__main__':
    unittest.main()
