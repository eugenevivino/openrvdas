"""Serial reader that initializes and reinitializes its instrument."""

import logging
import time
from collections import deque

try:
    from logger.readers.serial_reader import SerialReader, serial
except ImportError:
    from openrvdas.logger.readers.serial_reader import SerialReader, serial

from .profile import load_profile
from .runner import AuditLog, run


class _SerialTransport:
    def __init__(self, connection):
        self.connection = connection

    def write(self, data):
        return self.connection.write(data)

    def readline(self, timeout):
        previous = self.connection.timeout
        self.connection.timeout = timeout
        try:
            return self.connection.readline() or None
        finally:
            self.connection.timeout = previous


class InitSerialReader(SerialReader):
    """A ``SerialReader`` with reviewed initialization and reconnect."""

    def __init__(self, profile_file=None, audit_log=None, allow_unreviewed=False,
                 sleep=time.sleep, clock=time.monotonic, **kwargs):
        if profile_file is None:
            raise ValueError('profile_file is required; an unprofiled instrument is never opened')
        self.profile = load_profile(profile_file, allow_unreviewed=allow_unreviewed)
        self.audit = AuditLog(audit_log)
        self._sleep = sleep
        self._clock = clock
        self._serial_kwargs = dict(kwargs)
        self._runs = deque()
        self._last_data = clock()
        self._silence_ran = False
        self._unreviewed_warning = allow_unreviewed and not self.profile.get('reviewed_by')
        if self._unreviewed_warning:
            logging.warning('Running unreviewed profile %s', self.profile['profile_id'])
        super().__init__(**kwargs)
        self._initialize('open')

    def _allowed(self):
        now = self._clock()
        while self._runs and now - self._runs[0] >= 3600:
            self._runs.popleft()
        maximum = self.profile['reinit'].get('max_per_hour')
        if maximum is not None and len(self._runs) >= maximum:
            logging.error('Re-initialization cap reached for %s', self.profile['instrument'])
            return False
        self._runs.append(now)
        return True

    def _initialize(self, trigger):
        if trigger == 'open' or self._allowed():
            return run(self.profile, _SerialTransport(self.serial), trigger, self.audit)
        return None

    def _reopen(self):
        delay = 1
        while True:
            self._sleep(delay)
            try:
                self.serial = serial.Serial(**self._serial_kwargs)
                return
            except (serial.SerialException, serial.serialutil.SerialException):
                delay = min(delay * 2, 30)

    def read(self):
        try:
            if self.eol:
                raw = self.serial.read_until(expected=self.eol, size=self.max_bytes)
                raw = raw.rsplit(self.eol)[0]
            elif self.max_bytes:
                raw = self.serial.read(size=self.max_bytes)
            else:
                raw = self.serial.readline().rstrip()
            value = self._decode_bytes(raw) if raw else None
        except (serial.SerialException, serial.serialutil.SerialException):
            try:
                self.serial.close()
            except (AttributeError, OSError):
                pass
            value = None
        if value is not None:
            self._last_data = self._clock()
            self._silence_ran = False
            return value
        if not getattr(self.serial, 'is_open', True):
            self._reopen()
            if self.profile['reinit'].get('on_reconnect'):
                self._initialize('reconnect')
            self._last_data = self._clock()
        silence = self.profile['reinit'].get('after_silence_s')
        silent_too_long = (self._clock() - self._last_data >= silence
                           if silence is not None else False)
        if not self._silence_ran and silent_too_long:
            self._initialize('silence')
            self._silence_ran = True
        return None
