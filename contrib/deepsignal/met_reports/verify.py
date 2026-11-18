"""Exact-byte verification for report templates and known samples."""

import difflib
from pathlib import Path
import re

from .report_writer import _MissingValue, load_template


def render_sample(template, sample_bytes):
    parse = template.get('parse')
    if not isinstance(parse, dict) or not parse.get('pattern'):
        raise ValueError("setting 'parse': saw {!r}; expected a mapping with pattern; "
                         "example: parse: {{pattern: '...'}}".format(parse))
    text = sample_bytes.decode(parse.get('encoding', 'utf-8'))
    regex = re.compile(parse['pattern'], re.MULTILINE)
    rendered = []
    for match in regex.finditer(text):
        values = match.groupdict()
        for field, value in list(values.items()):
            if value == '':
                values[field] = _MissingValue(template['missing'].get(field, ''))
        rendered.append(template['row'].format_map(values))
    if not rendered:
        raise ValueError("setting 'parse.pattern': saw no matches; expected sample records; "
                         "example: ^(?P<value>.*)$")
    return ('\n'.join(rendered) + '\n').encode(parse.get('encoding', 'utf-8'))


def verify(template_path, sample_path, rendered_override=None):
    template = load_template(template_path)
    expected = Path(sample_path).read_bytes()
    actual = (rendered_override if rendered_override is not None
              else render_sample(template, expected))
    if actual == expected:
        print('exact match: {} bytes'.format(len(expected)))
        return 0
    expected_lines = expected.decode('utf-8', 'replace').splitlines(keepends=True)
    actual_lines = actual.decode('utf-8', 'replace').splitlines(keepends=True)
    print(''.join(difflib.unified_diff(expected_lines, actual_lines,
                                       fromfile='sample', tofile='rendered')), end='')
    return 1
