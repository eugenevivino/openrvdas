"""OpenRVDAS transform wrapper for quality-weighted depth."""

try:
    from logger.transforms.transform import Transform
except ImportError:
    from openrvdas.logger.transforms.transform import Transform

from contrib.deepsignal.weighted_depth.estimator import WeightedDepthEstimator


class WeightedDepthTransform(Transform):
    """Accept dict or DASRecord epochs and emit derived weighted-depth fields."""

    def __init__(self, sources=None, **settings):
        super().__init__()
        self.sources = sources or []
        self.settings = settings
        self.estimator = WeightedDepthEstimator(settings)

    def transform(self, record):
        """Pass None through; estimator implementation is supplied next lane."""
        if record is None:
            return None
        is_list = isinstance(record, list)
        records = record if is_list else [record]
        output = [self._transform_one(item) for item in records]
        return output if is_list else output[0]

    def _transform_one(self, record):
        """Map one input record to observations and estimate its epoch."""
        del record
        raise NotImplementedError("estimator implementation belongs to the next lane")
