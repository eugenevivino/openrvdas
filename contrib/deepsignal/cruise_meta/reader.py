"""OpenRVDAS reader that periodically emits cruise context."""

import time
from datetime import datetime, timezone

from logger.readers.reader import Reader
from logger.utils import formats
from logger.utils.das_record import DASRecord

from . import cruise_day, is_active, load


class CruiseMetaReader(Reader):
    """Emit cruise id, day and active status at a fixed interval."""

    def __init__(self, path, interval=60, clock=time.time):
        super().__init__(output_format=formats.Python_Record)
        if interval <= 0:
            raise ValueError(
                f'interval saw {interval!r}; expected a positive number of seconds, for example 60')
        self.metadata = load(path)
        self.interval = interval
        self.clock = clock
        self._next_read = None

    def read(self):
        """Return a record when due, otherwise return None."""
        now = self.clock()
        if self._next_read is not None and now < self._next_read:
            return None
        self._next_read = now + self.interval
        timestamp = datetime.fromtimestamp(now, timezone.utc)
        fields = {
            'cruise_id': self.metadata['cruise_id'],
            'cruise_day': cruise_day(self.metadata, timestamp),
            'cruise_active': is_active(self.metadata, timestamp),
        }
        return DASRecord(timestamp=now, fields=fields)
