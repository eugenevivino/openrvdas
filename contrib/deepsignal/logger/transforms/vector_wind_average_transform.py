#!/usr/bin/env python3
"""Average wind as vectors over a time window.

Wind direction is an angle, so its plain arithmetic mean is wrong: winds
from 359 and 1 degrees average to 180, the opposite of the truth. This
transform turns each (speed, direction) pair into a vector, averages the
vectors over a time window, and turns the mean vector back into a speed
and a direction. Winds from 359 and 1 degrees average to 0.

Each sample is weighted by its own speed, so a 20 knot gust from the west
counts for more than a 1 knot puff from the east. That is the standard
vector-mean wind used by meteorological systems. (Core OpenRVDAS's
InterpolationTransform has a 'polar_average' algorithm that averages a
single angle field with every sample weighted equally; use that for
heading or course, and this transform for wind.)

Typical use: compute true wind per sample with core TrueWindsTransform,
then feed PortTrueWindSpeed and PortTrueWindDir here. Relative (apparent)
wind can be averaged the same way, but it is only meaningful while the
ship holds a steady heading, because the frame it is measured in turns
with the ship.

Outputs come out once per `interval` seconds, at timestamps that are
whole multiples of `interval` (for interval 60: on each minute), and each
summarizes the samples in the `window` seconds up to and including that
timestamp. An output is emitted only once a record newer than its
timestamp arrives, so averages lag real time by up to one record.

Missing data is never filled in. A sample is used only when both its
speed and direction are present in the same record and are finite
numbers, with speed not negative. A window with fewer than `min_count`
usable samples produces no values for that wind. When the mean vector
is (close to) zero, the direction is undefined and is left out, while
the speeds are still reported.

Example logger config:
```
  transforms:
  - class: VectorWindAverageTransform
    module: contrib.deepsignal.logger.transforms.vector_wind_average_transform
    kwargs:
      window: 60       # seconds of data in each average
      interval: 60     # seconds between averages (defaults to window)
      min_count: 30    # skip a window with fewer usable samples
      winds:
      - speed_field: PortTrueWindSpeed
        direction_field: PortTrueWindDir
        prefix: Avg1m
        statistics: [speed, direction, max_speed, steadiness]
```
which emits Avg1mPortTrueWindSpeed, Avg1mPortTrueWindDir,
Avg1mPortTrueWindSpeedMax and Avg1mPortTrueWindSpeedSteadiness.

Available statistics, and the default output name for each:
```
  speed              vector mean speed           <prefix><speed_field>
  direction          vector mean direction       <prefix><direction_field>
  scalar_speed       arithmetic mean speed       <prefix><speed_field>Scalar
  max_speed          highest sample in window    <prefix><speed_field>Max
  steadiness         vector / scalar mean speed  <prefix><speed_field>Steadiness
                     (1 = direction never varied, near 0 = it was all over)
  direction_std_dev  Yamartino direction spread  <prefix><direction_field>StdDev
                     (degrees, unweighted; calm samples left out)
  count              usable samples in window    <prefix><speed_field>Count
```
A wind entry may also give `names: {statistic: output_field}` to choose
its own names, and `min_count` to override the transform-wide value.

Directions come out in the same convention they go in (from or to,
true or relative, degrees in [0, 360)). Speeds keep their units.

The transform is written to work with both older (formats-based) and
current (type-hint-based) OpenRVDAS cores.
"""

import bisect
import logging
import math
from typing import Union

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord

# Statistic name -> (which input field the default name builds on, suffix)
STATISTICS = {
    'speed': ('speed_field', ''),
    'direction': ('direction_field', ''),
    'scalar_speed': ('speed_field', 'Scalar'),
    'max_speed': ('speed_field', 'Max'),
    'steadiness': ('speed_field', 'Steadiness'),
    'direction_std_dev': ('direction_field', 'StdDev'),
    'count': ('speed_field', 'Count'),
}
DEFAULT_STATISTICS = ['speed', 'direction']
DEFAULT_PREFIX = 'Avg'

# A mean vector shorter than this fraction of the mean speed is treated as
# zero: rounding alone leaves about 1e-16 when equal winds cancel exactly.
CALM_TOLERANCE = 1e-9


