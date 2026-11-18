"""Dependency-free statistics for autocorrelated ship observations."""

import math
import random


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pairs(x, y):
    return [(float(a), float(b)) for a, b in zip(x, y)
            if finite(a) and finite(b)]


def pearson(x, y):
    pairs = _pairs(x, y)
    if len(pairs) < 2:
        return None
    return _pearson_finite(*zip(*pairs))


def _pearson_finite(xs, ys):
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((a - xm) * (b - ym) for a, b in zip(xs, ys))
    xx = sum((a - xm) ** 2 for a in xs)
    yy = sum((b - ym) ** 2 for b in ys)
    return numerator / math.sqrt(xx * yy) if xx and yy else None


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
        return None
    xs, ys = zip(*pairs)
    return _pearson_finite(_ranks(xs), _ranks(ys))


def acf(x, k, spans=None):
    values = [v for v in x if finite(v)]
    if not values or k < 0 or k >= len(x):
        return 0.0
    mean = sum(values) / len(values)
    denominator = sum((value - mean) ** 2 for value in values)
    if denominator == 0:
        return 0.0
    tracks = spans if spans is not None else [(0, len(x))]
    numerator = sum((x[i] - mean) * (x[i + k] - mean) for start, end in tracks
                    for i in range(start, end - k) if finite(x[i]) and finite(x[i + k]))
    return numerator / denominator


def decorrelation_lag(x, spans=None):
    cap = max(1, len(x) // 4)
    for lag in range(1, cap + 1):
        if acf(x, lag, spans) <= 1 / math.e:
            return lag
    return cap


def n_eff(x, y, max_lag, spans=None):
    pairs = _pairs(x, y)
    if not pairs:
        return None
    xs, ys = zip(*[(a, b) if finite(a) and finite(b) else (None, None)
                   for a, b in zip(x, y)])
    total = sum(acf(xs, k, spans) * acf(ys, k, spans)
                for k in range(1, min(max_lag, len(xs) - 1) + 1))
    denominator = 1 + 2 * total
    return max(2.0, len(pairs) / denominator) if denominator else None


def block_bootstrap_ci(x, y, stat, block=None, reps=1000, seed=0, spans=None):
    if (block is not None and block <= 0) or reps < 1:
        raise ValueError('Block length and bootstrap replicate count must be positive')
    pairs = list(zip(x, y))
    if len(_pairs(x, y)) < 3:
        return None
    block = block or 2 * max(decorrelation_lag(x, spans), decorrelation_lag(y, spans))
    tracks = spans if spans is not None else [(0, len(pairs))]
    rng, estimates = random.Random(seed), []
    for _ in range(reps):
        sample = []
        for lo, hi in tracks:
            width = min(block, hi - lo)
            while len(sample) < hi:
                start = rng.randrange(lo, hi - width + 1)
                sample.extend(pairs[start:start + min(width, hi - len(sample))])
        bx, by = zip(*sample)
        usable = _pairs(bx, by)
        if len(usable) < 3:
            return None
        estimate = stat(*zip(*usable))
        if not finite(estimate):
            return None
        estimates.append(estimate)
    estimates.sort()
    return (estimates[int(.025 * (reps - 1))], estimates[int(.975 * (reps - 1))])


def circular_shift_pvalue(x, y, stat, reps=500, min_shift=None, seed=0,
                          lags=None, spans=None):
    if min_shift is None:
        min_shift = 4 * max(decorrelation_lag(x, spans), decorrelation_lag(y, spans))
    # Each cruise is shifted on its own bin clock, including its missing bins.
    spans = [(0, len(y))] if spans is None else spans
    shifts = [range(max(1, min_shift), min(end - start, end - start - min_shift + 1))
              for start, end in spans]
    if not shifts or not all(shifts):
        return None

    def measure(values):
        if lags:
            return lagged_best(x, values, lags, spans)[1]
        pairs = _pairs(x, values)
        return stat(*zip(*pairs)) if len(pairs) >= 3 else None

    observed, count, rng = measure(y), 0, random.Random(seed)
    if observed is None:
        return None
    for _ in range(reps):
        shifted = list(y)
        for (start, end), allowed in zip(spans, shifts):
            offset = start + rng.choice(allowed)
            shifted[start:end] = list(y[offset:end]) + list(y[start:offset])
        value = measure(shifted)
        if value is None:
            return None
        count += abs(value) >= abs(observed)
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


def aligned(x, y, lag, spans=None):
    """Return the lagged vectors and their cruise boundaries on the aligned clock."""
    ax, ay, bounds = [], [], []
    for lo, hi in spans if spans is not None else [(0, min(len(x), len(y)))]:
        if hi - lo <= abs(lag):
            continue
        start = len(ax)
        ax.extend(x[lo + max(0, -lag):hi - max(0, lag)])
        ay.extend(y[lo + max(0, lag):hi - max(0, -lag)])
        bounds.append((start, len(ax)))
    return ax, ay, bounds


def lagged_best(x, y, lags, spans=None):
    best = (None, None)
    for lag in lags:
        ax, ay, _ = aligned(x, y, lag, spans)
        pairs = _pairs(ax, ay)
        if len(pairs) < 3:
            continue
        xs, ys = zip(*pairs)
        if min(xs) == max(xs) or min(ys) == max(ys):
            continue
        value = _pearson_finite(_ranks(xs), _ranks(ys))
        if best[0] is None or abs(value) > abs(best[1]):
            best = (lag, value)
    return best
