"""Passive, vendor-neutral quality control for parsed seismic shot records."""

import copy
import datetime
import math

try:
    from logger.transforms.transform import Transform
    from logger.utils.das_record import DASRecord
except ImportError:  # Current core package layout.
    from openrvdas.logger.transforms.transform import Transform
    from openrvdas.logger.utils.das_record import DASRecord


EARTH_RADIUS_M = 6371008.8
OUTPUT_FIELDS = ('Number', 'FireTime', 'Lat', 'Lon', 'NavGap', 'Interval_s',
                 'Spacing_m', 'GunsOut', 'WorstGun_ms', 'Missed',
                 'ClockOffset_s', 'Alarm', 'AlarmText')


def _number(value):
    """Return a finite float, or None for malformed/untrusted input."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _distance(lat1, lon1, lat2, lon2):
    """Approximate great-circle distance using the haversine formula."""
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2)
             * math.sin(delta_lon / 2) ** 2)
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


class ShotQCTransform(Transform):
    """Add ``SHOT_*`` QC fields without changing the input record."""

    def __init__(self, shot_number, fire_time, gun_errors, lat, lon,
                 nav_time=None, date_source=None, gun_tolerance_ms=1.0,
                 interval_s=None, spacing_m=None, interval_tolerance_pct=5,
                 nav_max_gap_s=2, prefix='SHOT'):
        super().__init__()
        self.shot_number = shot_number
        self.fire_time = fire_time
        self.gun_errors = list(gun_errors)
        self.lat = lat
        self.lon = lon
        self.nav_time = nav_time
        self.date_source = date_source
        self.gun_tolerance_ms = float(gun_tolerance_ms)
        self.interval_s = _number(interval_s)
        self.spacing_m = _number(spacing_m)
        self.interval_tolerance_pct = float(interval_tolerance_pct)
        self.nav_max_gap_s = float(nav_max_gap_s)
        self.prefix = prefix
        self._nav_history = []
        self._previous_shot = None
        self._alarm_active = False
        self._good_streak = 0

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        timestamp, fields = self._parts(record)
        self._remember_nav(timestamp, fields)
        if self.shot_number not in fields:
            return record
        additions = self._check_shot(timestamp, fields)
        if isinstance(record, DASRecord):
            result = copy.copy(record)
            result.fields = dict(record.fields)
            result.fields.update(additions)
            return result
        result = dict(record)
        result['fields'] = dict(fields)
        result['fields'].update(additions)
        return result

    @staticmethod
    def _parts(record):
        if isinstance(record, DASRecord):
            return _number(record.timestamp), record.fields
        if not isinstance(record, dict) or not isinstance(record.get('fields'), dict):
            raise TypeError('ShotQCTransform requires a DASRecord or timestamp/fields dict')
        return _number(record.get('timestamp')), record['fields']

    def _remember_nav(self, timestamp, fields):
        nav_timestamp = _number(fields.get(self.nav_time)) if self.nav_time else timestamp
        latitude = _number(fields.get(self.lat))
        longitude = _number(fields.get(self.lon))
        if nav_timestamp is None or latitude is None or longitude is None:
            return
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return
        self._nav_history.append((nav_timestamp, latitude, longitude))
        self._nav_history.sort(key=lambda item: item[0])
        newest = self._nav_history[-1][0]
        self._nav_history = [item for item in self._nav_history
                             if item[0] >= newest - 120]

    def _fire_timestamp(self, value, fields, record_timestamp):
        numeric = _number(value)
        if numeric is not None:
            return numeric
        if not isinstance(value, str):
            return None
        try:
            parsed_time = datetime.time.fromisoformat(value.rstrip('Z'))
            date_value = fields.get(self.date_source) if self.date_source else None
            if date_value:
                parsed_date = datetime.date.fromisoformat(str(date_value))
            elif record_timestamp is not None:
                parsed_date = datetime.datetime.fromtimestamp(
                    record_timestamp, datetime.timezone.utc).date()
            else:
                return None
            combined = datetime.datetime.combine(parsed_date, parsed_time,
                                                 datetime.timezone.utc)
            return combined.timestamp()
        except ValueError:
            return None

    def _position(self, fire_time):
        if fire_time is None:
            return None, None, True
        before = [fix for fix in self._nav_history if fix[0] <= fire_time]
        after = [fix for fix in self._nav_history if fix[0] >= fire_time]
        if not before or not after:
            return None, None, True
        lower, upper = before[-1], after[0]
        if fire_time - lower[0] > self.nav_max_gap_s:
            return None, None, True
        if upper[0] - fire_time > self.nav_max_gap_s:
            return None, None, True
        if upper[0] == lower[0]:
            return lower[1], lower[2], False
        fraction = (fire_time - lower[0]) / (upper[0] - lower[0])
        return (lower[1] + fraction * (upper[1] - lower[1]),
                lower[2] + fraction * (upper[2] - lower[2]), False)

    def _check_shot(self, timestamp, fields):
        shot_value = _number(fields.get(self.shot_number))
        shot = int(shot_value) if shot_value is not None and shot_value.is_integer() else shot_value
        fire = self._fire_timestamp(fields.get(self.fire_time), fields, timestamp)
        latitude, longitude, nav_gap = self._position(fire)
        errors = [_number(fields.get(name)) for name in self.gun_errors]
        valid_errors = [(index + 1, value) for index, value in enumerate(errors)
                        if value is not None]
        out_count = sum(abs(value) > self.gun_tolerance_ms
                        for _, value in valid_errors)
        worst = max((abs(value) for _, value in valid_errors), default=None)
        interval = None
        spacing = None
        missed = 0
        if self._previous_shot:
            previous_number, previous_fire, previous_lat, previous_lon = self._previous_shot
            if fire is not None and previous_fire is not None:
                interval = fire - previous_fire
            if None not in (latitude, longitude, previous_lat, previous_lon):
                spacing = _distance(previous_lat, previous_lon, latitude, longitude)
            if shot is not None and previous_number is not None:
                missed = max(0, int(shot - previous_number - 1))
        problems = self._problems(shot, valid_errors, interval, spacing, missed)
        if problems:
            self._alarm_active = True
            self._good_streak = 0
        elif self._alarm_active:
            self._good_streak += 1
            if self._good_streak >= 3:
                self._alarm_active = False
                self._good_streak = 0
        if shot is not None:
            self._previous_shot = (shot, fire, latitude, longitude)
        values = {'Number': shot, 'FireTime': fire, 'Lat': latitude, 'Lon': longitude,
                  'NavGap': nav_gap, 'Interval_s': interval, 'Spacing_m': spacing,
                  'GunsOut': out_count, 'WorstGun_ms': worst, 'Missed': missed,
                  'ClockOffset_s': fire - timestamp if None not in (fire, timestamp) else None,
                  'Alarm': self._alarm_active, 'AlarmText': ' '.join(problems)}
        return {f'{self.prefix}_{name}': values[name] for name in OUTPUT_FIELDS}

    def _problems(self, shot, errors, interval, spacing, missed):
        label = f'Shot {shot}'
        problems = []
        for gun, error in errors:
            if abs(error) > self.gun_tolerance_ms:
                direction = 'late' if error > 0 else 'early'
                problems.append(f'{label}: gun {gun} fired {abs(error):g} ms {direction} '
                                f'(limit {self.gun_tolerance_ms:.1f} ms). Check gun {gun} '
                                'timing in the controller.')
        if missed:
            problems.append(f'{label}: {missed} shot number(s) missed. Check the shot log.')
        if self.interval_s and interval is not None:
            limit = self.interval_s * self.interval_tolerance_pct / 100
            if abs(interval - self.interval_s) > limit:
                problems.append(f'{label}: interval {interval:g} s differs from '
                                f'{self.interval_s:g} s plan by more than {limit:g} s. '
                                'Check trigger timing.')
        if self.spacing_m and spacing is not None:
            limit = self.spacing_m * self.interval_tolerance_pct / 100
            if abs(spacing - self.spacing_m) > limit:
                problems.append(f'{label}: spacing {spacing:.1f} m differs from '
                                f'{self.spacing_m:g} m plan by more than {limit:g} m. '
                                'Check vessel speed and navigation.')
        return problems
