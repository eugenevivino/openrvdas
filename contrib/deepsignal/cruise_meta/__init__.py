"""Load and validate the metadata shared by one cruise."""

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml


_CRUISE_ID = re.compile(r'^[A-Za-z0-9_-]+$')
_UNLOCODE = re.compile(r'^[A-Za-z]{2}[A-Za-z0-9]{3}$')
_EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?!\w)')
_PHONE = re.compile(r'(?<!\w)(?:\+?\d[\d ().-]{6,}\d)(?!\w)')


def _datetime(value, setting):
    """Return a timezone-aware datetime, or raise a useful config error."""
    original = value
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ValueError(
            f'{setting} saw {original!r}; expected an ISO 8601 date and time with timezone, '
            'for example 2022-04-01T00:00Z')
    return parsed.astimezone(timezone.utc)


def _contact_path(value, path='metadata'):
    if isinstance(value, dict):
        for key, child in value.items():
            found = _contact_path(child, f'{path}.{key}')
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _contact_path(child, f'{path}[{index}]')
            if found:
                return found
    elif isinstance(value, str) and (_EMAIL.search(value) or _PHONE.search(value)):
        return path, value
    return None


def check(metadata):
    """Validate cruise metadata and return non-fatal warning strings."""
    if not isinstance(metadata, dict):
        raise ValueError(
            f'metadata saw {metadata!r}; expected a YAML mapping, for example cruise_id: RR2205')

    cruise_id = metadata.get('cruise_id')
    if not isinstance(cruise_id, str) or not _CRUISE_ID.fullmatch(cruise_id):
        raise ValueError(
            f'cruise_id saw {cruise_id!r}; expected letters, digits, dash or underscore, '
            'for example RR2205')

    start = _datetime(metadata.get('start'), 'start')
    end = _datetime(metadata.get('end'), 'end')
    if end <= start:
        raise ValueError(
            f'end saw {end.isoformat()}; expected a time after start {start.isoformat()}, '
            'for example 2022-05-10T00:00Z')

    for port_name in ('departure_port', 'arrival_port'):
        port = metadata.get(port_name)
        if not isinstance(port, dict):
            raise ValueError(
                f'{port_name} saw {port!r}; expected a mapping with name and unlocode, '
                'for example {name: San Diego, unlocode: USSAN}')
        code = port.get('unlocode')
        if code is not None and (not isinstance(code, str) or not _UNLOCODE.fullmatch(code)):
            raise ValueError(
                f'{port_name}.unlocode saw {code!r}; expected 5 characters with 2 letters '
                'then 3 letters or digits, for example USSAN')

    contact = _contact_path(metadata)
    if contact:
        path, value = contact
        raise ValueError(
            f'{path} saw {value!r}; expected names only because contact details do not belong '
            'in cruise metadata, for example Example Person')
    return []


def load(path):
    """Safely load and validate a cruise metadata YAML file."""
    with Path(path).open(encoding='utf-8') as stream:
        metadata = yaml.safe_load(stream)
    check(metadata)
    return metadata


def cruise_day(metadata, timestamp):
    """Return the 1-based cruise day containing timestamp."""
    start = _datetime(metadata['start'], 'start')
    current = _datetime(timestamp, 'timestamp')
    return (current - start).days + 1


def is_active(metadata, timestamp):
    """Return whether timestamp falls within the inclusive cruise dates."""
    current = _datetime(timestamp, 'timestamp')
    return _datetime(metadata['start'], 'start') <= current <= _datetime(metadata['end'], 'end')
