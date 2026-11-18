"""Load and validate vendor-agnostic scoreboard profile files."""
import copy
import os
import re
import string
from pathlib import Path
import yaml

from . import contract

_TOP_KEYS = {'name', 'description', 'source', 'verified', 'codec', 'limits', 'framing',
             'addressing', 'pacing', 'transport_defaults', 'init_frames'}
_CHARSETS = {'ascii', 'upper', 'digits_sign_point'}
_TYPES_32 = {'int32', 'uint32', 'float32'}
_REGISTER_TYPES = {'int16', 'uint16'} | _TYPES_32
_VERIFIED = re.compile(r'^(?:unverified|datasheet|bench|ship:[A-Za-z0-9 _-]+)$')


def _error(source, key, message):
    raise contract.ProfileError('%s: %s: %s' % (source, key, message))


def _mapping(value, source, key):
    if not isinstance(value, dict):
        _error(source, key, 'expected a mapping')
    return value


def _unknown(section, allowed, source, prefix):
    extra = set(section) - set(allowed)
    if extra:
        key = sorted(extra)[0]
        _error(source, '%s.%s' % (prefix, key) if prefix else key, 'unknown key')


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _required(data, key, kind, source, path):
    value = data.get(key)
    if not isinstance(value, kind) or isinstance(value, bool):
        _error(source, path, 'required %s' % kind.__name__)
    return value


def _unescape(value, source, key):
    if not isinstance(value, str):
        _error(source, key, 'expected a string')
    try:
        contract.unescape(value)
    except contract.ProfileError as error:
        _error(source, key, str(error))


def _validate_limits(data, source):
    limits = _mapping(data.get('limits'), source, 'limits')
    _unknown(limits, {'lines', 'chars_per_line', 'charset', 'replace_char'}, source, 'limits')
    for key in ('lines', 'chars_per_line'):
        value = _required(limits, key, int, source, 'limits.' + key)
        if value < 1:
            _error(source, 'limits.' + key, 'must be at least 1')
    charset = limits.setdefault('charset', 'ascii')
    if charset not in _CHARSETS:
        _error(source, 'limits.charset', 'unknown charset "%s"' % charset)
    replace = limits.setdefault('replace_char', '?')
    if not isinstance(replace, str) or len(replace) != 1:
        _error(source, 'limits.replace_char', 'must be one character')
    valid = (ord(replace) < 128 if charset == 'ascii' else
             replace in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -.' if charset == 'upper' else
             replace in '0123456789 -.+')
    if not valid:
        _error(source, 'limits.replace_char', 'not valid in charset "%s"' % charset)
    return limits


def _validate_template(framing, limits, source):
    allowed = {'template', 'frame_per', 'line_separator', 'checksum', 'checksum_format',
               'checksum_from'}
    _unknown(framing, allowed, source, 'framing')
    template = framing.get('template')
    if not isinstance(template, str):
        _error(source, 'framing.template', 'required str')
    _unescape(template, source, 'framing.template')
    frame_per = framing.setdefault('frame_per', 'line')
    if frame_per not in ('line', 'page'):
        _error(source, 'framing.frame_per', 'expected line or page')
    separator = framing.setdefault('line_separator', '')
    _unescape(separator, source, 'framing.line_separator')
    checksum = framing.setdefault('checksum', 'none')
    if checksum not in contract.CHECKSUM_NAMES:
        _error(source, 'framing.checksum', 'unknown checksum "%s"' % checksum)
    checksum_format = framing.setdefault('checksum_format', 'hex2')
    if checksum_format not in contract.CHECKSUM_FORMATS:
        _error(source, 'framing.checksum_format', 'unknown checksum format "%s"' % checksum_format)
    _unescape(framing.setdefault('checksum_from', ''), source, 'framing.checksum_from')
    count = 0
    fields = {'address', 'line', 'line_number', 'page', 'checksum'}
    fields.update('line%d' % number for number in range(1, 10))
    try:
        parsed = string.Formatter().parse(template)
        for _, field, _, _ in parsed:
            if field is None:
                continue
            if field not in fields or '.' in field or '[' in field:
                _error(source, 'framing.template', 'unknown or unsafe field {%s}' % field)
            if field == 'checksum':
                count += 1
            if field in ('line', 'line_number') and frame_per != 'line':
                _error(source, 'framing.template', '{%s} requires frame_per line' % field)
            if field == 'page' and frame_per != 'page':
                _error(source, 'framing.template', '{page} requires frame_per page')
            match = re.fullmatch(r'line([1-9])', field)
            if match and (frame_per != 'page' or int(match.group(1)) > limits['lines']):
                _error(source, 'framing.template', '{%s} is not available' % field)
    except (ValueError, IndexError) as error:
        _error(source, 'framing.template', 'invalid template: %s' % error)
    if count > 1:
        _error(source, 'framing.template', '{checksum} may appear only once')
    if (checksum == 'none') != (count == 0):
        _error(source, 'framing.template',
               '{checksum} must appear exactly when checksum is enabled')


