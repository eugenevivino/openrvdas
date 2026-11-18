"""Public estimator interfaces for quality-weighted depth."""


class FamilyContrastEstimator:
    """Learn private family variances and relative biases from clean blocks."""

    def __init__(self, variance_floors=None, prior_variances=None,
                 minimum_blocks=20, maximum_blocks=120,
                 bootstrap_resamples=999, bootstrap_minimum_blocks=30,
                 bootstrap_seed=17001, outlier_mad_cutoff=5.0,
                 trim=None, trim_consistency_factor=None,
                 trim_noise_law=None):
        self.variance_floors = variance_floors or {}
        self.prior_variances = prior_variances or {}
        self.minimum_blocks = minimum_blocks
        self.maximum_blocks = maximum_blocks
        self.bootstrap_resamples = bootstrap_resamples
        self.bootstrap_minimum_blocks = bootstrap_minimum_blocks
        self.bootstrap_seed = bootstrap_seed
        self.outlier_mad_cutoff = outlier_mad_cutoff
        self.trim = trim
        self.trim_consistency_factor = trim_consistency_factor
        self.trim_noise_law = trim_noise_law

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
