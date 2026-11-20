import asyncio
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from contrib.deepsignal.console.install import test_owned_site
from contrib.deepsignal.security import check_cds
from contrib.deepsignal.security.check_cds import check_cds_listener
from contrib.deepsignal.security.check_cds import check_udp_listener


nginx_install = test_owned_site.nginx_install


NGINX = Path(check_cds.__file__).parent / 'nginx'
RENDERER = runpy.run_path(str(NGINX / 'render_site.py'))


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


@pytest.mark.parametrize(('binary', 'listener'), [
    ('/usr/bin/ss', '127.0.0.1:8766'),
    ('/usr/sbin/ss', '[::1]:8766'),
], ids=['ipv4', 'ipv6'])
def test_d_fix1_checker_uses_system_ss(monkeypatch, binary, listener):
    def which(name, *, path):
        assert name == 'ss' and str(Path(binary).parent) in path.split(':')
        return binary

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs['timeout'] > 0
        return subprocess.CompletedProcess(argv, 0, f'LISTEN 0 128 {listener} *:*')

    monkeypatch.setattr(shutil, 'which', which)
    monkeypatch.setattr(subprocess, 'run', run)
    checker = runpy.run_path(check_cds.__file__)
    assert checker['check_cds_listener']()[0]
    assert calls == [[binary, '-ltn']]


@pytest.mark.parametrize('failure', ['missing', 'exit', 'timeout'])
def test_d_fix1_configured_listeners_fail_closed(monkeypatch, failure):
    binary = None if failure == 'missing' else '/usr/bin/ss'
    monkeypatch.setattr(shutil, 'which', lambda *args, **kwargs: binary)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(argv, kwargs.get('timeout'))
        return subprocess.CompletedProcess(argv, 1, 'UNCONN 0 0 192.0.2.10:6225 *:*\n'
                                           'LISTEN 0 128 127.0.0.1:8766 *:*')

    monkeypatch.setattr(subprocess, 'run', run)
    checker = runpy.run_path(check_cds.__file__)
    assert checker['check_udp_listener']() == (True, 'PASS: no UDP live-data feed is configured.')
    assert calls == []
    assert not checker['check_udp_listener'](6225, '192.0.2.10')[0]
    assert not checker['check_cds_listener']()[0]
    assert calls == ([] if binary is None else [[binary, '-lun'], [binary, '-ltn']])


@pytest.mark.parametrize(('address', 'display', 'expected'), [
    ('eth0', 'eth0', True),
    ('192.0.2.10', '192.0.2.10', True),
    ('2001:db8::1', '[2001:db8::1]', True),
    ('*', '*', False),
    ('0.0.0.0', '0.0.0.0', False),
    ('::', '[::]', False),
    ('0:0:0:0:0:0:0:0', '[0:0:0:0:0:0:0:0]', False),
], ids=['named', 'ipv4', 'ipv6', 'star', 'any-ipv4', 'any-ipv6', 'expanded-any-ipv6'])
def test_d_fix1_udp_binding(address, display, expected):
    assert check_udp_listener(6225, address,
                              runner_with(f'UNCONN 0 0 {display}:6225 *:*'))[0] is expected


def test_nginx_template_guard_pass_and_fail(nginx_install):
    _, _, site, run = nginx_install
    assert run().returncode == 0
    contents = site.read_bytes()
    assert RENDERER['check_site'](site, contents)[0]
    site.write_bytes(contents.replace(b'8767', b'8766'))
    assert not RENDERER['check_site'](site, contents)[0]
    site.unlink()
    assert not RENDERER['check_site'](site, contents)[0]


def test_owned_template_guard_preserves_nested_origin_check(nginx_install):
    _, _, site, run = nginx_install
    assert run().returncode == 0
    contents = site.read_bytes()
    assert b'if ($http_origin !~ "' in contents
    assert b'return 403;' in contents
    site.write_bytes(contents.replace(b'return 403;', b'return 200;'))
    assert not RENDERER['check_site'](site, contents)[0]


