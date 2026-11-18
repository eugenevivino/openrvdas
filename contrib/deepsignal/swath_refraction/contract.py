"""Versioned record names for swath-refraction observations."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "deepsignal.swath_refraction/v1"
RESULT_FIELDS = (
    "REFR_ModeVector",
    "REFR_ModeAmplitude_mps",
    "REFR_ModeSD_mps",
    "REFR_DataRank",
    "REFR_VisibleModes",
    "REFR_OuterResidual_m",
    "REFR_LikelihoodInfo",
    "REFR_PriorId",
    "REFR_CrossingIds",
    "REFR_Score",
    "REFR_Verdict",
    "REFR_Reason",
    "REFR_Support",
    "REFR_Persistence",
    "REFR_SourceIds",
    "REFR_Stale",
    "REFR_Excluded",
)


@dataclass(frozen=True)
class EstimateResult:
    """Typed result used by the transform and estimator boundary."""

    mode_vector: Sequence[float] | None
    mode_amplitude_mps: float | None
    mode_sd_mps: float | None
    data_rank: int
    visible_modes: int
    outer_residual_m: float | None
    likelihood_info: Mapping[str, Any] | None
    prior_id: str | None
    crossing_ids: Sequence[str]
    score: float | None
    verdict: str
    reason: str
    support: Mapping[str, Any]
    persistence: Mapping[str, Any]
    source_ids: Sequence[str]
    stale: bool
    excluded: Sequence[Mapping[str, Any]]

    def as_fields(self) -> dict[str, Any]:
        """Return namespaced, JSON-safe result fields."""
        values = (
            self.mode_vector,
            self.mode_amplitude_mps,
            self.mode_sd_mps,
            self.data_rank,
            self.visible_modes,
            self.outer_residual_m,
            self.likelihood_info,
            self.prior_id,
            list(self.crossing_ids),
            self.score,
            self.verdict,
            self.reason,
            dict(self.support),
            dict(self.persistence),
            list(self.source_ids),
            self.stale,
            list(self.excluded),
        )
        return dict(zip(RESULT_FIELDS, values))
