"""OpenRVDAS transform that appends host and stream time-health fields."""

import datetime
import math
import statistics
from collections import deque

from logger.transforms.transform import Transform
from logger.utils import formats

from contrib.deepsignal.time_health.host import HostTimeHealth


UTC = datetime.timezone.utc


def _percentile(values, percentile):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class TimeHealthTransform(Transform):
    """Add non-destructive time-health observations to incoming records."""

    def __init__(self, streams, stream_field='stream', window=120, jump_s=10,
                 host_reader=None):
        record_format = getattr(formats, 'DASRecord', formats.Python_Record)
        super().__init__(input_format=record_format, output_format=record_format)
        if not isinstance(streams, dict) or not streams:
            raise ValueError("setting 'streams' saw %r; expected a non-empty mapping, "
                             "for example {'gps': {'source_time_field': 'utc'}}" % streams)
        if not isinstance(window, int) or isinstance(window, bool) or window < 1:
            raise ValueError("setting 'window' saw %r; expected a positive integer, for example 120"
                             % window)
        if not isinstance(jump_s, (int, float)) or isinstance(jump_s, bool) or jump_s <= 0:
            raise ValueError("setting 'jump_s' saw %r; expected a positive number, for example 10"
                             % jump_s)
        self.streams = streams
        for name, config in streams.items():
            if not isinstance(config, dict):
                raise ValueError("setting 'streams.%s' saw %r; expected a mapping, for example "
                                 "{'source_time_field': 'utc'}" % (name, config))
            source = config.get('source', 'embedded' if config.get('source_time_field') else 'host')
            if source not in ('host', 'embedded'):
                raise ValueError("setting 'streams.%s.source' saw %r; expected 'host' or "
                                 "'embedded', for example 'embedded'" % (name, source))
            if source == 'embedded' and not config.get('source_time_field'):
                raise ValueError("setting 'streams.%s.source_time_field' saw %r; expected a field "
                                 "name, for example 'utc'" %
                                 (name, config.get('source_time_field')))
        self.stream_field = stream_field
        self.window = window
        self.jump_s = float(jump_s)
        self.host_reader = host_reader or HostTimeHealth().read
        self.state = {name: {'latencies': deque(maxlen=window), 'previous': None,
                             'repeats': 0, 'backward': 0, 'jumps': 0,
                             'backward_times': deque()}
                      for name in streams}
        self.latest_sources = {}
        self.skews = {}

    @staticmethod
    def _parts(record):
        if isinstance(record, dict):
            return record.get('timestamp'), record.get('fields')
        return getattr(record, 'timestamp', None), getattr(record, 'fields', None)

    @staticmethod
    def _epoch(value, arrival):
        if isinstance(value, datetime.datetime):
            value = value.replace(tzinfo=value.tzinfo or UTC)
            return value.timestamp()
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if len(text) >= 6 and text[:6].isdigit() and ('T' not in text):
                hour, minute = int(text[:2]), int(text[2:4])
                second = int(text[4:6]) + (float('0.' + text.split('.', 1)[1])
                                           if '.' in text else 0)
                date = datetime.datetime.fromtimestamp(arrival, UTC).date()
                return datetime.datetime(date.year, date.month, date.day, hour, minute,
                                         tzinfo=UTC).timestamp() + second
            parsed = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=parsed.tzinfo or UTC).timestamp()
        raise ValueError('unsupported source timestamp')

    def _host_fields(self, fields, host):
        for key, value in host.items():
            fields.setdefault('ds_time:host:' + key, value)

    def _confidence(self, host, state):
        if not host.get('synced'):
            return 'bad'
        offset = host.get('offset_s')
        if offset is not None and abs(offset) > 0.5:
            return 'bad'
        p95 = _percentile(state['latencies'], 0.95) if state['latencies'] else 0
        if p95 > 2 or state['backward_times']:
            return 'degraded'
        return 'good'

    def _one(self, record):
        arrival, fields = self._parts(record)
        if not isinstance(fields, dict):
            return record
        host = self.host_reader()
        self._host_fields(fields, host)
        name = fields.get(self.stream_field)
        if name not in self.streams:
            return record
        config = self.streams[name]
        default_source = 'embedded' if config.get('source_time_field') else 'host'
        source_kind = config.get('source', default_source)
        state = self.state[name]
        source = float(arrival)
        if source_kind == 'embedded':
            value = fields.get(config['source_time_field'])
            if value is None:
                fields.setdefault('ds_time:%s:status' % name, 'missing source timestamp')
                fields.setdefault('ds_time:%s:timestamp_source' % name, source_kind)
                fields.setdefault('ds_time:%s:confidence' % name, 'bad')
                return record
            try:
                source = self._epoch(value, float(arrival))
            except (TypeError, ValueError, OverflowError):
                fields.setdefault('ds_time:%s:status' % name, 'invalid source timestamp')
                fields.setdefault('ds_time:%s:timestamp_source' % name, source_kind)
                fields.setdefault('ds_time:%s:confidence' % name, 'bad')
                return record
            state['latencies'].append(float(arrival) - source)
            self.latest_sources[name] = source
        previous = state['previous']
        if previous is not None:
            delta = source - previous
            if delta == 0:
                state['repeats'] += 1
            elif delta < 0:
                state['backward'] += 1
                state['backward_times'].append(float(arrival))
            if abs(delta) > self.jump_s:
                state['jumps'] += 1
        state['previous'] = source
        while state['backward_times'] and state['backward_times'][0] < float(arrival) - 600:
            state['backward_times'].popleft()
        prefix = 'ds_time:%s:' % name
        fields.setdefault(prefix + 'timestamp_source', source_kind)
        fields.setdefault(
            prefix + 'latency_median_s',
            statistics.median(state['latencies']) if state['latencies'] else 0)
        fields.setdefault(
            prefix + 'latency_p95_s',
            _percentile(state['latencies'], 0.95) if state['latencies'] else 0)
        fields.setdefault(prefix + 'backward_steps', state['backward'])
        fields.setdefault(prefix + 'repeats', state['repeats'])
        fields.setdefault(prefix + 'jumps', state['jumps'])
        fields.setdefault(prefix + 'confidence', self._confidence(host, state))
        self._add_skew(name, fields)
        return record

    def _add_skew(self, name, fields):
        for other, other_time in self.latest_sources.items():
            if other == name:
                continue
            pair = tuple(sorted((name, other)))
            difference = (self.latest_sources[pair[0]] - self.latest_sources[pair[1]])
            values = self.skews.setdefault(pair, deque(maxlen=self.window))
            values.append(difference)
            fields.setdefault('ds_time:%s:%s:skew_median_s' % pair, statistics.median(values))

    def transform(self, record):
        """Append observations, preserving record identity and existing values."""
        if record is None:
            return None
        if isinstance(record, list):
            for item in record:
                self._one(item)
            return record
        return self._one(record)
