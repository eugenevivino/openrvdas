"""Offline ship-coupling discovery, replication, and frozen polar calibration."""

from collections import defaultdict
from datetime import datetime
from itertools import groupby, product
from statistics import median

from . import CODE_VERSION, controls, prep, stats
from .archive import read_input, select_splits, write_atlas


DEFAULTS = {
    'fields': [], 'ship_variables': [], 'regimes': ['transit'], 'lags': [0],
    'bin_seconds': 10, 'median_minutes': 30, 'station_knots': 1, 'turn_deg_s': 2,
    'sog_change_kn_min': 1, 'min_n_eff': 30, 'max_lag': None, 'block': None,
    'min_shift': None, 'reps': 500, 'bootstrap_reps': 1000, 'method': 'bh',
    'output_dir': 'ship-coupling', 'q': .05, 'seed': 78, 'sectors': 12, 'speed_bands': [1, 5, 10],
    'reciprocal_km': 10, 'reciprocal_hours': 12, 'min_reciprocal_pairs': 2,
    'reciprocal_agreement': .75, 'shift_effect_limit': .2,
}
# The explicitly configured partition takes precedence over these standard field names.
FAMILIES = {
    'met_vs_ship': ['air_temperature', 'barometer', 'humidity', 'MwxAirTemp'],
    'ocean_vs_ship': ['salinity', 'sea_temperature', 'water_temperature', 'conductivity'],
    'acoustic_vs_ship': ['backscatter', 'depth', 'sound_speed', 'echo_intensity'],
    'nav_consistency': ['latitude', 'longitude', 'course', 'heading', 'sog'],
}


