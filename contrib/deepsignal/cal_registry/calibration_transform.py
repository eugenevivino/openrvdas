"""OpenRVDAS transform applying effective-dated calibrations."""

from logger.transforms.transform import Transform

from contrib.deepsignal.cal_registry.registry import apply_formula
from contrib.deepsignal.cal_registry.registry import CalibrationRegistry


class CalibrationTransform(Transform):
    """Add calibrated values and calibration evidence without altering raw values."""

    def __init__(self, registry_path, sensor_id, **kwargs):
        super().__init__(**kwargs)
        self.registry = CalibrationRegistry(registry_path)
        self.sensor_id = sensor_id

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self._transform_one(item) for item in record]
        return self._transform_one(record)

    def _transform_one(self, record):
        if isinstance(record, dict):
            timestamp = record['timestamp']
            fields = record['fields']
        else:
            timestamp = record.timestamp
            fields = record.fields
        relevant = [entry for entry in self.registry.entries
                    if entry.sensor_id == self.sensor_id and entry.field in fields]
        for field in {entry.field for entry in relevant}:
            entry = self.registry.select(self.sensor_id, field, timestamp)
            if entry is None:
                fields[field + '_cal_state'] = 'none'
                continue
            fields[field + '_cal'] = apply_formula(
                entry.form, entry.coefficients, fields[field])
            fields[field + '_cal_version'] = entry.version
        return record
