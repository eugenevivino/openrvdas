"""OpenRVDAS transform adapter for sub-bottom reflector estimation."""

try:
    from logger.transforms.derived_data_transform import DerivedDataTransform
except ImportError:
    from logger.transforms.transform import Transform as DerivedDataTransform

from .estimator import EstimatorConfig, estimate_reflectors


class SubbottomReflectorsTransform(DerivedDataTransform):
    """Buffer decoded records and emit only closed-window derived results."""

    def __init__(self, **kwargs):
        super().__init__()
        self.config = EstimatorConfig(**kwargs)

    def transform(self, record):
        if record is None:
            return None
        records = record if isinstance(record, list) else [record]
        results = estimate_reflectors(records, self.config)
        return results if isinstance(record, list) else results[0]
