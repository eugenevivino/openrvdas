"""Passive sound-velocity consistency monitoring transform."""

import math
from datetime import datetime
from itertools import combinations
from statistics import median

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord


class SVConsistencyTransform(Transform):
    """Compare already-computed sound velocities using record time."""

    def __init__(self, sources, threshold_ms=2.0, persist_s=120,
                 clear_s=60, prefix='SV', valid_range=(1400, 1600)):
        super().__init__()
        self.sources = self._validate_sources(sources)
        self.threshold_ms = self._positive(
            'threshold_ms', threshold_ms, allow_zero=False, example='2.0')
        self.persist_s = self._positive(
            'persist_s', persist_s, allow_zero=True, example='120')
        self.clear_s = self._positive(
            'clear_s', clear_s, allow_zero=True, example='60')
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError(
                "prefix saw %r; expected a non-empty string, for example 'SV'."
                % (prefix,))
        self.prefix = prefix.strip()
        if (not isinstance(valid_range, (list, tuple)) or
                len(valid_range) != 2):
            raise ValueError(
                'valid_range saw %r; expected [minimum, maximum], for example '
                '[1400, 1600].' % (valid_range,))
        try:
            low, high = (float(valid_range[0]), float(valid_range[1]))
        except (TypeError, ValueError):
            raise ValueError(
                'valid_range saw %r; expected two numbers, for example '
                '[1400, 1600].' % (valid_range,)) from None
        if not math.isfinite(low) or not math.isfinite(high) or low >= high:
            raise ValueError(
                'valid_range saw %r; expected a finite minimum below a finite '
                'maximum, for example [1400, 1600].' % (valid_range,))
        self.valid_range = (low, high)
        self.latest = {}
        self.alarm = False
        self.condition_since = None
        self.clear_since = None

    @staticmethod
    def _positive(name, value, allow_zero, example):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = -1
        valid = math.isfinite(number) and (number >= 0 if allow_zero
                                           else number > 0)
        if not valid:
            qualifier = 'non-negative' if allow_zero else 'positive'
            raise ValueError(
                '%s saw %r; expected a finite %s number, for example %s.'
                % (name, value, qualifier, example))
        return number

    @classmethod
    def _validate_sources(cls, sources):
        if not isinstance(sources, dict) or not sources:
            raise ValueError(
                "sources saw %r; expected a mapping such as "
                "{'probe': {'field': 'SVP_Velocity', 'max_age_s': 30}}."
                % (sources,))
        validated = {}
        for role, settings in sources.items():
            if not isinstance(role, str) or not role.strip():
                raise ValueError(
                    "sources role saw %r; expected a non-empty name, for "
                    "example 'probe'." % (role,))
            if not isinstance(settings, dict):
                raise ValueError(
                    "sources[%s] saw %r; expected settings such as "
                    "{'field': 'SVP_Velocity', 'max_age_s': 30}."
                    % (role, settings))
            field = settings.get('field')
            if not isinstance(field, str) or not field.strip():
                raise ValueError(
                    "sources[%s].field saw %r; expected a field name, for "
                    "example 'SVP_Velocity'." % (role, field))
            age = settings.get('max_age_s')
            if age is not None:
                age = cls._positive('sources[%s].max_age_s' % role, age,
                                    allow_zero=True, example='30')
            validated[role.strip()] = {'field': field.strip(),
                                       'max_age_s': age}
        return validated

    def transform(self, record):
        """Add comparison fields when a configured input occurs."""
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        if isinstance(record, DASRecord):
            fields = record.fields
            timestamp = record.timestamp
        elif isinstance(record, dict) and 'timestamp' in record and 'fields' in record:
            fields = record['fields']
            timestamp = record['timestamp']
        else:
            raise TypeError('record saw %r; expected a DASRecord, a dict with '
                            'timestamp and fields, a list, or None.' % (record,))
        if not isinstance(fields, dict):
            raise TypeError('record fields saw %r; expected a field mapping, '
                            'for example {\'ProbeSV\': 1500.0}.' % (fields,))

        changed = False
        record_time = self._timestamp(timestamp)
        for role, settings in self.sources.items():
            if settings['field'] in fields:
                value = self._number(fields[settings['field']])
                self.latest[role] = (value, record_time)
                changed = True
        if not changed:
            return record

        output = self._measure(record_time)
        fields.update(output)
        return record

    @staticmethod
    def _timestamp(value):
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
            except ValueError:
                pass
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            timestamp = math.nan
        if not math.isfinite(timestamp):
            raise ValueError('record timestamp saw %r; expected a finite Unix '
                             'timestamp or ISO date, for example 1735689600.'
                             % (value,))
        return timestamp

    def _number(self, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if (not math.isfinite(number) or number < self.valid_range[0] or
                number > self.valid_range[1]):
            return None
        return number

    def _measure(self, now):
        fresh = {}
        stale = []
        for role, settings in self.sources.items():
            if role not in self.latest:
                continue
            value, observed = self.latest[role]
            age = max(0.0, now - observed)
            max_age = settings['max_age_s']
            if max_age is not None and age > max_age:
                stale.append(role)
            elif value is not None:
                fresh[role] = value

        result = {
            self.prefix + '_Spread': self._spread(fresh),
            self.prefix + '_OddOne': self._odd_one(fresh),
            self.prefix + '_Fresh': len(fresh),
            self.prefix + '_Stale': ','.join(stale),
        }
        for first, second in combinations(fresh, 2):
            result['%s_Diff_%s_%s' % (self.prefix, first, second)] = abs(
                fresh[first] - fresh[second])
        if 'cast' in self.sources:
            cast = self.latest.get('cast')
            result[self.prefix + '_CastAge_s'] = (None if cast is None else
                                                  max(0.0, now - cast[1]))

        spread = result[self.prefix + '_Spread']
        condition = spread is not None and spread > self.threshold_ms
        below_clear = (spread is not None and
                       spread < 0.75 * self.threshold_ms)
        self._update_alarm(condition, below_clear, now)
        result[self.prefix + '_Alarm'] = int(self.alarm)
        result[self.prefix + '_AlarmText'] = (
            self._alarm_text(fresh, result[self.prefix + '_OddOne'], now)
            if self.alarm else '')
        return result

    @staticmethod
    def _spread(values):
        if len(values) < 2:
            return None
        return max(values.values()) - min(values.values())

    def _odd_one(self, values):
        if len(values) < 3:
            return ''
        distances = {}
        for role, value in values.items():
            others = [other for name, other in values.items() if name != role]
            distances[role] = abs(value - median(others))
        role = max(distances, key=distances.get)
        return role if distances[role] > self.threshold_ms else ''

    def _update_alarm(self, condition, below_clear, now):
        if not self.alarm:
            self.clear_since = None
            if condition:
                if self.condition_since is None:
                    self.condition_since = now
                if now - self.condition_since >= self.persist_s:
                    self.alarm = True
            else:
                self.condition_since = None
        else:
            self.condition_since = None
            if below_clear:
                if self.clear_since is None:
                    self.clear_since = now
                if now - self.clear_since >= self.clear_s:
                    self.alarm = False
                    self.clear_since = None
            else:
                self.clear_since = None

    def _alarm_text(self, values, odd_one, now):
        ordered = sorted(values.items(), key=lambda item: item[0])
        if odd_one:
            odd_value = values[odd_one]
            comparisons = [(role, value) for role, value in ordered
                           if role != odd_one][:2]
            readings = ' and '.join('%s reads %.1f' % (role.title(), value)
                                    for role, value in comparisons)
            lead = '%s is using %.1f m/s; %s' % (
                odd_one.title(), odd_value, readings)
        else:
            extremes = sorted(ordered, key=lambda item: item[1])
            low, high = extremes[0], extremes[-1]
            lead = '%s reads %.1f m/s and %s reads %.1f' % (
                low[0].title(), low[1], high[0].title(), high[1])
        minutes = max(0, int(round((now - (self.condition_since or now)) / 60)))
        return ('%s (%.1f m/s limit, %d minutes). Check the SV input in SIS '
                'or take a cast.' % (lead, self.threshold_ms, minutes))