def _validate_alpha(framing, source):
    _unknown(framing, {'type_code', 'file_label', 'sync', 'checksum', 'mode',
                       'line_separator'}, source, 'framing')
    for key, default in (('type_code', 'Z'), ('file_label', 'A')):
        value = framing.setdefault(key, default)
        if not isinstance(value, str) or len(value) != 1:
            _error(source, 'framing.' + key, 'must be one character')
    if framing.setdefault('sync', 'nul') not in ('nul', 'soh'):
        _error(source, 'framing.sync', 'expected nul or soh')
    if not isinstance(framing.setdefault('checksum', True), bool):
        _error(source, 'framing.checksum', 'expected bool')
    _unescape(framing.setdefault('line_separator', ' '), source, 'framing.line_separator')
    if 'mode' in framing:
        mode = _mapping(framing['mode'], source, 'framing.mode')
        _unknown(mode, {'position', 'code'}, source, 'framing.mode')
        for key in ('position', 'code'):
            if not isinstance(mode.get(key), str) or len(mode[key]) != 1:
                _error(source, 'framing.mode.' + key, 'required one-character string')


def _validate_modbus(framing, lines, source):
    _unknown(framing, {'registers'}, source, 'framing')
    registers = framing.get('registers')
    if not isinstance(registers, list) or not registers:
        _error(source, 'framing.registers', 'required non-empty list')
    occupied = set()
    for index, item in enumerate(registers):
        key = 'framing.registers.%d' % index
        item = _mapping(item, source, key)
        _unknown(item, {'line', 'cell', 'register', 'type', 'scale', 'word_order',
                        'stale_value'}, source, key)
        line = item.get('line')
        if not _integer(line) or not 1 <= line <= lines:
            _error(source, key + '.line', 'must be between 1 and limits.lines')
        cell = item.setdefault('cell', 0)
        if not _integer(cell) or cell < 0:
            _error(source, key + '.cell', 'must be a non-negative int')
        register = item.get('register')
        if not _integer(register) or not 0 <= register <= 65535:
            _error(source, key + '.register', 'must be between 0 and 65535')
        register_type = item.get('type')
        if register_type not in _REGISTER_TYPES:
            _error(source, key + '.type', 'unknown register type')
        if not _number(item.setdefault('scale', 1)):
            _error(source, key + '.scale', 'must be a number')
        if 'stale_value' not in item or not _number(item['stale_value']):
            _error(source, key + '.stale_value', 'required number')
        if register_type in _TYPES_32:
            if item.setdefault('word_order', 'big') not in ('big', 'little'):
                _error(source, key + '.word_order', 'expected big or little')
            width = 2
        else:
            if 'word_order' in item:
                _error(source, key + '.word_order', 'only valid for 32-bit types')
            width = 1
        overlap = any(register + offset in occupied for offset in range(width))
        if register + width - 1 > 65535 or overlap:
            _error(source, key + '.register', 'overlaps another register')
        occupied.update(range(register, register + width))


