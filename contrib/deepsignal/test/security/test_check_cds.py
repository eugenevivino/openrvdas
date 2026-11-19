from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from contrib.deepsignal.security import check_cds
from contrib.deepsignal.security.check_cds import check_cds_listener
from contrib.deepsignal.security.check_cds import check_nginx
from contrib.deepsignal.security.check_cds import check_udp_listener


def runner_with(output):
    def run(unused_command, **unused_kwargs):
        return SimpleNamespace(stdout=output)
    return run


def test_cds_listener_pass_and_fail():
    passed = check_cds_listener(runner_with('LISTEN 0 128 127.0.0.1:8766 0.0.0.0:*'))
    failed = check_cds_listener(runner_with('LISTEN 0 128 0.0.0.0:8766 0.0.0.0:*'))
    assert passed[0]
    assert not failed[0]


def test_udp_listener_pass_and_fail():
    passed = check_udp_listener(6225, '10.2.3.4',
                                runner_with('UNCONN 0 0 10.2.3.4:6225 0.0.0.0:*'))
    failed = check_udp_listener(6225, '10.2.3.4',
                                runner_with('UNCONN 0 0 0.0.0.0:6225 0.0.0.0:*'))
    assert passed[0]
    assert not failed[0]


def test_nginx_pass_and_fail(tmp_path):
    config = tmp_path / 'cds-ws.conf'
    config.write_text('location /cds-ws { proxy_pass http://127.0.0.1:8767; }')
    assert check_nginx(config)[0]
    config.write_text('location /cds-ws { proxy_pass http://127.0.0.1:8766; }')
    assert not check_nginx(config)[0]
    assert not check_nginx(Path(tmp_path / 'missing'))[0]


def test_nginx_handles_nested_origin_guard():
    template = Path(check_cds.__file__).parent / 'nginx/cds-ws.conf'
    assert check_nginx(template)[0]


@pytest.mark.parametrize('config', [
    'location /cds-ws { # proxy_pass http://127.0.0.1:8767;\n return 503; }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; } }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; include unknown.conf; }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; } '
    'location /raw { proxy_pass http://127.0.0.1:8766; }',
])
def test_nginx_rejects_unverifiable_or_direct_routes(tmp_path, config):
    site = tmp_path / 'cds-ws.conf'
    site.write_text(config, encoding='utf-8')
    assert not check_nginx(site)[0]


def test_checker_cli_checks_both_configs_and_console_source(tmp_path, monkeypatch, capsys):
    django = tmp_path / 'django.conf'
    react = tmp_path / 'react.conf'
    route = 'location = /cds-ws { proxy_pass http://127.0.0.1:8767; }'
    django.write_text(route, encoding='utf-8')
    react.write_text(route, encoding='utf-8')
    console = tmp_path / 'console'
    source = console / 'src/pages.ts'
    source.parent.mkdir(parents=True)
    actual_source = Path(check_cds.__file__).parents[1] / 'console/src/pages.ts'
    contents = actual_source.read_text(encoding='utf-8')
    source.write_text(contents, encoding='utf-8')
    args = ['check_cds.py', '--nginx-config', str(django), '--nginx-react-config', str(react),
            '--console-source', str(console)]

    async def no_live_probe(*unused_args):
        return []

    monkeypatch.setattr(check_cds, 'check_cds_listener', lambda **kwargs: (True, 'CDS bound'))
    monkeypatch.setattr(check_cds, 'check_live', no_live_probe)

    def check_cli(arguments, expected):
        monkeypatch.setattr(sys, 'argv', arguments)
        with pytest.raises(SystemExit) as raised:
            check_cds.main()
        assert raised.value.code == expected
        return capsys.readouterr()

    output = check_cli(args, 0).out
    assert str(django) in output and str(react) in output
    assert source.read_text(encoding='utf-8') == contents
    react.write_text(route.replace('8767', '8766'), encoding='utf-8')
    assert str(react) in check_cli(args, 1).out
    react.write_text(route, encoding='utf-8')
    source.write_text(contents.replace('websocket, pages:', 'websocket: raw.websocket, pages:'),
                      encoding='utf-8')
    assert 'same-origin /cds-ws' in check_cli(args, 1).out
    assert 'unrecognized arguments' in check_cli([*args, '--unknown'], 2).err
