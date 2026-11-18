"""OpenRVDAS transform wrapper for the normalized sounding estimator."""

try:
    from logger.transforms.transform import Transform
except ImportError:
    from openrvdas.logger.transforms.transform import Transform

from .estimator import estimate_sounding


class SoundingUncertaintyTransform(Transform):
    """Pass records to the estimator while retaining their original content."""

    def __init__(self, calibration=None):
        super().__init__()
        self.calibration = calibration

    def transform(self, record):
        """Pass None through and estimate dicts, DASRecords, or lists of either."""
        if record is None:
            return None
        records = record if isinstance(record, list) else [record]
        return [self._transform_one(item) for item in records]

    def _transform_one(self, record):
        return estimate_sounding(record, self.calibration)
