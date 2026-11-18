"""Deterministic synthetic truth used by tests and the offline demo."""

import copy
import hashlib
import json

DEVELOPMENT_SEED = 17001
FINAL_TRIAL_SEEDS = tuple(range(27001, 27021))


def synthetic_records():
    """Return decoded voxel rows with a known earth-fixed flare and distractors."""
    common = {
        "bottom_depth_m": 100.0,
        "beam_footprint_m": 5.0,
        "current_en_mps": [0.05, 0.0],
        "rise_speed_mps": 0.2,
        "height_above_bottom_m": 20.0,
        "noise_variance": 1.0,
        "frequency_hz": 30000.0,
        "calibrated": True,
        "coverage_mask": True,
        "runtime_hash": "synthetic-runtime-1",
    }
    rows = []
    for line_id, heading, strength, x_coord in (
            ("discovery", 0.0, 1.0, 5.0),
            ("repeat", 90.0, 2.0, 5.0)):
        for trace in range(2):
            fields = dict(common)
            fields.update({
                "line_id": line_id,
                "trace_id": "%s-%d" % (line_id, trace),
                "heading_deg": heading,
                "voxel_en_m": [x_coord, float(trace)],
                "linear_excess": strength,
                "beam_angle_deg": 12.0,
                "beam_fixed_streak_en_m": [
                    25.0 if line_id == "discovery" else -25.0,
                    float(trace),
                ],
                "broad_layer_linear_excess": 0.25,
                "bottom_contaminated": trace == 0,
                "source_id": "MWC-%s-%d" % (line_id, trace),
                "holdout": line_id == "repeat",
                "limitations": [
                    "shared_ek_em_parent",
                    "fixed_current_assumption",
                ],
            })
            rows.append({"timestamp": 1700000000.0 + len(rows), "fields": fields})
    return rows


def missing_coverage_records():
    """Return truth where the repeat slice is not observed, not zero strength."""
    rows = synthetic_records()
    for row in rows:
        if row["fields"]["line_id"] == "repeat":
            row["fields"]["coverage_mask"] = False
            row["fields"]["linear_excess"] = None
    return rows


def record_hash(records):
    """Hash records using a stable representation for mutation checks."""
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def demo_records():
    """Return an isolated copy suitable for a local Reader replacement."""
    return copy.deepcopy(synthetic_records())
