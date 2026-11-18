"""A small range check for exercising the benchmark without other QC modules."""

import math

from logger.transforms.transform import Transform
from logger.utils import formats


class StubThresholdDetector(Transform):
    """Flag values outside an inclusive range and report None as QARTOD missing."""

    DEFAULT_RANGES = {
        'MwxAirTemp': (18, 21),
        'MwxPIRCaseTemp': (285, 305),
        'MwxPortRelWindDir': (0, 360),
    }

    def __init__(self, minimum=None, maximum=None, flag_suffix='_QC'):
        super().__init__(input_format=formats.Python_Record, output_format=formats.Python_Record)
        for name, bound in (('minimum', minimum), ('maximum', maximum)):
            if bound is not None and (not isinstance(bound, (int, float)) or
                                      isinstance(bound, bool) or not math.isfinite(bound)):
                raise ValueError(f'{name} must be a finite number')
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError('minimum must be <= maximum')
        if not isinstance(flag_suffix, str) or not flag_suffix:
            raise ValueError('flag_suffix must be a nonempty string')
        self.minimum = minimum
        self.maximum = maximum
        self.flag_suffix = flag_suffix

    def transform(self, record):
        for field, value in list(record.fields.items()):
            minimum, maximum = self.minimum, self.maximum
            if minimum is None and maximum is None:
                minimum, maximum = self.DEFAULT_RANGES.get(field, (None, None))
            if (value is None or not isinstance(value, (int, float)) or
                    isinstance(value, bool) or not math.isfinite(value)):
                flag = 9
            elif minimum is None and maximum is None:
                flag = 2
            elif ((minimum is not None and value < minimum) or
                  (maximum is not None and value > maximum)):
                flag = 4
            else:
                flag = 1
            record.fields[field + self.flag_suffix] = flag
        return record
