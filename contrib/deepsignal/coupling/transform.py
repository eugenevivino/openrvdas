"""Apply frozen ship-contamination evidence to copies of live records."""

from collections import OrderedDict
import copy
import json
import math

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord

from . import prep, stats


class ShipCouplingTransform(Transform):
    """Add QC annotations using the current regime, heading sector and speed band."""

    def __init__(self, atlas_path, fields=None, min_verdict='ship_artifact',
                 suspect_threshold=.3, fail_threshold=.7):
        super().__init__()
        with open(atlas_path, encoding='utf-8') as stream:
            atlas = json.load(stream)
        self.config = atlas.get('parameters', {})
        self.fields = list(atlas.get('polar', {})) if fields is None else fields
        self.thresholds = suspect_threshold, fail_threshold
        self.state = {}
        self.speed_change = None
        self.latest = None
        self.history = OrderedDict()
        self.lookback = 0
        self.clocks = {}
        self.spreads = atlas.get('healthy_spread', {})
        self.evidence = {}
        for h in sorted(atlas.get('hypotheses', []), key=lambda h: -abs(h.get('effect') or 0)):
            if (h.get('status') == 'confirmed' and
                    h.get('invariance') == min_verdict == 'ship_artifact'):
                lag = h.get('lag', 0)
                self.evidence.setdefault(h['field'], {}).setdefault(
                    h.get('regime'), (h['ship_variable'], lag))
                self.lookback = max(self.lookback, -lag)
        self.cells = {(field, row.get('regime'), row['sector'], row['speed_band']): row
                      for field, table in atlas.get('polar', {}).items() for row in table}

    def _state(self, fields, timestamp):
        updates = {}
        for name in ('relative_heading', 'heading', 'direction', 'sog', 'heading_rate', 'regime'):
            source = self.config.get(name + '_field', name)
            if source in fields:
                updates[name] = fields[source]
        for name in ('heading', 'sog'):
            if name not in updates:
                continue
            previous = self.clocks.get(name)
            if timestamp is not None and timestamp == previous:
                continue
            before, after = self.state.get(name), updates[name]
            rate = None
            if (timestamp is not None and previous is not None and
                    stats.finite(before) and stats.finite(after)):
                dt = timestamp - previous
                if name == 'sog':
                    rate = abs(after - before) * 60 / dt
                else:
                    rate = abs(prep.angle_difference(after, before)) / dt
            if name == 'sog':
                self.speed_change = rate
            elif timestamp is None or self.clocks.get('heading_rate') != timestamp:
                updates.setdefault('heading_rate', rate)

        self.state.update(updates)
        self.clocks.update(dict.fromkeys(updates, timestamp))
        if updates.keys() & {'relative_heading', 'heading', 'direction'}:
            direct = self.state.get('relative_heading')
            same_time = timestamp is not None and self.clocks.get('relative_heading') == timestamp
            if ('relative_heading' not in updates and not same_time and
                    'direction' in self.state and 'heading' in self.state):
                direct = None
            self.state['relative_heading'] = prep.relative_angle(
                direct, self.state.get('direction'), self.state.get('heading'))
        explicit_regime = timestamp is not None and self.clocks.get('regime') == timestamp
        if ('regime' not in updates and not explicit_regime and
                updates.keys() & {'sog', 'heading', 'heading_rate'}):
            self.state['regime'] = prep.regime(self.state.get('sog'),
                                               self.state.get('heading_rate'),
                                               self.speed_change, self.config)

    def _calibration(self, field, timestamp):
        current = self.state.get('regime')
        evidence = self.evidence[field].get(current)
        if not evidence:
            return None
        variable, lag = evidence
        state = self.state
        if lag:
            if timestamp is None or lag > 0:
                return None
            index = math.floor(timestamp / self.config.get('bin_seconds', 10))
            state = self.history.get(index + lag, {})
            if state.get('regime') != current:
                return None
        cell = prep.polar_cell(state, self.config)
        entry = self.cells.get((field, current, *cell)) if cell else None
        if (entry and entry.get('lag', 0) == lag and
                entry.get('ship_variable', variable) == variable):
            return variable, current, cell, entry
        return None

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        result = copy.deepcopy(record)
        if isinstance(result, DASRecord):
            fields, timestamp = result.fields, result.timestamp
        else:
            fields, timestamp = result.get('fields', result), result.get('timestamp')
        if not isinstance(fields, dict):
            return result
        try:
            timestamp = prep.timestamp(timestamp) if timestamp is not None else None
        except (ValueError, OverflowError):
            timestamp = None
        on_time = timestamp is None or self.latest is None or timestamp >= self.latest
        if on_time:
            self._state(fields, timestamp)
        if on_time and timestamp is not None:
            self.latest = timestamp
            if self.lookback:
                index = math.floor(timestamp / self.config.get('bin_seconds', 10))
                while self.history and next(iter(self.history)) < index - self.lookback:
                    self.history.popitem(last=False)
                self.history[index] = self.state.copy()
        for field in self.fields:
            if field not in fields or field not in self.evidence:
                continue
            # An incoming annotation set owns its meaning, including a prior missing/bad QC.
            if any(field + suffix in fields for suffix in ('_SHIP', '_SHIP_why', '_SHIP_QC')):
                continue
            if not stats.finite(fields[field]):
                fields[field + '_SHIP_QC'] = 9
                continue
            calibration = self._calibration(field, timestamp) if on_time else None
            spread = self.spreads.get(field)
            if not calibration or not stats.finite(spread) or spread <= 0:
                fields[field + '_SHIP_QC'] = 2
                continue
            evidence, regime, cell, entry = calibration
            if not stats.finite(entry.get('median')):
                fields[field + '_SHIP_QC'] = 2
                continue
            score = min(1.0, abs(entry['median']) / spread)
            fields[field + '_SHIP'] = score
            fields[field + '_SHIP_why'] = (f'The atlas replicated {evidence} contamination in '
                                           f'{regime}, sector {cell[0]}, speed band {cell[1]}.')
            fields[field + '_SHIP_QC'] = (4 if score >= self.thresholds[1] else
                                          3 if score >= self.thresholds[0] else 1)
        return result
