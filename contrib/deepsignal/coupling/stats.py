"""Dependency-free statistics for autocorrelated ship observations."""

import math
import random


def _pairs(x, y):
    return [(float(a), float(b)) for a, b in zip(x, y)
            if a is not None and b is not None]


def pearson(x, y):
    pairs = _pairs(x, y)
    if len(pairs) < 2:
        return 0.0
    xs, ys = zip(*pairs)
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((a - xm) * (b - ym) for a, b in pairs)
    xx = sum((a - xm) ** 2 for a in xs)
    yy = sum((b - ym) ** 2 for b in ys)
    return numerator / math.sqrt(xx * yy) if xx and yy else 0.0


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for position in order[start:end]:
            result[position] = rank
        start = end
    return result


def spearman(x, y):
    pairs = _pairs(x, y)
    if len(pairs) < 2:
        return 0.0
    xs, ys = zip(*pairs)
    return pearson(_ranks(xs), _ranks(ys))


def acf(x, k):
    values = [float(v) for v in x if v is not None]
    if not values or k < 0 or k >= len(values):
        return 0.0
    mean = sum(values) / len(values)
    denominator = sum((value - mean) ** 2 for value in values)
    if denominator == 0:
        return 0.0
    return sum((values[i] - mean) * (values[i + k] - mean)
               for i in range(len(values) - k)) / denominator


def decorrelation_lag(x):
    cap = max(1, len(x) // 4)
    for lag in range(1, cap + 1):
        if acf(x, lag) <= 1 / math.e:
            return lag
    return cap


def n_eff(x, y, max_lag):
    pairs = _pairs(x, y)
    if not pairs:
        return 2.0
    xs, ys = zip(*pairs)
    total = sum(acf(xs, k) * acf(ys, k)
                for k in range(1, min(max_lag, len(pairs) - 1) + 1))
    denominator = max(1.0, 1 + 2 * total)
    return max(2.0, min(float(len(pairs)), len(pairs) / denominator))


def block_bootstrap_ci(x, y, stat, block=None, reps=1000, seed=0):
    pairs = _pairs(x, y)
    if not pairs:
        return (0.0, 0.0)
    xs, ys = zip(*pairs)
    block = block or 2 * max(decorrelation_lag(xs), decorrelation_lag(ys))
    block = max(1, min(block, len(pairs)))
    rng, estimates = random.Random(seed), []
    for _ in range(reps):
        sample = []
        while len(sample) < len(pairs):
            start = rng.randrange(len(pairs) - block + 1)
            sample.extend(pairs[start:start + block])
        bx, by = zip(*sample[:len(pairs)])
        estimates.append(stat(bx, by))
    estimates.sort()
    return (estimates[int(.025 * (reps - 1))], estimates[int(.975 * (reps - 1))])


def circular_shift_pvalue(x, y, stat, reps=500, min_shift=None, seed=0,
                          lags=None):
    pairs = _pairs(x, y)
    if len(pairs) < 3:
        return 1.0
    xs, ys = zip(*pairs)
    if min_shift is None:
        min_shift = 2 * max(decorrelation_lag(xs), decorrelation_lag(ys))
    allowed = [i for i in range(1, len(pairs))
               if min(i, len(pairs) - i) >= min_shift]
    if not allowed:
        return 1.0
    measure = (lambda a, b: abs(lagged_best(a, b, lags)[1])) if lags else (
        lambda a, b: abs(stat(a, b)))
    observed, count, rng = measure(xs, ys), 0, random.Random(seed)
    for _ in range(reps):
        shift = rng.choice(allowed)
        shifted = ys[shift:] + ys[:shift]
        count += measure(xs, shifted) >= observed
    return (1 + count) / (reps + 1)


def _fdr(pvals, q):
    ordered = sorted((p, i) for i, p in enumerate(pvals) if p is not None)
    cutoff = 0
    for rank, (value, _) in enumerate(ordered, 1):
        if value <= q * rank / len(ordered):
            cutoff = rank
    return {index for _, index in ordered[:cutoff]}


def bh(pvals, q):
    return _fdr(pvals, q)


def by(pvals, q):
    m = len([p for p in pvals if p is not None])
    return _fdr(pvals, q / sum(1 / i for i in range(1, m + 1))) if m else set()


def lagged_best(x, y, lags):
    best = (None, 0.0)
    for lag in lags:
        if lag > 0:
            value = spearman(x[:-lag], y[lag:])
        elif lag < 0:
            value = spearman(x[-lag:], y[:lag])
        else:
            value = spearman(x, y)
        if best[0] is None or abs(value) > abs(best[1]):
            best = (lag, value)
    return best
