import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from contrib.deepsignal.security import check_cds
from contrib.deepsignal.security.check_cds import check_cds_listener
from contrib.deepsignal.security.check_cds import check_nginx
from contrib.deepsignal.security.check_cds import check_udp_listener


NGINX = Path(check_cds.__file__).parent / 'nginx'


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
    route = (NGINX / 'cds-ws.conf').read_text(encoding='utf-8')
    config.write_text(route.replace('location =', 'location'), encoding='utf-8')
    assert check_nginx(config)[0]
    config.write_text(route.replace('8767', '8766'), encoding='utf-8')
    assert not check_nginx(config)[0]
    assert not check_nginx(Path(tmp_path / 'missing'))[0]


def test_nginx_handles_nested_origin_guard():
    template = NGINX / 'cds-ws.conf'
    assert check_nginx(template)[0]


def test_nginx_follows_includes_relative_to_main_and_checks_http_upstreams(tmp_path):
    main = tmp_path / 'nginx.conf'
    sites = tmp_path / 'sites'
    sites.mkdir()
    main.write_text('events {} http { include sites/*.conf; }', encoding='utf-8')
    (sites / 'ship.conf').write_text('server { include relay.conf; }', encoding='utf-8')
    (tmp_path / 'relay.conf').write_bytes((NGINX / 'cds-ws.conf').read_bytes())
    assert check_nginx(main)[0]
    (sites / 'extra.conf').write_text(
        'upstream raw { server 127.0.0.1:8766; } '
        'server { location /raw { proxy_pass http://raw; } }', encoding='utf-8')
    assert not check_nginx(main)[0]


def test_nginx_refuses_unaccounted_for_files_from_nginx_dump(tmp_path):
    main = tmp_path / 'nginx.conf'
    main.write_bytes((NGINX / 'cds-ws.conf').read_bytes())
    dump = tmp_path / 'nginx-dump'
    dump.write_text(f'# configuration file {main}:\n'
                    f'# configuration file {tmp_path / "extra.conf"}:\n', encoding='utf-8')
    assert not check_nginx(main, dump=dump)[0]


def test_nginx_refuses_missing_or_weakened_origin_guard(tmp_path):
    config = tmp_path / 'nginx.conf'
    for guard in ('', 'if ($http_origin != "$scheme://$http_host") { return 200; }',
                  'if ($http_origin = "$scheme://$http_host") { return 403; }'):
        config.write_text(f'location = /cds-ws {{ {guard} '
                          'proxy_pass http://127.0.0.1:8767; }', encoding='utf-8')
        assert not check_nginx(config)[0], guard


def test_nginx_refuses_origin_variable_override(tmp_path):
    config = tmp_path / 'nginx.conf'
    route = (NGINX / 'cds-ws.conf').read_text(encoding='utf-8')
    config.write_text('events {} http { map $host $http_origin { default "$scheme://$http_host"; }'
                      f' server {{ {route} }} }}', encoding='utf-8')
    assert not check_nginx(config)[0]


def test_live_probe_refuses_relay_that_accepts_foreign_origin(monkeypatch):
    gateway = 'ws://ship.example/cds-ws'
    cds = 'ws://127.0.0.1:8766'
    origins = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *unused):
            pass

        async def send(self, unused_message):
            pass

        async def recv(self):
            return '{"status": 403, "data": {"deepsignal_gateway_self_test": []}}'

    def connect(uri, **kwargs):
        if uri == gateway:
            origins.append(kwargs.get('origin'))
        return Connection()

    monkeypatch.setattr(check_cds.websockets, 'connect', connect)
    checks = asyncio.run(check_cds.check_live(gateway, cds))
    assert any(origin and origin != 'http://ship.example' for origin in origins)
    assert any(not ok and 'Origin' in line for ok, line in checks)


@pytest.mark.parametrize(('status', 'refused'), [(403, True), (401, False)])
def test_foreign_origin_probe_requires_http_403(monkeypatch, status, refused):
    class RefusedHandshake:
        async def __aenter__(self):
            raise check_cds.websockets.exceptions.InvalidStatus(SimpleNamespace(status_code=status))

        async def __aexit__(self, *unused):
            pass

    def connect(uri, *, origin):
        assert uri == 'ws://ship.example/cds-ws'
        assert origin != 'http://ship.example'
        return RefusedHandshake()

    monkeypatch.setattr(check_cds.websockets, 'connect', connect)
    assert asyncio.run(check_cds._check_foreign_origin(
        'ws://ship.example/cds-ws', 'http://ship.example'))[0] is refused


def test_console_refuses_websocket_reassignment_before_return(tmp_path):
    source = tmp_path / 'src/pages.ts'
    source.parent.mkdir()
    actual_source = Path(check_cds.__file__).parents[1] / 'console/src/pages.ts'
    contents = actual_source.read_text(encoding='utf-8')
    source.write_text(contents.replace('  return { config, files:',
                                       '  config.websocket = raw.websocket\n'
                                       '  return { config, files:'), encoding='utf-8')
    assert not check_cds.check_console_source(tmp_path)[0]


@pytest.mark.parametrize('config', [
    'location /cds-ws { # proxy_pass http://127.0.0.1:8767;\n return 503; }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; } }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; include unknown.conf; }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; } '
    'location /raw { proxy_pass http://127.0.0.1:8766; }',
    'include unknown.conf;',
    'include cycle.conf;',
])
def test_nginx_rejects_unverifiable_or_direct_routes(tmp_path, config):
    site = tmp_path / 'cds-ws.conf'
    (tmp_path / 'cycle.conf').write_text('include cds-ws.conf;', encoding='utf-8')
    site.write_text(config, encoding='utf-8')
    assert not check_nginx(site)[0]


def test_checker_cli_checks_both_configs_and_console_source(tmp_path, monkeypatch, capsys):
    django = tmp_path / 'django.conf'
    react = tmp_path / 'react.conf'
    route = (NGINX / 'cds-ws.conf').read_text(encoding='utf-8')
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