def _evaluate(rows, field, variable, config, seed):
    x, y, spans = [], [], []
    lags = config.get('lags', [0])
    for _, track in groupby(rows, key=lambda r: r.get('cruise')):
        start = len(x)
        for r in track:
            x.append(r.get(field))
            y.append(r.get(variable))
        spans.append((start, len(x)))
    lag, effect = stats.lagged_best(x, y, lags, spans)
    fit = dict(effect=effect, lag=lag, n_eff=None, p=None, ci=None, seed=seed, insufficient=True)
    if lag is None:
        return fit

    # Estimate dependence and uncertainty from precisely the paired support of the winning lag.
    ax, ay, bounds = stats.aligned(x, y, lag, spans)
    wx, wy = zip(*[(a, b) if stats.finite(a) and stats.finite(b) else (None, None)
                   for a, b in zip(ax, ay)])
    count = sum(v is not None for v in wx)
    max_lag = config.get('max_lag')
    if max_lag is None:
        max_lag = min(20, count // 4)
    block = config.get('block') or 2 * max(stats.decorrelation_lag(wx, bounds),
                                           stats.decorrelation_lag(wy, bounds))
    min_shift = config.get('min_shift')
    if min_shift is None:
        min_shift = 2 * block
    effective = stats.n_eff(wx, wy, max_lag, bounds)
    ci = stats.block_bootstrap_ci(wx, wy, stats.spearman, block, config.get('bootstrap_reps', 1000),
                                  seed, bounds)
    fit.update(n_eff=effective, pairs=count, max_lag=max_lag, block=block, min_shift=min_shift,
               ci=list(ci) if ci else None)
    if effective is not None and effective >= config.get('min_n_eff', 30) and ci is not None:
        fit['p'] = stats.circular_shift_pvalue(x, y, stats.spearman, config.get('reps', 500),
                                               min_shift, seed, lags, spans)
        fit['insufficient'] = fit['p'] is None
    return fit


def _correct(items, config):
    method = {'bh': stats.bh, 'by': stats.by}[config['method']]
    steps = sorted(set(config['lags']))
    step = min((b - a for a, b in zip(steps, steps[1:])), default=1)
    for _, group in groupby(sorted(items, key=lambda h: h['family']), key=lambda h: h['family']):
        group = list(group)
        first = method([h['p'] for h in group], config['q'])
        second = method([h['holdout']['p'] for h in group], config['q'])
        for i, h in enumerate(group):
            holdout = h['holdout']
            h['q_pass'], holdout['q_pass'] = i in first, i in second
            replicated = (i in first and i in second and h['effect'] * holdout['effect'] > 0 and
                          abs(h['lag'] - holdout['lag']) <= step)
            if h['insufficient']:
                h['status'] = 'insufficient'
            elif replicated:
                h['status'] = 'confirmed'
            else:
                h['status'] = 'discovery_only' if i in first else 'rejected'


def _polar(rows, hypotheses, config):
    result = {}
    for field in sorted({h['field'] for h in hypotheses if h['status'] == 'confirmed'}):
        regimes = {h['regime'] for h in hypotheses if h['field'] == field and
                   h['status'] == 'confirmed'}
        cells = defaultdict(list)
        for row in rows:
            cell, value = prep.polar_cell(row, config), row.get(field + '_residual')
            if cell and row['regime'] in regimes and stats.finite(value):
                cells[(row['regime'], *cell)].append(value)
        result[field] = [dict(regime=regime, sector=sector, speed_band=band, median=median(values),
                              iqr=controls.iqr(values), count=len(values))
                         for (regime, sector, band), values in sorted(cells.items())]
    return result


def _parameters(config):
    params = dict(DEFAULTS, **config)
    if 'splits' in config:
        params['splits'] = {
            name: {k: v.isoformat() if isinstance(v, datetime) else v for k, v in spec.items()}
            for name, spec in config['splits'].items()
        }
    for k in ('heading', 'direction', 'sog', 'roll', 'pitch', 'rpm', 'thruster',
              'latitude', 'longitude', 'relative_heading'):
        params.setdefault(k + '_field', k)
    params['families'] = {k: list(v) for k, v in config.get('families', FAMILIES).items()}
    for field in params['fields']:
        memberships = [k for k, fields in params['families'].items() if field in fields]
        if not memberships and 'families' not in config:
            params['families']['met_vs_ship'].append(field)
        elif len(memberships) != 1:
            raise ValueError(f'Assign {field!r} to exactly one family')
    bands = params['speed_bands']
    if (params['bin_seconds'] <= 0 or params['sectors'] < 1 or sorted(set(bands)) != bands or
            not params['lags'] or min(params['reps'], params['bootstrap_reps']) < 1):
        raise ValueError('Invalid bins, sectors, speed bands, lags, or replicate counts')
    return params


def discover(discovery_rows, holdout_rows, config):
    """Each split is independently binned and detrended before fitting either set."""
    config = _parameters(config)
    grids = {'discovery': prep.prepare(discovery_rows, config),
             'holdout': prep.prepare(holdout_rows, config)}
    items = []
    for regime in config['regimes']:
        # Mask rather than compress. Both ends of every lag stay on the same clock.
        tracks = [[r if r['regime'] == regime else {'cruise': r['cruise']} for r in grid]
                  for grid in grids.values()]
        for field, variable in product(config['fields'], config['ship_variables']):
            residual = field + '_residual'
            first = _evaluate(tracks[0], residual, variable, config, config['seed'])
            second = _evaluate(tracks[1], residual, variable, config, config['seed'] + 1)
            family = next(k for k, fields in config['families'].items() if field in fields)
            first.update(field=field, ship_variable=variable, regime=regime, family=family,
                         holdout=second)
            items.append(first)
    _correct(items, config)
    for item in items:
        controls.invariance(item, grids, config)
    all_rows = grids['discovery'] + grids['holdout']
    polar = _polar(all_rows, items, config)
    events = [event for grid in grids.values() for event in controls.turns(grid, polar, config)]
    spreads = {}
    for field, table in polar.items():
        # Remove the typical bias of each cell before estimating the field-wide healthy spread.
        lookup = {(r['regime'], r['sector'], r['speed_band']): r['median'] for r in table}
        deviations = []
        for row in all_rows:
            cell = prep.polar_cell(row, config)
            key = (row['regime'], *cell) if cell else None
            value = row.get(field + '_residual')
            if key in lookup and stats.finite(value):
                deviations.append(value - lookup[key])
        spreads[field] = controls.iqr(deviations) if deviations else None
        for entry in table:
            deltas = [e['after'] - e['before'] for e in events if e['field'] == field and
                      e['regime'] == entry['regime'] and
                      e['cell'] == (entry['sector'], entry['speed_band'])]
            entry['turn_count'] = len(deltas)
            entry['turn_median_change'] = median(deltas) if deltas else None
    splits = {name: {'bins': len(rows), 'field_bins': {
        field: sum(stats.finite(row.get(field)) for row in rows) for field in config['fields']}}
        for name, rows in grids.items()}
    return dict(code_version=CODE_VERSION, parameters=config, splits=splits, hypotheses=items,
                polar=polar, healthy_spread=spreads, turn_events=events)


def run(config, config_path=None):
    rows, skipped, inputs = read_input(config)
    discovery, holdout = select_splits(rows, config.get('splits', {}))
    result = discover(discovery, holdout, config)
    result['unparseable_lines'] = skipped
    result['inputs'] = [str(path) for path in inputs]
    write_atlas(result, inputs + ([config_path] if config_path else []))
    return result
