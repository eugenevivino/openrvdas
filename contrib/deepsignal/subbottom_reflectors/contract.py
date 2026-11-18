"""Validation and output field declarations for decoded SBP traces."""

TRACE_KEYS = frozenset({
    "trace_id", "x_m", "y_m", "time_utc", "delay_s", "dt_s", "samples",
    "representation", "source_hash", "bottom_twt_s", "bottom_sd_s",
    "pulse_resolution_s",
})

RESULT_FIELDS = tuple("SBPH_" + name for name in (
    "TraceId", "HorizonId", "PickTWT_s", "SupportCount", "EnergyMargin",
    "Alternative", "Gap", "Resolution_s", "Score", "Verdict", "Reason",
    "Support", "Persistence", "SourceIds", "Stale", "Excluded",
))


def validate_trace_shape(trace):
    """Return missing contract keys without allocating estimator state."""
    return TRACE_KEYS.difference(trace)
