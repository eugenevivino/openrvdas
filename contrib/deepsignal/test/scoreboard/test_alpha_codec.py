import pytest

from contrib.deepsignal.scoreboard import contract
from contrib.deepsignal.scoreboard.codecs.alpha import AlphaCodec


def profile(**framing):
    settings = {'type_code': 'Z', 'file_label': 'A', 'checksum': True}
    settings.update(framing)
    return contract.Profile(
        name='test-alpha', codec='alpha',
        limits={'chars_per_line': 8, 'charset': 'upper', 'replace_char': '?'},
        framing=settings, addressing={'default': 1})


def page(*lines):
    return contract.Page([[contract.Cell(None, text)] for text in lines])


def test_golden_vector():
    frame = AlphaCodec(profile()).encode(page('HELLO'))[0]
    assert frame.hex(' ').upper() == (
        '00 00 00 00 00 01 5A 30 31 02 41 41 48 45 4C 4C 4F 03 30 31 46 42 04')


def test_checksum_false_omits_etx_and_checksum():
    assert AlphaCodec(profile(checksum=False)).encode(page('HELLO'))[0].endswith(b'HELLO\x04')


def test_soh_sync():
    assert AlphaCodec(profile(sync='soh')).encode(page('HELLO'))[0].startswith(b'\x01' * 6)


def test_mode_precedes_message():
    frame = AlphaCodec(profile(mode={'position': 'b', 'code': 'n'})).encode(page('HELLO'))[0]
    assert b'AA\x1bbnHELLO' in frame


def test_hex_and_integer_addresses_match():
    assert AlphaCodec(profile(), '0A').encode(page('HELLO')) == \
        AlphaCodec(profile(), 10).encode(page('HELLO'))


def test_address_out_of_range_raises():
    with pytest.raises(contract.ScoreboardError):
        AlphaCodec(profile(), 256).encode(page('HELLO'))


def test_control_characters_are_replaced():
    frame = AlphaCodec(profile()).encode(page('A\x03B'))[0]
    assert b'A?B' in frame


def test_two_lines_use_unescaped_separator():
    frame = AlphaCodec(profile(line_separator='\\x7c')).encode(page('ONE', 'TWO'))[0]
    assert b'ONE|TWO' in frame


def test_too_long_line_raises():
    with pytest.raises(contract.ScoreboardError):
        AlphaCodec(profile()).encode(page('TOO LONG!'))


def test_codec_registry():
    assert contract.codec_class('alpha') is AlphaCodec
