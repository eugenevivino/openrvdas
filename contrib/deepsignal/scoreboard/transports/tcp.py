import socket

from ..contract import RegisterWrite, Transport, TransportError
from .serial import _number


class TCPTransport(Transport):
    def __init__(self, **settings):
        values = {'connect_timeout': 5.0, 'send_timeout': 5.0,
                  'inter_frame_delay': 0.0}
        values.update(settings)
        for key in values:
            if key not in ('host', 'port', 'connect_timeout', 'send_timeout',
                           'inter_frame_delay'):
                raise TransportError('invalid %s: %r' % (key, values[key]))
        if not isinstance(values.get('host'), str) or not values.get('host'):
            raise TransportError('invalid host: %r' % values.get('host'))
        if (isinstance(values.get('port'), bool) or not isinstance(values.get('port'), int)
                or not 1 <= values['port'] <= 65535):
            raise TransportError('invalid port: %r' % values.get('port'))
        for key in ('connect_timeout', 'send_timeout', 'inter_frame_delay'):
            _number(key, values[key])
        super().__init__(**values)
        self.connection = None

    def open(self):
        if self.connection is None:
            try:
                self.connection = socket.create_connection(
                    (self.settings['host'], self.settings['port']),
                    self.settings['connect_timeout'])
                self.connection.settimeout(self.settings['send_timeout'])
            except OSError as error:
                self.close()
                raise TransportError('TCP connection failed: %s' % error) from error

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            connection.close()

    def send(self, frames):
        if any(isinstance(frame, RegisterWrite) or not isinstance(frame, bytes)
               for frame in frames):
            raise TransportError('TCP transport requires bytes frames')
        try:
            self.open()
            for index, frame in enumerate(frames):
                self.connection.sendall(frame)
                if index + 1 < len(frames):
                    self.sleep(self.settings['inter_frame_delay'])
        except TransportError:
            self.close()
            raise
        except OSError as error:
            self.close()
            raise TransportError('TCP send failed: %s' % error) from error


TRANSPORT = TCPTransport
