"""Inject faults into ordered (epoch seconds, value) samples without changing the input.

Windows use inclusive seconds relative to the first sample. Truth uses inclusive
timestamps on the original sample clock, including for clock faults.
"""

import math
import random
from bisect import bisect_left, bisect_right
from operator import itemgetter


def _window(series, start, end):
    if not math.isfinite(start) or (end is not None and
                                    (not math.isfinite(end) or end < start)):
        raise ValueError('Expected finite start and end offsets with start <= end')
    if not series:
        return slice(0, 0)
    origin = series[0][0]
    first = bisect_left(series, origin + start, key=itemgetter(0))
    stop = len(series) if end is None else bisect_right(series, origin + end, key=itemgetter(0))
    return slice(first, stop)


def _replace(series, window, values, label):
    output = series.copy()
    output[window] = values
    truth = []
    if window.start < window.stop:
        truth.append((series[window.start][0], series[window.stop - 1][0], label))
    return output, truth


def drift(series, *, rate_per_hour, start=0, end=None, seed=0):
    """Add a linear bias that starts at zero at the first sample in the window."""
    window = _window(series, start, end)
    onset = series[window.start][0] if window.start < window.stop else 0
    values = [(t, None if v is None else v + rate_per_hour * (t - onset) / 3600)
              for t, v in series[window]]
    return _replace(series, window, values, 'drift')


def step(series, *, bias, start=0, end=None, seed=0):
    """Add a constant bias within the window."""
    window = _window(series, start, end)
    values = [(t, None if v is None else v + bias) for t, v in series[window]]
    return _replace(series, window, values, 'step')


def lag(series, *, tau_seconds, start=0, end=None, seed=0):
    """Apply a first-order response using the previous clean sample as the initial state."""
    if not math.isfinite(tau_seconds) or tau_seconds <= 0:
        raise ValueError('tau_seconds must be positive and finite')
    window = _window(series, start, end)
    previous_time, filtered = series[window.start - 1] if window.start else (0, None)
    values = []
    for timestamp, value in series[window]:
        if value is None or filtered is None:
            filtered = value
        else:
            alpha = -math.expm1(-(timestamp - previous_time) / tau_seconds)
            filtered += alpha * (value - filtered)
        values.append((timestamp, filtered))
        previous_time = timestamp
    return _replace(series, window, values, 'lag')


def hysteresis(series, *, rising_offset, falling_offset, start=0, end=None, seed=0):
    """Apply direction-dependent offsets, retaining the last direction on ties."""
    window = _window(series, start, end)
    previous = series[window.start - 1][1] if window.start else None
    offset = 0
    values = []
    for timestamp, value in series[window]:
        if value is None or previous is None:
            offset = 0
        elif value > previous:
            offset = rising_offset
        elif value < previous:
            offset = falling_offset
        values.append((timestamp, None if value is None else value + offset))
        previous = value
    return _replace(series, window, values, 'hysteresis')


def clock_jump(series, *, seconds, start=0, end=None, seed=0):
    """Add a signed timestamp offset within the window."""
    window = _window(series, start, end)
    return _shift(series, window, seconds, 'clock_jump')


def clock_reset(series, *, seconds, start=0, end=None, seed=0):
    """Subtract a positive offset large enough for the first timestamp to go backwards."""
    window = _window(series, start, end)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('clock_reset seconds must be positive and finite')
    if window.start < window.stop and (window.start == 0 or
                                       series[window.start][0] - seconds >=
                                       series[window.start - 1][0]):
        raise ValueError('clock_reset needs a preceding sample and a backward timestamp')
    return _shift(series, window, -seconds, 'clock_reset')


def _shift(series, window, seconds, label):
    if not math.isfinite(seconds):
        raise ValueError('Clock offset must be finite')
    values = [(timestamp + seconds, value) for timestamp, value in series[window]]
    return _replace(series, window, values, label)


def spikes(series, *, count, size, start=0, end=None, seed=0):
    """Add signed spikes to distinct nonmissing samples chosen with a local RNG."""
    if seed is None:
        raise ValueError('spikes requires a deterministic seed')
    window = _window(series, start, end)
    candidates = [i for i in range(window.start, window.stop) if series[i][1] is not None]
    indices = sorted(random.Random(seed).sample(candidates, count))
    output = series.copy()
    truth = []
    for index in indices:
        timestamp, value = series[index]
        output[index] = timestamp, value + size
        truth.append((timestamp, timestamp, 'spikes'))
    return output, truth


def flatline(series, *, start=0, end=None, seed=0):
    """Hold the first value in the window for its duration."""
    window = _window(series, start, end)
    held = series[window.start][1] if window.start < window.stop else None
    values = [(timestamp, None if value is None else held)
              for timestamp, value in series[window]]
    return _replace(series, window, values, 'flatline')


def dropout(series, *, start=0, end=None, seed=0):
    """Replace all values in the window with None."""
    window = _window(series, start, end)
    values = [(timestamp, None) for timestamp, _ in series[window]]
    return _replace(series, window, values, 'dropout')
