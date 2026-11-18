"""Bin observations on the cruise clock and derive offline residuals and ship state."""

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
import math
from statistics import fmean, median

from .stats import finite


def timestamp(value):
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            value = dt
    if isinstance(value, datetime):
        value = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    if not finite(value):
        raise ValueError('Expected a finite timestamp')
    return value


def rolling_median(values, window):
    radius = max(0, window // 2)
    result = []
    for i in range(len(values)):
        local = [v for v in values[max(0, i - radius):i + radius + 1] if finite(v)]
        result.append(median(local) if local else None)
    return result


def angle_difference(a, b):
    return (a - b + 180) % 360 - 180


def normalized_angle(value):
    # Circular averaging and angle subtraction can each add a few ulps at a sector edge.
    return round(value % 360, 12) % 360


def sine_degrees(angle):
    angle = normalized_angle(angle)
    sign = -1 if angle > 180 else 1
    half = angle % 180
    folded = round(min(half, 180 - half), 12)
    return sign * math.sin(math.radians(folded))


def relative_angle(direct, direction, heading):
    if finite(direct):
        return normalized_angle(direct)
    if finite(direction) and finite(heading):
        return normalized_angle(direction - heading)
    return None


def angle_mean(values):
    angles = [math.radians(v) for v in values]
    x, y = sum(map(math.cos, angles)), sum(map(math.sin, angles))
    if math.hypot(x, y) > 1e-12 * len(values):
        return normalized_angle(math.degrees(math.atan2(y, x)))
    return None


def regime(speed, rate, change, config):
    if not finite(speed):
        return None
    if speed < config.get('station_knots', 1):
        return 'station'
    if ((finite(rate) and rate > config.get('turn_deg_s', 2)) or
            (finite(change) and change > config.get('sog_change_kn_min', 1))):
        return 'maneuver'
    return 'transit'


def polar_cell(row, config):
    angle, speed = row.get('relative_heading'), row.get('sog')
    if finite(angle) and finite(speed):
        sector = int(normalized_angle(angle) * config.get('sectors', 12) / 360)
        return sector, bisect_right(config.get('speed_bands', [1, 5, 10]), speed)
    return None


def _grid(indexed, cruise, config):
    seconds = config.get('bin_seconds', 10)
    names = {k: config.get(k + '_field', k) for k in
             ('heading', 'direction', 'sog', 'roll', 'pitch', 'rpm', 'thruster',
              'latitude', 'longitude', 'relative_heading')}
    angles = {names[k] for k in ('heading', 'direction', 'relative_heading', 'longitude')}
    rows = []
    for index in range(min(indexed), max(indexed) + 1):
        row = {'timestamp': index * seconds, 'cruise': cruise}
        samples = indexed.get(index, [])
        numbers = defaultdict(list)
        labels = set()
        for sample in samples:
            for key, value in sample.items():
                if key == 'regime' and value is not None:
                    labels.add(value)
                elif key not in ('timestamp', 'cruise') and finite(value):
                    numbers[key].append(value)
        for key, values in numbers.items():
            row[key] = angle_mean(values) if key in angles else fmean(values)
        for key, name in names.items():
            if name in row:
                row[key] = row[name]
        angle = relative_angle(row.get('relative_heading'), row.get('direction'),
                               row.get('heading'))
        if angle is not None:
            row.update(relative_heading=angle, relative_heading_cos=sine_degrees(angle + 90),
                       relative_heading_sin=sine_degrees(angle))
        previous = rows[-1] if rows else {}
        if finite(row.get('heading')) and finite(previous.get('heading')):
            delta = angle_difference(row['heading'], previous['heading'])
            row['heading_rate'] = abs(delta) / seconds
        change = None
        if finite(row.get('sog')) and finite(previous.get('sog')):
            change = abs(row['sog'] - previous['sog']) * 60 / seconds
        label = regime(row.get('sog'), row.get('heading_rate'), change, config)
        row['regime'] = label if label else next(iter(labels)) if len(labels) == 1 else None
        rows.append(row)

    window = max(1, int(config.get('median_minutes', 30) * 60 / seconds))
    for field in config.get('fields', []):
        values = [row.get(field) for row in rows]
        for row, value, center in zip(rows, values, rolling_median(values, window)):
            row[field + '_residual'] = value - center if finite(value) else None
    return rows


def prepare(rows, config):
    """Untimestamped in-memory series represent one row per successive bin."""
    seconds = config.get('bin_seconds', 10)
    cruises = defaultdict(lambda: defaultdict(list))
    clocked = None
    for i, row in enumerate(rows):
        has_time = 'timestamp' in row
        if clocked is not None and clocked != has_time:
            raise ValueError('Mixed timestamped and untimestamped observations')
        clocked = has_time
        index = math.floor(timestamp(row.get('timestamp', i * seconds)) / seconds)
        cruises[row.get('cruise')][index].append(row)
    bins = sum(max(series) - min(series) + 1 for series in cruises.values())
    limit = config.get('max_grid_bins', 250000)
    if not isinstance(limit, int) or limit < 1 or bins > limit:
        raise ValueError(f'Split requires {bins} bins with max_grid_bins={limit}')
    return [row for cruise, indexed in cruises.items() for row in _grid(indexed, cruise, config)]
