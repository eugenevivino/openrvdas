"""Add QARTOD quality flags to parsed records while preserving sensor data."""

from collections import deque
from copy import copy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import count
import logging
from math import floor, isfinite, isnan
from numbers import Rational
from sys import maxsize
from threading import Lock
import time
from typing import Union

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord


PASS, NOT_EVALUATED, SUSPECT, FAIL, MISSING = 1, 2, 3, 4, 9
VERDICT_AMBIGUOUS = 'AMBIGUOUS'
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
JUMP_BASELINES = {'spike': 0, 'rate_of_change': -1}
UTC_WARNING_INTERVAL = 60


def _is_number(value):
    return (isinstance(value, Rational) and not isinstance(value, bool)
            or isinstance(value, float) and isfinite(value)
            or isinstance(value, Decimal) and value.is_finite())


def _value_flag(value):
    if value is None or (isinstance(value, str) and not value):
        return MISSING
    if (isinstance(value, float) and isnan(value)
            or isinstance(value, Decimal) and value.is_nan()):
        return MISSING
    return PASS if _is_number(value) else FAIL


def _comparison_number(value):
    # Use the float's shortest decimal spelling for comparisons in sensor units.
    # Exact arithmetic on those numbers avoids cancellation at decimal limits.
    return Fraction(str(value) if isinstance(value, float) else value)


def _number_text(value):
    """Format exact numbers compactly without Fraction's version-dependent format."""
    number = _comparison_number(value)
    with localcontext() as context:
        context.prec = 12
        decimal = Decimal(number.numerator) / Decimal(number.denominator)
    return format(decimal, '.12g')


def _change(value, previous):
    return abs(_comparison_number(value) - _comparison_number(previous))


def _config_error(field, setting, value, expected, example=None):
    seen = 'missing' if value is UNSET else repr(value)
    example = example or EXAMPLES[setting.split('.')[0]]
    escaped = repr(setting)[1:-1]
    raise ValueError(f'Field {field!r}, {escaped}: got {seen}, expected {expected}. '
                     f'Good example: {example}.')


def _span(field, setting, value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(_is_number(bound) for bound in value)):
        _config_error(field, setting, value,
                      'two finite numbers with the minimum below the maximum')
    normalized = tuple(_comparison_number(bound) for bound in value)
    if normalized[0] >= normalized[1]:
        _config_error(field, setting, value,
                      'two finite numbers with the minimum below the maximum')
    return normalized


def _positive(field, setting, value):
    if not _is_number(value) or _comparison_number(value) <= 0:
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
        if _comparison_number(settings['fail']) < _comparison_number(settings['suspect']):
            _config_error(field, 'spike.fail', settings['fail'],
                          'a limit at least as large as spike.suspect')
    elif (test == 'flat_line'
          and _comparison_number(settings['fail_seconds'])
          < _comparison_number(settings['suspect_seconds'])):
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
    value = _comparison_number(value)
    if not span[0] <= value <= span[1]:
        return _verdict(flag, f'{test} {_number_text(value)} outside '
                        f'[{_number_text(span[0])}, {_number_text(span[1])}]')
    return _verdict(PASS)


def _timing(settings, timestamp, previous, now):
    if timestamp is None:
        return _verdict(NOT_EVALUATED)
    timestamp = _comparison_number(timestamp)
    previous = _comparison_number(previous) if previous is not None else None
    if previous is not None and timestamp <= previous:
        return _verdict(FAIL, 'timing timestamp is not later than the previous record')
    future = settings['max_future_seconds']
    if timestamp > _comparison_number(now) + _comparison_number(future):
        return _verdict(FAIL, f'timing timestamp is more than {future} seconds ahead of wall time')
    gap = settings.get('max_gap_seconds')
    if gap is not None and previous is not None:
        elapsed = timestamp - previous
        if elapsed > _comparison_number(gap):
            return _verdict(SUSPECT, f'timing gap {_number_text(elapsed)} seconds over limit {gap}')
    return _verdict(PASS)


