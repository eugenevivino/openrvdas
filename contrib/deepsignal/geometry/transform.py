"""Correct an antenna fix to a surveyed point using true heading."""

import argparse
import logging
import math
from copy import copy

from contrib.deepsignal.geometry.survey import finite_number, problem, read_points, read_yaml
from logger.transforms.transform import Transform
from logger.utils import formats
from logger.utils.das_record import DASRecord


def north_east(dx, dy, heading):
    """Rotate forward and starboard metres into north and east metres."""
    h = math.radians(heading)
    return dx * math.cos(h) - dy * math.sin(h), dx * math.sin(h) + dy * math.cos(h)


def earth_radii(latitude):
    """WGS84 meridian and prime vertical radii in metres, at latitude in degrees."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    q = 1 - e2 * math.sin(math.radians(latitude)) ** 2
    return a * (1 - e2) / q ** 1.5, a / math.sqrt(q)


class LeverArmTransform(Transform):
    """Add target latitude and longitude to fixes with a recent heading."""

    def __init__(self, geometry_file=None, antenna=None, lat_field=None, lon_field=None,
                 heading_field=None, target=None, prefix='Corrected', heading_timeout=2, **unknown):
        super().__init__(input_format=formats.Python_Record, output_format=formats.Python_Record)
        if unknown:
            key = next(iter(unknown))
            raise ValueError(problem(key, unknown[key], 'a listed transform setting', 'antenna'))
        if not isinstance(prefix, str):
            raise ValueError(problem('prefix', prefix, 'text before the output names', 'Corrected'))
        if not finite_number(heading_timeout) or heading_timeout < 0:
            raise ValueError(problem('heading_timeout', heading_timeout, 'seconds of 0 or more', 2))
        self.outputs = (prefix + 'Latitude', prefix + 'Longitude')
        used = set(self.outputs)
        for key, name, example in [('lat_field', lat_field, 'lat'), ('lon_field', lon_field, 'lon'),
                                   ('heading_field', heading_field, 'heading')]:
            if not isinstance(name, str) or not name.strip() or name in used:
                raise ValueError(problem(key, name, 'a distinct, nonempty field name', example))
            used.add(name)

        points = read_points(geometry_file)
        positions = points['positions']
        if not isinstance(antenna, str) or antenna not in positions:
            raise ValueError(problem('antenna', antenna, 'an id in positions',
                                     next(iter(positions), 'gnss_primary')))
        targets = positions | points['monuments']
        if target is not None and (not isinstance(target, str) or target not in targets):
            raise ValueError(problem('target', target, 'a surveyed id, or omit for the origin',
                                     antenna))
        end = targets[target] if target is not None else (0, 0, 0)
        self.dx = end[0] - positions[antenna][0]
        self.dy = end[1] - positions[antenna][1]
        if not (finite_number(self.dx) and finite_number(self.dy)
                and finite_number(math.hypot(self.dx, self.dy))):
            raise ValueError(problem('target', target, 'a finite offset in metres', antenna))

        self.lat_field = lat_field
        self.lon_field = lon_field
        self.heading_field = heading_field
        self.heading_timeout = heading_timeout
        self.heading_time = None
        self.heading = None
        self.last_issue = None

    def _warn(self, issue, message, *args):
        if self.last_issue != issue:
            logging.warning(message, *args)
        self.last_issue = issue

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        if isinstance(record, DASRecord):
            ts, fields = record.timestamp, record.fields
        elif isinstance(record, dict):
            ts, fields = record.get('timestamp'), record.get('fields')
        else:
            self._warn('record', 'Expected a record with timestamp and fields. Check the reader.')
            return record
        if not isinstance(fields, dict) or not finite_number(ts):
            self._warn('structure', 'Saw timestamp %r and fields of type %s. Supply a timestamp '
                       'in seconds and named fields.', ts, type(fields).__name__)
            return record

        if self.heading_field in fields:
            h = fields[self.heading_field]
            valid = finite_number(h) and 0 <= h <= 360
            if self.heading_time is None or ts >= self.heading_time:
                self.heading_time = ts
                self.heading = h if valid else None
            if not valid:
                self._warn('bad heading', '%s was %r at %s s. Supply true heading in degrees '
                           'from 0 to 360.', self.heading_field, h, ts)
                return record
            if self.last_issue in ('bad heading', 'missing heading') and self.heading is not None:
                self.last_issue = None

        if self.lat_field not in fields and self.lon_field not in fields:
            if self.heading_field not in fields:
                self._warn('no inputs', 'At %s s the record had none of %r, %r or %r. Check the '
                           'configured field names and sensor feeds.', ts, self.lat_field,
                           self.lon_field, self.heading_field)
            return record
        lat, lon = fields.get(self.lat_field), fields.get(self.lon_field)
        for name, value in ((self.lat_field, lat), (self.lon_field, lon)):
            if not finite_number(value):
                self._warn(name, '%s was %r at %s s. Supply a position in decimal degrees.',
                           name, value, ts)
                return record
        if abs(lat) > 89.5:
            self._warn('polar', '%s was %r degrees at %s s. Use fixes between 89.5 degrees south '
                       'and 89.5 degrees north.', self.lat_field, lat, ts)
            return record
        if abs(lon) > 180:
            self._warn('longitude', '%s was %r degrees at %s s. Supply longitude between -180 '
                       'and 180 degrees.', self.lon_field, lon, ts)
            return record
        if self.heading_time is None or self.heading is None:
            self._warn('missing heading', 'Missing valid %s for fix at %s s. Check the heading '
                       'feed and field name.', self.heading_field, ts)
            return record
        age = ts - self.heading_time
        if age < 0 or age > self.heading_timeout:
            reason = 'future' if age < 0 else 'stale'
            self._warn(reason + ' heading', '%s heading for fix at %s s. Last %s was %s degrees '
                       'at %s s (age %s s, limit %s s). Check the feed and sensor clocks.',
                       reason.capitalize(), ts, self.heading_field, self.heading,
                       self.heading_time, age, self.heading_timeout)
            return record
        if any(key in fields for key in self.outputs):
            self._warn('collision', 'At %s s the record already has %s or %s. Choose an unused '
                       'prefix and reload the logger.', ts, *self.outputs)
            return record

        dn, de = north_east(self.dx, self.dy, self.heading)
        m, n = earth_radii(lat)
        out = fields.copy()
        out[self.outputs[0]] = lat + math.degrees(dn / m)
        longitude = lon + math.degrees(de / (n * math.cos(math.radians(lat))))
        out[self.outputs[1]] = (longitude + 180) % 360 - 180
        result = copy(record)
        if isinstance(result, dict):
            result['fields'] = out
        else:
            result.fields = out
        self.last_issue = None
        return result


def check_logger(filename):
    """Preflight the geometry settings without starting any readers or writers."""
    sample = 'contrib/deepsignal/configs/geometry_logger.yaml'
    config = read_yaml(filename, 'logger file', sample)
    stages = config.get('transforms') if isinstance(config, dict) else None
    if not isinstance(stages, list):
        stages = [stages]
    geometry = [s for s in stages if isinstance(s, dict) and s.get('class') == 'LeverArmTransform']
    if not geometry:
        raise ValueError(problem('transforms', 'missing LeverArmTransform',
                                 'a geometry transform in the logger file', sample))
    for stage in geometry:
        module = stage.get('module')
        if module != 'contrib.deepsignal.geometry.transform':
            raise ValueError(problem('module', module, 'the geometry transform module',
                                     'contrib.deepsignal.geometry.transform'))
        settings = stage.get('kwargs', {})
        if not isinstance(settings, dict) or not all(isinstance(k, str) for k in settings):
            raise ValueError(problem('kwargs', settings, 'named geometry settings',
                                     {'antenna': 'gnss_primary'}))
        LeverArmTransform(**settings)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Check the geometry settings in a logger file.')
    parser.add_argument('logger_file')
    args = parser.parse_args()
    try:
        check_logger(args.logger_file)
    except ValueError as error:
        parser.exit(1, f'{error}\n')
    print('Geometry settings OK.')
