"""Read timestamped archives, enforce named splits and export the offline atlas."""

import csv
import fcntl
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
        for name, fit in [('Discovery', h), ('Holdout', holdout)]:
            lines.append(f"  {name} block {fit.get('block', 'unavailable')}, "
                         f"min_shift {fit.get('min_shift', 'unavailable')} bins.")
        if h['status'] == 'confirmed':
            cruises = h['holdout_cruises']
            count = sum(c['replicated'] for c in cruises)
            if cruises:
                lines.append(f"  Replicated on {count} of {len(cruises)} holdout cruises.")
            else:
                lines.append("  Cruise IDs unavailable for the holdout.")
            cells = [r for r in atlas['polar'][h['field']] if r['regime'] == h['regime']]
            if cells and cells[0].get('ship_variable') == h['ship_variable']:
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


def _owned_polar(path):
    """Recognize this exporter's CSVs, including leftovers from older runs."""
    if not path.is_file():
        return False
    try:
        with path.open(encoding='utf-8', newline='') as stream:
            row = next(csv.DictReader(stream), {})
        if not {'median', 'sector', 'speed_band', 'regime', 'code_version'} <= row.keys():
            return False
        fields = json.loads(row['parameters'])['fields']
        return isinstance(fields, list) and path.stem.removeprefix('polar_') in fields
    except (csv.Error, KeyError, TypeError, ValueError):
        return False


def write_atlas(atlas, inputs):
    output = Path(atlas['parameters'].get('output_dir', 'ship-coupling'))
    output.mkdir(parents=True, exist_ok=True)
    # Serialize publication and stale-file cleanup across atlas writers sharing this directory.
    directory = os.open(output, os.O_RDONLY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        _publish(atlas, output, inputs)
    finally:
        os.close(directory)


def _publish(atlas, output, inputs):
    params = atlas['parameters']
    names = {'atlas.json', 'atlas.md'}
    for field in params['fields']:
        if Path(field).name != field:
            raise ValueError('Field names must be single filename components')
        names.add(f'polar_{field}.csv')
    files = {'atlas.md': _markdown(atlas)}
    for field, table in atlas['polar'].items():
        if not table:
            continue
        stream = StringIO(newline='')
        meta = dict(code_version=atlas['code_version'],
                    parameters=json.dumps(params, sort_keys=True),
                    discovery_seed=params['seed'], holdout_seed=params['seed'] + 1,
                    healthy_spread=atlas['healthy_spread'][field])
        fits = {(h['regime'], h['ship_variable']): h for h in atlas['hypotheses']
                if h['field'] == field}
        lengths = {}
        for key, h in fits.items():
            lengths[key] = {f'{name}_{parameter}': fit.get(parameter)
                            for name, fit in [('discovery', h), ('holdout', h['holdout'])]
                            for parameter in ('block', 'min_shift', 'shift_reps')}
        meta['fit_lengths'] = json.dumps([dict(regime=r, ship_variable=v, **length)
                                          for (r, v), length in lengths.items()], sort_keys=True)
        records = [dict(row, **lengths[row['regime'], row['ship_variable']], **meta)
                   for row in table]
        writer = csv.DictWriter(stream, records[0])
        writer.writeheader()
        writer.writerows(records)
        files[f'polar_{field}.csv'] = stream.getvalue()
    stale = {p.name for p in output.glob('polar_*.csv') if p.name not in files and _owned_polar(p)}
    for name in names | stale:
        path = output / name
        if path.exists() and any(os.path.samefile(path, source) for source in inputs):
            raise ValueError(f'Input file aliases output {path}')
    files['atlas.json'] = json.dumps(atlas, indent=2, sort_keys=True, allow_nan=False) + '\n'
    for name, contents in files.items():
        if name == 'atlas.json':
            for old in stale:
                (output / old).unlink()
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
