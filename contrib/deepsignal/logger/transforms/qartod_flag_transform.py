"""Add QARTOD quality flags to parsed records while preserving sensor data."""

from collections import deque
from copy import copy
from datetime import datetime, timezone
import logging
from math import isfinite, isnan
from statistics import median
from sys import maxsize
from threading import Lock
import time
from typing import Union

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord


PASS, NOT_EVALUATED, SUSPECT, FAIL, MISSING = 1, 2, 3, 4, 9
EXAMPLES = {
    'gross_range': '{fail_span: [-2, 40], suspect_span: [0, 32]}',
    'climatology': '{suspect_span: [0, 32]} or {months: [{months: [1], suspect_span: [0, 20]}]}',
    'spike': '{suspect: 0.5, fail: 2.0, window: 3}',
    'rate_of_change': '{max_rate: 0.5}',
    'flat_line': '{tolerance: 0.01, suspect_seconds: 10, fail_seconds: 30}',
    'timing': '{max_future_seconds: 60, max_gap_seconds: 10}',
    'front_check': '{companions: [Salt], min_change: {Salt: 0.2}}',
}
ALLOWED_KEYS = {
    'gross_range': {'fail_span', 'suspect_span'},
    'climatology': {'suspect_span', 'months'},
    'spike': {'suspect', 'fail', 'window'},
    'rate_of_change': {'max_rate'},
    'flat_line': {'tolerance', 'suspect_seconds', 'fail_seconds'},
    'timing': {'max_future_seconds', 'max_gap_seconds'},
    'front_check': {'companions', 'min_change'},
}
REQUIRED_POSITIVE = {
    'spike': ('suspect', 'fail'),
    'rate_of_change': ('max_rate',),
    'flat_line': ('tolerance', 'suspect_seconds', 'fail_seconds'),
}
UNSET = object()


def _is_number(value):
    return (isinstance(value, int) and not isinstance(value, bool)
            or isinstance(value, float) and isfinite(value))


def _value_flag(value):
    if value is None or (isinstance(value, str) and not value):
        return MISSING
    if isinstance(value, float) and isnan(value):
        return MISSING
    return PASS if _is_number(value) else FAIL


def _config_error(field, setting, value, expected, example=None):
    seen = 'missing' if value is UNSET else repr(value)
    example = example or EXAMPLES[setting.split('.')[0]]
    raise ValueError(f'Field {field!r}, {setting}: got {seen}, expected {expected}. '
                     f'Good example: {example}.')


def _span(field, setting, value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(_is_number(bound) for bound in value) or value[0] >= value[1]):
        _config_error(field, setting, value,
                      'two finite numbers with the minimum below the maximum')
    return tuple(value)


def _positive(field, setting, value):
    if not _is_number(value) or value <= 0:
        _config_error(field, setting, value, 'a finite number greater than zero')


def _climatology_spans(field, settings):
    if set(settings) == {'suspect_span'}:
        return _span(field, 'climatology.suspect_span', settings['suspect_span'])
    rows = settings.get('months', UNSET)
    if set(settings) != {'months'} or not isinstance(rows, list) or not rows:
        _config_error(field, 'climatology.months', settings,
                      'either one suspect_span or a nonempty list of monthly spans')
    spans = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'months', 'suspect_span'}:
            _config_error(field, 'climatology.months', row, 'a months list and a suspect_span')
        months = row.get('months', UNSET)
        if (not isinstance(months, list) or not months
                or any(type(month) is not int or not 1 <= month <= 12 for month in months)
                or len(set(months)) != len(months) or set(months) & spans.keys()):
            _config_error(field, 'climatology.months', months,
                          'a nonempty list of distinct months from 1 to 12, assigned once each')
        span = _span(field, 'climatology.months.suspect_span', row.get('suspect_span', UNSET))
        spans.update(dict.fromkeys(months, span))
    return spans


def _front_check(field, settings, fields):
    companions = settings.get('companions', UNSET)
    if (not isinstance(companions, list) or not companions
            or any(not isinstance(name, str) or name == field or name not in fields
                   for name in companions)
            or len(set(companions)) != len(companions)):
        _config_error(field, 'front_check.companions', companions,
                      'a nonempty list of distinct other names listed under fields; '
                      'for example, list Salt under fields even if it has no tests')
    limits = settings.get('min_change', UNSET)
    if not isinstance(limits, dict):
        _config_error(field, 'front_check.min_change', limits,
                      'a minimum change for each companion')
    for name in companions:
        _positive(field, f'front_check.min_change.{name}', limits.get(name, UNSET))
    if limits.keys() - set(companions):
        _config_error(field, 'front_check.min_change', limits, 'only the named companions')
    return {name: limits[name] for name in companions}


