"""Apply frozen ship-contamination evidence to copies of live records."""

import copy
import json

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
        self.clocks = {}
        self.spreads = atlas.get('healthy_spread', {})
        self.evidence = {}
        for h in atlas.get('hypotheses', []):
            if (h.get('status') == 'confirmed' and
                    h.get('invariance') == min_verdict == 'ship_artifact'):
                self.evidence.setdefault(h['field'], {})[h.get('regime')] = h['ship_variable']
        self.cells = {(field, row.get('regime'), row['sector'], row['speed_band']): row
                      for field, table in atlas.get('polar', {}).items() for row in table}

    def _state(self, fields, timestamp):
        updates = {}
        for name in ('relative_heading', 'heading', 'direction', 'sog', 'heading_rate'):
            source = self.config.get(name + '_field', name)
            if source in fields:
                updates[name] = fields[source]
        change = None
        for name in ('heading', 'sog'):
            if name not in updates:
                continue
            before, after = self.state.get(name), updates[name]
            previous = self.clocks.get(name)
            self.clocks[name] = timestamp
            if (stats.finite(previous) and stats.finite(timestamp) and timestamp > previous and
                    stats.finite(before) and stats.finite(after)):
                dt = timestamp - previous
                if name == 'sog':
                    change = abs(after - before) * 60 / dt
                else:
                    rate = abs(prep.angle_difference(after, before)) / dt
                    updates.setdefault('heading_rate', rate)
        self.state.update(updates)
        if ('relative_heading' not in updates and ('heading' in updates or 'direction' in updates)
                and 'direction' in self.state):
            a, b = self.state.get('direction'), self.state.get('heading')
            valid = stats.finite(a) and stats.finite(b)
            self.state['relative_heading'] = (a - b) % 360 if valid else None
        if 'regime' in fields:
            self.state['regime'] = fields['regime']
        elif 'sog' in updates or 'heading' in updates or 'heading_rate' in updates:
            self.state['regime'] = prep.regime(
                self.state.get('sog'), self.state.get('heading_rate'), change, self.config)

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
        if isinstance(timestamp, str):
            try:
                timestamp = prep.timestamp(timestamp)
            except (OverflowError, ValueError):
                timestamp = None
        self._state(fields, timestamp)
        for field in self.fields:
            if field not in fields or field not in self.evidence:
                continue
            # An incoming annotation set owns its meaning, including a prior missing/bad QC.
            if any(field + suffix in fields for suffix in ('_SHIP', '_SHIP_why', '_SHIP_QC')):
                continue
            if not stats.finite(fields[field]):
                fields[field + '_SHIP_QC'] = 9
                continue
            regime = self.state.get('regime')
            evidence = self.evidence[field].get(regime)
            cell = prep.polar_cell(self.state, self.config)
            entry = self.cells.get((field, regime, *cell)) if cell else None
            spread = self.spreads.get(field)
            if (not evidence or not entry or not stats.finite(entry.get('median')) or
                    not stats.finite(spread) or spread <= 0):
                fields[field + '_SHIP_QC'] = 2
                continue
            score = min(1.0, abs(entry['median']) / spread)
            fields[field + '_SHIP'] = score
            fields[field + '_SHIP_why'] = (f'The atlas replicated {evidence} contamination in '
                                           f'{regime}, sector {cell[0]}, speed band {cell[1]}.')
            fields[field + '_SHIP_QC'] = (4 if score >= self.thresholds[1] else
                                          3 if score >= self.thresholds[0] else 1)
        return result
