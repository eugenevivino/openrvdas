"""Deterministic synthetic truth shared by tests and the offline demo."""

import copy
import hashlib
import json
import math
import random

DEVELOPMENT_SEED = 17001
FINAL_INJECTION_SEEDS = tuple(range(27001, 27021))


def constant_c_truth():
    """Return the binding 1500 m/s, 30 degree, 0.1 second ray truth."""
    sound_speed_mps = 1500.0
    angle_deg = 30.0
    one_way_time_s = 0.1
    distance_m = sound_speed_mps * one_way_time_s
    angle_rad = math.radians(angle_deg)
    return {
        "sound_speed_mps": sound_speed_mps,
        "angle_deg": angle_deg,
        "angle_rad": angle_rad,
        "one_way_time_s": one_way_time_s,
        "x_m": distance_m * math.sin(angle_rad),
        "z_m": distance_m * math.cos(angle_rad),
    }


def solve_rows():
    """Return the binding solve-only residual, derivative and nuisance rows."""
    return {
        "residual_m": (-0.4, 0.4, 0.0),
        "jacobian_m_per_mps": (0.2, -0.2, 0.0),
        "nuisance": (1.0, 1.0, 1.0),
        "row_sd_m": 0.01,
        "prior_sd_mps": 5.0,
    }


def synthetic_records(seed=DEVELOPMENT_SEED):
    """Build bounded records without touching a socket, file or global RNG."""
    rng = random.Random(seed)
    records = []
    for line_id, sign in (("fit-a", -1.0), ("fit-b", 1.0),
                          ("holdout-c", 1.0)):
        for ping_id in range(4):
            records.append({
                "data_id": "synthetic_kmall",
                "timestamp": 1763467200.0 + len(records),
                "fields": {
                    "schema_version": "kmall-410224-normalized/v1",
                    "line_id": line_id,
                    "ping_id": ping_id,
                    "head_depth_m": 5.0,
                    "one_way_time_s": 0.1,
                    "beam_angle_deg": sign * (20.0 + 4.0 * ping_id),
                    "z_re_ref_point_m": 130.0 + rng.uniform(-0.002, 0.002),
                    "datum": "waterline",
                    "profile_id": "cast-reserved",
                },
                "metadata": {"source_id": f"{line_id}:{ping_id}"},
            })
    return records


def fixture_hash(records=None):
    """Hash canonical fixture input for mutation and lineage assertions."""
    value = synthetic_records() if records is None else records
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def demo_records():
    """Return an isolated copy appropriate for a local Reader."""
    return copy.deepcopy(synthetic_records())
