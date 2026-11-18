"""Effective-dated calibration registry and validation helpers."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os

import yaml


ALLOWED_UNITS = {
    'temperature': {'degC', 'K'},
    'conductivity': {'S/m', 'mS/cm'},
    'pressure': {'dbar', 'hPa', 'kPa'},
    'speed': {'m/s', 'kn'},
    'resistance': {'ohm'},
    'voltage': {'V', 'mV'},
}
FORMS = {'linear', 'polynomial', 'steinhart_hart', 'table'}
REQUIRED = ('sensor_id', 'serial', 'field', 'units_in', 'units_out', 'form',
            'coefficients', 'valid_from', 'certificate', 'entered_by', 'note')


class RegistryError(ValueError):
    """A plain-English registry configuration error."""


def _error(setting, saw, expected, example):
    return RegistryError("setting %s saw %r; expected %s; for example %s" %
                         (setting, saw, expected, example))


def _instant(value, setting):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise _error(setting, value, 'an ISO 8601 date and time',
                         '2024-01-01T00:00:00Z') from exc
    else:
        raise _error(setting, value, 'an ISO 8601 date and time',
                     '2024-01-01T00:00:00Z')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class CalibrationEntry:
    data: dict
    start: datetime
    end: datetime | None

    def __getattr__(self, name):
        try:
            return self.data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def verified(self):
        return bool(self.data.get('checked_by') and
                    self.data['checked_by'] != self.data['entered_by'])

    @property
    def version(self):
        return self.data['certificate']


def apply_formula(form, coefficients, value):
    """Apply one of the pinned calibration formulas."""
    x = float(value)
    if form == 'linear':
        return coefficients[0] + coefficients[1] * x
    if form == 'polynomial':
        return sum(coefficient * x ** power
                   for power, coefficient in enumerate(coefficients))
    if form == 'steinhart_hart':
        logarithm = math.log(x)
        inverse = (coefficients[0] + coefficients[1] * logarithm +
                   coefficients[2] * logarithm ** 3)
        return 1 / inverse
    if form == 'table':
        points = sorted((float(point[0]), float(point[1])) for point in coefficients)
        if x <= points[0][0]:
            return points[0][1]
        if x >= points[-1][0]:
            return points[-1][1]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 <= x <= x1:
                return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    raise _error('form', form, 'linear, polynomial, steinhart_hart, or table', 'linear')


class CalibrationRegistry:
    """Load, validate, and select effective calibration entries."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding='utf-8') as stream:
                document = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise RegistryError("setting registry_path saw %r; expected readable YAML; "
                                "for example contrib/deepsignal/cal_registry/registry.yaml" %
                                path) from exc
        if not isinstance(document, dict) or not isinstance(document.get('calibrations'), list):
            raise _error('calibrations', document, 'a YAML list', 'calibrations: []')
        self.entries = [self._validate(item, index)
                        for index, item in enumerate(document['calibrations'])]
        self._check_overlaps()

    @staticmethod
    def _validate(item, index):
        if not isinstance(item, dict):
            raise _error('calibrations[%d]' % index, item, 'a mapping', 'sensor_id: tsg1')
        for name in REQUIRED:
            if name not in item:
                raise _error(name, 'missing', 'a value', '%s: tsg1' % name)
        if item['form'] not in FORMS:
            raise _error('form', item['form'], ', '.join(sorted(FORMS)), 'linear')
        coefficients = item['coefficients']
        if not isinstance(coefficients, list):
            raise _error('coefficients', coefficients, 'a YAML list', '[0.0, 1.0]')
        expected = {'linear': 2, 'steinhart_hart': 3}
        if item['form'] in expected and len(coefficients) != expected[item['form']]:
            raise _error('coefficients', coefficients,
                         '%d numbers for %s' % (expected[item['form']], item['form']),
                         '[0.0, 1.0]')
        if item['form'] == 'polynomial' and not 1 <= len(coefficients) <= 6:
            raise _error('coefficients', coefficients,
                         '1 to 6 numbers for polynomial order 0 through 5', '[0, 1, 0.2]')
        if item['form'] == 'table' and len(coefficients) < 2:
            raise _error('coefficients', coefficients, 'at least two [x, y] points',
                         '[[0, 0], [10, 1]]')
        start = _instant(item['valid_from'], 'valid_from')
        end = _instant(item['valid_to'], 'valid_to') if item.get('valid_to') else None
        if end is not None and end <= start:
            raise _error('valid_to', item['valid_to'], 'a time after valid_from',
                         '2025-01-01T00:00:00Z')
        return CalibrationEntry(dict(item), start, end)

    def _check_overlaps(self):
        groups = {}
        for entry in self.entries:
            groups.setdefault((entry.sensor_id, entry.field), []).append(entry)
        for key, entries in groups.items():
            entries.sort(key=lambda entry: entry.start)
            for first, second in zip(entries, entries[1:]):
                if first.end is None or second.start < first.end:
                    raise RegistryError("setting validity saw overlap for sensor %s field %s; "
                                        "expected non-overlapping [valid_from, valid_to) ranges; "
                                        "for example end one entry when the next starts" % key)

    def select(self, sensor_id, field, timestamp):
        instant = _instant(timestamp, 'timestamp')
        for entry in self.entries:
            if (entry.sensor_id == sensor_id and entry.field == field and
                    entry.start <= instant and (entry.end is None or instant < entry.end)):
                return entry
        return None

    def record_change(self, entry, log_path=None):
        """Append an audit event when the shared change recorder is unavailable."""
        event = {'action': 'calibration_added', 'calibration': entry,
                 'recorded_at': datetime.now(timezone.utc).isoformat()}
        path = log_path or os.path.join(os.path.dirname(self.path), 'changes.jsonl')
        with open(path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, sort_keys=True) + '\n')


def check_unit_suspicion(quantity, units, values):
    """Return a warning for a conservative, recognizable unit mismatch."""
    key = quantity.lower()
    allowed = ALLOWED_UNITS.get(key)
    if allowed and units not in allowed:
        return "warning: %s units say %s; allowed units are %s" % (
            quantity, units, ', '.join(sorted(allowed)))
    numeric = [abs(float(value)) for value in values if value is not None]
    if key == 'conductivity' and units == 'S/m' and numeric:
        middle = sorted(numeric)[len(numeric) // 2]
        if 20 <= middle <= 80:
            return ("warning: conductivity values about %g look like mS/cm, but units say S/m" %
                    middle)
    return None


def find_affected(sensor_id, config_paths, sensor_fields):
    """Find transform output names that share a mapping with sensor fields."""
    inputs = set(sensor_fields.get(sensor_id, []))
    outputs = set()

    def visit(value):
        if isinstance(value, dict):
            scalars = {item for item in value.values() if isinstance(item, str)}
            if inputs & scalars:
                outputs.update(item for key, item in value.items()
                               if key.endswith('_name') and isinstance(item, str))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for path in config_paths:
        with open(path, encoding='utf-8') as stream:
            visit(yaml.safe_load(stream))
    return sorted(outputs)
