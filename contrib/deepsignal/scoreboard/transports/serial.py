import serial

from ..contract import RegisterWrite, Transport, TransportError


SERIAL_DEFAULTS = {
    'baudrate': 9600, 'bytesize': 8, 'parity': 'N', 'stopbits': 1,
    'xonxoff': False, 'rtscts': False, 'write_timeout': 2.0, 'exclusive': True,
    'inter_frame_delay': 0.0,
}


def _error(key, value):
    raise TransportError('invalid %s: %r' % (key, value))


def _number(key, value, minimum=0, allow_none=False):
    if allow_none and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        _error(key, value)


def validate_serial(settings, extra=None):
    allowed = set(SERIAL_DEFAULTS) | {'port'} | set(extra or ())
    for key in settings:
        if key not in allowed:
            _error(key, settings[key])
    if not isinstance(settings.get('port'), str) or not settings.get('port'):
        _error('port', settings.get('port'))
    for key in ('baudrate', 'bytesize'):
        if isinstance(settings[key], bool) or not isinstance(settings[key], int):
            _error(key, settings[key])
    if settings['baudrate'] <= 0:
        _error('baudrate', settings['baudrate'])
    if settings['bytesize'] not in range(5, 9):
        _error('bytesize', settings['bytesize'])
    if settings['parity'] not in ('N', 'E', 'O', 'M', 'S'):
        _error('parity', settings['parity'])
    if settings['stopbits'] not in (1, 1.5, 2) or isinstance(settings['stopbits'], bool):
        _error('stopbits', settings['stopbits'])
    for key in ('xonxoff', 'rtscts', 'exclusive'):
        if not isinstance(settings[key], bool):
            _error(key, settings[key])
    _number('write_timeout', settings['write_timeout'])
    _number('inter_frame_delay', settings['inter_frame_delay'])


class SerialTransport(Transport):
    def __init__(self, **settings):
        values = dict(SERIAL_DEFAULTS)
        values.update(settings)
        validate_serial(values)
        super().__init__(**values)
        self.connection = None

    def open(self):
        if self.connection is not None:
            return
        options = {key: self.settings[key] for key in SERIAL_DEFAULTS
                   if key != 'inter_frame_delay'}
        options['port'] = self.settings['port']
        try:
            self.connection = serial.Serial(**options)
        except Exception as error:
            self.close()
            raise TransportError('could not open serial port: %s' % error) from error

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception as error:
                raise TransportError('could not close serial port: %s' % error) from error

    def send(self, frames):
        for frame in frames:
            if isinstance(frame, RegisterWrite) or not isinstance(frame, bytes):
                raise TransportError('serial transport requires bytes frames')
        try:
            self.open()
            for index, frame in enumerate(frames):
                self.connection.write(frame)
                if index + 1 < len(frames):
                    self.sleep(self.settings['inter_frame_delay'])
        except TransportError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise TransportError('serial send failed: %s' % error) from error


TRANSPORT = SerialTransport
