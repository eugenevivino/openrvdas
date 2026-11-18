import time

from ..contract import RegisterWrite, TransportError, checksum
from .serial import SERIAL_DEFAULTS, SerialTransport, _number, validate_serial


def _validate_write(write):
    if not isinstance(write, RegisterWrite):
        raise TransportError('Modbus transport requires RegisterWrite frames')
    if (isinstance(write.unit, bool) or not isinstance(write.unit, int)
            or not 0 <= write.unit <= 255):
        raise TransportError('invalid unit: %r' % write.unit)
    if (isinstance(write.address, bool) or not isinstance(write.address, int)
            or not 0 <= write.address <= 65535):
        raise TransportError('invalid address: %r' % write.address)
    if not isinstance(write.values, list) or not 1 <= len(write.values) <= 123:
        raise TransportError('invalid values count: %r' % len(write.values))
    for value in write.values:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
            raise TransportError('invalid register value: %r' % value)


def _pdu(write):
    count = len(write.values)
    return (bytes([0x10]) + write.address.to_bytes(2, 'big') + count.to_bytes(2, 'big')
            + bytes([count * 2])
            + b''.join(value.to_bytes(2, 'big') for value in write.values))


class ModbusRTUTransport(SerialTransport):
    def __init__(self, **settings):
        values = dict(SERIAL_DEFAULTS)
        values['response_timeout'] = 1.0
        values.update(settings)
        validate_serial(values, {'response_timeout'})
        _number('response_timeout', values['response_timeout'])
        serial_keys = set(SERIAL_DEFAULTS) | {'port'}
        super().__init__(**{key: values[key] for key in serial_keys})
        self.settings['response_timeout'] = values['response_timeout']

    def open(self):
        super().open()
        self.connection.timeout = self.settings['response_timeout']

    def _read_reply(self, write):
        deadline = time.monotonic() + self.settings['response_timeout']
        reply = b''
        while len(reply) < 8 and time.monotonic() < deadline:
            reply += self.connection.read(8 - len(reply))
            if len(reply) >= 2 and reply[1] == 0x90 and len(reply) >= 5:
                break
        if len(reply) >= 2 and reply[1] == 0x90:
            if len(reply) != 5:
                raise TransportError('short Modbus RTU exception reply')
            self._check_crc(reply)
            raise TransportError('Modbus exception code 0x%02X' % reply[2])
        if len(reply) != 8:
            raise TransportError('Modbus RTU response timeout or short reply')
        self._check_crc(reply)
        expected = (bytes([write.unit, 0x10]) + write.address.to_bytes(2, 'big')
                    + len(write.values).to_bytes(2, 'big'))
        if reply[:6] != expected:
            raise TransportError('Modbus RTU reply does not match request')

    @staticmethod
    def _check_crc(reply):
        expected = checksum(reply[:-2], 'crc16_modbus').to_bytes(2, 'little')
        if reply[-2:] != expected:
            raise TransportError('bad Modbus RTU reply CRC')

    def send(self, frames):
        for frame in frames:
            _validate_write(frame)
        try:
            self.open()
            for index, write in enumerate(frames):
                body = bytes([write.unit]) + _pdu(write)
                request = body + checksum(body, 'crc16_modbus').to_bytes(2, 'little')
                self.connection.write(request)
                if write.unit:
                    self._read_reply(write)
                if index + 1 < len(frames):
                    self.sleep(self.settings['inter_frame_delay'])
        except TransportError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise TransportError('Modbus RTU send failed: %s' % error) from error


TRANSPORT = ModbusRTUTransport
