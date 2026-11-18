"""Inject credible changes that should leave detector flags clear."""

from .faults import _replace, _window, step


def front(series, companion, *, bias, start=0, end=None, seed=0):
    """Apply the same step to two physically linked fields on synchronized records."""
    if [t for t, _ in series] != [t for t, _ in companion]:
        raise ValueError('front requires fields sampled on the same timestamps')
    primary, truth = step(series, bias=bias, start=start, end=end, seed=seed)
    linked, _ = step(companion, bias=bias, start=start, end=end, seed=seed)
    return (primary, linked), [(first, last, 'trap') for first, last, _ in truth]


def turn(series, *, degrees, start=0, end=None, seed=0):
    """Sweep an angle over the window with eased endpoints and wrap at 360 degrees."""
    window = _window(series, start, end)
    samples = series[window]
    if not samples:
        return series.copy(), []
    first, initial = samples[0]
    duration = samples[-1][0] - first
    values = []
    for timestamp, value in samples:
        fraction = (timestamp - first) / duration if duration else 0
        # Return to the source heading at the boundary so ending the synthetic
        # manoeuvre cannot create an out-of-truth reversal.
        eased = 16 * fraction ** 2 * (1 - fraction) ** 2
        values.append((timestamp, None if value is None else
                       (value + degrees * eased) % 360))
    return _replace(series, window, values, 'trap')
