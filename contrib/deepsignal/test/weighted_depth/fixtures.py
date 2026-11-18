"""Deterministic synthetic truth shared by weighted-depth tests and demo."""

import hashlib
import json

from contrib.deepsignal.weighted_depth.records import Observation

DEVELOPMENT_SEED = 17001
INJECTION_SEEDS = tuple(range(27001, 27021))
PAIR_VARIANCES = {("f1", "f2"): 5.0, ("f1", "f3"): 10.0,
                  ("f2", "f3"): 13.0}
PRIVATE_VARIANCES = {"f1": 1.0, "f2": 4.0, "f3": 9.0}


def observations(depths=(100.0, 102.0, 97.0), duplicate_first=False):
    """Return independent-family observations, optionally with copied ancestry."""
    result = []
    for index, (depth, variance) in enumerate(zip(depths, (1.0, 4.0, 9.0)), 1):
        result.append(Observation(
            source="s%d" % index, family="f%d" % index, event_time=10.0,
            depth_m=depth, uncertainty_m=variance ** 0.5,
            footprint_m=(1.0, 1.0), parent_ids=("raw-%d" % index,)))
    if duplicate_first:
        first = result[0]
        result.append(Observation(
            source="s1-copy", family="f1", event_time=first.event_time,
            depth_m=first.depth_m, uncertainty_m=first.uncertainty_m,
            footprint_m=first.footprint_m, parent_ids=first.parent_ids))
    return result


def synthetic_epochs(count=6000, seed=DEVELOPMENT_SEED):
    """Build causal truth with a family fault, bank, stale gap, and shared draft."""
    import numpy as np

    rng = np.random.default_rng(seed)
    true_depth = np.full(count, 100.0)
    true_depth[3000:3300] += np.linspace(0.0, 10.0, 300)
    true_depth[3300:] += 10.0
    noise = rng.normal(size=(count, 3)) * np.array((0.10, 0.20, 1.00))
    measured = true_depth[:, None] + noise + 1.0
    measured[1800:1890, 1] += 2.0
    stale = np.zeros(count, dtype=bool)
    stale[4000:4060] = True
    return {"time": np.arange(count, dtype=float), "truth": true_depth,
            "measured": measured, "stale": stale,
            "fit_ids": tuple("fit-%d" % i for i in range(0, 1500)),
            "holdout_ids": tuple("holdout-%d" % i for i in range(4500, count))}


def fixture_hash(fixture):
    """Hash JSON-compatible fixture content to detect accidental mutation."""
    normalized = {key: value.tolist() if hasattr(value, "tolist") else value
                  for key, value in fixture.items()}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
