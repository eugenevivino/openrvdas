"""Read and check a vessel survey in metres."""

import logging
import math
import sys
from pathlib import Path
from typing import NamedTuple

import yaml


class Finding(NamedTuple):
    level: int
    message: str


def problem(setting, saw, expected, example):
    return f"{setting} saw {saw!r}, expected {expected} (example {example!r})."


def finite_number(value):
    # YAML and JSON can also encode booleans, infinities and unbounded integers.
    return type(value) in (int, float) and abs(value) <= sys.float_info.max


def check(survey):
    """Return all survey findings. Warnings allow the survey to be used."""
    findings = []
    ids = set()
    if not isinstance(survey, dict):
        return [Finding(logging.ERROR, problem('geometry_file', survey, 'a survey with positions',
                                               {'positions': []}))]
    for group in ('positions', 'monuments'):
        entries = survey.get(group, [] if group == 'monuments' else 'missing')
        if not isinstance(entries, list):
            findings.append(Finding(logging.ERROR, problem(group, entries, 'a list of points',
                                                           [dict(id='BM1', x=0, y=0, z=0)])))
            continue
        for index, point in enumerate(entries):
            label = f'{group}[{index}]'
            if not isinstance(point, dict):
                findings.append(Finding(logging.ERROR, problem(label, point, 'a named point',
                                                               dict(id='BM1', x=0, y=0, z=0))))
                continue
            name = point.get('id', 'missing')
            if ('id' not in point or not isinstance(name, str) or not name.strip()
                    or name in ids):
                findings.append(Finding(logging.ERROR, problem(f'{label}.id', name,
                                                               'a unique point name', 'BM2')))
            else:
                ids.add(name)
            coords = [point.get(axis, 'missing') for axis in 'xyz']
            for axis, value in zip('xyz', coords):
                if not finite_number(value):
                    findings.append(Finding(logging.ERROR, problem(f'{label}.{axis}', value,
                                                                   'a finite number in metres', 0)))
            if group == 'positions' and all(map(finite_number, coords)):
                distance = math.hypot(*coords)
                if distance > 200:
                    findings.append(Finding(logging.WARNING, f'{label} {name!r} is {distance:g} m '
                                            'from the origin (over 200 m). Check the survey units '
                                            'and reference point.'))
    return findings


def read_yaml(filename, setting, example):
    if not isinstance(filename, (str, Path)) or not str(filename).strip():
        raise ValueError(problem(setting, filename, 'a YAML file path', example))
    try:
        with open(filename, encoding='utf-8') as stream:
            return yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        if isinstance(exc, yaml.MarkedYAMLError) and exc.problem_mark:
            detail = f'{exc.problem} at line {exc.problem_mark.line + 1}'
        else:
            detail = str(exc)
        raise ValueError(problem(setting, f'{filename}: {detail}', 'a readable YAML file',
                                 example)) from None


def read_points(filename):
    survey = read_yaml(filename, 'geometry_file',
                       'contrib/deepsignal/configs/geometry_example.yaml')
    errors = []
    for finding in check(survey):
        if finding.level == logging.ERROR:
            errors.append(finding.message)
        else:
            logging.warning('%s', finding.message)
    if errors:
        raise ValueError('\n'.join(errors))
    return {group: {p['id']: (p['x'], p['y'], p['z']) for p in survey.get(group, [])}
            for group in ('positions', 'monuments')}
