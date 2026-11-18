"""Profile-driven codec for scoreboards that accept text frames."""
import string

from contrib.deepsignal.scoreboard import contract


class TextCodec(contract.Codec):
    """Render pages using a profile's text framing template."""

    def __init__(self, profile, address=None):
        address = profile.addressing.get('default') if address is None else address
        super().__init__(profile, address)
        framing = profile.framing
        template = framing.get('template', '{line}')
        decoded = contract.unescape(template).decode('latin-1')
        self._has_checksum = '{checksum}' in decoded
        self._validate_checksum_placeholder(decoded)
        parts = decoded.split('{checksum}')
        if len(parts) > 2:
            raise contract.ProfileError(
                '%s template contains checksum more than once' % profile.name)
        self._head = parts[0]
        self._tail = parts[1] if self._has_checksum else ''
        self._frame_per = framing.get('frame_per', 'line')
        if self._frame_per not in ('line', 'page'):
            raise contract.ProfileError('%s framing.frame_per is %r' %
                                        (profile.name, self._frame_per))
        self._line_count = profile.limits['lines']
        allowed = {'address'}
        if self._frame_per == 'line':
            allowed.update(('line', 'line_number'))
        else:
            allowed.add('page')
            allowed.update('line%d' % number for number in range(1, self._line_count + 1))
        fields = self._validate_fields(self._head + self._tail, allowed)
        if 'address' in fields:
            self._validate_address()

    def _validate_checksum_placeholder(self, template):
        for _, field, spec, conversion in string.Formatter().parse(template):
            if field == 'checksum' and (spec or conversion):
                raise contract.ProfileError('%s template checksum must be exactly {checksum}' %
                                            self.profile.name)

    def _validate_fields(self, template, allowed):
        fields = set()
        try:
            parsed = string.Formatter().parse(template)
            for _, field, spec, _ in parsed:
                if field is None:
                    continue
                if '.' in field or '[' in field or field not in allowed:
                    raise contract.ProfileError('%s template field %r is not allowed' %
                                                (self.profile.name, field))
                if '{' in spec or '}' in spec:
                    raise contract.ProfileError('%s nested template fields are not allowed' %
                                                self.profile.name)
                fields.add(field)
        except ValueError as err:
            raise contract.ProfileError('%s invalid template: %s' % (self.profile.name, err))
        return fields

    def _validate_address(self):
        if self.address is None:
            raise contract.ScoreboardError('%s address is required by template' % self.profile.name)
        address_range = self.profile.addressing.get('range')
        if address_range is not None:
            low, high = address_range
            if not low <= self.address <= high:
                raise contract.ScoreboardError('%s address %r is outside range %r' %
                                               (self.profile.name, self.address, address_range))

    def init(self):
        return [contract.unescape(value) for value in self.profile.init_frames]

    def encode(self, page):
        if len(page.lines) > self._line_count:
            raise contract.ScoreboardError('%s page has %d lines; limit is %d' %
                                           (self.profile.name, len(page.lines), self._line_count))
        lines = [page.line_text(index) if index < len(page.lines) else ''
                 for index in range(self._line_count)]
        lines = [self._clean_line(value, index + 1) for index, value in enumerate(lines)]
        if self._frame_per == 'page':
            values = {'address': self.address}
            values.update(('line%d' % (index + 1), value)
                          for index, value in enumerate(lines))
            separator = contract.unescape(
                self.profile.framing.get('line_separator', '')).decode('latin-1')
            values['page'] = separator.join(lines)
            return [self._format(values)]
        return [self._format({'address': self.address, 'line': value,
                              'line_number': index + 1})
                for index, value in enumerate(lines)]

    def _clean_line(self, value, line_number):
        limits = self.profile.limits
        if len(value) > limits['chars_per_line']:
            raise contract.ScoreboardError('%s line %d has %d characters; limit is %d' %
                                           (self.profile.name, line_number, len(value),
                                            limits['chars_per_line']))
        charset = limits.get('charset', 'ascii')
        if charset == 'upper':
            value = value.upper()
            allowed_characters = None
        elif charset == 'ascii':
            allowed_characters = None
        elif charset == 'digits_sign_point':
            allowed_characters = '0123456789 -.+'
        else:
            raise contract.ProfileError('%s limits.charset is %r' %
                                        (self.profile.name, charset))
        replacement = limits.get('replace_char', '?')
        return ''.join(
            char if ((0x20 <= ord(char) <= 0x7E) if allowed_characters is None
                     else char in allowed_characters) else replacement
            for char in value)

    def _format(self, values):
        try:
            head = self._head.format(**values)
            tail = self._tail.format(**values)
        except (KeyError, ValueError, TypeError) as err:
            raise contract.ProfileError('%s template cannot be formatted: %s' %
                                        (self.profile.name, err))
        head_bytes = self._latin1(head)
        tail_bytes = self._latin1(tail)
        if not self._has_checksum:
            return head_bytes
        marker = contract.unescape(self.profile.framing.get('checksum_from', ''))
        start = 0 if not marker else head_bytes.find(marker)
        if start < 0:
            raise contract.ScoreboardError('%s checksum_from %r was not found' %
                                           (self.profile.name,
                                            self.profile.framing.get('checksum_from')))
        value = contract.checksum(head_bytes[start:],
                                  self.profile.framing.get('checksum', 'none'))
        checksum = contract.format_checksum(
            value, self.profile.framing.get('checksum_format', 'hex2'))
        return head_bytes + checksum + tail_bytes

    def _latin1(self, value):
        replacement = self.profile.limits.get('replace_char', '?')
        try:
            replacement.encode('latin-1')
        except UnicodeEncodeError:
            raise contract.ProfileError('%s replace_char %r is not latin-1' %
                                        (self.profile.name, replacement))
        return ''.join(char if ord(char) <= 255 else replacement
                       for char in value).encode('latin-1')


CODEC = TextCodec
