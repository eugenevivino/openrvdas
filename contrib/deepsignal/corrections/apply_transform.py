"""Add ledger-backed corrected values to OpenRVDAS records."""

import logging
from copy import copy
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from threading import Lock
from typing import Union

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord

from .ledger import Ledger, _file_signature, _is_number, _record_seconds, _utc_seconds


_LOG = logging.getLogger(__name__)


class CorrectionApplyTransform(Transform):
    """Add correction fields from a verified ledger while preserving every input field."""

    def __init__(self, ledger_path, fields):
        super().__init__()
        if (not isinstance(fields, (list, tuple)) or not fields
                or any(not isinstance(field, str) or not field.strip() for field in fields)):
            raise ValueError('fields must be a non-empty list of field names')
        self.ledger_path = Path(ledger_path)
        self.fields = tuple(dict.fromkeys(fields))
        self._ledger = Ledger.load(self.ledger_path)
        self._warned_pairs = set()
        self._lock = Lock()

    def transform(self, record: Union[DASRecord, dict]):
        """Return the same record shape, with additions when a correction applies."""
        if record is None:
            return None
        with self._lock:
            if _file_signature(self.ledger_path.stat()) != self._ledger._file_signature:
                self._ledger = Ledger.load(self.ledger_path, previous=self._ledger)
            ledger = self._ledger
        return self._transform(record, ledger)

    def _transform(self, record, ledger):
        if record is None:
            return None
        if isinstance(record, list):
            return [self._transform(item, ledger) for item in record]
        if isinstance(record, DASRecord):
            timestamp, fields = record.timestamp, record.fields
        elif isinstance(record, dict):
            timestamp, fields = record.get('timestamp'), record.get('fields')
        else:
            # Use the core's fallback for types it may be able to convert.
            if hasattr(self, 'can_process_record') and not self.can_process_record(record):
                return self.digest_record(record)
            _LOG.warning('CorrectionApplyTransform cannot process record type %s', type(record))
            return record

        if not isinstance(fields, dict):
            return record
        try:
            seconds = _record_seconds(timestamp)
        except ValueError as error:
            _LOG.warning('Skipping corrections: %s (%r)', error, timestamp)
            return record

        additions = {}
        for field in self.fields:
            if field not in fields:
                continue
            entries = ledger._active_at(field, seconds)
            if len(entries) == 1:
                outputs = _corrected_fields(field, fields[field], seconds, entries[0])
                if outputs.keys().isdisjoint(fields) and outputs.keys().isdisjoint(additions):
                    additions.update(outputs)
                else:
                    _LOG.warning('Skipping correction %s for %s: output fields already exist',
                                 entries[0]['id'], field)
            elif len(entries) > 1:
                self._warn_overlap(field, entries)
        if not additions:
            return record

        result = copy(record)
        new_fields = fields.copy()
        new_fields.update(additions)
        if isinstance(result, DASRecord):
            result.fields = new_fields
        else:
            result['fields'] = new_fields
        return result

    def _warn_overlap(self, field, entries):
        for pair in combinations(sorted(entry['id'] for entry in entries), 2):
            with self._lock:
                if pair in self._warned_pairs:
                    continue
                self._warned_pairs.add(pair)
            _LOG.warning('Overlapping corrections for %s: %s and %s', field, *pair)


def _corrected_fields(field, raw, seconds, entry):
    method = entry['method']
    prefix = f'{field}_corr'
    outputs = {prefix: raw, f'{prefix}_id': entry['id'],
               f'{prefix}_u': entry['standard_uncertainty']}
    try:
        if method == 'time_shift':
            outputs[f'{prefix}_time'] = float(seconds + Fraction(str(entry['seconds'])))
        else:
            if not _is_number(raw):
                raise ValueError('raw value is not a finite number')
            corrected = _correct_value(raw, seconds, entry)
            if not _is_number(corrected):
                raise ValueError('corrected value is non-finite')
            outputs[prefix] = corrected
    except (OverflowError, ValueError) as error:
        _LOG.warning('Skipping correction %s for %s: %s', entry['id'], field, error)
        return {}
    return outputs


def _correct_value(raw, seconds, entry):
    method = entry['method']
    if method == 'offset':
        return raw + entry['value']
    if method == 'linear_drift':
        days = float((seconds - _utc_seconds(entry['t0'], 't0')) / 86400)
        return raw + entry['rate_per_day'] * days
    if method == 'gain_offset':
        return (raw - entry['offset']) / entry['gain']

    # Polynomial evaluated by Horner's method, from highest to lowest order.
    coefficients = entry['coefficients']
    result = coefficients[-1]
    for coefficient in reversed(coefficients[:-1]):
        result = result * raw + coefficient
    return result
