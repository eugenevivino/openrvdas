import pytest

from contrib.deepsignal.scoreboard import contract


def profile(**changes):
    values = {
        'name': 'test-text',
        'codec': 'text',
        'limits': {'lines': 1, 'chars_per_line': 16},
        'framing': {'template': r'{line}\r\n'},
    }
    values.update(changes)
    return contract.Profile(**values)


def page(*lines):
    return contract.Page([[contract.Cell(None, text)] for text in lines])


def codec(**changes):
    from contrib.deepsignal.scoreboard.codecs.text import TextCodec

    return TextCodec(profile(**changes))


def test_plain_text_golden_vector():
    assert codec().encode(page('HELLO')) == [b'HELLO\r\n']


def test_address_and_checksum_golden_vector():
    framing = {
        'template': r'\x02{address:02d}{line}\x03{checksum}',
        'checksum': 'xor8',
        'checksum_format': 'hex2',
        'checksum_from': r'\x02',
    }
    addressing = {'default': 1, 'range': [0, 99]}
    assert codec(framing=framing, addressing=addressing).encode(page(' 12.3')) == [
        b'\x0201 12.3\x033E'
    ]


@pytest.mark.parametrize(('charset', 'text', 'expected'), [
    ('digits_sign_point', '12a.5', b'12?.5\r\n'),
    ('upper', 'knots', b'KNOTS\r\n'),
])
def test_charset_golden_vectors(charset, text, expected):
    limits = {'lines': 1, 'chars_per_line': 16, 'charset': charset}
    assert codec(limits=limits).encode(page(text)) == [expected]


def test_page_frame_joins_lines_and_exposes_numbered_lines():
    limits = {'lines': 2, 'chars_per_line': 8}
    framing = {
        'template': r'{line1}|{line2}|{page}\n',
        'frame_per': 'page',
        'line_separator': r'\r',
    }
    assert codec(limits=limits, framing=framing).encode(page('ONE', 'TWO')) == [
        b'ONE|TWO|ONE\rTWO\n'
    ]


def test_missing_page_lines_are_empty():
    limits = {'lines': 2, 'chars_per_line': 8}
    framing = {'template': '{line1}/{line2}', 'frame_per': 'page'}
    assert codec(limits=limits, framing=framing).encode(page('ONE')) == [b'ONE/']


def test_too_long_line_and_too_many_lines_raise():
    with pytest.raises(contract.ScoreboardError, match='line 1'):
        codec(limits={'lines': 1, 'chars_per_line': 3}).encode(page('LONG'))
    with pytest.raises(contract.ScoreboardError, match='lines'):
        codec().encode(page('ONE', 'TWO'))


def test_missing_and_out_of_range_addresses_raise():
    framing = {'template': '{address}:{line}'}
    with pytest.raises(contract.ScoreboardError, match='address'):
        codec(framing=framing)
    with pytest.raises(contract.ScoreboardError, match='address'):
        codec(framing=framing, addressing={'range': [1, 4], 'default': 5})


def test_checksum_format_conversion_is_rejected():
    with pytest.raises(contract.ProfileError, match='checksum'):
        codec(framing={'template': '{line}{checksum:x}'})


def test_checksum_from_must_exist():
    framing = {
        'template': '{line}{checksum}',
        'checksum': 'sum8',
        'checksum_format': 'hex2',
        'checksum_from': 'missing',
    }
    with pytest.raises(contract.ScoreboardError, match='checksum_from'):
        codec(framing=framing).encode(page('DATA'))


@pytest.mark.parametrize('name', contract.CHECKSUM_NAMES)
def test_each_checksum_name_round_trips_through_contract(name):
    framing = {
        'template': '{line}{checksum}',
        'checksum': name,
        'checksum_format': 'hex4',
    }
    expected = contract.format_checksum(contract.checksum(b'abc', name), 'hex4')
    assert codec(framing=framing).encode(page('abc')) == [b'abc' + expected]


def test_init_frames_are_unescaped_bytes():
    assert codec(init_frames=[r'\x02INIT\r', r'END\n']).init() == [b'\x02INIT\r', b'END\n']


def test_registry_exports_text_codec():
    from contrib.deepsignal.scoreboard.codecs.text import TextCodec

    assert contract.codec_class('text') is TextCodec


def test_stale_cell_text_passes_through_unchanged():
    stale_page = contract.Page([[contract.Cell('wind', '----', value=12, stale=True)]])
    assert codec().encode(stale_page) == [b'----\r\n']