################################################################################
class VectorWindAverageTransform(Transform):
    """Average one or more wind (speed, direction) pairs as vectors over
    a time window. See the module docstring for details and an example.
    """

    def __init__(self, winds, window=60, interval=None, min_count=1,
                 calm_speed=0, data_id=None):
        """
        ```
        winds     A list of dicts, one per wind to average. Each must have
                  speed_field and direction_field, and may have prefix
                  (default 'Avg'), statistics (default [speed, direction]),
                  names and min_count.

        window    Seconds of data in each average. Must be positive.

        interval  Seconds between averages. Defaults to window, which gives
                  back-to-back, non-overlapping averages. A shorter interval
                  gives running averages.

        min_count Fewest usable samples a window must hold to produce a
                  value. Default 1. Set it to most of the samples a full
                  window should hold, so a window that is mostly gap is
                  reported as missing instead of as a thin average.

        calm_speed If the mean vector's speed is at or below this, the
                  direction is left out as undefined. Default 0, meaning
                  only when the vectors cancel completely.

        data_id   If given, set as the data_id of output records.
        ```
        """
        super().__init__()

        if not isinstance(window, (int, float)) or window <= 0:
            raise ValueError(f'VectorWindAverageTransform: window must be a '
                             f'positive number of seconds; got {window!r}')
        if interval is None:
            interval = window
        if not isinstance(interval, (int, float)) or interval <= 0:
            raise ValueError(f'VectorWindAverageTransform: interval must be a '
                             f'positive number of seconds; got {interval!r}')
        if not isinstance(winds, list) or not winds:
            raise ValueError('VectorWindAverageTransform: winds must be a '
                             f'non-empty list of dicts; got {winds!r}')

        self.window = window
        self.interval = interval
        self.calm_speed = calm_speed
        self.data_id = data_id
        self.winds = [self._parse_wind_spec(spec, min_count) for spec in winds]

        # Per wind: sorted list of sample timestamps, and the parallel list
        # of (speed, direction in radians) samples.
        self.sample_times = [[] for _ in self.winds]
        self.samples = [[] for _ in self.winds]

        # Timestamp of the next average to emit; set by the first record.
        self.next_output = None

    ############################
    @staticmethod
    def _parse_wind_spec(spec, default_min_count):
        """Check one entry of 'winds' and fill in its output names."""
        if not isinstance(spec, dict):
            raise ValueError('VectorWindAverageTransform: each wind must be a '
                             f'dict; got {spec!r}')
        allowed = {'speed_field', 'direction_field', 'prefix', 'statistics',
                   'names', 'min_count'}
        unknown = set(spec) - allowed
        if unknown:
            raise ValueError('VectorWindAverageTransform: unknown keys '
                             f'{sorted(unknown)} in wind {spec!r}')
        for key in ('speed_field', 'direction_field'):
            if not isinstance(spec.get(key), str) or not spec.get(key):
                raise ValueError(f'VectorWindAverageTransform: wind must name '
                                 f'its {key}; got {spec!r}')

        prefix = spec.get('prefix', DEFAULT_PREFIX)
        statistics = spec.get('statistics', DEFAULT_STATISTICS)
        names = spec.get('names') or {}
        if not isinstance(statistics, list) or not statistics:
            raise ValueError('VectorWindAverageTransform: statistics must be a '
                             f'non-empty list; got {statistics!r}')
        bad = [s for s in list(statistics) + list(names) if s not in STATISTICS]
        if bad:
            raise ValueError(f'VectorWindAverageTransform: unknown statistics {bad}; '
                             f'choose from {sorted(STATISTICS)}')

        outputs = {}
        for stat in statistics:
            base_key, suffix = STATISTICS[stat]
            outputs[stat] = names.get(stat, prefix + spec[base_key] + suffix)
        if len(set(outputs.values())) != len(outputs):
            raise ValueError('VectorWindAverageTransform: two statistics would '
                             f'write the same output field: {outputs}')

        min_count = spec.get('min_count', default_min_count)
        if not isinstance(min_count, int) or min_count < 1:
            raise ValueError('VectorWindAverageTransform: min_count must be an '
                             f'integer of at least 1; got {min_count!r}')

        return {'speed_field': spec['speed_field'],
                'direction_field': spec['direction_field'],
                'outputs': outputs,
                'min_count': min_count}

    ############################
    def transform(self, record: Union[DASRecord, dict]):
        """Take in one record and return a list of any averages it
        completes, or None if it completes none."""
        if record is None:
            return None
        if isinstance(record, list):
            results = []
            for single in record:
                result = self.transform(single)
                if result:
                    results.extend(result)
            return results or None

        if isinstance(record, DASRecord):
            timestamp, fields = record.timestamp, record.fields
        elif isinstance(record, dict):
            timestamp, fields = record.get('timestamp'), record.get('fields')
        else:
            # Current cores can digest other types (e.g. JSON strings)
            if hasattr(self, 'can_process_record') and not self.can_process_record(record):
                return self.digest_record(record)
            logging.warning('VectorWindAverageTransform: cannot process record '
                            'of type %s: %s', type(record), record)
            return None

        if not _is_number(timestamp):
            logging.warning('VectorWindAverageTransform: record has no usable '
                            'timestamp; ignoring it: %s', record)
            return None

        # Emit every average whose window has closed: we take the arrival
        # of a newer record to mean nothing more is coming for it.
        results = self._emit_through(timestamp, as_das_record=isinstance(record, DASRecord))

        if isinstance(fields, dict):
            self._add_samples(timestamp, fields)
        return results or None

    ############################
    def _add_samples(self, timestamp, fields):
        """Store this record's usable (speed, direction) pairs."""
        if self.next_output is not None and timestamp <= self.next_output - self.window:
            logging.debug('VectorWindAverageTransform: record at %s is too old '
                          'for any window still open; ignoring it', timestamp)
            return
        for i, wind in enumerate(self.winds):
            speed = fields.get(wind['speed_field'])
            direction = fields.get(wind['direction_field'])
            if speed is None and direction is None:
                continue
            if not (_is_number(speed) and _is_number(direction)) or speed < 0:
                logging.debug('VectorWindAverageTransform: skipping unusable '
                              'sample %s=%r, %s=%r at %s', wind['speed_field'],
                              speed, wind['direction_field'], direction, timestamp)
                continue
            pos = bisect.bisect_right(self.sample_times[i], timestamp)
            self.sample_times[i].insert(pos, timestamp)
            self.samples[i].insert(pos, (float(speed), math.radians(direction)))

    ############################
    def _emit_through(self, timestamp, as_das_record):
        """Compute and return the averages for every output time before
        timestamp, and move next_output past them."""
        if self.next_output is None:
            self.next_output = _next_multiple(timestamp, self.interval)
            return []

        results = []
        while self.next_output < timestamp:
            fields = self._averages_at(self.next_output)
            if fields:
                results.append(self._make_record(self.next_output, fields, as_das_record))
            self.next_output += self.interval
            self._discard_older_than(self.next_output - self.window)

            # Jump over a long gap rather than stepping through empty windows
            if not any(self.sample_times):
                self.next_output = max(self.next_output,
                                       _next_multiple(timestamp - self.window, self.interval))
        return results

    ############################
    def _discard_older_than(self, cutoff):
        """Drop samples no window still to come can use (at or before cutoff)."""
        for i in range(len(self.winds)):
            keep = bisect.bisect_right(self.sample_times[i], cutoff)
            if keep:
                del self.sample_times[i][:keep]
                del self.samples[i][:keep]

    ############################
    def _averages_at(self, output_time):
        """Return a dict of output fields for the window ending at output_time."""
        fields = {}
        start = output_time - self.window
        for i, wind in enumerate(self.winds):
            times = self.sample_times[i]
            lo = bisect.bisect_right(times, start)
            hi = bisect.bisect_right(times, output_time)
            window_samples = self.samples[i][lo:hi]
            if len(window_samples) < wind['min_count']:
                continue
            stats = vector_wind_statistics(window_samples, self.calm_speed)
            for stat, output_field in wind['outputs'].items():
                value = stats.get(stat)
                if value is not None:
                    fields[output_field] = value
        return fields

    ############################
    def _make_record(self, timestamp, fields, as_das_record):
        if as_das_record:
            return DASRecord(data_id=self.data_id, timestamp=timestamp, fields=fields)
        result = {'timestamp': timestamp, 'fields': fields}
        if self.data_id:
            result['data_id'] = self.data_id
        return result


