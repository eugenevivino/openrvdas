"""Dependency-free statistics for autocorrelated ship observations."""

from itertools import product
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

    def scaled(values):
        exponent = math.frexp(max(map(abs, values)))[1]
        normalized = [math.ldexp(v, -exponent) for v in values]
        return [v - normalized[0] for v in normalized]

    xs, ys = zip(*pairs)
    return _pearson_finite(scaled(xs), scaled(ys))


def _pearson_finite(xs, ys):
    xm, ym = math.fsum(xs) / len(xs), math.fsum(ys) / len(ys)
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
    # An exact power-of-two rescaling cancels in the ratio. Subtracting an
    # origin first also preserves small deviations from a large common level.
    exponent = math.frexp(max(map(abs, values)))[1]
    origin = math.ldexp(values[0], -exponent)
    scaled = [math.ldexp(v, -exponent) - origin if finite(v) else None for v in x]
    mean = math.fsum(v for v in scaled if v is not None) / len(values)
    centered = [v - mean if v is not None else None for v in scaled]
    denominator = math.fsum(v*v for v in centered if v is not None)
    if denominator == 0:
        return 0.0
    tracks = spans if spans is not None else [(0, len(x))]
    numerator = math.fsum(centered[i] * centered[i+k] for start, end in tracks
                          for i in range(start, end-k)
                          if centered[i] is not None and centered[i+k] is not None)
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
    return circular_shift_test(x, y, stat, reps, min_shift, seed, lags, spans)[0]


def has_lag_pair(x, y, lo, hi, lags):
    return any(finite(x[i]) and finite(y[i+lag]) for lag in lags
               for i in range(lo + max(0, -lag), hi - max(0, lag)))


def _rotation_period(values):
    """Shortest repeating tile, including missing bins, in linear time."""
    values = [v if finite(v) else None for v in values]
    prefix = [0] * len(values)
    for i in range(1, len(values)):
        length = prefix[i-1]
        while length and values[length] != values[i]:
            length = prefix[length-1]
        prefix[i] = length + (values[length] == values[i])
    period = len(values) - prefix[-1]
    return period if len(values) % period == 0 else len(values)


def _shift_period(x, y, lags, stat):
    period = _rotation_period(y)
    if period == 1 or stat not in (spearman, pearson):
        return period
    # Correlations depend on pairs, irrespective of order. A rotation that
    # preserves the field and its observation mask on every tested lag clock
    # also reproduces the same pairs. Truncation at lag boundaries matters.
    n = len(y)
    field_period = 1
    for lag in lags:
        field = [x[i-lag] if 0 <= i-lag < n else None for i in range(n)]
        field_period = math.lcm(field_period, _rotation_period(field))
        if field_period == n:
            break
    return math.gcd(period, field_period)


def circular_shift_test(x, y, stat, reps, min_shift, seed, lags, spans):
    """Return the plus-one p-value and the number of distinct shifts used in it."""
    if len(x) < len(y):
        x = list(x) + [None] * (len(y) - len(x))
    if min_shift is None:
        min_shift = 4 * max(decorrelation_lag(x, spans), decorrelation_lag(y, spans))
    if reps < 1:
        raise ValueError('Shift replicate count must be positive')
    # Each cruise is shifted on its own bin clock, including its missing bins.
    spans = [(0, len(y))] if spans is None else spans
    lags = [0] if lags is None else lags
    spans = [(lo, hi) for lo, hi in spans if has_lag_pair(x, y, lo, hi, lags)]
    shifts = []
    first = max(1, min_shift)
    for lo, hi in spans:
        # Rotations separated by a whole period give exactly the same data.
        period = _shift_period(x[lo:hi], y[lo:hi], lags, stat)
        stop = min(hi - lo, hi - lo - min_shift + 1, first + period)
        shifts.append(range(first, stop))
    if not shifts or not all(shifts):
        return None, 0

    def measure(values):
        return lagged_best(x, values, lags, spans, stat)[1]

    observed = measure(y)
    if observed is None:
        return None, 0
    support = math.prod(len(options) for options in shifts)
    draws = min(reps, support)
    if draws == support:
        offsets = product(*shifts)
    else:
        rng = random.Random(seed)
        seen = set()
        while len(seen) < draws:
            seen.add(tuple(rng.choice(options) for options in shifts))
        offsets = seen
    count = 0
    for offsets_by_cruise in offsets:
        shifted = list(y)
        for (start, end), distance in zip(spans, offsets_by_cruise):
            offset = start + distance
            shifted[start:end] = list(y[offset:end]) + list(y[start:offset])
        value = measure(shifted)
        if value is None:
            return None, 0
        count += abs(value) >= abs(observed)
    return (1 + count) / (draws + 1), draws


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


def lagged_best(x, y, lags, spans=None, stat=spearman):
    best = (None, None)
    for lag in lags:
        ax, ay, _ = aligned(x, y, lag, spans)
        pairs = _pairs(ax, ay)
        if len(pairs) < 3:
            continue
        xs, ys = zip(*pairs)
        if stat is spearman:
            value = _pearson_finite(_ranks(xs), _ranks(ys))
        else:
            value = stat(xs, ys)
        if not finite(value):
            continue
        if best[0] is None or abs(value) > abs(best[1]):
            best = (lag, value)
    return best