def _spike(settings, value, history):
    if len(history) < settings['window']:
        return _verdict(NOT_EVALUATED)
    ordered = sorted(sample[2] for sample in history)
    middle = len(ordered) // 2
    median = ordered[middle]
    even = len(ordered) % 2 == 0
    if even:
        median = (median + ordered[middle - 1]) / 2
    deviation = abs(_comparison_number(value) - median)
    for key, flag in [('fail', FAIL), ('suspect', SUSPECT)]:
        limit = settings[key]
        if deviation > _comparison_number(limit):
            text = _number_text(deviation)
            if isinstance(value, float):
                text = str(float(deviation))
            return _verdict(flag, f'spike {text} over limit {limit}')
    return _verdict(PASS)


def _rate_of_change(settings, timestamp, value, history):
    if not history or timestamp is None:
        return _verdict(NOT_EVALUATED)
    _, previous, previous_value = history[-1]
    if previous is None:
        return _verdict(NOT_EVALUATED)
    elapsed = _comparison_number(timestamp) - _comparison_number(previous)
    if elapsed <= 0:
        return _verdict(NOT_EVALUATED)
    delta = _change(value, previous_value)
    limit = settings['max_rate']
    if delta > _comparison_number(limit) * elapsed:
        rate = delta / elapsed
        return _verdict(SUSPECT, f'rate_of_change {_number_text(rate)} per second '
                        f'over limit {limit}')
    return _verdict(PASS)


def _flat_line(settings, timestamp, value, history, earliest=None):
    if not history or timestamp is None:
        return _verdict(NOT_EVALUATED), None
    timestamp = _comparison_number(timestamp)
    if timestamp <= history[-1][0]:
        return _verdict(NOT_EVALUATED), None
    tolerance = settings['tolerance']
    allowed_change = _comparison_number(tolerance)
    suspect = _comparison_number(settings['suspect_seconds'])
    fail = _comparison_number(settings['fail_seconds'])
    duration = timestamp - earliest if earliest is not None else Fraction(0)
    value = _comparison_number(value)
    if earliest is None:
        for prior_time, prior_value in reversed(history):
            if abs(value - prior_value) > allowed_change:
                break
            earliest = prior_time
            duration = timestamp - prior_time
            if duration >= fail:
                break
    if duration >= fail:
        return (_verdict(FAIL, f'flat_line within {tolerance} for at least '
                         f'{_number_text(duration)} seconds'), earliest)
    if duration >= suspect:
        return (_verdict(SUSPECT, f'flat_line within {tolerance} for '
                         f'{_number_text(duration)} seconds'), earliest)
    return _verdict(PASS), earliest


def _aggregate(flags):
    for flag in (MISSING, FAIL, SUSPECT, PASS):
        if flag in flags:
            return flag
    return NOT_EVALUATED


def _record_fields(record):
    if isinstance(record, list):
        for single in record:
            yield from _record_fields(single)
    elif isinstance(record, DASRecord):
        yield record.fields
    elif isinstance(record, dict):
        yield record['fields']


