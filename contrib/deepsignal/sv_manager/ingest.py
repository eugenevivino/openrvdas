"""Bounded, read-only decoders for casts and shore-prepared references."""
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .profile import ARRAYS, BOTTOM, Profile, interpolate, ordered

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 100_000
DEFAULT_MAP = Path(__file__).with_name('formats') / 'sondes.yaml'


def read_bytes(path, limit=MAX_BYTES):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f'{path.name}: supply a regular text file.')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'{path.name} exceeds {limit} bytes. Split or reduce this file.')
    return data


def text_lines(data):
    lines = []
    for i, line in enumerate(io.StringIO(data.decode('utf-8-sig'), newline=None)):
        if i >= MAX_ROWS + 8192:
            raise ValueError('Too many header or data lines. Split the file.')
        if line.strip():
            lines.append(line.strip())
    return lines


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(path, data):
    return dict(path=str(Path(path).absolute()), sha256=digest(data))


def number(value, bad=None):
    if value is None or str(value).strip().upper() in ('', 'NA', 'N/A', 'NULL'):
        return None
    n = float(value)
    if not math.isfinite(n):
        raise ValueError(f'Non-finite number {value!r}. Check the cast or use an empty CSV cell.')
    return None if n == bad else n


def instant(value):
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ('%b %d %Y %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S.%f'):
            try:
                when = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f'Unknown UTC time {value!r}. Use 2026-11-18T00:00:00Z.')
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp()


def coordinate(value, axis):
    if value is None:
        return None
    parts = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)(?:[ °:]+(\d+(?:\.\d+)?))?'
                         r"\s*['′]?\s*([NSEW])?", value.strip().upper())
    if not parts:
        raise ValueError(f'Invalid {axis}: {value!r}. Use signed decimal degrees.')
    degrees, minutes, hemi = parts.groups()
    degrees = float(degrees)
    if minutes and not 0 <= float(minutes) < 60:
        raise ValueError(f'Invalid minutes in {axis}: {value!r}.')
    if hemi and (degrees < 0 or hemi not in ('NS' if axis == 'latitude' else 'EW')):
        raise ValueError(f'Invalid hemisphere in {axis}: {value!r}.')
    sign = -1 if hemi in ('S', 'W') or degrees < 0 else 1
    result = sign*(abs(degrees) + float(minutes or 0)/60)
    if abs(result) > (90 if axis == 'latitude' else 180):
        raise ValueError(f'{axis} out of range: {value!r}.')
    return result


def column_data(indices, rows, bad=None):
    if 'depth_m' not in indices or not ({'sv_ms', 't_c', 's_psu'} & indices.keys()):
        raise ValueError('Check the mapping. Name depth in metres and the sample column.')
    arrays = {k: [] for k in indices}
    for n, row in enumerate(rows, 1):
        if n > MAX_ROWS:
            raise ValueError(f'Cast exceeds {MAX_ROWS} rows. Split the file.')
        for k, i in indices.items():
            try:
                arrays[k].append(number(row[i], bad))
            except (ValueError, IndexError) as exc:
                raise ValueError(f'Data row {n}, {k}: check the value and columns. {exc}') from exc
    if not arrays['depth_m']:
        raise ValueError('No cast samples. Finish the export and drop the completed file.')
    return arrays


def set_index(indices, key, i):
    if key in indices or i in indices.values():
        raise ValueError(f'Duplicate column for {key}. Supply an unambiguous column mapping.')
    indices[key] = i


