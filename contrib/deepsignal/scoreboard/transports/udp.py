import socket

from ..contract import RegisterWrite, Transport, TransportError
from .serial import _number


class UDPTransport(Transport):
    def __init__(self, **settings):
        values = {'broadcast': False, 'inter_frame_delay': 0.0}
        values.update(settings)
        for key in values:
            if key not in ('host', 'port', 'broadcast', 'inter_frame_delay'):
                raise TransportError('invalid %s: %r' % (key, values[key]))
        if not isinstance(values.get('host'), str) or not values.get('host'):
            raise TransportError('invalid host: %r' % values.get('host'))
        if (isinstance(values.get('port'), bool) or not isinstance(values.get('port'), int)
                or not 1 <= values['port'] <= 65535):
            raise TransportError('invalid port: %r' % values.get('port'))
        if not isinstance(values['broadcast'], bool):
            raise TransportError('invalid broadcast: %r' % values['broadcast'])
        _number('inter_frame_delay', values['inter_frame_delay'])
        super().__init__(**values)
        self.connection = None

    def open(self):
        if self.connection is None:
            try:
                self.connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                if self.settings['broadcast']:
                    self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except OSError as error:
                self.close()
                raise TransportError('UDP open failed: %s' % error) from error

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            connection.close()

    def send(self, frames):
        if any(isinstance(frame, RegisterWrite) or not isinstance(frame, bytes)
               for frame in frames):
            raise TransportError('UDP transport requires bytes frames')
        try:
            self.open()
            destination = (self.settings['host'], self.settings['port'])
            for index, frame in enumerate(frames):
                sent = self.connection.sendto(frame, destination)
                if sent != len(frame):
                    raise OSError('short datagram send')
                if index + 1 < len(frames):
                    self.sleep(self.settings['inter_frame_delay'])
        except TransportError:
            self.close()
            raise
        except OSError as error:
            self.close()
            raise TransportError('UDP send failed: %s' % error) from error


TRANSPORT = UDPTransport