class QartodFlagTransform(Transform):
    """Append quality flags to DASRecords or equivalent dictionaries.

    Spike uses a trailing median so the logger can flag the current record
    immediately. Timing and sensor history are held only for this instance.
    """

    def __init__(self, /, fields=UNSET, flag_suffix='_QC', per_test_flags=False, **unknown):
        super().__init__()
        for setting, value in unknown.items():
            _config_error('all fields', setting, value,
                          'one of fields, flag_suffix or per_test_flags', 'per_test_flags: true')
        if not isinstance(fields, dict) or not fields:
            _config_error('all fields', 'fields', fields, 'a nonempty map of field names to tests',
                          'fields: {SeaTemp: {gross_range: {fail_span: [-2, 40]}}}')
        if not isinstance(flag_suffix, str) or not flag_suffix:
            _config_error('all fields', 'flag_suffix', flag_suffix, 'a nonempty string', '_QC')
        if not isinstance(per_test_flags, bool):
            _config_error('all fields', 'per_test_flags', per_test_flags, 'true or false', 'true')

        self.tests = {}
        self.front_checks = {}
        for field, tests in fields.items():
            if not isinstance(field, str) or not field or not isinstance(tests, dict):
                _config_error(field, 'fields', tests, 'a named field with a map of tests',
                              'SeaTemp: {gross_range: {fail_span: [-2, 40]}}')
            settings = {test: _test_settings(field, test, options, fields)
                        for test, options in tests.items()}
            self.front_checks[field] = settings.pop('front_check', {})
            self.tests[field] = settings

        self.flag_suffix = flag_suffix
        self.per_test_flags = per_test_flags
        self.output_names = self._output_names(flag_suffix)
        collision = self._output_collision(self.output_names, fields)
        if collision:
            field, name = collision
            _config_error(field, 'flag_suffix', flag_suffix,
                          f'separate names for raw fields and generated flags; {name!r} is in use',
                          self._suffix_example(fields))
        self.history = {
            field: deque(maxlen=settings.get('spike', {}).get('window', 1))
            for field, settings in self.tests.items()
        }
        self.flat_history = {field: deque() for field in self.tests
                             if 'flat_line' in self.tests[field]}
        self.flat_cache = dict.fromkeys(self.flat_history)
        self.previous_companion = dict.fromkeys(name for companions in self.front_checks.values()
                                                for name in companions)
        self.has_timing = any('timing' in tests for tests in self.tests.values())
        self.previous_timestamp = None
        self.record_number = 0
        self.warned_raw = False
        self.last_utc_warning = None
        self.lock = Lock()

    def _output_names(self, suffix):
        names = {}
        for field, tests in self.tests.items():
            base = field + suffix
            names[field] = [base, base + '_reason']
            if self.per_test_flags:
                names[field].extend(f'{base}_{test}' for test in tests)
        return names

    @staticmethod
    def _output_collision(output_names, raw_names):
        used = set(raw_names)
        for field, names in output_names.items():
            for name in names:
                if name in used:
                    return field, name
                used.add(name)
        return None

    def _suffix_example(self, raw_names):
        for index in count(2):
            suffix = f'_QC_{index}'
            if not self._output_collision(self._output_names(suffix), raw_names):
                return f'flag_suffix: {suffix!r}'

    def transform(self, record: Union[DASRecord, dict, list, str, None]):
        with self.lock:
            # Check the whole batch before updating any history.
            for fields in _record_fields(record):
                names = {field: self.output_names[field] for field in self.tests if field in fields}
                collision = self._output_collision(names, fields)
                if collision:
                    field, name = collision
                    raw_names = set(self.tests)
                    for values in _record_fields(record):
                        raw_names.update(values)
                    _config_error(field, 'flag_suffix', self.flag_suffix,
                                  f'an unused output name; {name!r} is in the input',
                                  self._suffix_example(raw_names))
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
        bad, companion_notes = self._resolve_fronts(results, fields, present)
        output = fields.copy()
        for field, status in present.items():
            self._write_flags(output, field, status, results[field], companion_notes.get(field, ()))
        for field, status in present.items():
            checks = results[field]
            if status == PASS and checks.get('gross_range', (PASS, ''))[0] != FAIL:
                self._remember(field, timestamp, fields[field])
            if field in self.previous_companion and status == PASS and field not in bad:
                self.previous_companion[field] = (self.record_number, fields[field])
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
                normalized = _comparison_number(value)
                cache = self.flat_cache[field]
                earliest = None
                history = self.flat_history[field]
                if (cache is not None and cache[0] == normalized and history
                        and history[-1][0] == cache[1]):
                    earliest = cache[2]
                result, earliest = _flat_line(settings, timestamp, normalized, history, earliest)
                self.flat_cache[field] = (normalized, _comparison_number(timestamp), earliest)
            checks[test] = result
        return checks

    def _utc_month(self, timestamp):
        if timestamp is None:
            return None
        try:
            return datetime.fromtimestamp(floor(timestamp), timezone.utc).month
        except (OverflowError, OSError, ValueError) as error:
            now = time.monotonic()
            if self.last_utc_warning is None or now - self.last_utc_warning >= UTC_WARNING_INTERVAL:
                logging.warning('QartodFlagTransform: cannot convert timestamp %r to UTC for '
                                'monthly climatology: %s', timestamp, error)
                self.last_utc_warning = now
            return None

    def _resolve_fronts(self, results, fields, present):
        failures = {field: {test for test, (flag, _) in checks.items() if flag == FAIL}
                    for field, checks in results.items()}
        bad = {field for field, failed in failures.items() if failed or present[field] == FAIL}
        pending = {field for field, failed in failures.items()
                   if present[field] == PASS and self.front_checks[field]
                   and failed and failed <= JUMP_BASELINES.keys()}
        notes = {}
        evidence = {}
        # A jump failure can be corroborated only by companions available at the start
        # of the round. Keep that evidence once found so cycles cannot confirm themselves.
        while pending:
            confirmed = {}
            for field in pending:
                checks, unavailable, sources = self._check_front(
                    field, results[field], fields, present, bad, evidence)
                if all(flag != FAIL for flag, _ in checks.values()):
                    confirmed[field] = checks
                    notes[field] = unavailable
                    evidence[field] = sources
            if not confirmed:
                break
            results.update(confirmed)
            bad.difference_update(confirmed)
            pending.difference_update(confirmed)

        for field in results:
            if field not in notes and present[field] == PASS and self.front_checks[field]:
                results[field], notes[field], _ = self._check_front(
                    field, results[field], fields, present, bad, evidence)
        return bad, notes

    def _check_front(self, field, checks, fields, present, bad, evidence):
        companions = self.front_checks[field]
        checked = checks.copy()
        unavailable = []
        sources = set()
        for test, baseline in JUMP_BASELINES.items():
            flag, reason = checks.get(test, (NOT_EVALUATED, ''))
            if flag not in (SUSPECT, FAIL):
                continue
            start = self.history[field][baseline][0]
            checked[test], details, source = self._companion_verdict(
                field, companions, start, fields, present, bad, evidence, flag, reason)
            unavailable.extend(details)
            if source:
                sources.add(source)
                sources.update(evidence.get(source, ()))
        return checked, tuple(dict.fromkeys(unavailable)), sources

    def _companion_verdict(self, field, companions, start, fields, present, bad,
                           evidence, flag, reason):
        unavailable = []
        for name, limit in companions.items():
            previous = self.previous_companion[name]
            if present.get(name, MISSING) == MISSING:
                unavailable.append(f'{name} missing')
            elif name in bad:
                unavailable.append(f'{name} bad')
            elif field in evidence.get(name, ()):
                unavailable.append(f'{name} depends on this field')
            elif previous is None or previous[0] < start:
                unavailable.append(f'{name} has no previous good value in the jump window')
            elif _change(fields[name], previous[1]) >= _comparison_number(limit):
                reason = (f'{VERDICT_AMBIGUOUS}: jump matches a change in {name}; '
                          'may be a real front, check before trusting or discarding')
                return (SUSPECT, reason), (), name
        if unavailable:
            reason += '; ' + '; '.join(unavailable)
        return (flag, reason), unavailable, None

    def _write_flags(self, output, field, status, checks, companion_notes):
        base = field + self.flag_suffix
        aggregate = status if status != PASS else _aggregate([flag for flag, _ in checks.values()])
        output[base] = aggregate
        if self.per_test_flags:
            for test, (flag, _) in checks.items():
                output[f'{base}_{test}'] = flag
        if status == FAIL:
            reason = 'FAIL: syntax expected a finite number'
        elif aggregate in (SUSPECT, FAIL):
            # Keep front details when the jump has the same severity as other checks.
            candidates = [(test, reason) for test, (flag, reason) in checks.items()
                          if flag == aggregate]
            test, reason = min(candidates, key=lambda item: (
                not (aggregate == FAIL
                     and item[0] in ('gross_range', 'timing', 'flat_line')),
                not item[1].startswith(f'{VERDICT_AMBIGUOUS}:'),
                not (self.front_checks[field] and item[0] in JUMP_BASELINES),
            ))
            if aggregate == FAIL and test not in JUMP_BASELINES and companion_notes:
                reason += '; ' + '; '.join(companion_notes)
        else:
            return
        output[base + '_reason'] = reason

    def _remember(self, field, timestamp, value):
        normalized = _comparison_number(value)
        self.history[field].append((self.record_number, timestamp, normalized))
        if field not in self.flat_history:
            return
        history = self.flat_history[field]
        stamp = _comparison_number(timestamp) if timestamp is not None else None
        if stamp is None or (history and stamp <= _comparison_number(history[-1][0])):
            history.clear()
        if stamp is not None:
            history.append((stamp, normalized))
            cutoff = stamp - _comparison_number(self.tests[field]['flat_line']['fail_seconds'])
            # Keep one sample on or before the cutoff to establish a full run.
            while len(history) > 1 and history[1][0] <= cutoff:
                history.popleft()
