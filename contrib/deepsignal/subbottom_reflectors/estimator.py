"""Public pure-estimator API for sub-bottom reflector tracking."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class EstimatorConfig:
    """Configuration values and units fixed by the science contract."""

    contrast_threshold: float = 1.0
    minimum_support: int = 5
    gap_penalty: float = 2.0
    gap_entry_penalty: float = 2.0
    maximum_primary_dip_s_per_m: float = 0.0002
    lag_scale_s_per_m: float = 0.0001
    max_missing_run: int = 3
    multiple_orders: tuple[int, ...] = (2, 3)


def estimate_reflectors(
        traces: Sequence[Mapping[str, Any]],
        config: EstimatorConfig | None = None) -> list[dict[str, Any]]:
    """Estimate reflector tracks from decoded traces.

    The implementation is deliberately deferred to the numerical owner. The
    cloud lane publishes this signature so RED tests exercise the future API.
    """
    raise NotImplementedError("sub-bottom reflector estimator is not implemented")
