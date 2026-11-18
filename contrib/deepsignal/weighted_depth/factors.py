"""Linear robust-fit API shared by weighted-depth estimators."""


def solve_linear(y, H, R, m, P, cutoff=1.5):
    """Return state, covariance, rank, and residuals for a robust linear fit.

    The implementation lane must use a symmetric eigendecomposition whitener.
    """
    del y, H, R, m, P, cutoff
    raise NotImplementedError("estimator implementation belongs to the next lane")
