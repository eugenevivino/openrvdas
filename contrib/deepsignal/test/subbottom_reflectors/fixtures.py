"""Deterministic synthetic truth for the sub-bottom estimator."""

import hashlib
import math
import random


def synthetic_crossing(seed=17001, delay_s=0.0, count=256, draft_m=0.0,
                       include_shallow=False):
    """Return fixed crossing truth with a 1 ms zero-phase wavelet."""
    rng = random.Random(seed)
    dt_s = 0.00025
    resolution_s = 0.001
    traces = []
    for index in range(count):
        bottom = 0.040 + 0.00004 * index
        primary = bottom + 0.044
        multiple = 2 * bottom + 2 * draft_m / 1500.0
        samples = [rng.gauss(0.0, 0.05) for _ in range(512)]
        arrivals = [(primary, 1.0), (multiple, 1.5)]
        if include_shallow:
            arrivals.append((bottom + 0.012, 0.8))
        for arrival, amplitude in arrivals:
            center = round((arrival - delay_s) / dt_s)
            for offset in range(-4, 5):
                sample = center + offset
                if 0 <= sample < len(samples):
                    phase = math.pi * offset * dt_s / resolution_s
                    samples[sample] += amplitude * math.cos(phase) * math.exp(-phase * phase)
        raw = ("%.9g," * len(samples) % tuple(samples)).encode("ascii")
        traces.append({
            "trace_id": "T%03d" % index, "x_m": float(index), "y_m": 0.0,
            "time_utc": "2026-11-18T00:%02d:%02dZ" % divmod(index, 60),
            "delay_s": delay_s, "dt_s": dt_s, "samples": samples,
            "representation": "envelope", "source_hash": hashlib.sha256(raw).hexdigest(),
            "bottom_twt_s": bottom, "bottom_sd_s": 0.00025,
            "pulse_resolution_s": resolution_s,
        })
    return traces


def four_trace_gap():
    traces = synthetic_crossing(count=12)
    for trace in traces[4:8]:
        trace["samples"] = []
    return traces


def multiple_only_stretch():
    traces = synthetic_crossing(count=24)
    for trace in traces[8:16]:
        trace["truth_primary_twt_s"] = None
    return traces


def pinch_out():
    traces = synthetic_crossing(count=24)
    for index, trace in enumerate(traces):
        trace["truth_primary_amplitude"] = max(0.0, 1.0 - abs(index - 12) / 6)
    return traces
