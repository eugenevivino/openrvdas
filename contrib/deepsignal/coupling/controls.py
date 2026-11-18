"""Geographic reciprocal-leg and fixed-clock controls for replicated heading effects."""

from collections import Counter
from itertools import groupby
import math
from statistics import median

from . import prep, stats


def iqr(values):
    """Linearly interpolated quartiles, including singleton and constant cells."""
    ordered = sorted(values)

    def quantile(q):
        k = (len(ordered) - 1) * q
        lo = int(k)
        return ordered[lo] + (k - lo) * (ordered[math.ceil(k)] - ordered[lo])

    return quantile(.75) - quantile(.25)


def _km(a, b):
    lat, lon = math.radians(a['latitude']), math.radians(b['longitude'] - a['longitude'])
    other = math.radians(b['latitude'])
    h = math.sin((other - lat) / 2)**2 + math.cos(lat) * math.cos(other) * math.sin(lon / 2)**2
    return 12742 * math.asin(math.sqrt(min(1, h)))


def _legs(rows, field, variable, config):
    segment = []
    for row in rows:
        valid = (row.get('regime') == 'transit' and
                 all(stats.finite(row.get(k)) for k in
                     ('latitude', 'longitude', 'heading', field, variable)))
        valid = valid and -90 <= row['latitude'] <= 90
        if segment and (not valid or row['cruise'] != segment[0]['cruise'] or
                        abs(prep.angle_difference(row['heading'], segment[0]['heading'])) > 30 or
                        _km(segment[0], row) > config['reciprocal_km']):
            if len(segment) >= 2:
                yield segment
            segment = []
        if valid:
            segment.append(row)
    if len(segment) >= 2:
        yield segment


def _votes(rows, field, variable, sign, config):
    legs = []
    for segment in _legs(rows, field, variable, config):
        residuals = [r[field] for r in segment]
        angles = [r['relative_heading'] for r in segment if stats.finite(r.get('relative_heading'))]
        legs.append(dict(cruise=segment[0]['cruise'], relative=prep.angle_mean(angles),
                         latitude=median(r['latitude'] for r in segment),
                         longitude=prep.angle_mean([r['longitude'] for r in segment]),
                         heading=prep.angle_mean([r['heading'] for r in segment]),
                         timestamp=median(r['timestamp'] for r in segment),
                         ship=median(r[variable] for r in segment),
                         residual=median(residuals), spread=iqr(residuals)))
    votes = Counter()
    # Match nearest eligible earlier leg. Each transit segment contributes at most once.
    used = set()
    for j, b in enumerate(legs):
        candidates = []
        for i in range(j - 1, -1, -1):
            a = legs[i]
            if a['cruise'] != b['cruise'] or b['timestamp'] - a['timestamp'] > (
                    config['reciprocal_hours'] * 3600):
                break
            if i in used or abs(prep.angle_difference(a['heading'], b['heading'])) < 150:
                continue
            km = _km(a, b)
            if km <= config['reciprocal_km']:
                candidates.append((km, -i))
        if not candidates:
            continue
        i = -min(candidates)[1]
        used.update([i, j])
        a = legs[i]
        delta = b['residual'] - a['residual']
        noise = max(a['spread'], b['spread'])
        if variable in ('relative_heading_cos', 'relative_heading_sin'):
            relative_reversed = a['ship'] * b['ship'] < 0
        else:
            relative_reversed = (stats.finite(a['relative']) and stats.finite(b['relative']) and
                                 abs(prep.angle_difference(a['relative'], b['relative'])) >= 150)
        if abs(delta) <= noise or (a['residual'] * b['residual'] > 0 and
                                   abs(delta) < min(abs(a['residual']), abs(b['residual']))):
            votes['environmental'] += 1
        elif (relative_reversed and a['residual'] * b['residual'] < 0 and
              delta * (b['ship'] - a['ship']) * sign > 0):
            votes['ship_artifact'] += 1
        else:
            votes['ambiguous'] += 1
    return votes