def load_mapping(path):
    data = read_bytes(path, 65536)
    try:
        spec = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise ValueError(f'{path}: check the YAML column mapping.') from exc
    if not isinstance(spec, dict) or not isinstance(spec.get('columns'), dict):
        raise ValueError(f'Mapping is {spec!r}. Use columns: {{depth_m: [Depth], sv_ms: [SV]}}.')
    if 'depth_m' not in spec['columns']:
        raise ValueError(f'{path}: columns {list(spec["columns"])} must include depth_m, '
                         'e.g. depth_m: [Depth (m)].')
    for key, aliases in spec['columns'].items():
        if key not in ARRAYS:
            raise ValueError(f'Unknown column role {key!r}. Choose from {ARRAYS}, e.g. sv_ms.')
        if not isinstance(aliases, list) or not aliases or not all(
                isinstance(a, str) and a.strip() for a in aliases):
            raise ValueError(f'Mapping for {key} is {aliases!r}. List header names, '
                             f'e.g. {key}: [column_name].')
    delim = spec.get('delimiter', ',')
    if not isinstance(delim, str) or len(delim) != 1 or delim in ('\n', '\r'):
        raise ValueError(f'delimiter is {delim!r}. Use one character, for example a comma.')
    return spec, identity(path, data)


def mapped_csv(lines, spec):
    delim = spec.get('delimiter', ',')
    meta = {}
    start = 0
    for start, line in enumerate(lines):
        if not line.startswith('#'):
            break
        key, _, value = line[1:].partition(':')
        meta[key.strip().lower()] = value.strip()
    rows = csv.reader(lines[start:], delimiter=delim, strict=True)
    headers = [h.strip().casefold() for h in next(rows, [])]
    indices = {}
    for key, aliases in spec['columns'].items():
        for i, header in enumerate(headers):
            if header in {a.casefold() for a in aliases}:
                set_index(indices, key, i)
    return column_data(indices, rows), meta


def cnv(lines):
    columns = {'depsm': 'depth_m', 'svcm': 'sv_ms', 'svdm': 'sv_ms',
               't090c': 't_c', 'sal00': 's_psu', 'prdm': 'pressure_dbar'}
    indices, meta = {}, {}
    bad = None
    for n, line in enumerate(lines):
        if line.strip() == '*END*':
            break
        match = re.match(r'#\s*name\s+(\d+)\s*=\s*([^: ]+)', line, re.I)
        if match:
            key = columns.get(match[2].lower())
            if key:
                set_index(indices, key, int(match[1]))
        key, _, value = line.lstrip('*# ').partition('=')
        key, value = key.strip().lower(), value.strip()
        if key == 'bad_flag':
            bad = number(value)
        elif key in ('nmea latitude', 'nmea longitude', 'nmea utc (time)'):
            meta[{'nmea latitude': 'lat', 'nmea longitude': 'lon',
                  'nmea utc (time)': 'time'}[key]] = value
    else:
        raise ValueError('Sea-Bird header has no *END*. Drop the complete .cnv file.')
    return column_data(indices, (line.split() for line in lines[n+1:]), bad), meta


def edf_key(label):
    label = label.strip().lower()
    if re.fullmatch(r'depth(?:\s*\(m(?:eters)?\))?', label):
        return 'depth_m'
    if re.fullmatch(r'temp(?:erature)?(?:\s*\((?:deg(?:rees)?\s*)?c(?:elsius)?\))?', label):
        return 't_c'
    return None


def edf(lines):
    indices, header = {}, {}
    for n, line in enumerate(lines):
        key, colon, val = line.partition(':')
        if colon:
            key = key.lstrip('// ').strip().lower()
            field = re.fullmatch(r'field\s*(\d+)', key)
            if field and edf_key(val):
                index = int(field[1])-1
                if index < 0:
                    raise ValueError('EDF fields are numbered starting at 1.')
                set_index(indices, edf_key(val), index)
            header[key] = val.strip()
        elif re.match(r'^[+\-.\d]', line):
            break
        else:
            labels = re.split(r'\t+|,|\s{2,}', line)
            if len(labels) == 1:
                labels = re.findall(r'[A-Za-z]+(?:\s*\([^)]*\))?', line)
            named = {}
            for i, label in enumerate(labels):
                if edf_key(label):
                    set_index(named, edf_key(label), i)
            if {'depth_m', 't_c'} <= named.keys():
                if indices and named != indices:
                    raise ValueError('Conflicting EDF field order. Check the text export.')
                indices = named
    else:
        raise ValueError('No EDF samples. Drop the complete ASCII export.')
    if set(indices) != {'depth_m', 't_c'}:
        raise ValueError('Name the EDF depth (m) and temperature (C) columns in the header.')
    date = header.get('date of launch', header.get('date'))
    clock = header.get('time of launch', header.get('time'))
    meta = dict(lat=header.get('latitude'), lon=header.get('longitude'),
                probe=header.get('probe type'), time=f'{date} {clock}' if date and clock else None)
    return column_data(indices, (re.split(r'[,\s]+', line) for line in lines[n:])), meta


