"""Fault-bench compatible synthetic coupling injector."""

import math
import random


def heading_coupled_bias(series, ship_heading, amplitude, sector=0, seed=0):
    """Return a copy with a cosine ship-heading bias and reproducible jitter."""
    rng = random.Random(seed)
    return [value + amplitude * math.cos(math.radians(heading - sector)) +
            rng.uniform(-1e-12, 1e-12)
            for value, heading in zip(series, ship_heading)]
