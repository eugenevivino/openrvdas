"""Numerical estimator boundary.

The implementation is intentionally reserved for the sequential numerical
review lane. The executable tests define the required behavior.
"""


class SwathRefractionEstimator:
    """Estimate observable sound-speed modes from independent crossings."""

    def solve(self, **observations):
        """Solve a validated crossing set."""
        raise NotImplementedError("estimator implementation is the next lane")

    def trace_constant_layer(self, **ray):
        """Trace one fixed-geometry ray in a constant layer."""
        raise NotImplementedError("ray tracing implementation is the next lane")


def projected_information(*, residual_m, jacobian, nuisance, covariance,
                          prior_covariance):
    """Return projected local-quadratic information and observability."""
    raise NotImplementedError("projection implementation is the next lane")