def reference(path, key):
    data = read_bytes(path)
    lines = text_lines(data)
    arrays, _ = mapped_csv(lines, dict(columns={k: [k] for k in ('depth_m', key)}))
    depths, vals = arrays['depth_m'], arrays.get(key)
    if (None in depths or not ordered(depths) or depths[0] < 0 or vals is None or
            any(v is None or not (1300 <= v <= 2000 if key == 'sv_ms' else 0 <= v <= 50)
                for v in vals)):
        raise ValueError(f'{path}: supply increasing depths and complete, plausible {key} values.')
    return depths, vals, identity(path, data)


def ingest(path, *, mapping=None, surface_salinity=None, salinity_profile=None):
    path = Path(path)
    data = read_bytes(path)
    lines = text_lines(data)
    args = {'path': str(path.absolute())}
    event = dict(step='ingest', args=args, input=identity(path, data), version=1)
    fmt = path.suffix.lower().lstrip('.')
    if fmt == 'cnv':
        arrays, meta = cnv(lines)
    elif fmt == 'edf':
        arrays, meta = edf(lines)
    else:
        location = mapping or DEFAULT_MAP
        spec, event['mapping'] = load_mapping(location)
        arrays, meta = mapped_csv(lines, spec)
        if mapping:
            args['mapping'] = str(Path(mapping).absolute())
        fmt = 'csv'
    reasons = []
    source = dict(id=path.stem, type=fmt)
    if meta.get('probe'):
        source['probe'] = meta['probe']
    if fmt == 'edf':
        if surface_salinity is not None and salinity_profile is not None:
            raise ValueError('Choose one salinity source: surface_salinity or salinity_profile.')
        if salinity_profile is not None:
            depths, vals, info = reference(salinity_profile, 's_psu')
            arrays['s_psu'] = [interpolate(z, depths, vals)
                               if z is not None and depths[0] <= z <= depths[-1] else None
                               for z in arrays['depth_m']]
            args['salinity_profile'] = info['path']
            event['salinity_reference'] = info
        elif surface_salinity is not None:
            sal = number(surface_salinity)
            if sal is None or not 0 <= sal <= 50:
                raise ValueError(f'surface_salinity is {sal!r}. Use salinity in PSU, e.g. 35.')
            args['surface_salinity'] = sal
            arrays['s_psu'] = [sal]*len(arrays['depth_m'])
        if 's_psu' in arrays:
            try:
                from logger.utils.met_formulas import sound_speed_mackenzie
            except ModuleNotFoundError as exc:
                if exc.name != 'logger.utils.met_formulas':
                    raise
            else:
                arrays['sv_ms'] = [sound_speed_mackenzie(t, s, z) if None not in (t, s, z)
                                   else None for t, s, z in zip(arrays['t_c'], arrays['s_psu'],
                                                                arrays['depth_m'])]
                event['conversion'] = 'Mackenzie (1981), logger.utils.met_formulas'
                converted = json.dumps(arrays['sv_ms'], allow_nan=False).encode()
                event['converted_sv_sha256'] = digest(converted)
    if 'sv_ms' not in arrays:
        arrays['sv_ms'] = [None]*len(arrays['depth_m'])
    if all(v is None for v in arrays['sv_ms']):
        reasons.append('needs SV conversion')
    zmax = max((z for z in arrays['depth_m'] if z is not None and 0 <= z <= BOTTOM), default=None)
    return Profile(source, instant(meta.get('time')), coordinate(meta.get('lat'), 'latitude'),
                   coordinate(meta.get('lon'), 'longitude'), **arrays, reasons=reasons,
                   quality=0. if reasons else 1., max_cast_depth_m=zmax, history=[event])
