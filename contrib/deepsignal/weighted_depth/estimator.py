"""Public estimator interfaces for quality-weighted depth."""


class FamilyContrastEstimator:
    """Learn private family variances and relative biases from clean blocks."""

    def __init__(self, variance_floors=None, prior_variances=None,
                 minimum_blocks=20, maximum_blocks=120):
        self.variance_floors = variance_floors or {}
        self.prior_variances = prior_variances or {}
        self.minimum_blocks = minimum_blocks
        self.maximum_blocks = maximum_blocks

    def fit(self, pair_blocks, residual_covariances=None):
        """Fit the declared pair-contrast model without fused-depth leakage."""
        del pair_blocks, residual_covariances
        raise NotImplementedError("estimator implementation belongs to the next lane")


class WeightedDepthEstimator:
    """Causal depth/rate estimator with duplicate and attribution gates."""

    def __init__(self, config=None):
        self.config = config or {}

    def estimate(self, observations, record_time, anchor=None):
        """Estimate one epoch from observations available by record_time."""
        del observations, record_time, anchor
        raise NotImplementedError("estimator implementation belongs to the next lane")
