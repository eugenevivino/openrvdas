import copy
from pathlib import Path

import pytest
import yaml

from contrib.deepsignal.scoreboard import contract
from contrib.deepsignal.scoreboard.profiles import list_profiles, load_profile, validate_profile


STARTERS = {'generic_ascii', 'alpha_sign', 'example_framed', 'example_modbus'}


def base(codec='text'):
    framing = {'template': '{line}'} if codec == 'text' else {}
    if codec == 'modbus':
        framing = {'registers': [
            {'line': 1, 'register': 0, 'type': 'int16', 'stale_value': -1},
        ]}
    return {'name': 'test', 'codec': codec,
            'limits': {'lines': 1, 'chars_per_line': 8}, 'framing': framing}


def assert_bad(data, key):
    with pytest.raises(contract.ProfileError) as error:
        validate_profile(data, 'test.yaml')
    assert 'test.yaml' in str(error.value)
    assert key in str(error.value)


def test_starter_profiles_load_and_list():
    for name in STARTERS:
        assert load_profile(name).name == name
    assert STARTERS == {item['name'] for item in list_profiles()}


def test_local_profile_shadows_packaged(tmp_path):
    source = Path(load_profile('generic_ascii').path)
    data = yaml.safe_load(source.read_text())
    data['description'] = 'local'
    (tmp_path / source.name).write_text(yaml.safe_dump(data))
    profile = load_profile('generic_ascii', search_path=[str(tmp_path), str(source.parent)])
    assert profile.description == 'local'
    item = next(item for item in list_profiles([str(tmp_path), str(source.parent)])
                if item['name'] == 'generic_ascii')
    assert item['shadowed'] is True
    assert item['path'] == str(tmp_path / source.name)


def test_overrides_deep_merge():
    profile = load_profile('generic_ascii', {'transport_defaults': {'baudrate': 19200}})
    assert profile.transport_defaults['type'] == 'serial'
    assert profile.transport_defaults['baudrate'] == 19200


@pytest.mark.parametrize(('change', 'key'), [
    (lambda d: d.update(typo=True), 'typo'),
    (lambda d: d['framing'].update(typo=True), 'framing.typo'),
    (lambda d: d.update(name='wrong'), 'name'),
    (lambda d: d.update(verified='maybe'), 'verified'),
    (lambda d: d['framing'].update(template='{foo}'), 'framing.template'),
    (lambda d: d['framing'].update(template='{line.__class__}'), 'framing.template'),
    (lambda d: d['framing'].update(template='{line[0]}'), 'framing.template'),
    (lambda d: d['framing'].update(template='{checksum}'), 'framing.template'),
    (lambda d: (d['limits'].update(lines=1),
                d['framing'].update(frame_per='page', template='{line2}')),
     'framing.template'),
    (lambda d: d.update(init_frames=[r'\q']), 'init_frames.0'),
])
def test_invalid_text_profiles_name_bad_key(change, key):
    data = copy.deepcopy(base())
    change(data)
    assert_bad(data, key)


def test_modbus_rejects_byte_transport():
    data = base('modbus')
    data['transport_defaults'] = {'type': 'serial'}
    assert_bad(data, 'transport_defaults.type')


def test_modbus_rejects_overlapping_registers():
    data = base('modbus')
    data['framing']['registers'] += [
        {'line': 1, 'register': 0, 'type': 'uint32', 'stale_value': 0},
    ]
    assert_bad(data, 'framing.registers.1.register')


def test_unsafe_yaml_tag_is_rejected(tmp_path):
    path = tmp_path / 'evil.yaml'
    path.write_text('!!python/object:builtins.object {}')
    with pytest.raises(contract.ProfileError) as error:
        load_profile(str(path))
    assert str(path) in str(error.value)
