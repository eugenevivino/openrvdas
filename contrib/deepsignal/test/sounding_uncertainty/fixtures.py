"""Deterministic synthetic truth shared by unit and logger-chain tests."""

from copy import deepcopy

from contrib.deepsignal.sounding_uncertainty.contract import NormalizedSoundingPacket


DEVELOPMENT_SEED = 17001
FINAL_INJECTION_SEEDS = tuple(range(27001, 27021))


def vertical_packet(correlation=0.0, heave_up_m=0.0):
    """Return vertical truth with an explicitly upward-positive heave input."""
    # ``correlation`` describes the positive-down truth equation in the brief.
    # The packet carries upward-positive heave, so its covariance changes sign.
    covariance_t_heave = -correlation * 0.001 * 0.2
    return NormalizedSoundingPacket(
        event_time="2026-11-18T12:00:00Z", system_id="em-example",
        head_id="head-1", swath_id="single", ping_id="ping-0001",
        beam_id="beam-000", sector_id="sector-0",
        origin_enz_m=(0.0, 0.0, 5.0), launch_vector=(0.0, 0.0, 1.0),
        travel_time_s=0.1,
        pose={"roll_rad": 0.0, "pitch_rad": 0.0, "heading_rad": 0.0,
              "heave_up_m": heave_up_m, "speed_e_mps": 0.0,
              "speed_n_mps": 0.0},
        lever_arm_m=(0.0, 0.0, 0.0), q_names=("travel_time", "heave_up"),
        q_units=("s", "m"),
        covariance=((0.001 ** 2, covariance_t_heave),
                    (covariance_t_heave, 0.2 ** 2)),
        covariance_source_ids=("range-spec", "measured-motion"),
        static_installation_id="install-2026-01", datum="chart-datum",
        validity_mask=(True, True), detection_variance_m2=0.0,
        detection_independence_source_id="detector-test-independent")


def packet_dict(correlation=0.0):
    """Return a mutable record representation for immutability tests."""
    packet = vertical_packet(correlation)
    return deepcopy({"timestamp": packet.event_time, "fields": {
        "normalized_sounding": packet,
        "raw_bytes": "234d525a00ff",
        "existing_qc": {"quality": 1},
    }})


def calibration_samples(count=39):
    """Create one representative per independent line block."""
    return [{"block_id": "line-%02d" % index,
             "score": round(index / 10, 1), "holdout_id": None,
             "sounding_sd_m": 1.0, "reference_sd_m": 0.1,
             "regime": "nadir"} for index in range(1, count + 1)]