def _shifted(rows, field, variable, regime, lag, seconds, hours, config):
    # Same cruise and actual time. Never wrap the end of a short cruise to its start.
    x, y, spans = [], [], []
    delay = hours * 3600 - lag * seconds
    for _, track in groupby(rows, key=lambda r: r['cruise']):
        track = list(track)
        ship = {r['timestamp']: r.get(variable) for r in track if r['regime'] == regime}
        start = len(x)
        for r in track:
            x.append(r.get(field) if r['regime'] == regime else None)
            y.append(ship.get(r['timestamp'] - delay))
        spans.append((start, len(x)))
    pairs = stats._pairs(x, y)
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    max_lag = config.get('max_lag')
    size = stats.n_eff(x, y, min(20, len(xs) // 4) if max_lag is None else max_lag, spans)
    if (size is None or size < config['min_n_eff'] or
            min(xs) == max(xs) or min(ys) == max(ys)):
        return None
    return stats.spearman(xs, ys)


def invariance(item, splits, config):
    item['invariance'] = 'cannot_tell'
    item['time_shift'] = {'12h': None, '24h': None}
    item['reciprocal_pairs'] = {}
    variable = item['ship_variable']
    if (item['status'] != 'confirmed' or variable not in
            ('relative_heading', 'relative_heading_sin', 'relative_heading_cos', 'heading')):
        return
    field = item['field'] + '_residual'
    votes = Counter()
    controls = {}
    vanished = True
    for name, rows in splits.items():
        fit = item if name == 'discovery' else item['holdout']
        # Locate the residual on the ship-state clock using the replicated lag convention.
        lag = fit['lag'] * config['bin_seconds']
        values = {(r['cruise'], r['timestamp']): r.get(field) for r in rows
                  if r['regime'] == item['regime']}
        aligned = [dict(r, paired_residual=values.get((r['cruise'], r['timestamp'] - lag)))
                   for r in rows]
        votes.update(_votes(aligned, 'paired_residual', variable, fit['effect'], config))
        controls[name] = {f'{hours}h': _shifted(rows, field, variable, item['regime'], fit['lag'],
                                                config['bin_seconds'], hours, config)
                          for hours in (12, 24)}
        vanished &= all(stats.finite(v) and abs(v) <= config['shift_effect_limit'] and
                        abs(v) < abs(fit['effect']) for v in controls[name].values())
    item['time_shift_by_split'] = controls
    for shift in item['time_shift']:
        values = [result[shift] for result in controls.values()]
        if all(stats.finite(v) for v in values):
            item['time_shift'][shift] = max(values, key=abs)
    item['reciprocal_pairs'] = dict(votes)
    total = sum(votes.values())
    if total < config['min_reciprocal_pairs']:
        return
    if votes['environmental'] / total >= config['reciprocal_agreement']:
        item['invariance'] = 'environmental'
    elif votes['ship_artifact'] / total >= config['reciprocal_agreement'] and vanished:
        item['invariance'] = 'ship_artifact'


def turns(rows, fields, config):
    """One comparison per nonoverlapping steady-speed turn on a cruise clock."""
    events = []
    seconds = config['bin_seconds']
    width = int(300 // seconds)
    if width < 1 or not fields:
        return events
    for _, track in groupby(rows, key=lambda r: r['cruise']):
        track = list(track)
        next_end = width
        for end in range(width, len(track) - width + 1):
            if end < next_end or not stats.finite(track[end].get('heading')):
                continue
            # Take the latest qualifying start so an abrupt turn uses the immediately
            # preceding five minutes, even when the preceding leg was long and straight.
            for start in range(end - 1, max(width - 2, end - width - 1), -1):
                head = track[start].get('heading')
                a, b = track[start].get('sog'), track[start + 1].get('sog')
                if (not all(map(stats.finite, (a, b, head))) or
                        abs(a - b) * 60 / seconds > config['sog_change_kn_min']):
                    break
                if abs(prep.angle_difference(track[end]['heading'], head)) <= 60:
                    continue
                for field in fields:
                    key = field + '_residual'
                    before = [r[key] for r in track[start-width+1:start+1]
                              if stats.finite(r.get(key))]
                    after = [r[key] for r in track[end:end+width] if stats.finite(r.get(key))]
                    if before and after:
                        events.append(dict(field=field, timestamp=track[end]['timestamp'],
                                           cruise=track[end]['cruise'], regime=track[end]['regime'],
                                           cell=prep.polar_cell(track[end], config),
                                           before=median(before), after=median(after)))
                next_end = end + width
                break
    return events
