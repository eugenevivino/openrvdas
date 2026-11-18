import math

import pytest

from contrib.deepsignal.scoreboard import contract


def profile(registers, unit=1):
    return contract.Profile(
        name='test-board',
        codec='modbus',
        limits={},
        framing={'registers': registers},
        addressing={'default': unit},
    )


def register(data_type='int16', scale=1, stale_value=0, word_order='big'):
    return {
        'name': 'reading',
        'line': 1,
        'cell': 0,
        'address': 0,
        'type': data_type,
        'scale': scale,
        'stale_value': stale_value,
        'word_order': word_order,
    }


def page(value=12.3, stale=False):
    return contract.Page([[contract.Cell('reading', str(value), value, stale)]])


def test_golden_int16_vectors():
    codec = contract.codec_class('modbus')(
        profile([register(scale=10, stale_value=-32768)])
    )
    assert codec.encode(page(12.3)) == [contract.RegisterWrite(1, 0, [123])]
    assert codec.encode(page(-0.05)) == [contract.RegisterWrite(1, 0, [0xFFFF])]
    assert codec.encode(page(12.3, stale=True)) == [
        contract.RegisterWrite(1, 0, [0x8000])
    ]


@pytest.mark.parametrize(
    ('order', 'words'), [('big', [0x4148, 0]), ('little', [0, 0x4148])]
)
def test_float32_golden_word_orders(order, words):
    codec = contract.codec_class('modbus')(
        profile([register('float32', word_order=order)])
    )
    assert codec.encode(page(12.5))[0].values == words


@pytest.mark.parametrize(
    ('order', 'words'), [('big', [0x1234, 0x5678]), ('little', [0x5678, 0x1234])]
)
def test_uint32_word_orders(order, words):
    codec = contract.codec_class('modbus')(
        profile([register('uint32', word_order=order)])
    )
    assert codec.encode(page(0x12345678))[0].values == words


@pytest.mark.parametrize('value', [math.nan, 'not a number'])
def test_invalid_live_value_uses_stale(value):
    codec = contract.codec_class('modbus')(
        profile([register(stale_value=-32768)])
    )
    assert codec.encode(page(value))[0].values == [0x8000]


def test_missing_cell_uses_stale_value():
    codec = contract.codec_class('modbus')(
        profile([register(stale_value=-32768)])
    )
    assert codec.encode(contract.Page([[]]))[0].values == [0x8000]


def test_stale_value_out_of_range_fails_at_construction():
    with pytest.raises(contract.ProfileError, match='reading'):
        contract.codec_class('modbus')(profile([register(stale_value=32768)]))


def test_unit_out_of_range_raises():
    with pytest.raises(contract.ScoreboardError, match='248'):
        contract.codec_class('modbus')(profile([register()], unit=248))


def test_live_value_out_of_range_raises():
    codec = contract.codec_class('modbus')(profile([register(scale=10)]))
    with pytest.raises(contract.ScoreboardError, match=r'reading.*4000'):
        codec.encode(page(4000))


def test_codec_registry_and_init():
    from contrib.deepsignal.scoreboard.codecs.modbus import ModbusCodec

    assert contract.codec_class('modbus') is ModbusCodec
    assert ModbusCodec(profile([register()]), address=2).init() == []
    assert ModbusCodec(profile([register()]), address=2).unit == 2
