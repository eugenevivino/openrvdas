"""Encode pages using the Alpha Communications Protocol Rev D.

The protocol uses at least five NUL sync bytes, SOH, a type and two-character
address, then an STX-delimited command. Write TEXT command ``A`` starts with a
file label and can include an ESC display mode. When ETX is present, four ASCII
hex digits contain the 16-bit sum from STX through ETX, inclusive, before EOT.
Type ``Z`` addresses all sign types and address ``00`` is broadcast.

The documented inter-byte limit is one second and Alpha 2.0 signs support 1200
to 38400 baud. Multi-line separation and display modes must be confirmed on a
bench before a profile is marked ``verified: bench``.
"""

from contrib.deepsignal.scoreboard import contract


def _charset(text, name, replace_char):
    """Apply the profile charset and prevent protocol-control injection."""
    if name == 'upper':
        text = text.upper()
    allowed = None
    if name == 'digits_sign_point':
        allowed = set('0123456789+-. ')
    return ''.join(
        char if 0x20 <= ord(char) <= 0x7E and
        (allowed is None or char in allowed) else replace_char
        for char in text
    )


def _one_byte(profile, key, value):
    try:
        encoded = value.encode('latin-1')
    except (AttributeError, UnicodeEncodeError):
        raise contract.ScoreboardError(
            '%s framing.%s must be one latin-1 character: %r'
            % (profile.name, key, value))
    if len(encoded) != 1:
        raise contract.ScoreboardError(
            '%s framing.%s must be one latin-1 character: %r'
            % (profile.name, key, value))
    return encoded


class AlphaCodec(contract.Codec):
    """Turn each rendered page into one Alpha Write TEXT frame."""

    def _address(self):
        value = self.address
        if value is None:
            value = self.profile.addressing.get('default', 0)
        if isinstance(value, str):
            if len(value) != 2:
                value = -1
            else:
                try:
                    value = int(value, 16)
                except ValueError:
                    value = -1
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise contract.ScoreboardError(
                '%s address must be 0..255 or two hex digits: %r'
                % (self.profile.name, value))
        return ('%02X' % value).encode('ascii')

    def encode(self, page):
        framing = self.profile.framing
        limits = self.profile.limits
        replace_char = limits.get('replace_char', '?')
        replace = _one_byte(self.profile, 'limits.replace_char', replace_char)
        if not 0x20 <= replace[0] <= 0x7E:
            raise contract.ScoreboardError(
                '%s limits.replace_char must be printable ASCII: %r'
                % (self.profile.name, replace_char))

        lines = []
        for index in range(len(page.lines)):
            line = _charset(page.line_text(index), limits.get('charset', 'ascii'), replace_char)
            if len(line) > limits['chars_per_line']:
                raise contract.ScoreboardError(
                    '%s line %d exceeds chars_per_line %d'
                    % (self.profile.name, index + 1, limits['chars_per_line']))
            lines.append(line.encode('ascii'))
        separator = contract.unescape(framing.get('line_separator', ' '))
        message = separator.join(lines)

        type_code = _one_byte(self.profile, 'type_code', framing.get('type_code', 'Z'))
        file_label = _one_byte(self.profile, 'file_label', framing.get('file_label', 'A'))
        sync_name = framing.get('sync', 'nul')
        if sync_name not in ('nul', 'soh'):
            raise contract.ScoreboardError(
                '%s framing.sync must be nul or soh: %r' % (self.profile.name, sync_name))
        sync = (b'\x00' if sync_name == 'nul' else b'\x01') * 5

        data = b'A' + file_label
        mode = framing.get('mode')
        if mode is not None:
            if not isinstance(mode, dict):
                raise contract.ScoreboardError(
                    '%s framing.mode must be a mapping' % self.profile.name)
            data += (b'\x1b' + _one_byte(self.profile, 'mode.position', mode.get('position'))
                     + _one_byte(self.profile, 'mode.code', mode.get('code')))
        data += message

        body = b'\x02' + data
        if framing.get('checksum', True):
            body += b'\x03'
            body += contract.format_checksum(contract.checksum(body, 'sum16'), 'hex4')
        frame = sync + b'\x01' + type_code + self._address() + body + b'\x04'
        return [frame]


CODEC = AlphaCodec
