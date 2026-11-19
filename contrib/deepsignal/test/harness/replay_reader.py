"""Replay archived fixture records against a shared source clock."""

import fcntl
import logging
import time

from logger.readers.reader import Reader
from logger.readers.text_file_reader import TextFileReader
from logger.utils import timestamp
from logger.utils.formats import Text


class ReplayReader(Reader):
    def __init__(self, filebase, epoch_file, speed):
        super().__init__(output_format=Text)
        self.reader = TextFileReader(file_spec=filebase, tail=True)
        self.epoch_file = epoch_file
        self.speed = float(speed)
        self.epoch = None

    def _read_epoch(self, source_time):
        with open(self.epoch_file, "r+", encoding="ascii") as clock:
            fcntl.flock(clock.fileno(), fcntl.LOCK_EX)
            epoch = clock.read()
            if epoch:
                return tuple(map(float, epoch.split()))
            # The first valid record to reach this point starts all replay clocks.
            wall, monotonic = time.time(), time.monotonic()
            clock.write(f"{source_time} {wall} {monotonic}\n")
            return source_time, wall, monotonic

    def read(self):
        while (record := self.reader.read()) is not None:
            try:
                data_id, stamp, payload = record.split(" ", 2)
                source_time = timestamp.timestamp(stamp)
            except ValueError:
                logging.warning("Invalid fixture replay record: %r", record)
                continue

            if self.epoch is None:
                self.epoch = self._read_epoch(source_time)
            origin, wall, monotonic = self.epoch
            offset = (source_time - origin) / self.speed
            wait = monotonic + offset - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            # Late reads keep their scheduled source timestamp so lag remains visible.
            return f"{data_id} {timestamp.time_str(wall + offset)} {payload}"
        return None
