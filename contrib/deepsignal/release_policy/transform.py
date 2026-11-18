"""Apply an audience and EEZ release policy to outbound records."""

import copy
import fnmatch
import hashlib
import importlib.util
import logging

import yaml

if importlib.util.find_spec('logger.transforms.transform'):
    from logger.transforms.transform import Transform
    from logger.utils.das_record import DASRecord
else:  # Current core exposes the same classes from openrvdas.logger.
    from openrvdas.logger.transforms.transform import Transform
    from openrvdas.logger.utils.das_record import DASRecord


AUDIENCES = ('public', 'science', 'shore_ops')


def _error(setting, value, expected, example):
    raise ValueError('%s saw %r; expected %s; good example: %s' %
                     (setting, value, expected, example))


def _validate_audience(setting, value):
    if value not in AUDIENCES:
        _error(setting, value, 'public, science, or shore_ops', 'science')


def load_policy(policy_path):
    """Safely load and validate a release policy."""
    with open(policy_path, 'rb') as policy_file:
        raw = policy_file.read()
    try:
        policy = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        _error('policy YAML', str(exc).splitlines()[0], 'valid YAML', 'audience: science')
    if not isinstance(policy, dict):
        _error('policy', policy, 'a YAML mapping', 'audience: science')

    _validate_audience('audience', policy.get('audience'))
    _validate_audience('default_level', policy.get('default_level'))
    levels = policy.get('levels')
    if not isinstance(levels, dict):
        _error('levels', levels, 'a mapping of glob to audience', "'TSG_*': science")
    for pattern, audience in levels.items():
        if (not isinstance(pattern, str) or pattern.count('[') != pattern.count(']')):
            _error('levels glob', pattern, 'a valid shell-style glob', 'TSG_*')
        _validate_audience('level for glob %s' % pattern, audience)

    eez = policy.get('eez')
    if not isinstance(eez, dict):
        _error('eez', eez, 'a mapping', 'inside_field: eez_inside')
    for setting in ('inside_field',):
        if not isinstance(eez.get(setting), str) or not eez[setting]:
            _error('eez.%s' % setting, eez.get(setting), 'a non-empty field name',
                   'eez_inside')
    for setting in ('hold_back', 'position_fields'):
        value = eez.get(setting)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            _error('eez.%s' % setting, value, 'a list of field globs', "['TSG_*']")
    rounding = eez.get('position_rounding_deg')
    if not isinstance(rounding, (int, float)) or isinstance(rounding, bool) or rounding <= 0:
        _error('eez.position_rounding_deg', rounding, 'a positive number', '0.1')
    return policy, hashlib.sha256(raw).hexdigest()[:12]


class ReleasePolicyTransform(Transform):
    """Filter copies of records according to a release policy YAML file."""

    def __init__(self, policy_path):
        super().__init__()
        self.policy, self.policy_hash = load_policy(policy_path)
        self.eez_inside = None
        self._unknown_warning_logged = False

    def _level_for(self, field):
        for pattern, level in self.policy['levels'].items():
            if fnmatch.fnmatchcase(field, pattern):
                return level
        return self.policy['default_level']

    def _allowed_for_audience(self, field):
        required = self._level_for(field)
        return AUDIENCES.index(self.policy['audience']) >= AUDIENCES.index(required)

    def _held_back(self, field):
        return any(fnmatch.fnmatchcase(field, pattern)
                   for pattern in self.policy['eez']['hold_back'])

    def _transform_one(self, record):
        if record is None:
            return None
        output = copy.deepcopy(record)
        if isinstance(output, DASRecord):
            fields = output.fields
        elif isinstance(output, dict) and isinstance(output.get('fields'), dict):
            fields = output['fields']
        else:
            logging.warning(
                'ReleasePolicyTransform expected a DASRecord or record dictionary; saw %r',
                type(record).__name__)
            return None

        if not fields:
            return None
        eez = self.policy['eez']
        if eez['inside_field'] in fields:
            self.eez_inside = bool(fields[eez['inside_field']])
        inside = self.eez_inside
        if inside is None:
            inside = True
            if not self._unknown_warning_logged:
                logging.warning(
                    'EEZ state is unknown; release policy is failing closed as inside EEZ')
                self._unknown_warning_logged = True

        released = {}
        for field, value in fields.items():
            if not self._allowed_for_audience(field):
                continue
            is_position = field in eez['position_fields']
            if inside and self._held_back(field) and not is_position:
                continue
            if inside and is_position and isinstance(value, (int, float)):
                step = eez['position_rounding_deg']
                value = round(value / step) * step
            released[field] = value
        if not released:
            return None
        released['release_policy'] = self.policy_hash
        if isinstance(output, DASRecord):
            output.fields = released
        else:
            output['fields'] = released
        return output

    def transform(self, record):
        """Return a policy-shaped copy, preserving lists and passing None through."""
        if isinstance(record, list):
            return [self._transform_one(item) for item in record]
        return self._transform_one(record)

    def explain(self, field):
        """Return a plain-English explanation for one field."""
        level = self._level_for(field)
        audiences = ', '.join(AUDIENCES[AUDIENCES.index(level):])
        held = self._held_back(field) and field not in self.policy['eez']['position_fields']
        inside = ('withheld for every audience' if held else
                  'visible to %s (positions are rounded when configured)' % audiences)
        return ('%s requires the %s audience: outside the EEZ it is visible to %s; '
                'inside the EEZ it is %s.' % (field, level, audiences, inside))
