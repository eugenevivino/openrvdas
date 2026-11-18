"""Convert rendered scoreboard pages to Modbus register writes."""
import math
import numbers
import struct

from contrib.deepsignal.scoreboard import contract


_INTEGER_RANGES = {
    'int16': (-0x8000, 0x7FFF, 16),
    'uint16': (0, 0xFFFF, 16),
    'int32': (-0x80000000, 0x7FFFFFFF, 32),
    'uint32': (0, 0xFFFFFFFF, 32),
}


class ModbusCodec(contract.Codec):
    """Encode each configured cell as one register write."""

    def __init__(self, profile, address=None):
        super().__init__(profile, address)
        self.unit = profile.addressing.get('default') if address is None else address
        if (isinstance(self.unit, bool) or not isinstance(self.unit, int)
                or not 0 <= self.unit <= 247):
            raise contract.ScoreboardError(
                'profile "%s" unit id %r is outside 0..247'
                % (profile.name, self.unit)
            )

        self.registers = profile.framing.get('registers', [])
        self._stale_words = []
        for entry in self.registers:
            try:
                self._stale_words.append(
                    self._words(entry, entry['stale_value'], scale=False)
                )
            except (KeyError, TypeError, ValueError, OverflowError,
                    contract.ScoreboardError) as err:
                name = entry.get('name', '<unnamed>') if isinstance(entry, dict) else '<unnamed>'
                raise contract.ProfileError(
                    'profile "%s" register "%s" has invalid stale_value: %s'
                    % (profile.name, name, err)
                ) from err

    def init(self):
        return []

    def encode(self, page):
        writes = []
        for entry, stale_words in zip(self.registers, self._stale_words):
            cell = self._cell(page, entry)
            if cell is None or not self._valid_live_value(cell):
                words = list(stale_words)
            else:
                words = self._words(entry, cell.value, scale=True)
            writes.append(contract.RegisterWrite(self.unit, entry['address'], words))
        return writes

    @staticmethod
    def _cell(page, entry):
        try:
            line = entry['line'] - 1
            cell = entry['cell']
            if line < 0 or cell < 0:
                return None
            return page.lines[line][cell]
        except (IndexError, KeyError, TypeError):
            return None

    @staticmethod
    def _valid_live_value(cell):
        value = cell.value
        return (not cell.stale and not isinstance(value, bool)
                and isinstance(value, numbers.Real) and math.isfinite(value))

    def _words(self, entry, value, scale):
        name = entry.get('name', '<unnamed>')
        data_type = entry['type']
        if (isinstance(value, bool) or not isinstance(value, numbers.Real)
                or not math.isfinite(value)):
            raise contract.ScoreboardError(
                'register "%s" value %r is not a finite number' % (name, value)
            )

        converted = value * entry.get('scale', 1) if scale else value
        if not math.isfinite(converted):
            raise contract.ScoreboardError(
                'register "%s" value %r is not finite after scaling' % (name, value)
            )

        if data_type in _INTEGER_RANGES:
            converted = int(math.copysign(math.floor(abs(converted) + 0.5), converted))
            minimum, maximum, bits = _INTEGER_RANGES[data_type]
            if not minimum <= converted <= maximum:
                raise contract.ScoreboardError(
                    'register "%s" value %r becomes %r, outside %s range'
                    % (name, value, converted, data_type)
                )
            unsigned = converted & ((1 << bits) - 1)
            words = [unsigned] if bits == 16 else [unsigned >> 16, unsigned & 0xFFFF]
        elif data_type == 'float32':
            try:
                packed = struct.pack('>f', converted)
            except (OverflowError, struct.error) as err:
                raise contract.ScoreboardError(
                    'register "%s" value %r does not fit float32' % (name, value)
                ) from err
            words = list(struct.unpack('>HH', packed))
        else:
            raise contract.ScoreboardError(
                'register "%s" has unknown type %r' % (name, data_type)
            )

        order = entry.get('word_order', 'big')
        if order not in ('big', 'little'):
            raise contract.ScoreboardError(
                'register "%s" has unknown word_order %r' % (name, order)
            )
        if len(words) == 2 and order == 'little':
            words.reverse()
        return words


CODEC = ModbusCodec
