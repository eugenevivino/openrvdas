"""Replay NBP1406 mast weather scenarios through an OpenRVDAS transform."""

import argparse
import csv
import importlib
import json
import math
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path
from statistics import median

from logger.utils.das_record import DASRecord

from . import faults, traps


SAMPLE_ROOT = Path(__file__).resolve().parents[3] / 'test' / 'NBP1406'
FAULTS = {
    fault.__name__: fault for fault in (
        faults.drift, faults.step, faults.lag, faults.hysteresis, faults.clock_jump,
        faults.clock_reset, faults.spikes, faults.flatline, faults.dropout,
    )
}
TRAPS = {'front': traps.front, 'turn': traps.turn}

# Field order and record names from the NBP1406 MastWx device definitions.
MWX_FIELDS = {
    'MET': ('PowerVolt', 'EncRelHumid', 'AirTemp', 'AirRelHumid', 'PAR', 'PSP',
            'PIRThermo', 'PIRCaseTemp', 'PIRDomeTemp', 'Barometer'),
    'PUS': (None, 'PortRelWindDir', 'PortRelWindSpeed', None, 'PortSoundSpeed',
            'PortSonicTemp', 'PortStatus', None),
    'SUS': (None, 'StbdRelWindDir', 'StbdRelWindSpeed', None, 'StbeSoundSpeed',
            'StbdSonicTemp', 'StbdStatus', None),
}


def _sample_files(root):
    for layout in ('mwx1', 'data/mwx1'):
        directory = root / layout
        raw = directory / 'raw'
        files = sorted((raw if raw.is_dir() else directory).glob('NBP1406_mwx1-*'))
        if files:
            return files
    raise FileNotFoundError(f'No NBP1406 mwx1 sample files at {root}/{{mwx1,data/mwx1}}')


def _sample_rows(root, field):
    rows = []
    for path in _sample_files(root):
        with path.open(encoding='utf-8', newline='') as stream:
            for line_number, row in enumerate(csv.reader(stream), 1):
                if not row:
                    continue
                stamp, _, message = row[0].partition(' ')
                names = MWX_FIELDS.get(message, ())
                if field not in {f'Mwx{name}' for name in names if name}:
                    continue
                try:
                    observed = datetime.fromisoformat(stamp).timestamp()
                    fields = {f'Mwx{name}': (int(row[index]) if name.endswith('Status')
                                             else float(row[index])) if row[index] else None
                              for index, name in enumerate(names, 1) if name}
                except (IndexError, ValueError) as exc:
                    raise ValueError(f'Invalid {message} record in {path}:{line_number}') from exc
                rows.append((observed, message, fields))
    if not rows:
        raise ValueError(f'No NBP1406 mwx1 samples for field {field!r}')
    return sorted(rows, key=lambda row: row[0])


def _reference(value):
    module, separator, name = value.partition(':')
    if not (separator and module and name and ':' not in name):
        raise ValueError(f'Expected module:name, got {value!r}')
    return module, name


def _resolve(module, name):
    target = getattr(importlib.import_module(module), name, None)
    if not callable(target):
        raise ValueError(f'{module}:{name} is not callable')
    return target


