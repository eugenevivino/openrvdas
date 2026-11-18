"""Load and validate instrument initialization profiles."""

import re
from pathlib import Path

import yaml


class ProfileError(ValueError):
    """A single, actionable profile validation error."""


def _error(setting, saw, expected, example):
    raise ProfileError(f'{setting}: saw {saw!r}; expected {expected}; example: {example}')


def load_profile(source, allow_unreviewed=False):
    """Return a validated profile loaded with ``yaml.safe_load``."""
    if isinstance(source, (str, Path)):
        with open(source, encoding='utf-8') as stream:
            data = yaml.safe_load(stream)
    else:
        data = dict(source) if isinstance(source, dict) else source
    if not isinstance(data, dict):
        _error('profile', data, 'a YAML mapping', 'profile_id: example-v1')
    for key, kind, example in [('profile_id', str, 'example-v1'),
                               ('version', int, 'version: 1'),
                               ('source', str, 'source: Vendor manual p. 4')]:
        if not isinstance(data.get(key), kind) or data.get(key) == '':
            _error(key, data.get(key), kind.__name__, example)
    if not data.get('reviewed_by') and not allow_unreviewed:
        _error('reviewed_by', data.get('reviewed_by'),
               'a reviewer name or allow_unreviewed: true on the reader',
               'reviewed_by: J. Tech')
    if 'reviewed_on' not in data:
        _error('reviewed_on', None, 'a review date', 'reviewed_on: 2026-11-18')
    steps = data.get('steps')
    if not isinstance(steps, list):
        _error('steps', steps, 'a list', 'steps: []')
    for index, step in enumerate(steps):
        label = f'step {step.get("name", index) if isinstance(step, dict) else index}'
        if not isinstance(step, dict):
            _error(label, step, 'a mapping', '- {name: id, class: query, send: ID?}')
        for key in ('name', 'class', 'send'):
            if not isinstance(step.get(key), str):
                _error(f'{label} {key}', step.get(key), 'text', f'{key}: value')
        if step['class'] not in {'query', 'setup', 'persist'}:
            _error(f'{label} class', step['class'], 'query, setup, or persist', 'class: query')
        send = step['send']
        scrubbed = send.replace('{secret}', '')
        for match in re.finditer(r'\{([^{}]*)\}', scrubbed):
            if not match.group(1).startswith('utc:'):
                _error(f'{label} send', match.group(0), 'only {utc:FMT}', '{utc:%H:%M:%S}')
        if '{secret}' in send and not step.get('secret_env'):
            _error(f'{label} secret_env', None, 'an environment variable name',
                   'secret_env: SENSOR_PASSWORD')
        try:
            if step.get('expect') is not None:
                re.compile(step['expect'])
        except (re.error, TypeError) as exc:
            _error(f'{label} expect', str(exc), 'a regular expression', 'expect: ^OK$')
        for key in ('timeout_s', 'pause_s'):
            if key in step and not isinstance(step[key], (int, float)):
                _error(f'{label} {key}', step[key], 'a number', f'{key}: 1.0')
        if 'retries' in step and (not isinstance(step['retries'], int) or step['retries'] < 0):
            _error(f'{label} retries', step['retries'], 'a nonnegative integer', 'retries: 1')
    data.setdefault('instrument', data['profile_id'])
    data.setdefault('line_ending', '')
    data.setdefault('reinit', {})
    return data
