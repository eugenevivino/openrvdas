import serial
import serial.rs485

from ..contract import TransportError
from .serial import SERIAL_DEFAULTS, SerialTransport, _number, validate_serial


RS485_DEFAULTS = {
    'rts_level_for_tx': True, 'rts_level_for_rx': False,
    'delay_before_tx': None, 'delay_before_rx': None,
}


class RS485Transport(SerialTransport):
    def __init__(self, **settings):
        values = dict(SERIAL_DEFAULTS)
        values.update(RS485_DEFAULTS)
        values.update(settings)
        validate_serial(values, RS485_DEFAULTS)
        for key in ('rts_level_for_tx', 'rts_level_for_rx'):
            if not isinstance(values[key], bool):
                raise TransportError('invalid %s: %r' % (key, values[key]))
        for key in ('delay_before_tx', 'delay_before_rx'):
            _number(key, values[key], allow_none=True)
        serial_keys = set(SERIAL_DEFAULTS) | {'port'}
        super().__init__(**{key: values[key] for key in serial_keys})
        self.settings.update({key: values[key] for key in RS485_DEFAULTS})

    def _rs485_settings(self, settings_class=serial.rs485.RS485Settings):
        return settings_class(
            rts_level_for_tx=self.settings['rts_level_for_tx'],
            rts_level_for_rx=self.settings['rts_level_for_rx'],
            loopback=False,
            delay_before_tx=self.settings['delay_before_tx'],
            delay_before_rx=self.settings['delay_before_rx'])

    def open(self):
        if self.connection is not None:
            return
        super().open()
        try:
            self.connection.rs485_mode = self._rs485_settings()
        except Exception as error:
            self.close()
            raise TransportError(
                'RS-485 direction control unsupported; use type: serial with an '
                'auto-direction adapter: %s' % error) from error


TRANSPORT = RS485Transport
