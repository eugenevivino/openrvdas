"""OpenRVDAS transform entry point for crossing-swath observations."""

try:
    from logger.transforms.transform import Transform
    from logger.utils import formats
except ImportError:
    from openrvdas.logger.transforms.transform import Transform
    from openrvdas.logger.utils import formats

from .estimator import SwathRefractionEstimator


class SwathRefractionTransform(Transform):
    """Bounded derived-observation transform. Numerical work is stubbed."""

    def __init__(self, max_angular_bins=32, max_matched_cells=128,
                 minimum_solve_interval_s=30.0, **kwargs):
        super().__init__(input_format=formats.Python_Record,
                         output_format=formats.Python_Record)
        if not 1 <= max_angular_bins <= 32:
            raise ValueError("max_angular_bins must be in [1, 32]")
        if not 1 <= max_matched_cells <= 128:
            raise ValueError("max_matched_cells must be in [1, 128]")
        if minimum_solve_interval_s < 30.0:
            raise ValueError("minimum_solve_interval_s must be at least 30")
        self.max_angular_bins = max_angular_bins
        self.max_matched_cells = max_matched_cells
        self.minimum_solve_interval_s = minimum_solve_interval_s
        self.estimator = SwathRefractionEstimator()

    def transform(self, record):
        """Pass None through; numerical handling is supplied next lane."""
        if record is None:
            return None
        raise NotImplementedError("record estimation is the next lane")
