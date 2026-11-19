"""Replay archived fixture records against a shared source clock."""

import fcntl
import logging
from threading import Event
import time

from logger.readers.reader import Reader
from logger.readers.text_file_reader import TextFileReader
from logger.utils import timestamp
from logger.utils.formats import Text


class ReplayReader(Reader):
    def __init__(self, filebase, epoch_file, speed):
        super().__init__(output_format=Text)
        self.reader = TextFileReader(file_spec=filebase)
        self.epoch_file = epoch_file
        self.speed = float(speed)
        self.epoch = None
        self._stopped = Event()

    def quit(self):
        """Cancel the pending read and end replay."""
        self._stopped.set()

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
        while not self._stopped.is_set():
            record = self.reader.read()
            if record is None:
                # Prepared archives are immutable. Keep the worker idle at EOF
                # until shutdown, so the manager does not restart the stream.
                self._stopped.wait()
                return None
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
            deadline = monotonic + offset
            while (remaining := deadline - time.monotonic()) > 0:
                if self._stopped.wait(remaining):
                    return None
            if self._stopped.is_set():
                return None
            # Late reads keep their scheduled source timestamp so lag remains visible.
            return f"{data_id} {timestamp.time_str(wall + offset)} {payload}"
        return None
