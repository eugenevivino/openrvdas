"""Outbound TCP reader with reviewed instrument initialization."""

import socket
import time
from collections import deque

try:
    from logger.readers.reader import Reader
except ImportError:
    from openrvdas.logger.readers.reader import Reader

from .profile import load_profile
from .runner import AuditLog, run


class _TCPTransport:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = b''

    def write(self, data):
        self.sock.sendall(data)

    def readline(self, timeout):
        self.sock.settimeout(timeout)
        while b'\n' not in self.buffer:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                return None
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b'\n', 1)
        return line + b'\n'


class InitTCPClientReader(Reader):
    def __init__(self, host, port, profile_file, audit_log, allow_unreviewed=False,
                 connect_timeout=10, encoding='utf-8', sleep=time.sleep,
                 clock=time.monotonic):
        super().__init__(encoding=encoding)
        self.host, self.port = host, port
        self.profile = load_profile(profile_file, allow_unreviewed=allow_unreviewed)
        self.audit, self.sleep, self.clock = AuditLog(audit_log), sleep, clock
        self.connect_timeout = connect_timeout
        self.runs, self.last_data, self.silence_ran = deque(), clock(), False
        self._connect()
        run(self.profile, self.transport, 'open', self.audit)

    def _connect(self):
        self.socket = socket.create_connection((self.host, self.port), self.connect_timeout)
        self.transport = _TCPTransport(self.socket)

    def _reinitialize(self, trigger):
        now = self.clock()
        while self.runs and now - self.runs[0] >= 3600:
            self.runs.popleft()
        maximum = self.profile['reinit'].get('max_per_hour')
        if maximum is None or len(self.runs) < maximum:
            self.runs.append(now)
            run(self.profile, self.transport, trigger, self.audit)

    def read(self):
        try:
            value = self.transport.readline(1)
        except OSError:
            delay = 1
            while True:
                self.sleep(delay)
                try:
                    self._connect()
                    break
                except OSError:
                    delay = min(delay * 2, 30)
            if self.profile['reinit'].get('on_reconnect'):
                self._reinitialize('reconnect')
            return None
        if value:
            self.last_data, self.silence_ran = self.clock(), False
            return self._decode_bytes(value.rstrip())
        silence = self.profile['reinit'].get('after_silence_s')
        silent_too_long = self.clock() - self.last_data >= silence if silence is not None else False
        if not self.silence_ran and silent_too_long:
            self._reinitialize('silence')
            self.silence_ran = True
        return None
