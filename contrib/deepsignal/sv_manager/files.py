"""Local, immutable export pairs. The JSON receipt is published last."""
import json
import math
import os
import re
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from string import Template

from .ingest import MAX_BYTES, digest, ingest, read_bytes
from .profile import BOTTOM, Profile, clean, extend, ordered, thin


def encoded(obj):
    return json.dumps(obj, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()


def validate(p):
    if (not ordered(p.depth_m) or p.depth_m[0] != 0 or p.depth_m[-1] != BOTTOM
            or p.max_cast_depth_m not in p.depth_m):
        raise ValueError('Export needs a surface sample, cast endpoint and increasing depths '
                         'to 12000 m. Review, fill the surface and extend the cast first.')
    if (len(p.sv_ms) != len(p.depth_m) or
            any(v is None or not math.isfinite(v) or v <= 0 for v in p.sv_ms)):
        raise ValueError('Missing or invalid sound speed. Review conversion and cleaning.')
    if not ordered([float(f'{z:.2f}') for z in p.depth_m]):
        raise ValueError('Depths coincide at export precision (0.01 m). Review the bin widths.')


def render(p, fmt, template):
    utc = datetime.fromtimestamp(p.time, timezone.utc) if p.time is not None else None
    context = dict(cast_id=p.source['id'], count=len(p.depth_m),
                   utc=utc.isoformat().replace('+00:00', 'Z') if utc else '',
                   lat=p.lat if p.lat is not None else '', lon=p.lon if p.lon is not None else '')
    info = {}
    layout = '$rows\n'
    row = '$depth_m $sv_ms'
    if fmt == 'asvp':
        if utc is None or p.lat is None or p.lon is None:
            raise ValueError('SIS needs the UTC cast time, latitude and longitude. Check header.')
        layout = (f'( SoundVelocity 1.0 0 {utc:%Y%m%d%H%M} {p.lat:.6f} {p.lon:.6f}'
                  f' -1 0 0 DeepSignal {len(p.depth_m)} )\n$rows\n')
    elif fmt == 'csv':
        layout = 'depth_m,sv_ms\n$rows\n'
        row = '$depth_m,$sv_ms'
    elif fmt == 'template' and template:
        data = read_bytes(template, 16384)
        layout = data.decode('utf-8-sig')
        if layout.startswith('@row '):
            row, _, layout = layout[5:].partition('\n')
        info['template_sha256'] = digest(data)
    else:
        raise ValueError(f'fmt is {fmt!r}. Use asvp, csv, or template with a template file.')
    body = Template(layout)
    row = Template(row)
    row_refs = [m for m in body.pattern.finditer(layout)
                if (m['named'] or m['braced']) == 'rows']
    if len(row_refs) != 1 or not {'depth_m', 'sv_ms'} <= set(row.get_identifiers()):
        raise ValueError('Template needs one $rows and a row with $depth_m and $sv_ms.')
    size, rows = len(layout), []
    try:
        for z, v in zip(p.depth_m, p.sv_ms):
            line = row.substitute(depth_m=f'{z:.2f}', sv_ms=f'{v:.3f}')
            size += len(line.encode()) + 1
            if size > MAX_BYTES:
                raise ValueError('Export exceeds 8 MiB. Thin the profile or shorten the template.')
            rows.append(line)
        return body.substitute(context, rows='\n'.join(rows)).encode(), info
    except KeyError as exc:
        raise ValueError(f'Unknown template field {exc}. Check placeholders.') from exc


def publish(path, data):
    # link(2) never replaces a cast, another worker's output, or a symlink.
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.svm-') as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        try:
            os.link(tmp.name, path)
        except FileExistsError:
            if read_bytes(path, len(data)) != data:
                raise ValueError(f'{path.name} already exists with different contents. '
                                 'Inspect the export directory.')


def export(profile, fmt, out_dir, *, template=None):
    folder = Path(out_dir)
    if not folder.is_dir():
        raise ValueError(f'out_dir is {str(folder)!r}. Choose an existing local export folder.')
    name = profile.source['id']
    if not isinstance(name, str) or not re.fullmatch(r'[\w -][\w. -]{0,99}', name):
        raise ValueError(f'Unsafe cast ID {name!r}. Use a short filename without path separators.')
    validate(profile)
    if not profile.history or profile.history[-1]['step'] != 'thin':
        profile = thin(profile)
    data, info = render(profile, fmt, template)
    snapshot = asdict(profile)
    receipt = dict(version=1, profile=snapshot, profile_sha256=digest(encoded(snapshot)),
                   output_sha256=digest(data), format=fmt, **info)
    manifest = encoded(receipt)
    if len(manifest) > MAX_BYTES:
        raise ValueError('Sidecar exceeds 8 MiB. Thin the profile before exporting.')
    path = folder / f'{name}-{digest(manifest)[:16]}.{fmt if fmt != "template" else "txt"}'
    side = Path(str(path) + '.json')
    publish(path, data)
    publish(side, manifest)
    # A repeated, identical export selects this profile again.
    os.utime(side, follow_symlinks=False)
    return path


def load_export(sidecar):
    side = Path(sidecar)
    raw = read_bytes(side)
    doc = json.loads(raw)
    if (side.suffix != '.json' or not isinstance(doc, dict) or doc.get('version') != 1
            or side.with_suffix('').stem.rpartition('-')[2] != digest(raw)[:16]
            or doc.get('profile_sha256') != digest(encoded(doc.get('profile')))
            or doc.get('output_sha256') != digest(read_bytes(side.with_suffix('')))):
        raise ValueError(f'{side.name}: profile or export hash mismatch. Review and re-export.')
    p = Profile(**doc['profile'])
    validate(p)
    return p


def replay(history):
    """Re-run a trusted receipt against its original source and configuration files."""
    p = None
    for n, entry in enumerate(history):
        step = entry['step']
        if n == 0 and step == 'ingest':
            p = ingest(**entry['args'])
        elif p is not None and step in ('clean', 'extend', 'thin'):
            p = {'clean': clean, 'extend': extend, 'thin': thin}[step](p, **entry['args'])
        else:
            raise ValueError(f'Unexpected replay step {step!r}. Check the receipt.')
        if p.history[-1] != entry:
            raise ValueError(f'{step} differs from the receipt. Check hashes and parameters.')
    if p is None:
        raise ValueError('Receipt has no cast history.')
    return p
