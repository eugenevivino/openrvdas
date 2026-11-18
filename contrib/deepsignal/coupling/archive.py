"""Read timestamped archives, enforce named splits and export the offline atlas."""

import csv
from io import StringIO
import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .prep import timestamp


def _number(value):
    return float(value) if value and value.strip() else None


def _csv_rows(path):
    rows, skipped = [], 0
    with path.open('rb') as stream:
        names = next(csv.reader([stream.readline().decode('utf-8-sig')], strict=True), [])
        if 'timestamp' not in names or len(set(names)) != len(names):
            raise ValueError(f'{path} requires a timestamp and distinct column names')
        for line in stream:
            try:
                values = next(csv.reader([line.decode('utf-8')], strict=True))
                row = dict(zip(names, values, strict=True))
                parsed = {'timestamp': timestamp(row.pop('timestamp'))}
                for key, value in row.items():
                    parsed[key] = value if key in ('regime', 'cruise') else _number(value)
                rows.append(parsed)
            except (csv.Error, ValueError, TypeError, OverflowError):
                skipped += 1
    return rows, skipped


def _messages(path, messages, cruise):
    rows, skipped = [], 0
    with path.open('rb') as stream:
        for line in stream:
            try:
                stamp, payload = line.decode('utf-8').split(None, 1)
                t = timestamp(stamp)
                parts = payload.rstrip().split(',')
                if parts[0] in messages:
                    fields = {name: _number(parts[index].split('*')[0]) for name, index
                              in messages[parts[0]].items()}
                    rows.append(dict(fields, timestamp=t, cruise=cruise))
            except (IndexError, ValueError, OverflowError):
                skipped += 1
    return rows, skipped


def read_input(config):
    if bool(config.get('input_csv')) == bool(config.get('streams')):
        raise ValueError('Specify input_csv or timestamped message streams')
    if config.get('input_csv'):
        path = Path(config['input_csv'])
        rows, skipped = _csv_rows(path)
        paths = [path]
    else:
        rows, skipped, paths = [], 0, []
        for stream in config['streams']:
            path = Path(stream['path'])
            paths.append(path)
            data, errors = _messages(path, stream['messages'], stream.get('cruise'))
            rows.extend(data)
            skipped += errors
    if skipped:
        logging.getLogger(__name__).warning('Skipped %d unparseable input lines', skipped)
    return rows, skipped, paths


def select_splits(rows, splits):
    if set(splits) != {'discovery', 'holdout'}:
        raise ValueError('Expected named discovery and holdout splits')
    selectors = []
    for name in ('discovery', 'holdout'):
        spec = splits[name]
        cruises = spec.get('cruises')
        if 'start' in spec or 'end' in spec:
            start, end = timestamp(spec['start']), timestamp(spec['end'])
            if start >= end:
                raise ValueError(f'Empty or reversed time range in {name}')
        elif cruises:
            start, end = -float('inf'), float('inf')
        else:
            raise ValueError(f'Expected cruises or a time range in {name}')
        selectors.append((set(cruises) if cruises is not None else None, start, end))
    (a, lo, hi), (b, low, high) = selectors
    if (a is None or b is None or a & b) and max(lo, low) < min(hi, high):
        raise ValueError('Discovery and holdout selections overlap')
    return [[r for r in rows if start <= r['timestamp'] < end and
             (cruises is None or r.get('cruise') in cruises)] for cruises, start, end in selectors]


def _markdown(atlas):
    lines = ['# Ship-coupling atlas', '',
             f"Skipped {atlas['unparseable_lines']} unparseable input lines.", '']
    for h in sorted(atlas['hypotheses'], key=lambda h: h['status'] != 'confirmed'):
        effect = 'unavailable' if h['effect'] is None else f"{h['effect']:.3f}"
        holdout = h['holdout']
        if holdout['insufficient']:
            replication = 'The holdout has insufficient evidence.'
        else:
            replication = f"Holdout FDR {'passed' if holdout['q_pass'] else 'did not pass'}."
        lines.append(f"* {h['field']} vs {h['ship_variable']} during {h['regime']}: "
                     f"**{h['status']}**. Residual rank correlation {effect}. "
                     f"{replication} Ship-coordinate control: {h['invariance']}.")
        if h['status'] == 'confirmed':
            cells = [r for r in atlas['polar'][h['field']] if r['regime'] == h['regime']]
            if cells:
                cell = max(cells, key=lambda r: abs(r['median']))
                lines.append(f"  Sector {cell['sector']}, speed band {cell['speed_band']} has "
                             f"median residual {cell['median']:+.3g} in field units "
                             f"across {cell['count']} bins.")
    lines += ['', f"Code version {atlas['code_version']}. "
              f"Discovery seed {atlas['parameters']['seed']}, "
              f"holdout seed {atlas['parameters']['seed'] + 1}.", '',
              'Resolved parameters', '', '```json',
              json.dumps(atlas['parameters'], indent=2, sort_keys=True), '```', '']
    return '\n'.join(lines)


def write_atlas(atlas, inputs):
    params = atlas['parameters']
    output = Path(params.get('output_dir', 'ship-coupling'))
    names = ['atlas.json', 'atlas.md']
    for field in params['fields']:
        if Path(field).name != field:
            raise ValueError('Field names must be single filename components')
        names.append(f'polar_{field}.csv')
    for path in (output / name for name in names):
        if path.exists() and any(os.path.samefile(path, source) for source in inputs):
            raise ValueError(f'Input file aliases output {path}')
    files = {'atlas.json': json.dumps(atlas, indent=2, sort_keys=True, allow_nan=False) + '\n',
             'atlas.md': _markdown(atlas)}
    for field, table in atlas['polar'].items():
        if not table:
            continue
        stream = StringIO(newline='')
        meta = dict(code_version=atlas['code_version'],
                    parameters=json.dumps(params, sort_keys=True),
                    discovery_seed=params['seed'], holdout_seed=params['seed'] + 1,
                    healthy_spread=atlas['healthy_spread'][field])
        writer = csv.DictWriter(stream, [*table[0], *meta])
        writer.writeheader()
        writer.writerows(dict(row, **meta) for row in table)
        files[f'polar_{field}.csv'] = stream.getvalue()
    output.mkdir(parents=True, exist_ok=True)
    for name, contents in files.items():
        # Replace the directory entry instead of truncating any existing file or link target.
        with NamedTemporaryFile(mode='w', dir=output, encoding='utf-8', newline='',
                                delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(contents)
                stream.close()
                temporary.replace(output / name)
            finally:
                temporary.unlink(missing_ok=True)