def _flag_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def score_flags(flags, truth, *, threshold=3, flag_suffix='_QC', truth_samples=None,
                ignored_samples=()):
    """Score (source timestamp, flag) pairs against inclusive injector truth intervals."""
    if not _flag_number(threshold):
        raise ValueError('Flag threshold must be a finite number')

    timestamps = [timestamp for timestamp, _ in flags]
    if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError('Score timestamps must be in source order')
    del flag_suffix  # Verdict semantics do not depend on the field spelling.
    numeric = [_flag_number(flag) for _, flag in flags]
    invalid = sorted({flag for _, flag in flags
                      if isinstance(flag, (int, float)) and not isinstance(flag, bool)
                      and (not math.isfinite(flag) or flag not in (1, 2, 3, 4, 9))},
                     key=str)
    if invalid:
        raise ValueError(f'Invalid QARTOD verdict code(s): {invalid}')
    present = [valid and flag in (1, 3, 4) for (_, flag), valid in zip(flags, numeric)]
    flagged = [valid and flag in (3, 4) and flag >= threshold
               for (_, flag), valid in zip(flags, present)]

    on_fault = [False] * len(flags)
    on_trap = [False] * len(flags)
    events = []
    ignored = set(ignored_samples)
    if any(index < 0 or index >= len(flags) for index in ignored):
        raise ValueError('Ignored sample index is out of range')
    if truth_samples is not None and len(truth_samples) != len(truth):
        raise ValueError('Truth sample selections must match truth intervals')
    fault_events = []
    for truth_index, (start, end, name) in enumerate(truth):
        if not (math.isfinite(start) and math.isfinite(end) and start <= end):
            raise ValueError(f'Invalid truth interval {start!r}, {end!r}')
        first = bisect_left(timestamps, start)
        stop = bisect_right(timestamps, end)
        if first == stop:
            raise ValueError(f'Truth interval {start!r}, {end!r} has no source samples')
        selected = (list(range(first, stop)) if truth_samples is None else
                    list(truth_samples[truth_index]))
        if not selected:
            raise ValueError(f'Truth interval {start!r}, {end!r} has no injected samples')
        if name == 'trap':
            for index in selected:
                on_trap[index] = True
        else:
            for index in selected:
                on_fault[index] = True
            event = {'name': name, 'start': start, 'end': end,
                     'latency_seconds': None}
            events.append(event)
            fault_events.append((event, selected))

    # A verdict is one alarm and can detect at most one truth event.
    available_alarms = {i for i, raised in enumerate(flagged) if raised and i not in ignored}
    for event, selected in fault_events:
        detected = next((i for i in selected if i in available_alarms), None)
        if detected is not None:
            event['latency_seconds'] = timestamps[detected] - event['start']
            available_alarms.remove(detected)

    # Verdict coverage is attributed forward, but fault exposure is continuous.
    durations = [after - before for before, after in zip(timestamps, timestamps[1:])] + [0]
    fault_ranges = [(start, end) for start, end, name in truth if name != 'trap']
    trap_ranges = [(start, end) for start, end, name in truth if name == 'trap']

    def overlap(begin, end, ranges):
        clipped = sorted((max(begin, first), min(end, last)) for first, last in ranges
                         if max(begin, first) < min(end, last))
        total = 0
        for first, last in clipped:
            if first > begin:
                total += last - first
                begin = last
            elif last > begin:
                total += last - begin
                begin = last
        return total

    outside_seconds = sum(
        max(0, seconds - overlap(timestamp, timestamp + seconds, fault_ranges))
        for index, ((timestamp, _), seconds, valid) in
        enumerate(zip(flags, durations, present)) if valid)
    trap_seconds = sum(
        overlap(timestamp, timestamp + seconds, trap_ranges)
        for index, ((timestamp, _), seconds, valid) in
        enumerate(zip(flags, durations, present)) if valid)
    false_flags = sum(raised and not fault and index not in ignored
                      for index, (raised, fault) in enumerate(zip(flagged, on_fault)))
    trap_flags = sum(raised and trap and index not in ignored
                     for index, (raised, trap) in enumerate(zip(flagged, on_trap)))
    false_rate = false_flags * 3600 / outside_seconds if outside_seconds else None

    return {
        'faults': events,
        'missed': sum(event['latency_seconds'] is None for event in events),
        'samples': len(flags),
        'missing_flag_samples': len(flags) - sum(present),
        'outside_fault_seconds': outside_seconds,
        'false_flags': false_flags,
        'false_flags_per_hour': false_rate,
        'false_alarms_per_ship_day': false_rate * 24 if false_rate is not None else None,
        'trap_seconds': trap_seconds,
        'trap_flags': trap_flags,
        'trap_flags_per_hour': trap_flags * 3600 / trap_seconds if trap_seconds else None,
    }


def _inject(scenario, series, rows):
    kinds = [key for key in ('fault', 'trap', 'injector') if key in scenario]
    if len(kinds) != 1:
        raise ValueError('Expected exactly one of fault, trap or injector')
    kind, = kinds
    name = scenario[kind]
    params = dict(scenario.get('params', {}), seed=scenario.get('seed', 0))
    companion_field = scenario.get('companion_field')
    if companion_field:
        if companion_field == scenario['field'] or companion_field not in rows[0][2]:
            raise ValueError('companion_field must be a different field in the same mwx1 message')
        if kind == 'fault' or name == 'turn':
            raise ValueError('companion_field applies to front and plug-in injectors')
        params['companion'] = [(timestamp, fields[companion_field])
                               for timestamp, _, fields in rows]

    if kind == 'injector':
        inject = _resolve(*_reference(name))
    else:
        catalog = FAULTS if kind == 'fault' else TRAPS
        if name not in catalog:
            raise ValueError(f'Unknown {kind} {name!r}')
        inject = catalog[name]

    linked = None
    if inject is traps.front:
        if 'companion' not in params:
            raise ValueError('front requires companion_field')
        (injected, linked), truth = inject(series, **params)
    else:
        injected, truth = inject(series, **params)

    if not truth:
        raise ValueError('Injection produced no truth intervals')
    if len(injected) != len(rows) or (linked is not None and len(linked) != len(rows)):
        raise ValueError('Injection must preserve the number and source order of samples')
    return injected, linked, truth


