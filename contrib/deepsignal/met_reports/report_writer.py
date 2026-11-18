"""Write records using hand-editable, safe YAML report templates."""

import datetime
import logging
from pathlib import Path
import string
import zipfile

import yaml

from logger.utils.formats import Python_Record
from logger.writers.writer import Writer


class TemplateError(ValueError):
    """A template has an actionable configuration error."""


def _error(setting, saw, expected, example):
    return TemplateError("setting '{}': saw {!r}; expected {}; example: {}".format(
        setting, saw, expected, example))


def load_template(path):
    """Safely load and validate a report template."""
    try:
        with Path(path).open(encoding='utf-8') as source:
            template = yaml.safe_load(source)
    except (OSError, yaml.YAMLError) as exc:
        raise _error('template', str(exc), 'readable YAML', 'templates/samos_daily.yaml') from exc
    if not isinstance(template, dict):
        raise _error('template', template, 'a YAML mapping', 'name: samos_daily')
    required = {'name', 'status', 'period', 'filename', 'row', 'fields', 'missing'}
    absent = sorted(required - set(template))
    if absent:
        raise _error('template', absent, 'all required settings', 'period: daily')
    if template['period'] not in ('1min', 'hourly', 'daily'):
        raise _error('period', template['period'], '1min, hourly, or daily', 'period: hourly')
    if not isinstance(template['fields'], list):
        raise _error('fields', template['fields'], 'a list of field names', 'fields: [latitude]')
    known = set(template['fields']) | {'ship', 'yyyymmdd', 'hh', 'timestamp'}
    for setting in ('row', 'filename'):
        try:
            placeholders = [name for _, name, _, _ in string.Formatter().parse(template[setting])
                            if name]
        except ValueError as exc:
            raise _error(setting, template[setting], 'valid Python format placeholders',
                         '{latitude:.5f}') from exc
        unknown = [name for name in placeholders if name not in known]
        if unknown:
            raise _error(setting, unknown[0], 'a declared field (missing declaration)',
                         'fields: [{}]'.format(unknown[0]))
    return template


def parse_timestamp(value):
    """Return an aware UTC datetime from common record timestamp forms."""
    if isinstance(value, datetime.datetime):
        stamp = value
    elif isinstance(value, (int, float)):
        stamp = datetime.datetime.fromtimestamp(value, datetime.timezone.utc)
    elif isinstance(value, str):
        stamp = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        message = ("record timestamp: saw {!r}; expected UTC ISO text, epoch seconds, "
                   "or datetime; example: 2026-11-18T12:00:00Z")
        raise ValueError(message.format(value))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return stamp.astimezone(datetime.timezone.utc)


class _MissingValue:
    def __init__(self, text):
        self.text = text

    def __format__(self, unused_spec):
        return str(self.text)


class ReportWriter(Writer):
    """Write one text (or zip) file per template period, based on record time."""

    def __init__(self, template, directory, ship, designators=None):
        super().__init__(input_format=Python_Record)
        self.template_path = Path(template)
        self.template = load_template(template)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ship = ship
        self.designators = dict(self.template.get('designator_defaults', {}))
        self.designators.update(designators or {})
        self._period = None
        self._handle = None
        self._path = None
        if self.template['status'] != 'VERIFIED':
            logging.warning('Report template %s has status %s', self.template['name'],
                            self.template['status'])

    def _period_key(self, stamp):
        if self.template['period'] == 'daily':
            return stamp.strftime('%Y%m%d')
        if self.template['period'] == 'hourly':
            return stamp.strftime('%Y%m%d%H')
        return stamp.strftime('%Y%m%d%H%M')

    def _open(self, stamp):
        values = {'ship': self.ship, 'yyyymmdd': stamp.strftime('%Y%m%d'),
                  'hh': stamp.strftime('%H')}
        try:
            filename = self.template['filename'].format_map(values)
        except (KeyError, ValueError) as exc:
            raise _error('filename', self.template['filename'], 'renderable placeholders',
                         '{ship}_{yyyymmdd}.txt') from exc
        self._path = self.directory / filename
        self._handle = self._path.open('w', encoding='utf-8', newline='\n')
        for line in self.template.get('header', []):
            self._handle.write(str(line) + '\n')

    def _close_current(self):
        if self._handle is None:
            return
        self._handle.close()
        self._handle = None
        if self.template.get('zip'):
            archive = self._path.with_suffix(self._path.suffix + '.zip')
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as target:
                target.write(self._path, arcname=self._path.name)
            self._path.unlink()

    def _render(self, timestamp, fields):
        values = dict(fields)
        values.update(self.designators)
        values['timestamp'] = timestamp
        for name in self.template['fields']:
            if values.get(name) is None:
                values[name] = _MissingValue(self.template['missing'].get(name, ''))
        try:
            return self.template['row'].format_map(values)
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("setting 'row': could not render input; expected declared values; "
                             "example: {{latitude:.5f}}: {}".format(exc)) from exc

    def write(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            for item in record:
                self.write(item)
            return None
        if isinstance(record, dict):
            timestamp = record.get('timestamp')
            fields = record.get('fields', {})
        else:
            timestamp = record.timestamp
            fields = record.fields
        stamp = parse_timestamp(timestamp)
        period = self._period_key(stamp)
        if period != self._period:
            self._close_current()
            self._open(stamp)
            self._period = period
        timestamp_text = (timestamp if isinstance(timestamp, str)
                          else stamp.isoformat().replace('+00:00', 'Z'))
        self._handle.write(self._render(timestamp_text, fields) + '\n')
        return None

    def close(self):
        self._close_current()
