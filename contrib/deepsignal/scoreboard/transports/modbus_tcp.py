import socket

from ..contract import Transport, TransportError
from .modbus_rtu import _pdu, _validate_write
from .serial import _number


class ModbusTCPTransport(Transport):
    def __init__(self, **settings):
        values = {'port': 502, 'connect_timeout': 5.0, 'response_timeout': 1.0,
                  'inter_frame_delay': 0.0}
        values.update(settings)
        for key in values:
            if key not in ('host', 'port', 'connect_timeout', 'response_timeout',
                           'inter_frame_delay'):
                raise TransportError('invalid %s: %r' % (key, values[key]))
        if not isinstance(values.get('host'), str) or not values.get('host'):
            raise TransportError('invalid host: %r' % values.get('host'))
        if (isinstance(values['port'], bool) or not isinstance(values['port'], int)
                or not 1 <= values['port'] <= 65535):
            raise TransportError('invalid port: %r' % values['port'])
        for key in ('connect_timeout', 'response_timeout', 'inter_frame_delay'):
            _number(key, values[key])
        super().__init__(**values)
        self.connection = None
        self.transaction_id = 0

    def open(self):
        if self.connection is None:
            try:
                self.connection = socket.create_connection(
                    (self.settings['host'], self.settings['port']),
                    self.settings['connect_timeout'])
                self.connection.settimeout(self.settings['response_timeout'])
            except OSError as error:
                self.close()
                raise TransportError('Modbus TCP connection failed: %s' % error) from error

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            connection.close()

    def _read_exact(self, count):
        data = b''
        while len(data) < count:
            chunk = self.connection.recv(count - len(data))
            if not chunk:
                raise TransportError('short Modbus TCP reply')
            data += chunk
        return data

    def _reply(self, write, transaction):
        header = self._read_exact(7)
        reply_transaction = int.from_bytes(header[:2], 'big')
        protocol = int.from_bytes(header[2:4], 'big')
        length = int.from_bytes(header[4:6], 'big')
        if protocol != 0 or reply_transaction != transaction or header[6] != write.unit:
            raise TransportError('invalid Modbus TCP reply header')
        if length < 2 or length > 254:
            raise TransportError('invalid Modbus TCP reply length: %d' % length)
        payload = self._read_exact(length - 1)
        if payload[0] == 0x90:
            if len(payload) != 2:
                raise TransportError('invalid Modbus TCP exception reply')
            raise TransportError('Modbus exception code 0x%02X' % payload[1])
        expected = (bytes([0x10]) + write.address.to_bytes(2, 'big')
                    + len(write.values).to_bytes(2, 'big'))
        if payload != expected:
            raise TransportError('Modbus TCP reply does not match request')

    def send(self, frames):
        for frame in frames:
            _validate_write(frame)
        try:
            self.open()
            for index, write in enumerate(frames):
                self.transaction_id = self.transaction_id % 65535 + 1
                pdu = _pdu(write)
                header = (self.transaction_id.to_bytes(2, 'big') + b'\x00\x00'
                          + (len(pdu) + 1).to_bytes(2, 'big') + bytes([write.unit]))
                self.connection.sendall(header + pdu)
                self._reply(write, self.transaction_id)
                if index + 1 < len(frames):
                    self.sleep(self.settings['inter_frame_delay'])
        except TransportError:
            self.close()
            raise
        except (OSError, TimeoutError) as error:
            self.close()
            raise TransportError('Modbus TCP send failed: %s' % error) from error


TRANSPORT = ModbusTCPTransport
