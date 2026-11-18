"""Normalized record contract for sounding uncertainty estimation."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple


RESULT_FIELDS = (
    "TPU_SoundingId", "TPU_Cov_ENZ_m2", "TPU_VerticalSD_m",
    "TPU_Vertical95_m", "TPU_HorizontalAxes95_m",
    "TPU_HorizontalAzimuth_deg", "TPU_DominantTerm",
    "TPU_CalibrationId", "TPU_IntervalTarget", "TPU_Score",
    "TPU_Verdict", "TPU_Reason", "TPU_Support", "TPU_Persistence",
    "TPU_SourceIds", "TPU_Stale", "TPU_Excluded",
)


@dataclass(frozen=True)
class NormalizedSoundingPacket:
    """Immutable, unit-tagged input packet shared by live and offline paths."""

    event_time: str
    system_id: str
    head_id: str
    swath_id: str
    ping_id: str
    beam_id: str
    sector_id: str
    origin_enz_m: Tuple[float, float, float]
    launch_vector: Tuple[float, float, float]
    travel_time_s: float
    pose: Mapping[str, float]
    lever_arm_m: Tuple[float, float, float]
    q_names: Tuple[str, ...]
    q_units: Tuple[str, ...]
    covariance: Tuple[Tuple[float, ...], ...]
    covariance_source_ids: Tuple[str, ...]
    static_installation_id: str
    datum: str
    frame: str = "local_ENZ_positive_down"
    ray_model: str = "straight_homogeneous"
    validity_mask: Tuple[bool, ...] = ()
    profile_id: Optional[str] = None
    ancestry: Tuple[str, ...] = ()
    detection_variance_m2: float = 0.0
    detection_cross_covariance: Tuple[float, ...] = ()
    detection_independence_source_id: Optional[str] = None

    @property
    def sounding_id(self) -> str:
        """Return the stable, installation-qualified sounding identity."""
        parts = (self.system_id, self.head_id, self.swath_id, self.ping_id,
                 self.beam_id)
        return ":".join(parts)


def result_record(timestamp: Any, fields: Mapping[str, Any],
                  metadata: Optional[Mapping[str, Any]] = None) -> dict:
    """Build a derived record while enforcing the result prefix contract."""
    unknown = set(fields) - set(RESULT_FIELDS)
    if unknown:
        raise ValueError("Unknown or unprefixed TPU fields: %s" % sorted(unknown))
    return {
        "timestamp": timestamp,
        "fields": dict(fields),
        "metadata": dict(metadata or {}),
    }


def require_shape(values: Sequence[Any], length: int, label: str) -> None:
    """Reject malformed vectors before numerical allocation."""
    if len(values) != length:
        raise ValueError("%s must contain %d values" % (label, length))
