"""Immutable records at the weighted-depth estimator boundary."""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Observation:
    """One validated observation and the evidence needed to reproduce it."""

    source: str
    family: str
    event_time: float
    depth_m: float
    uncertainty_m: float
    footprint_m: Tuple[float, float]
    parent_ids: Tuple[str, ...]
    shared_loadings: Tuple[float, ...] = ()
    datum: Optional[str] = None

    def __post_init__(self):
        """Reject mutable ancestry and malformed footprint values."""
        if not isinstance(self.parent_ids, tuple):
            raise TypeError("parent_ids must be an immutable tuple")
        if len(self.footprint_m) != 2:
            raise ValueError("footprint_m must contain along/across dimensions")
