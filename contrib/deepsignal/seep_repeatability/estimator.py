"""Numerical interface for the repeatability estimator.

The implementation is intentionally deferred to the numerical implementation lane.
"""


def fit_amplitude(y, template, covariance, prior_precision=0.0):
    """Return non-negative amplitude and penalized gain."""
    raise NotImplementedError("estimator implementation belongs to the numerical lane")


def heading_separation(first_deg, second_deg):
    """Return the wrapped absolute heading separation in degrees."""
    raise NotImplementedError("estimator implementation belongs to the numerical lane")


def null_p_value(observed, null_maxima):
    """Return the finite-sample empirical upper-tail probability."""
    raise NotImplementedError("estimator implementation belongs to the numerical lane")


def estimate_repeatability(records, **options):
    """Estimate a shared anchor and independent pass strengths."""
    raise NotImplementedError("estimator implementation belongs to the numerical lane")
