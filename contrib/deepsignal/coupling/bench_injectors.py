"""Fault-bench plug-in for an additive bias in ship-relative coordinates."""

import math


def heading_coupled_bias(series, ship_heading=None, amplitude=1, sector=0, seed=0,
                         *, companion=None, start=0, end=None):
    """Return timestamped samples and inclusive truth intervals on the source clock.

    The bench supplies the synchronized direction series through companion_field.
    The cosine injection is deterministic for every seed.
    """
    if companion is not None:
        if ship_heading is not None or [t for t, _ in companion] != [t for t, _ in series]:
            raise ValueError('Expected one synchronized heading per sample')
        ship_heading = [v for _, v in companion]
    if ship_heading is None or len(ship_heading) != len(series):
        raise ValueError('Expected one heading per sample')
    output, truth = [], []
    first = None
    for (t, value), heading in zip(series, ship_heading):
        elapsed = t - series[0][0]
        if (elapsed >= start and (end is None or elapsed <= end) and
                value is not None and heading is not None):
            value += amplitude * math.cos(math.radians(heading - sector))
            if first is None:
                first = t
        elif first is not None:
            truth.append((first, output[-1][0], 'heading_coupled_bias'))
            first = None
        output.append((t, value))
    if first is not None:
        truth.append((first, output[-1][0], 'heading_coupled_bias'))
    return output, truth