################################################################################
def vector_wind_statistics(samples, calm_speed=0):
    """Given a non-empty list of (speed, direction in radians) samples,
    return a dict of the statistics named in STATISTICS. 'direction' and
    'steadiness' are None when undefined (calm)."""
    count = len(samples)
    speeds = [speed for speed, _ in samples]
    # Vector components: u toward east, v toward north (for a 'from'
    # direction both point the opposite way, which cancels on the way back)
    u_mean = sum(speed * math.sin(rad) for speed, rad in samples) / count
    v_mean = sum(speed * math.cos(rad) for speed, rad in samples) / count
    vector_speed = math.hypot(u_mean, v_mean)
    scalar_speed = sum(speeds) / count

    direction = None
    if vector_speed > max(calm_speed, CALM_TOLERANCE * scalar_speed):
        direction = math.degrees(math.atan2(u_mean, v_mean)) % 360
        # A tiny negative angle modulo 360 can round to exactly 360.0
        if direction >= 360:
            direction = 0.0

    return {
        'speed': vector_speed,
        'direction': direction,
        'scalar_speed': scalar_speed,
        'max_speed': max(speeds),
        'steadiness': vector_speed / scalar_speed if scalar_speed > 0 else None,
        'direction_std_dev': _yamartino_std_dev([rad for speed, rad in samples if speed > 0]),
        'count': count,
    }


############################
def _yamartino_std_dev(radian_angles):
    """Standard deviation in degrees of angles (in radians), by the
    Yamartino method, unweighted by speed. None if there are no angles."""
    n = len(radian_angles)
    if not n:
        return None
    sin_mean = sum(math.sin(a) for a in radian_angles) / n
    cos_mean = sum(math.cos(a) for a in radian_angles) / n
    # max() because rounding can take 1 - (length squared) just below zero
    epsilon = math.sqrt(max(0.0, 1 - (sin_mean ** 2 + cos_mean ** 2)))
    return math.degrees(math.asin(epsilon) * (1 + (2 / math.sqrt(3) - 1) * epsilon ** 3))


############################
def _is_number(value):
    """A finite int or float, and not a bool."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


############################
def _next_multiple(timestamp, interval):
    """Smallest whole multiple of interval at or after timestamp."""
    return math.ceil(timestamp / interval) * interval
