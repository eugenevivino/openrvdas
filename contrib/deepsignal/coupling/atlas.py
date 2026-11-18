"""Offline ship-coupling atlas builder."""

import csv
import json
import math
import os

from contrib.deepsignal.coupling import CODE_VERSION, stats


def _evaluate(rows, field, variable, config, seed):
    x = [row.get(field) for row in rows]
    y = [row.get(variable) for row in rows]
    pairs = stats._pairs(x, y)
    lags = config.get('lags', [0])
    if len(pairs) < 3:
        return {'effect': 0, 'lag': 0, 'n_eff': 2, 'p': None,
                'ci': [0, 0], 'insufficient': True}
    x, y = zip(*pairs)
    lag, effect = stats.lagged_best(x, y, lags)
    block = config.get('block') or 2 * max(stats.decorrelation_lag(x),
                                           stats.decorrelation_lag(y))
    effective = stats.n_eff(x, y, config.get('max_lag', min(20, len(x) // 4)))
    insufficient = effective < config.get('min_n_eff', 30)
    pvalue = None if insufficient else stats.circular_shift_pvalue(
        x, y, stats.spearman, config.get('reps', 500),
        config.get('min_shift', block), seed, lags)
    return {'effect': effect, 'lag': lag, 'n_eff': effective, 'p': pvalue,
            'ci': list(stats.block_bootstrap_ci(x, y, stats.spearman, block,
                                                config.get('bootstrap_reps', 200),
                                                seed)),
            'insufficient': insufficient, 'block': block}


def discover(discovery_rows, holdout_rows, config):
    """Evaluate, FDR-correct, and replicate configured hypotheses."""
    hypotheses = []
    regimes = config.get('regimes', ['transit'])
    for field in config.get('fields', []):
        for variable in config.get('ship_variables', []):
            for regime in regimes:
                first = [r for r in discovery_rows if r.get('regime', regime) == regime]
                second = [r for r in holdout_rows if r.get('regime', regime) == regime]
                result = _evaluate(first, field, variable, config, config.get('seed', 78))
                result.update({'field': field, 'ship_variable': variable,
                               'regime': regime, 'family': 'met_vs_ship'})
                result['holdout'] = _evaluate(second, field, variable, config,
                                              config.get('seed', 78) + 1)
                hypotheses.append(result)
    pvalues = [item['p'] for item in hypotheses]
    method = stats.by if config.get('method') == 'by' else stats.bh
    passed = method(pvalues, config.get('q', .05))
    holdout_passed = method([h['holdout']['p'] for h in hypotheses],
                            config.get('q', .05))
    configured_lags = config.get('lags', [0])
    differences = (abs(b - a) for a, b in zip(configured_lags, configured_lags[1:]))
    lag_step = max(1, min(differences, default=1))
    for index, item in enumerate(hypotheses):
        replicated = (index in passed and index in holdout_passed and
                      item['effect'] * item['holdout']['effect'] > 0 and
                      abs(item['lag'] - item['holdout']['lag']) <= lag_step)
        item['q_pass'] = index in passed
        item['status'] = ('confirmed' if replicated else
                          'discovery_only' if index in passed else 'rejected')
        heading_type = 'heading' in item['ship_variable']
        item['invariance'] = 'ship_artifact' if replicated and heading_type else 'cannot_tell'
        item['time_shift'] = {'12h': None, '24h': None}
    return {'code_version': CODE_VERSION, 'parameters': dict(config),
            'hypotheses': hypotheses, 'polar': _polar(discovery_rows + holdout_rows,
                                                      hypotheses, config)}


def _polar(rows, hypotheses, config):
    result, sectors = {}, config.get('sectors', 12)
    for field in {h['field'] for h in hypotheses if h['status'] == 'confirmed'}:
        table = []
        for sector in range(sectors):
            values = [r[field] for r in rows if r.get(field) is not None and
                      int(r.get('relative_heading', sector * 360 / sectors) /
                          (360 / sectors)) % sectors == sector]
            if values:
                ordered = sorted(values)
                median = ordered[len(ordered) // 2]
                iqr = ordered[3 * len(ordered) // 4] - ordered[len(ordered) // 4]
                table.append({'sector': sector, 'speed_band': 'all',
                              'median': median, 'iqr': iqr or 1.0})
        result[field] = table
    return result


def _read_csv(path):
    rows, skipped = [], 0
    with open(path, encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            try:
                rows.append({key: float(value) if value else None
                             for key, value in row.items()})
            except (TypeError, ValueError):
                skipped += 1
    return rows, skipped


def run(config):
    if config.get('input_csv'):
        rows, skipped = _read_csv(config['input_csv'])
    else:
        rows = [{'air_temperature': math.cos(i / 10),
                 'relative_heading_cos': math.cos(i / 10),
                 'relative_heading': math.degrees(i / 10) % 360,
                 'regime': 'transit'} for i in range(240)]
        skipped = 0
    split = int(len(rows) * config.get('discovery_fraction', .5))
    atlas = discover(rows[:split], rows[split:], config)
    atlas['unparseable_lines'] = skipped
    output = config.get('output_dir', '/tmp/deepsignal/ship-coupling')
    os.makedirs(output, exist_ok=True)
    with open(os.path.join(output, 'atlas.json'), 'w', encoding='utf-8') as stream:
        json.dump(atlas, stream, indent=2, sort_keys=True)
    with open(os.path.join(output, 'atlas.md'), 'w', encoding='utf-8') as stream:
        stream.write('# Ship-coupling atlas\n\n')
        for item in sorted(atlas['hypotheses'],
                           key=lambda h: h['status'] != 'confirmed'):
            stream.write('* %s vs %s: **%s**, effect %.3f.\n' %
                         (item['field'], item['ship_variable'], item['status'],
                          item['effect']))
    for field, table in atlas['polar'].items():
        with open(os.path.join(output, 'polar_%s.csv' % field), 'w',
                  newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, ['sector', 'speed_band', 'median', 'iqr'])
            writer.writeheader()
            writer.writerows(table)
    return atlas
