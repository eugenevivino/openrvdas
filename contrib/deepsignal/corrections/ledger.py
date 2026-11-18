"""Validate, replay and append correction ledger events."""

import fcntl
import hashlib
import json
import math
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from uuid import UUID


_METHOD_FIELDS = {
    'offset': {'value'},
    'linear_drift': {'rate_per_day', 't0'},
    'polynomial': {'coefficients'},
    'time_shift': {'seconds'},
    'gain_offset': {'offset', 'gain'},
}
_PROPOSAL_FIELDS = {
    'event', 'id', 'field', 'start', 'end', 'method', 'standard_uncertainty',
    'evidence', 'author', 'code_version', 'reason', 'correction_state',
    'model_id', 'fit_refs', 'validation_refs',
}
_OPTIONAL_FIELDS = {'instrument', 'coverage_interval', 'independence_score'}
_TRANSITION_FIELDS = {'event', 'id', 'by', 'reason', 'time'}
_TRANSITIONS = {
    'approve': ('proposed', 'approved'),
    'reject': ('proposed', 'rejected'),
    'rollback': ('approved', 'rolled_back'),
}
_UTC_ISO = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                      r'(?:\.[0-9]{1,6})?(?:Z|\+00:00)')
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)


def _canonical(event):
    return json.dumps(event, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _digest(event):
    return hashlib.sha256(_canonical(event)).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _reject_constant(token):
    raise ValueError(f'invalid JSON constant {token}')


def _is_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _number(value, name):
    if not _is_number(value):
        raise ValueError(f'{name} must be a finite number')
    return value


def _utc_seconds(value, name):
    if isinstance(value, str) and _UTC_ISO.fullmatch(value):
        try:
            pattern = '%Y-%m-%dT%H:%M:%S.%f%z' if '.' in value else '%Y-%m-%dT%H:%M:%S%z'
            elapsed = datetime.strptime(value, pattern) - _EPOCH
            return Fraction(elapsed // _MICROSECOND, 1_000_000)
        except ValueError:
            pass
    raise ValueError(f'{name} must be a UTC ISO timestamp')


def _record_seconds(value):
    if isinstance(value, str):
        return _utc_seconds(value, 'timestamp')
    # Compare epoch floats at their recorded decimal precision.
    return Fraction(str(_number(value, 'timestamp')))


def _check_keys(event, required, optional=()):
    missing = required - event.keys()
    extra = event.keys() - required - set(optional)
    if missing:
        raise ValueError(f'missing event fields: {", ".join(sorted(missing))}')
    if extra:
        raise ValueError(f'unknown event fields: {", ".join(sorted(map(repr, extra)))}')


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be non-empty text')
    return value


def _refs(event, name):
    refs = event[name]
    if not isinstance(refs, list):
        raise ValueError(f'{name} must be a list of non-empty strings')
    return {_text(ref, name).strip().casefold() for ref in refs}


def _validate_proposal(event):
    method = _text(event.get('method'), 'method')
    if method not in _METHOD_FIELDS:
        raise ValueError(f'unknown correction method {method!r}')
    parameters = _METHOD_FIELDS[method]
    _check_keys(event, _PROPOSAL_FIELDS | parameters, _OPTIONAL_FIELDS)
    for name in ('field', 'author', 'code_version', 'reason'):
        _text(event[name], name)
    if 'instrument' in event:
        _text(event['instrument'], 'instrument')
    if event['correction_state'] != 'CORRECTABLE':
        raise ValueError('correction_state must be CORRECTABLE')
    if event['model_id'] not in ('C0', 'C1', 'C2', 'C3', 'C4', 'C5'):
        raise ValueError('model_id must be C0 to C5')
    if not _refs(event, 'evidence'):
        raise ValueError('evidence must contain at least one reference')
    shared = _refs(event, 'fit_refs') & _refs(event, 'validation_refs')
    if shared:
        raise ValueError(f'fit_refs and validation_refs share ids: {", ".join(sorted(shared))}')

    start = _utc_seconds(event['start'], 'start')
    end = _utc_seconds(event['end'], 'end')
    if end <= start:
        raise ValueError('end must be later than start')
    if _number(event['standard_uncertainty'], 'standard_uncertainty') < 0:
        raise ValueError('standard_uncertainty must be non-negative')
    if 'independence_score' in event:
        if not 0 <= _number(event['independence_score'], 'independence_score') <= 1:
            raise ValueError('independence_score must be between 0 and 1')
    if 'coverage_interval' in event:
        interval = event['coverage_interval']
        if (not isinstance(interval, list) or len(interval) != 2
                or _number(interval[0], 'coverage_interval') >
                _number(interval[1], 'coverage_interval')):
            raise ValueError('coverage_interval must be [low, high] with low <= high')

    for name in parameters - {'t0', 'coefficients'}:
        _number(event[name], name)
    if method == 'linear_drift':
        _utc_seconds(event['t0'], 't0')
    elif method == 'polynomial':
        coefficients = event['coefficients']
        if not isinstance(coefficients, list) or not coefficients:
            raise ValueError('coefficients must be a non-empty list')
        for coefficient in coefficients:
            _number(coefficient, 'coefficients')
    elif method == 'gain_offset' and event['gain'] == 0:
        raise ValueError('gain must be non-zero')


def _validate_event(event):
    if not isinstance(event, dict):
        raise ValueError('event must be a JSON object')
    action = _text(event.get('event'), 'event')
    entry_id = _text(event.get('id'), 'id')
    uid = UUID(entry_id)
    if uid.version != 4 or str(uid) != entry_id:
        raise ValueError('id must be a canonical UUID4')
    if action == 'propose':
        _validate_proposal(event)
    elif action in _TRANSITIONS:
        _check_keys(event, _TRANSITION_FIELDS)
        for name in ('by', 'reason'):
            _text(event[name], name)
        _utc_seconds(event['time'], 'time')
    else:
        raise ValueError(f'unknown event {action!r}')


def _file_signature(stat):
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


class Ledger:
    """Verified snapshot of the correction ledger."""

    def __init__(self):
        self._entries = {}
        self._approved = {}
        self._head = None
        self._line_count = 0
        self._file_signature = None

    @property
    def entries(self):
        """Return proposals by ID, with current status and standard uncertainty."""
        return deepcopy(self._entries)

    @classmethod
    def load(cls, path, *, previous=None):
        """Verify every event and, if supplied, preserve the previous snapshot's history."""
        with open(path, 'rb') as file:
            fcntl.flock(file, fcntl.LOCK_SH)
            return cls._read(file, previous)

    @classmethod
    def append(cls, path, event):
        """Validate and append one event. Supply every event field except the hashes."""
        event = deepcopy(event)
        _validate_event(event)
        with open(path, 'a+b') as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            cls._require_live_file(path, file)
            file.seek(0)
            ledger = cls._read(file)
            ledger._apply_event(event)
            payload = dict(event, prev_hash=ledger._head)
            payload['hash'] = _digest(payload)
            file.write(_canonical(payload) + b'\n')
            file.flush()
            os.fsync(file.fileno())
            cls._require_live_file(path, file)

    @staticmethod
    def _require_live_file(path, file):
        """Require the locked descriptor to still be the path's live inode."""
        descriptor = os.fstat(file.fileno())
        live = os.stat(path)
        if (descriptor.st_dev, descriptor.st_ino) != (live.st_dev, live.st_ino):
            raise ValueError(f'{path}: ledger path was replaced during append')

    @classmethod
    def _read(cls, file, previous=None):
        ledger = cls()
        signature = _file_signature(os.fstat(file.fileno()))
        for line_number, line in enumerate(file, start=1):
            try:
                ledger._read_line(line)
                if (previous is not None and line_number == previous._line_count
                        and ledger._head != previous._head):
                    raise ValueError('history differs from the previously verified ledger')
            except (ValueError, RecursionError) as error:
                raise ValueError(f'{file.name}: line {line_number}: {error}') from error
            ledger._line_count = line_number
        if previous is not None and ledger._line_count < previous._line_count:
            raise ValueError(f'{file.name}: line {ledger._line_count + 1}: '
                             'previously verified history is missing')
        if signature != _file_signature(os.fstat(file.fileno())):
            raise ValueError(f'{file.name}: ledger changed during verification')
        ledger._file_signature = signature
        return ledger

    def _read_line(self, line):
        if not line.endswith(b'\n'):
            raise ValueError('incomplete JSON Lines event')
        event = json.loads(line.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        if not isinstance(event, dict):
            raise ValueError('event must be a JSON object')
        digest = event.pop('hash', None)
        if not isinstance(digest, str) or digest != _digest(event):
            raise ValueError('event hash does not match')
        if 'prev_hash' not in event or event.pop('prev_hash') != self._head:
            raise ValueError('prev_hash does not match the preceding event')
        if (event.get('event') == 'propose' and 'uncertainty' in event
                and 'standard_uncertainty' not in event):
            event['standard_uncertainty'] = event.pop('uncertainty')
        _validate_event(event)
        self._apply_event(event)
        self._head = digest

    def _apply_event(self, event):
        entry_id = event['id']
        action = event['event']
        if action == 'propose':
            if entry_id in self._entries:
                raise ValueError(f'duplicate proposal id {entry_id}')
            self._entries[entry_id] = dict(event, status='proposed')
            return

        entry = self._entries.get(entry_id)
        if entry is None:
            raise ValueError(f'unknown proposal id {entry_id}')
        expected, status = _TRANSITIONS[action]
        if entry['status'] != expected:
            raise ValueError(f'cannot {action} {entry_id} while it is {entry["status"]}')
        if event['by'].strip().casefold() == entry['author'].strip().casefold():
            raise ValueError(f'the proposal author cannot {action} their own proposal')

        field = entry['field']
        if action == 'approve':
            self._approved.setdefault(field, {})[entry_id] = (
                _utc_seconds(entry['start'], 'start'), _utc_seconds(entry['end'], 'end'))
        elif action == 'rollback':
            del self._approved[field][entry_id]
        entry['status'] = status

    def active(self, field, t):
        """Return approved proposals for field at UTC instant t, in approval order."""
        return self._active_at(field, _record_seconds(t))

    def _active_at(self, field, seconds):
        return [deepcopy(self._entries[entry_id])
                for entry_id, (start, end) in self._approved.get(field, {}).items()
                if start <= seconds < end]
