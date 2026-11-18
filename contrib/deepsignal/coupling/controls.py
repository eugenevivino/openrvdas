"""Geographic reciprocal-leg and fixed-clock controls for replicated heading effects."""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
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
    return _site_km((a['latitude'], a['longitude']), (b['latitude'], b['longitude']))


def _site_km(a, b):
    lat, lon = math.radians(a[0]), math.radians(b[1] - a[1])
    other = math.radians(b[0])
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


def _site_summary(rows, field, variable):
    residuals = [r[field] for r in rows]
    readings = [r['paired_reading'] for r in rows]
    angles = [r['relative_heading'] for r in rows if stats.finite(r.get('relative_heading'))]
    return dict(relative=prep.angle_mean(angles), ship=median(r[variable] for r in rows),
                residual=median(residuals), spread=iqr(residuals),
                reading=median(readings), reading_spread=iqr(readings),
                background=median(v-r for v, r in zip(readings, residuals)))


def _site_vote(a, b, variable, sign):
    if (not stats.finite(a['relative']) or not stats.finite(b['relative']) or
            abs(prep.angle_difference(a['relative'], b['relative'])) < 150):
        return 'ambiguous'
    if variable in ('relative_heading_cos', 'relative_heading_sin') and a['ship']*b['ship'] >= 0:
        return 'ambiguous'
    delta = b['residual'] - a['residual']
    noise = max(a['spread'], b['spread'])
    raw_delta = b['reading'] - a['reading']
    if abs(raw_delta) <= max(a['reading_spread'], b['reading_spread']):
        return 'environmental'
    if abs(delta) <= noise or (a['residual'] * b['residual'] > 0 and
                               abs(delta) < min(abs(a['residual']), abs(b['residual']))):
        return 'environmental'
    # The reversal must survive using either leg's background for both
    # readings. A change in rolling baseline alone cannot then cast a vote.
    low, high = sorted((a['reading'], b['reading']))
    common_flip = all(low < leg['background'] < high for leg in (a, b))
    if (common_flip and raw_delta * delta > 0 and a['residual'] * b['residual'] < 0 and
            delta * (b['ship'] - a['ship']) * sign > 0):
        return 'ship_artifact'
    return 'ambiguous'


def _matched_sites(a, b, tolerance):
    # Pair closest sites one-to-one. The tighter site tolerance represents
    # position precision at the observation, separate from the leg search radius.
    shared = a.keys() & b.keys()
    pairs = [(site, site) for site in shared]
    # Search only the latitude strip within reach. Keeping just each site's
    # nearest neighbor bounds storage even in a dense cloud of GPS fixes.
    sites = sorted(b.keys() - shared)
    latitudes = [lat for lat, _ in sites]
    margin = math.degrees(tolerance / 6371)
    nearest_a, nearest_b = {}, {}
    for x in a.keys() - shared:
        start = bisect_left(latitudes, x[0] - margin)
        end = bisect_right(latitudes, x[0] + margin)
        for i in range(start, end):
            y = sites[i]
            distance = _site_km(x, y)
            if distance <= tolerance:
                if x not in nearest_b or (distance, y) < nearest_b[x]:
                    nearest_b[x] = distance, y
                if y not in nearest_a or (distance, x) < nearest_a[y]:
                    nearest_a[y] = distance, x
    pairs.extend((x, y) for x, (_, y) in nearest_b.items() if nearest_a[y][1] == x)
    return pairs


def _votes(rows, field, variable, sign, config):
    legs = []
    for segment in _legs(rows, field, variable, config):
        # Condition on where the environmental observation was made, including at nonzero lag.
        sites = defaultdict(list)
        for r in segment:
            if r.get('sample_site') is not None and stats.finite(r.get('paired_reading')):
                sites[r['sample_site']].append(r)
        legs.append(dict(cruise=segment[0]['cruise'],
                         latitude=median(r['latitude'] for r in segment),
                         longitude=prep.angle_mean([r['longitude'] for r in segment]),
                         heading=prep.angle_mean([r['heading'] for r in segment]),
                         timestamp=median(r['timestamp'] for r in segment),
                         sites={k: _site_summary(v, field, variable) for k, v in sites.items()}))
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
        for _, neg_i in sorted(candidates):
            a = legs[-neg_i]
            sites = _matched_sites(a['sites'], b['sites'],
                                   min(config['reciprocal_km'], config['reciprocal_site_m']/1000))
            if sites:
                used.update([-neg_i, j])
                evidence = {_site_vote(a['sites'][x], b['sites'][y], variable, sign)
                            for x, y in sites}
                votes[evidence.pop() if len(evidence) == 1 else 'ambiguous'] += 1
                break
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
        clock = {(r['cruise'], r['timestamp']): r for r in rows if r['regime'] == item['regime']}
        aligned = []
        for r in rows:
            observation = clock.get((r['cruise'], r['timestamp'] - lag), {})
            lat, lon = observation.get('latitude'), observation.get('longitude')
            site = (lat, lon % 360) if stats.finite(lat) and stats.finite(lon) else None
            aligned.append(dict(r, paired_residual=observation.get(field), sample_site=site,
                                paired_reading=observation.get(item['field'])))
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
