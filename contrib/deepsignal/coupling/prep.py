"""Binning, residualization, and ship-state preparation."""

import math
import statistics


def rolling_median(values, window):
    radius = max(0, window // 2)
    return [statistics.median([v for v in values[max(0, i - radius):i + radius + 1]
                               if v is not None]) for i in range(len(values))]


def prepare(rows, config):
    """Return copied rows augmented with configured ship variables and residuals."""
    output = [dict(row) for row in rows]
    heading = config.get('heading_field', 'heading')
    direction = config.get('direction_field', 'direction')
    sog = config.get('sog_field', 'sog')
    for index, row in enumerate(output):
        if heading in row and direction in row:
            angle = math.radians(row[direction] - row[heading])
            row['relative_heading_sin'] = math.sin(angle)
            row['relative_heading_cos'] = math.cos(angle)
            row['relative_heading'] = math.degrees(angle) % 360
        rate = abs(row.get(heading, 0) - output[index - 1].get(heading, 0)) if index else 0
        row['heading_rate'] = rate / config.get('bin_seconds', 10)
        speed = row.get(sog, 0)
        change = abs(speed - output[index - 1].get(sog, speed)) * 6 if index else 0
        row['regime'] = ('station' if speed < config.get('station_knots', 1) else
                         'maneuver' if rate > config.get('turn_deg_s', 2) or
                         change > config.get('sog_change_kn_min', 1) else 'transit')
    window = max(1, int(config.get('median_minutes', 30) * 60 /
                        config.get('bin_seconds', 10)))
    for field in config.get('fields', []):
        values = [row.get(field) for row in output]
        medians = rolling_median(values, window)
        for row, median in zip(output, medians):
            if row.get(field) is not None:
                row[field + '_residual'] = row[field] - median
    return output