def _test_settings(field, test, settings, fields):
    if test not in ALLOWED_KEYS:
        _config_error(field, str(test), test, f'one of {", ".join(ALLOWED_KEYS)}',
                      'gross_range: {fail_span: [-2, 40]}')
    if not isinstance(settings, dict):
        _config_error(field, test, settings, 'a map of settings')
    for key, value in settings.items():
        if key not in ALLOWED_KEYS[test]:
            allowed = ', '.join(sorted(ALLOWED_KEYS[test]))
            _config_error(field, f'{test}.{key}', value, f'one of these settings: {allowed}')

    settings = settings.copy()
    for key in REQUIRED_POSITIVE.get(test, ()):
        _positive(field, f'{test}.{key}', settings.get(key, UNSET))
    if test == 'gross_range':
        settings['fail_span'] = _span(field, 'gross_range.fail_span',
                                      settings.get('fail_span', UNSET))
        if 'suspect_span' in settings:
            settings['suspect_span'] = _span(field, 'gross_range.suspect_span',
                                             settings['suspect_span'])
    elif test == 'climatology':
        return _climatology_spans(field, settings)
    elif test == 'spike':
        window = settings.setdefault('window', 3)
        if type(window) is not int or not 1 <= window <= maxsize:
            _config_error(field, 'spike.window', window,
                          f'a whole number of samples from 1 to {maxsize}')
        if settings['fail'] < settings['suspect']:
            _config_error(field, 'spike.fail', settings['fail'],
                          'a limit at least as large as spike.suspect')
    elif test == 'flat_line' and settings['fail_seconds'] < settings['suspect_seconds']:
        _config_error(field, 'flat_line.fail_seconds', settings['fail_seconds'],
                      'a duration at least as long as flat_line.suspect_seconds')
    elif test == 'timing':
        _positive(field, 'timing.max_future_seconds', settings.setdefault('max_future_seconds', 60))
        if 'max_gap_seconds' in settings:
            _positive(field, 'timing.max_gap_seconds', settings['max_gap_seconds'])
    elif test == 'front_check':
        return _front_check(field, settings, fields)
    return settings


def _verdict(flag, explanation=''):
    if flag == FAIL:
        return flag, f'FAIL: {explanation}'
    if flag == SUSPECT:
        return flag, f'SUSPECT: {explanation}'
    return flag, ''


def _range_result(test, value, span, flag):
    if span is None:
        return _verdict(NOT_EVALUATED)
    if not span[0] <= value <= span[1]:
        return _verdict(flag, f'{test} {value} outside [{span[0]}, {span[1]}]')
    return _verdict(PASS)


def _timing(settings, timestamp, previous, now):
    if timestamp is None:
        return _verdict(NOT_EVALUATED)
    if previous is not None and timestamp <= previous:
        return _verdict(FAIL, 'timing timestamp is not later than the previous record')
    future = settings['max_future_seconds']
    if timestamp > now + future:
        return _verdict(FAIL, f'timing timestamp is more than {future} seconds ahead of wall time')
    gap = settings.get('max_gap_seconds')
    if gap is not None and previous is not None and timestamp - previous > gap:
        return _verdict(SUSPECT, f'timing gap {timestamp - previous} seconds over limit {gap}')
    return _verdict(PASS)


def _spike(settings, value, history):
    if len(history) < settings['window']:
        return _verdict(NOT_EVALUATED)
    deviation = abs(value - median(sample[2] for sample in history))
    for key, flag in [('fail', FAIL), ('suspect', SUSPECT)]:
        limit = settings[key]
        if deviation > limit:
            return _verdict(flag, f'spike {deviation} over limit {limit}')
    return _verdict(PASS)


def _rate_of_change(settings, timestamp, value, history):
    if not history or timestamp is None:
        return _verdict(NOT_EVALUATED)
    _, previous, previous_value = history[-1]
    if previous is None or timestamp <= previous:
        return _verdict(NOT_EVALUATED)
    rate = abs(value - previous_value) / (timestamp - previous)
    limit = settings['max_rate']
    if rate > limit:
        return _verdict(SUSPECT, f'rate_of_change {rate:g} per second over limit {limit}')
    return _verdict(PASS)