def test_inventory_follows_includes_relative_to_main_and_checks_http_upstreams(nginx_install):
    root, _, site, run = nginx_install
    neighbor = site.with_name('other.conf')
    neighbor.write_text('include backend.conf; server { location /raw { proxy_pass http://raw; } }')
    upstream = root / 'backend.conf'
    upstream.write_text('upstream raw { server 127.0.0.1:9000; }')
    result = run(DUMP_FILES=str(upstream))
    assert result.returncode == 0, result.stderr
    installed = site.read_bytes()
    upstream.write_text('upstream raw { server 127.0.0.1:8766; }')
    result = run(DUMP_FILES=str(upstream))
    assert result.returncode != 0
    assert str(upstream) in result.stderr and 'upstream targets CDS port 8766' in result.stderr
    assert site.read_bytes() == installed


def test_inventory_refuses_unaccounted_for_files_from_nginx_dump(nginx_install):
    root, _, site, run = nginx_install
    extra = root / 'empty.conf'
    extra.touch()
    result = run(DUMP_FILES=str(extra))
    assert result.returncode != 0
    assert f'{extra}: unaccounted configuration from nginx -T' in result.stderr
    assert not site.exists()


@pytest.mark.parametrize('mutation', [
    lambda site: site.replace(b'$http_origin', b'$host'),
    lambda site: site.replace(b'return 403;', b'return 200;'),
    lambda site: site.replace(b'$http_origin !~', b'$http_origin ~'),
    lambda site: site.replace(site[site.index(b'        if'):site.index(b'        client')], b''),
])
def test_nginx_guard_refuses_missing_or_weakened_origin_check(nginx_install, mutation):
    _, _, site, run = nginx_install
    assert run().returncode == 0
    edited = mutation(site.read_bytes())
    site.write_bytes(edited)
    result = run('--check')
    assert result.returncode != 0
    assert 'differs from the rendered template' in result.stderr
    assert site.read_bytes() == edited


def test_inventory_refuses_origin_variable_override(nginx_install):
    _, main, site, run = nginx_install
    main.write_text(main.read_text().replace(
        'include sites',
        'map $host $http_origin { default "$scheme://$http_host"; } include sites'))
    result = run()
    assert result.returncode != 0
    assert 'unclassifiable map block' in result.stderr
    assert not site.exists()


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


@pytest.mark.parametrize('config', [
    'location /cds-ws { # proxy_pass http://127.0.0.1:8767;\n return 503; }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; } }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; include unknown.conf; }',
    'location /cds-ws { proxy_pass http://127.0.0.1:8767; } '
    'location /raw { proxy_pass http://127.0.0.1:8766; }',
    'include unknown.conf;',
    'include cycle.conf;',
])
def test_inventory_rejects_unverifiable_or_direct_routes(nginx_install, config):
    root, _, site, run = nginx_install
    extra = site.with_name('unowned.conf')
    extra.write_text(f'server {{ {config} }}')
    (root / 'cycle.conf').write_text(f'include {extra};')
    result = run('--dry-run', offline=True)
    assert result.returncode != 0
    assert str(extra) in result.stderr
    assert not site.exists()


def test_checker_keeps_console_source_out_of_its_gate(nginx_install):
    root, _, _, run = nginx_install
    deployment = root / 'deployment'
    source = deployment / 'contrib/deepsignal/console/src/pages.ts'
    source.parent.mkdir(parents=True)
    source.write_text('config.websocket = raw.websocket\n')
    result = run('--openrvdas-root', str(deployment))
    assert result.returncode == 0, result.stderr
    args = (root / 'checker-args').read_text()
    assert '--console-source' not in args
    assert source.read_text() == 'config.websocket = raw.websocket\n'


def test_checker_cli_rejects_old_static_config_flags_and_unknown_options(tmp_path):
    command = [sys.executable, check_cds.__file__, '--nginx-site', str(tmp_path / 'site'),
               '--origin', 'http://ship.example', '--site-only']
    for option in ('--nginx-config', '--nginx-react-config', '--unknown'):
        result = subprocess.run([*command, option, str(tmp_path)], text=True,
                                capture_output=True, check=False)
        assert result.returncode == 2
        assert option in result.stderr


@pytest.mark.parametrize('origin', ('http://ship.example/path', 'https://*.example',
                                    'http://ship.example;include x;',
                                    'http://ship.example:80', 'http://ship.example:8768'))
def test_rejects_noncanonical_or_unsafe_origins(nginx_install, origin):
    _, _, site, run = nginx_install
    result = run(origins=(origin,))
    assert result.returncode != 0
    assert not site.exists()


def test_installer_help_describes_origin(nginx_install):
    _, _, _, run = nginx_install
    result = run('--help')
    assert result.returncode == 0
    assert 'allowed console origin' in result.stdout