def validate_profile(data: dict, source: str) -> contract.Profile:
    """Validate profile data and return a normalized Profile."""
    data = copy.deepcopy(_mapping(data, source, '<root>'))
    _unknown(data, _TOP_KEYS, source, '')
    name = data.get('name')
    if not isinstance(name, str) or not name:
        _error(source, 'name', 'required str')
    stem = Path(source).stem
    if name != stem:
        _error(source, 'name', 'must equal file stem "%s"' % stem)
    for key in ('description', 'source'):
        if not isinstance(data.setdefault(key, ''), str):
            _error(source, key, 'expected str')
    verified = data.setdefault('verified', 'unverified')
    if not isinstance(verified, str) or not _VERIFIED.fullmatch(verified):
        _error(source, 'verified', 'invalid verification status')
    codec = data.get('codec')
    if codec not in contract.CODEC_NAMES:
        _error(source, 'codec', 'unknown codec "%s"' % codec)
    limits = _validate_limits(data, source)
    framing = _mapping(data.get('framing'), source, 'framing')
    if codec == 'text':
        _validate_template(framing, limits, source)
    elif codec == 'alpha':
        _validate_alpha(framing, source)
    else:
        _validate_modbus(framing, limits['lines'], source)
    addressing = _mapping(data.setdefault('addressing', {}), source, 'addressing')
    _unknown(addressing, {'default', 'range', 'multidrop'}, source, 'addressing')
    if 'default' in addressing and not _integer(addressing['default']):
        _error(source, 'addressing.default', 'expected int')
    if 'range' in addressing:
        bounds = addressing['range']
        if (not isinstance(bounds, list) or len(bounds) != 2 or
                not all(_integer(value) for value in bounds) or bounds[0] > bounds[1]):
            _error(source, 'addressing.range', 'expected [low, high] ints with low <= high')
        if 'default' in addressing and not bounds[0] <= addressing['default'] <= bounds[1]:
            _error(source, 'addressing.default', 'outside addressing.range')
    if not isinstance(addressing.setdefault('multidrop', False), bool):
        _error(source, 'addressing.multidrop', 'expected bool')
    pacing = _mapping(data.setdefault('pacing', {}), source, 'pacing')
    _unknown(pacing, {'inter_frame_delay', 'max_rate_hz'}, source, 'pacing')
    delay = pacing.setdefault('inter_frame_delay', 0)
    if not _number(delay) or delay < 0:
        _error(source, 'pacing.inter_frame_delay', 'must be a non-negative number')
    if 'max_rate_hz' in pacing and (not _number(pacing['max_rate_hz']) or
                                    pacing['max_rate_hz'] <= 0):
        _error(source, 'pacing.max_rate_hz', 'must be greater than zero')
    transport = _mapping(data.setdefault('transport_defaults', {}), source,
                         'transport_defaults')
    transport_type = transport.get('type')
    if transport_type is not None and transport_type not in contract.TRANSPORT_NAMES:
        _error(source, 'transport_defaults.type', 'unknown transport "%s"' % transport_type)
    allowed_transports = (contract.REGISTER_TRANSPORTS if codec == 'modbus'
                          else contract.BYTE_TRANSPORTS)
    if transport_type is not None and transport_type not in allowed_transports:
        _error(source, 'transport_defaults.type', 'incompatible with codec "%s"' % codec)
    init_frames = data.setdefault('init_frames', [])
    if not isinstance(init_frames, list):
        _error(source, 'init_frames', 'expected list')
    if init_frames and codec != 'text':
        _error(source, 'init_frames', 'only valid for text codec')
    for index, frame in enumerate(init_frames):
        _unescape(frame, source, 'init_frames.%d' % index)
    return contract.Profile(name=name, codec=codec, limits=limits, framing=framing,
                            addressing=addressing, pacing=pacing,
                            transport_defaults=transport, init_frames=init_frames,
                            description=data['description'], source=data['source'],
                            verified=verified)


def _default_search_path():
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.realpath(__file__)))))
    return [os.path.join(repo, 'local', 'scoreboard_profiles'),
            os.path.join(os.path.dirname(os.path.realpath(__file__)), 'profiles')]


def _merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        result = copy.deepcopy(base)
        for key, value in override.items():
            result[key] = _merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    return copy.deepcopy(override)


def load_profile(name_or_path, overrides=None, search_path=None):
    """Load a path or find a named profile in search path order."""
    separators = [separator for separator in (os.sep, os.altsep) if separator]
    is_path = str(name_or_path).endswith('.yaml') or any(
        separator in str(name_or_path) for separator in separators)
    if is_path:
        path = os.path.realpath(os.fspath(name_or_path))
    else:
        paths = _default_search_path() if search_path is None else list(search_path)
        matches = [os.path.join(directory, str(name_or_path) + '.yaml') for directory in paths]
        path = next((os.path.realpath(candidate) for candidate in matches
                     if os.path.isfile(candidate)), '')
        if not path:
            raise contract.ProfileError('%s: profile not found' % name_or_path)
    try:
        with open(path, encoding='utf-8') as stream:
            data = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as error:
        raise contract.ProfileError('%s: <root>: %s' % (path, error))
    profile = validate_profile(_merge(data, overrides or {}), path)
    profile.path = path
    return profile


def list_profiles(search_path=None):
    """List the first profile of each name, noting profiles hidden later."""
    paths = _default_search_path() if search_path is None else list(search_path)
    candidates = {}
    for directory in paths:
        if not os.path.isdir(directory):
            continue
        for path in sorted(Path(directory).glob('*.yaml')):
            candidates.setdefault(path.stem, []).append(path)
    result = []
    for name in sorted(candidates):
        profile = load_profile(str(candidates[name][0]))
        result.append({'name': name, 'path': profile.path, 'codec': profile.codec,
                       'verified': profile.verified, 'shadowed': len(candidates[name]) > 1})
    return result
