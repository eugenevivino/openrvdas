"""Apply frozen ship-contamination evidence to copies of live records."""

import copy
import json
import math
from typing import Union

try:
    from logger.transforms.transform import Transform
    from logger.utils.das_record import DASRecord
except ModuleNotFoundError as exc:
    if exc.name not in ('logger', 'logger.transforms', 'logger.transforms.transform',
                        'logger.utils', 'logger.utils.das_record'):
        raise
    from openrvdas.logger.transforms.transform import Transform
    from openrvdas.logger.utils.das_record import DASRecord

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
        self.readings = {}
        self.speed_change = None
        self.heading_rate = None
        self.latest = None
        self.history = {}
        self.seconds = self.config.get('bin_seconds', 10)
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

    def _remember(self, updates, timestamp):
        """Accumulate actual observations, including late packets within the lag window."""
        index = math.floor(timestamp / self.seconds)
        if self.latest is None or timestamp > self.latest:
            self.latest = timestamp
            oldest = index - self.lookback - 1
            for key in list(self.history):
                if key < oldest:
                    del self.history[key]
        if updates and index >= math.floor(self.latest / self.seconds) - self.lookback - 1:
            if index not in self.history:
                self.history[index] = prep.ObservationBin()
            self.history[index].add(updates, ('heading', 'direction', 'relative_heading'), 'regime')
        return index

    def _means(self, index):
        observations = self.history.get(index)
        return observations.means() if observations else {}

    def _latest_bin(self, *names):
        times = [self.clocks[name] for name in names if self.clocks.get(name) is not None]
        return math.floor(max(times) / self.seconds) if times else None

    def _update_motion(self, index, updates):
        speed_bin = self._latest_bin('sog')
        heading_bin = self._latest_bin('heading', 'heading_rate')
        # A late observation can change either side of an adjacent-bin difference.
        for key in (index, index + 1):
            if key not in (speed_bin, heading_bin):
                continue
            row = self._means(key)
            if not row and key == index:
                row = updates
            if row:
                rate, change = prep.bin_motion(row, self._means(key-1), self.seconds)
                if key == speed_bin:
                    self.speed_change = change
                if key == heading_bin:
                    self.heading_rate = rate

    def _relative_heading(self, updates, timestamp):
        direct = self.readings.get('relative_heading')
        if 'heading' in self.readings and 'direction' in self.readings:
            if timestamp is None:
                use_derived = 'relative_heading' not in updates
            else:
                derived_bin = self._latest_bin('heading', 'direction')
                direct_bin = self._latest_bin('relative_heading')
                use_derived = derived_bin is not None and (
                    direct_bin is None or derived_bin > direct_bin)
            if use_derived:
                direct = None
        return prep.relative_angle(direct, self.readings.get('direction'),
                                   self.readings.get('heading'))

    def _state(self, fields, timestamp):
        updates = {name: fields[source] for name in prep.STATE_CHANNELS
                   if (source := self.config.get(name + '_field', name)) in fields}
        if timestamp is not None:
            index = self._remember(updates, timestamp)
        if not updates:
            return
        if timestamp is None:
            self.clocks.update(dict.fromkeys(updates))
            if 'heading' in updates or 'heading_rate' in updates:
                self.heading_rate = updates.get('heading_rate')
            if 'sog' in updates:
                self.speed_change = None
        else:
            means = self._means(index)
            # A late packet can improve a bin mean or supply the newest observation
            # of one channel after an unrelated channel advanced.
            updates = {k: means.get(k, v) for k, v in updates.items()
                       if self.clocks.get(k) is None or timestamp >= self.clocks[k]
                       or (means and index == self._latest_bin(k))}
            for name in updates:
                last = self.clocks.get(name)
                self.clocks[name] = timestamp if last is None else max(last, timestamp)
            self._update_motion(index, updates)
        self.readings.update(updates)
        self.state.update(updates)
        self.state['heading_rate'] = self.heading_rate
        if updates.keys() & {'relative_heading', 'heading', 'direction'}:
            self.state['relative_heading'] = self._relative_heading(updates, timestamp)

        measured = prep.regime(self.state.get('sog'), self.heading_rate,
                               self.speed_change, self.config)
        label = self.readings.get('regime')
        if timestamp is None and measured == 'transit' and label == 'maneuver':
            # Without elapsed time a label can supply missing turn evidence.
            measured = label
        self.state['regime'] = measured or label

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
            index = math.floor(timestamp / self.seconds) + lag
            state = self._means(index)
            if not state:
                return None
            state = prep.bin_state(state, self._means(index-1), self.seconds, self.config)
            if state.get('regime') != current:
                return None
        cell = prep.polar_cell(state, self.config)
        entry = self.cells.get((field, current, *cell)) if cell else None
        if (entry and entry.get('lag', 0) == lag and
                entry.get('ship_variable', variable) == variable):
            return variable, current, cell, entry
        return None

    def transform(self, record: Union[DASRecord, dict]):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        if not isinstance(record, (dict, DASRecord)):
            if hasattr(self, 'can_process_record') and not self.can_process_record(record):
                return self.digest_record(record)
            return None
        result = copy.deepcopy(record)
        if isinstance(result, DASRecord):
            fields, timestamp = result.fields, result.timestamp
            timed = True
        else:
            fields, timestamp = result.get('fields', result), result.get('timestamp')
            timed = 'timestamp' in result
        if not isinstance(fields, dict):
            return result
        try:
            timestamp = prep.timestamp(timestamp) if timed else None
        except (ValueError, OverflowError, OSError):
            on_time = False
        else:
            on_time = timestamp is None or self.latest is None or timestamp >= self.latest
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
