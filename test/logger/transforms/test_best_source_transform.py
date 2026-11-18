import logging

import pytest

from logger.transforms.best_source_transform import BestSourceTransform
from logger.utils.das_record import DASRecord


ROLES = {'latitude': {'sources': ['primary', 'backup'], 'timeout': 10}}


def record(timestamp, **fields):
    return DASRecord(timestamp=timestamp, fields=fields)


def test_primary_healthy_then_times_out_and_warns(caplog):
    transform = BestSourceTransform(roles=ROLES, return_after=30)

    first = transform.transform(record(100, primary=1.0, backup=2.0))
    assert first.fields['latitude'] == 1.0
    assert first.fields['latitude_source'] == 'primary'
    assert first.fields['latitude_age'] == 0

    with caplog.at_level(logging.WARNING):
        failed_over = transform.transform(record(112, backup=2.1))

    assert failed_over.fields['latitude'] == 2.1
    assert failed_over.fields['latitude_source'] == 'backup'
    assert failed_over.fields['latitude_age'] == 0
    assert 'latitude: switched from primary to backup (primary 12.0 s old)' in caplog.text


def test_bad_qc_triggers_failover():
    transform = BestSourceTransform(roles=ROLES, bad_flags=[3, 4, 9])

    result = transform.transform(record(100, primary=1.0, primary_QC=3,
                                        backup=2.0))

    assert result.fields['latitude'] == 2.0
    assert result.fields['latitude_source'] == 'backup'


def test_hysteresis_holds_backup_then_returns_to_primary():
    transform = BestSourceTransform(roles=ROLES, return_after=30)
    transform.transform(record(100, primary=1.0, backup=2.0))
    transform.transform(record(111, backup=2.1))

    held = transform.transform(record(120, primary=1.1, backup=2.2))
    assert held.fields['latitude_source'] == 'backup'
    transform.transform(record(129, primary=1.2, backup=2.3))
    transform.transform(record(139, primary=1.3, backup=2.4))
    almost = transform.transform(record(149, primary=1.4, backup=2.5))
    assert almost.fields['latitude_source'] == 'backup'
    returned = transform.transform(record(150, primary=1.5, backup=2.6))
    assert returned.fields['latitude_source'] == 'primary'


def test_both_dead_emits_only_none_source_and_age():
    transform = BestSourceTransform(roles=ROLES)
    transform.transform(record(100, primary=1.0, backup=2.0))

    result = transform.transform(record(111))

    assert 'latitude' not in result.fields
    assert result.fields['latitude_source'] == 'none'
    assert 'latitude_age' not in result.fields


def test_source_order_controls_preference():
    roles = {'wind': {'sources': ['second', 'first'], 'timeout': 10}}
    result = BestSourceTransform(roles=roles).transform(
        record(100, first=1, second=2))

    assert result.fields['wind'] == 2
    assert result.fields['wind_source'] == 'second'


def test_dasrecord_dict_list_and_none_inputs():
    transform = BestSourceTransform(roles=ROLES)
    das_record = record(100, primary=1.0)
    assert transform.transform(das_record) is das_record

    dict_record = {'timestamp': 101, 'fields': {'primary': 1.1}}
    assert transform.transform(dict_record) is dict_record
    assert dict_record['fields']['latitude'] == 1.1

    records = [record(102, primary=1.2), record(103, primary=1.3)]
    assert transform.transform(records) == records
    assert [item.fields['latitude'] for item in records] == [1.2, 1.3]
    assert transform.transform(None) is None


@pytest.mark.parametrize('roles', [
    {'latitude': {'sources': [], 'timeout': 10}},
    {'latitude': {'sources': ['primary'], 'timeout': -1}},
])
def test_invalid_role_config_raises_value_error(roles):
    with pytest.raises(ValueError):
        BestSourceTransform(roles=roles)