def _flat_line(settings, timestamp, value, history):
    if not history or timestamp is None or timestamp <= history[-1][0]:
        return _verdict(NOT_EVALUATED)
    tolerance = settings['tolerance']
    duration = 0
    for prior_time, prior_value in reversed(history):
        if abs(value - prior_value) > tolerance:
            break
        duration = timestamp - prior_time
        if duration >= settings['fail_seconds']:
            return _verdict(FAIL, f'flat_line within {tolerance} for at least {duration} seconds')
    if duration >= settings['suspect_seconds']:
        return _verdict(SUSPECT, f'flat_line within {tolerance} for {duration} seconds')
    return _verdict(PASS)


def _aggregate(flags):
    for flag in (MISSING, FAIL, SUSPECT, PASS):
        if flag in flags:
            return flag
    return NOT_EVALUATED


class QartodFlagTransform(Transform):
    """Append quality flags to DASRecords or equivalent dictionaries.

    Spike uses a trailing median so the logger can flag the current record
    immediately. Timing and sensor history are held only for this instance.
    """

    def __init__(self, fields, flag_suffix='_QC', per_test_flags=False):
        super().__init__()
        if not isinstance(fields, dict) or not fields:
            _config_error('all fields', 'fields', fields, 'a nonempty map of field names to tests',
                          'fields: {SeaTemp: {gross_range: {fail_span: [-2, 40]}}}')
        if not isinstance(flag_suffix, str) or not flag_suffix:
            _config_error('all fields', 'flag_suffix', flag_suffix, 'a nonempty string', '_QC')
        if not isinstance(per_test_flags, bool):
            _config_error('all fields', 'per_test_flags', per_test_flags, 'true or false', 'true')

        self.tests = {}
        self.front_checks = {}
        output_names = set()
        for field, tests in fields.items():
            if not isinstance(field, str) or not field or not isinstance(tests, dict):
                _config_error(field, 'fields', tests, 'a named field with a map of tests',
                              'SeaTemp: {gross_range: {fail_span: [-2, 40]}}')
            settings = {test: _test_settings(field, test, options, fields)
                        for test, options in tests.items()}
            self.front_checks[field] = settings.pop('front_check', {})
            self.tests[field] = settings
            base = field + flag_suffix
            names = {base, base + '_reason'}
            if per_test_flags:
                names.update(f'{base}_{test}' for test in settings)
            if names & (fields.keys() | output_names):
                _config_error(field, 'flag_suffix', flag_suffix,
                              'separate names for raw fields and generated flags', '_QC')
            output_names.update(names)

        self.flag_suffix = flag_suffix
        self.per_test_flags = per_test_flags
        self.history = {
            field: deque(maxlen=settings.get('spike', {}).get('window', 1))
            for field, settings in self.tests.items()
        }
        self.flat_history = {field: deque() for field in self.tests
                             if 'flat_line' in self.tests[field]}
        self.has_timing = any('timing' in tests for tests in self.tests.values())
        self.previous_timestamp = None
        self.record_number = 0
        self.warned_raw = False
        self.lock = Lock()

    def transform(self, record: Union[DASRecord, dict, list, str, None]):
        with self.lock:
            return self._transform(record)

    def _transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self._transform(single) for single in record]
        if isinstance(record, str):
            if not self.warned_raw:
                logging.warning('QartodFlagTransform: raw text received. '
                                'Put a parse transform before QartodFlagTransform.')
                self.warned_raw = True
            return record
        if isinstance(record, DASRecord):
            output = copy(record)
            output.fields = self._flag_fields(record.timestamp, record.fields)
            return output
        if isinstance(record, dict):
            output = record.copy()
            output['fields'] = self._flag_fields(record['timestamp'], record['fields'])
            return output
        return record

    def _flag_fields(self, timestamp, fields):
        self.record_number += 1
        timestamp = timestamp if _is_number(timestamp) else None
        now = time.time() if self.has_timing else None
        present = {field: _value_flag(fields[field]) for field in self.tests if field in fields}
        results = {field: self._evaluate(field, fields[field], status, timestamp, now)
                   for field, status in present.items()}
        # Take a snapshot before front checks so field order and circular companion
        # references cannot change which companions qualify.
        bad = {field for field, checks in results.items()
               if present[field] == FAIL or any(flag == FAIL for flag, _ in checks.values())}
        output = fields.copy()
        for field, status in present.items():
            checks = results[field]
            if status == PASS:
                self._check_front(field, checks, fields, present, bad)
            self._write_flags(output, field, status, checks)
        for field, status in present.items():
            checks = results[field]
            if status == PASS and checks.get('gross_range', (PASS, ''))[0] != FAIL:
                self._remember(field, timestamp, fields[field])
        if timestamp is not None:
            self.previous_timestamp = timestamp
        return output

    def _evaluate(self, field, value, status, timestamp, now):
        checks = {}
        for test, settings in self.tests[field].items():
            if test == 'timing':
                result = _timing(settings, timestamp, self.previous_timestamp, now)
            elif status != PASS:
                result = _verdict(NOT_EVALUATED)
            elif test == 'gross_range':
                result = _range_result(test, value, settings['fail_span'], FAIL)
                if result[0] == PASS and 'suspect_span' in settings:
                    result = _range_result(test, value, settings['suspect_span'], SUSPECT)
            elif test == 'climatology':
                span = settings
                if isinstance(settings, dict):
                    span = settings.get(self._utc_month(timestamp))
                result = _range_result(test, value, span, SUSPECT)
            elif test == 'spike':
                result = _spike(settings, value, self.history[field])
            elif test == 'rate_of_change':
                result = _rate_of_change(settings, timestamp, value, self.history[field])
            else:
                result = _flat_line(settings, timestamp, value, self.flat_history[field])
            checks[test] = result
        return checks

    @staticmethod
    def _utc_month(timestamp):
        if timestamp is None:
            return None
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc).month
        except (OverflowError, OSError, ValueError):
            return None

    def _check_front(self, field, checks, fields, present, bad):
        companions = self.front_checks[field]
        if not companions:
            return
        for test, baseline in [('spike', 0), ('rate_of_change', -1)]:
            flag, reason = checks.get(test, (NOT_EVALUATED, ''))
            if flag not in (SUSPECT, FAIL):
                continue
            start = self.history[field][baseline][0]
            checks[test] = self._companion_verdict(companions, start, fields, present, bad,
                                                   flag, reason)

    def _companion_verdict(self, companions, start, fields, present, bad, flag, reason):
        unavailable = []
        for name, limit in companions.items():
            history = self.history[name]
            if present.get(name, MISSING) == MISSING:
                unavailable.append(f'{name} missing')
            elif name in bad:
                unavailable.append(f'{name} bad')
            elif not history or not start <= history[-1][0] < self.record_number:
                unavailable.append(f'{name} has no previous good value in the jump window')
            elif abs(fields[name] - history[-1][2]) >= limit:
                return (SUSPECT, f'UNDECIDED: jump matches a change in {name}; '
                        'may be a real front, check before trusting or discarding')
        if unavailable:
            reason += '; ' + '; '.join(unavailable)
        return flag, reason

    def _write_flags(self, output, field, status, checks):
        base = field + self.flag_suffix
        aggregate = status if status != PASS else _aggregate([flag for flag, _ in checks.values()])
        output.setdefault(base, aggregate)
        if self.per_test_flags:
            for test, (flag, _) in checks.items():
                output.setdefault(f'{base}_{test}', flag)
        if status == FAIL:
            reason = 'FAIL: syntax expected a finite number'
        elif aggregate in (SUSPECT, FAIL):
            # Keep front details when the jump has the same severity as other checks.
            candidates = [(test, reason) for test, (flag, reason) in checks.items()
                          if flag == aggregate]
            _, reason = min(candidates, key=lambda item: (
                not (aggregate == FAIL and item[0] in ('gross_range', 'timing')),
                not item[1].startswith('UNDECIDED:'),
                not (self.front_checks[field] and item[0] in ('spike', 'rate_of_change')),
            ))
        else:
            return
        output.setdefault(base + '_reason', reason)

    def _remember(self, field, timestamp, value):
        self.history[field].append((self.record_number, timestamp, value))
        if field not in self.flat_history:
            return
        history = self.flat_history[field]
        if timestamp is None or (history and timestamp <= history[-1][0]):
            history.clear()
        if timestamp is not None:
            history.append((timestamp, value))
            cutoff = timestamp - self.tests[field]['flat_line']['fail_seconds']
            # Keep one sample on or before the cutoff to establish a full run.
            while len(history) > 1 and history[1][0] <= cutoff:
                history.popleft()
