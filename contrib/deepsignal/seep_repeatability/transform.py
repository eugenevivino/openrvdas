"""OpenRVDAS transform adapter for seep repeatability evidence."""

try:
    from logger.transforms.transform import Transform
except ImportError:
    from openrvdas.logger.transforms.transform import Transform

from .estimator import estimate_repeatability


class SeepRepeatabilityTransform(Transform):
    """Collect a documented window and emit one derived evidence record."""

    def __init__(self, **options):
        super().__init__()
        self.options = dict(options)

    def transform(self, record):
        """Pass None through and delegate supported records to the estimator."""
        if record is None:
            return None
        return estimate_repeatability(record, **self.options)
