"""Public numerical entry points reserved for the sequential estimator lane."""

from typing import Any, Mapping, Sequence

from .contract import NormalizedSoundingPacket


def convert_covariance_units(covariance: Sequence[Sequence[float]],
                             units: Sequence[str]) -> tuple:
    """Convert a labeled covariance to the estimator's SI unit system."""
    raise NotImplementedError("Estimator implementation belongs to the Mac Astra lane")


def estimate_sounding(packet: NormalizedSoundingPacket,
                      calibration: Mapping[str, Any] | None = None) -> dict:
    """Propagate one normalized sounding packet into the TPU result schema."""
    raise NotImplementedError("Estimator implementation belongs to the Mac Astra lane")


def compare_crossline(first: Mapping[str, Any], second: Mapping[str, Any],
                      gradient_en: Sequence[float], match_sd_m: float) -> dict:
    """Compare two soundings without treating a difference as absolute truth."""
    raise NotImplementedError("Crossline implementation belongs to the Mac Astra lane")


def calibrate_vertical(samples: Sequence[Mapping[str, Any]], *, alpha: float,
                       seed: int, target: str = "single_vertical") -> dict:
    """Fit a frozen calibration table from independent block representatives."""
    raise NotImplementedError("Calibration implementation belongs to the Mac Astra lane")