def run(scenario, detector_module, detector_class, kwargs, *,
        sample_root=SAMPLE_ROOT, flag_suffix='_QC', threshold=3):
    """Replay one scenario in source order and return scores plus injector truth."""
    field = scenario['field']
    rows = _sample_rows(Path(sample_root), field)
    series = [(timestamp, fields[field]) for timestamp, _, fields in rows]
    injected, linked, truth = _inject(scenario, series, rows)
    detector = _resolve(detector_module, detector_class)(**kwargs)

    flags = [[source_time, None] for source_time, _, _ in rows]
    record_sources = {}
    source_key = '__deepsignal_bench_source_index__'
    for i, ((source_time, message, fields), (timestamp, value)) in enumerate(zip(rows, injected)):
        record_fields = dict(fields)
        record_fields[field] = value
        if linked is not None:
            record_fields[scenario['companion_field']] = linked[i][1]
        record = DASRecord(timestamp=timestamp, fields=record_fields, data_id='mwx1',
                           message_type=message)
        record.metadata[source_key] = i
        record_sources[i] = i
        if timestamp == 0:
            record.timestamp = timestamp
        result = detector.transform(record)
        if result is not None:
            result_index = record_sources.get(getattr(result, 'metadata', {}).get(source_key))
            if result_index is None:
                raise ValueError('Detector returned a record that was not supplied by the replay')
            flags[result_index][1] = result.fields.get(field + flag_suffix)

    changed = [original != modified for original, modified in zip(series, injected)]
    truth_samples = []
    claimed_points = set()
    for start, end, _ in truth:
        selected = [index for index, (timestamp, _) in enumerate(series)
                    if start <= timestamp <= end]
        if start == end and len(selected) > 1:
            choices = [index for index in selected
                       if changed[index] and index not in claimed_points]
            choices.extend(index for index in selected if index not in claimed_points
                           and index not in choices)
            selected = choices[:1]
            claimed_points.update(selected)
        truth_samples.append(selected)
    ignored = []
    if scenario.get('fault') in ('clock_jump', 'clock_reset'):
        altered = [index for index, value in enumerate(changed) if value]
        if altered and altered[-1] + 1 < len(rows):
            ignored.append(altered[-1] + 1)
    scores = score_flags([tuple(item) for item in flags], truth, threshold=threshold,
                         flag_suffix=flag_suffix, truth_samples=truth_samples,
                         ignored_samples=ignored)
    return {'field': field, 'flag_field': field + flag_suffix, 'threshold': threshold,
            'truth': truth, **scores}


def _metric(value):
    return 'n/a' if value is None else f'{value:.3f}'


def _summary(results):
    headings = ('Scenario', 'Median latency (s)', 'Missed/total', 'False flags/h',
                'Trap flags', 'Trap flags/h', 'False alarms/ship-day', 'Missing flag samples')
    rows = [headings, ('---',) * len(headings)]
    for name, result in results.items():
        events = result['faults']
        latencies = [e['latency_seconds'] for e in events if e['latency_seconds'] is not None]
        rows.append((
            name.replace('|', '\\|').replace('\n', ' '),
            _metric(median(latencies) if latencies else None),
            f'{result["missed"]}/{len(events)}',
            _metric(result['false_flags_per_hour']),
            str(result['trap_flags']),
            _metric(result['trap_flags_per_hour']),
            _metric(result['false_alarms_per_ship_day']),
            str(result['missing_flag_samples']),
        ))
    return ''.join('| ' + ' | '.join(row) + ' |\n' for row in rows)


def main(argv=None):
    """Run named scenarios from YAML and write results.json and summary.md."""
    import yaml

    class UniqueKeyLoader(yaml.SafeLoader):
        """Safe YAML loader that rejects silently overwritten scenario names."""

        def construct_mapping(self, node, deep=False):
            explicit = set()
            for key_node, _ in node.value:
                if key_node.tag == 'tag:yaml.org,2002:merge':
                    continue
                key = self.construct_object(key_node, deep=deep)
                if key in explicit:
                    raise ValueError(f'Duplicate scenario name {key!r}')
                explicit.add(key)
            self.flatten_mapping(node)
            mapping = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('run', help='replay and score a scenario file')
    command.add_argument('--scenarios', required=True, type=Path)
    command.add_argument('--detector', required=True, metavar='MODULE:CLASS')
    command.add_argument('--kwargs', default='{}', help='JSON object of detector constructor args')
    command.add_argument('--flag-suffix', default='_QC')
    command.add_argument('--threshold', default=3, type=float)
    command.add_argument('--sample-root', default=SAMPLE_ROOT, type=Path)
    command.add_argument('--output-dir', default=Path.cwd(), type=Path)
    args = parser.parse_args(argv)
    try:
        detector_module, detector_class = _reference(args.detector)
        kwargs = json.loads(args.kwargs)
        if not isinstance(kwargs, dict):
            raise ValueError('--kwargs must be a JSON object')
        with args.scenarios.open(encoding='utf-8') as stream:
            scenarios = yaml.load(stream, Loader=UniqueKeyLoader)
        if not isinstance(scenarios, dict) or not scenarios:
            raise ValueError('Expected a nonempty mapping of scenario names to configurations')
        results = {}
        for name, scenario in scenarios.items():
            if not isinstance(name, str) or not isinstance(scenario, dict):
                raise ValueError('Expected a string scenario name and a configuration mapping')
            try:
                results[name] = run(scenario, detector_module, detector_class, kwargs,
                                    sample_root=args.sample_root, flag_suffix=args.flag_suffix,
                                    threshold=args.threshold)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f'Scenario {name!r}: {exc}') from exc
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / 'results.json').write_text(
            json.dumps(results, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        (args.output_dir / 'summary.md').write_text(_summary(results), encoding='utf-8')
    except (ImportError, OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
