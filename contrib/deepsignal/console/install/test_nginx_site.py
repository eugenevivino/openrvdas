"""Installer trust, isolation, and live nginx regression tests."""

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from contrib.deepsignal.console.install import test_owned_site
from contrib.deepsignal.test.security.test_probe_cds import BUNDLE


nginx_install = test_owned_site.nginx_install


CONSOLE = Path(__file__).resolve().parents[1]
SECURITY = CONSOLE.parent / 'security'


def test_multiple_includes_refuse_an_ambiguous_target(nginx_install):
    _, main, site, run = nginx_install
    original = f'events {{}} http {{ include sites/*.conf; include {site}; }}\n'
    main.write_text(original)
    result = run()
    assert result.returncode != 0
    assert 'exactly one include' in result.stderr
    assert main.read_text() == original
    assert not site.exists()


def test_install_and_uninstall_only_touch_dedicated_site(nginx_install):
    _, main, site, run = nginx_install
    other = site.with_name('other.conf')
    original = (b'server { # }\n    server_name other;\n'
                b'    location / { return 200 "a } # b"; }}\n'
                b'# Preserve this last line without a newline')
    other.write_bytes(original)
    before = main.read_bytes()
    for mode in [(), (), ('--uninstall',)]:
        result = run(*mode)
        assert result.returncode == 0, result.stdout + result.stderr
        assert other.read_bytes() == original
        assert main.read_bytes() == before
        assert site.exists() == (mode != ('--uninstall',))


def test_rejects_nginx_syntax_in_install_root(nginx_install):
    _, main, site, run = nginx_install
    before = main.read_bytes()
    result = run('--openrvdas-root', '/srv/ship; include extra.conf; #')
    assert result.returncode != 0
    assert '--openrvdas-root' in result.stderr
    assert main.read_bytes() == before
    assert not site.exists()


@pytest.mark.parametrize('app', ('Django', 'React'))
def test_refuses_stock_cds_proxy_in_either_app(nginx_install, app):
    root, _, site, run = nginx_install
    extra = site.with_name('other.conf')
    original = (f'# {app}\nserver {{ server_name ship;\n'
                'location /cds-ws { proxy_pass http://localhost:8766; }\n}\n')
    extra.write_text(original)
    result = run()
    assert result.returncode != 0
    assert 'unowned /cds-ws location' in result.stderr
    assert str(extra) in result.stderr
    assert extra.read_text() == original
    assert not site.exists()
    assert not (root / 'checker-args').exists()


@pytest.mark.parametrize('direct', [
    'http { server { location /raw { proxy_pass http://127.0.0.1:8766; } } }',
    'stream { server { listen 6225 udp; proxy_pass 127.0.0.1:6225; } }',
])
def test_refuses_direct_cds_and_udp_exposure_before_changing_nginx(nginx_install, direct):
    root, main, site, run = nginx_install
    original = main.read_text() + direct + '\n'
    main.write_text(original)
    result = run('--udp-port', '6225', '--udp-interface', '127.0.0.1')
    assert result.returncode != 0
    assert str(main) in result.stderr and 'CDS port' in result.stderr
    assert main.read_text() == original
    assert list(site.parent.iterdir()) == []
    assert not (root / 'checker-args').exists()


@pytest.mark.parametrize('nested', [True, False])
def test_refuses_direct_cds_in_nested_include_or_sibling_host(nginx_install, nested):
    root, _, site, run = nginx_install
    extra = site.with_name('other.conf')
    unsafe = 'server { location /raw { proxy_pass http://127.0.0.1:8766; } }'
    sibling = root / 'sibling.conf'
    if nested:
        extra.write_text('include sibling.conf;')
        sibling.write_text(unsafe)
    else:
        extra.write_text(unsafe)
    before = extra.read_bytes()
    result = run(DUMP_FILES=str(sibling) if nested else '')
    assert result.returncode != 0
    assert str(sibling if nested else extra) in result.stderr
    assert 'targets CDS port 8766' in result.stderr
    assert extra.read_bytes() == before
    assert not site.exists()


def test_refuses_named_stream_upstream_to_cds_udp_bind(nginx_install):
    _, main, site, run = nginx_install
    original = (main.read_text() + 'stream { upstream feed { server 127.0.0.1:6225; } '
                'server { listen 7225 udp; proxy_pass feed; } }\n')
    main.write_text(original)
    result = run('--udp-port', '6225', '--udp-interface', '127.0.0.1')
    assert result.returncode != 0
    assert 'upstream targets CDS port 6225' in result.stderr
    assert main.read_text() == original
    assert list(site.parent.iterdir()) == []


def test_refuses_variable_proxy_when_relay_is_absent(nginx_install):
    _, _, site, run = nginx_install
    extra = site.with_name('other.conf')
    original = 'server { location /raw { proxy_pass http://$backend; } }'
    extra.write_text(original)
    result = run()
    assert result.returncode != 0
    assert 'variable backend' in result.stderr
    assert extra.read_text() == original
    assert not site.exists()


def test_refuses_even_origin_guarded_relay_in_include(nginx_install):
    root, _, site, run = nginx_install
    extra = site.with_name('other.conf')
    extra.write_text('server { include relay.conf; }')
    route = root / 'relay.conf'
    route.write_text('location = /cds-ws { '
                     'if ($http_origin != "http://ship.example:8080") { return 403; } '
                     'proxy_pass http://127.0.0.1:8767; }')
    before = route.read_bytes()
    result = run(DUMP_FILES=str(route))
    assert result.returncode != 0
    assert str(route) in result.stderr and 'unowned /cds-ws' in result.stderr
    assert route.read_bytes() == before
    assert not site.exists()


def test_backup_stays_out_of_nginx_wildcard_includes(nginx_install):
    root, main, site, run = nginx_install
    main.write_text('events {} http { include sites/*; }\n')
    stub = root / 'nginx_stub.py'
    stub.write_text(stub.read_text().replace('glob("*.conf")', 'glob("*")'))
    original = b''
    site.write_bytes(original)
    invalid = run(NGINX_TEST_EXIT='1')
    assert invalid.returncode != 0
    assert site.read_bytes() == original
    assert list(site.parent.iterdir()) == [site]
    valid = run()
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert list(site.parent.iterdir()) == [site]


def release_file(root, suffix):
    return root / 'release/contrib/deepsignal' / suffix


@pytest.mark.parametrize('mode', [(), ('--check',)])
def test_relay_requires_trusted_checker_even_if_deployment_supplies_one(nginx_install, mode):
    root, _, site, run = nginx_install
    checker = release_file(root, 'security/check_cds.py')
    checker.unlink()
    deployment = root / 'deployment'
    copied = deployment / 'contrib/deepsignal/security/check_cds.py'
    copied.parent.mkdir(parents=True)
    copied.write_text('print("untrusted checker executed")\n')
    result = run('--openrvdas-root', str(deployment), *mode)
    assert result.returncode != 0
    assert str(checker) in result.stderr and 'root-owned' in result.stderr
    assert 'untrusted checker executed' not in result.stdout
    assert not site.exists()


@pytest.mark.parametrize('app', ('Django', 'React'))
def test_refuses_direct_cds_when_the_owned_template_was_edited(nginx_install, app):
    _, _, site, run = nginx_install
    assert run().returncode == 0
    original = site.read_bytes().replace(b'8767', b'8766') + f'# {app}\n'.encode()
    site.write_bytes(original)
    result = run()
    assert result.returncode != 0
    assert 'site differs from the rendered template' in result.stderr
    assert site.read_bytes() == original


def test_relay_self_check_delegates_to_197_and_propagates_failure(nginx_install):
    root, _, site, run = nginx_install
    assert run().returncode == 0
    original = site.read_bytes()
    for status in (0, 1):
        result = run('--check', CHECKER_STATUS=str(status))
        assert result.returncode == status
        assert '#197 checker called' in result.stdout
        assert site.read_bytes() == original
    site.unlink()
    result = run(CHECKER_STATUS='1')
    assert result.returncode == 1
    assert '#197 checker called' in result.stdout
    assert 'restored' in result.stderr
    assert not site.exists()
    assert (root / 'reloads').read_text().splitlines() == ['reload'] * 3


def test_relay_self_check_passes_all_optional_udp_binds_to_197(nginx_install):
    root, _, _, run = nginx_install
    args = ['--udp-port', '6225', '--udp-port', '6226', '--udp-interface', '127.0.0.1']
    assert run(*args).returncode == 0
    result = run('--check', *args)
    assert result.returncode == 0, result.stderr
    assert json.loads((root / 'checker-args').read_text())[-6:] == args


def test_refuses_service_writable_checker_and_helper_before_execution(nginx_install):
    root, _, site, run = nginx_install
    checker = release_file(root, 'security/check_cds.py')
    helper = release_file(root, 'console/install/nginx_inventory.py')
    with helper.open('a') as stream:
        stream.write('\nprint("untrusted helper executed")\n')
    for variable, path in (
        ('SERVICE_OWNED', checker),
        ('SERVICE_WRITABLE', checker.parent),
        ('SERVICE_WRITABLE', helper),
        ('SERVICE_OWNED', helper.parent),
        ('SERVICE_WRITABLE', release_file(root, 'security/nginx/render_site.py')),
        ('SERVICE_WRITABLE', release_file(root, 'security/nginx/deepsignal-console.conf.template')),
    ):
        result = run(**{variable: str(path)})
        assert result.returncode != 0
        assert 'root-owned' in result.stderr
        assert '#197 checker called' not in result.stdout
        assert 'untrusted helper executed' not in result.stdout
        assert not site.exists()


def test_relay_self_check_uses_owned_site_and_configured_origins(nginx_install):
    root, _, site, run = nginx_install
    deployment = root / 'deployment'
    assert run('--openrvdas-root', str(deployment)).returncode == 0
    result = run('--check', '--openrvdas-root', str(deployment))
    assert result.returncode == 0, result.stderr
    assert json.loads((root / 'checker-args').read_text()) == [
        '--nginx-site', str(site), '--openrvdas-root', str(deployment), '--site-only',
        '--origin', 'http://ship.example:8080', '--origin', 'http://alias.example:8080',
    ]


def test_readme_routes_initial_setup_through_the_relay_gate():
    setup = (CONSOLE / 'README.md').read_text().split('### Try it without a ship', 1)[0]
    assert '/opt/deepsignal-release/contrib/deepsignal/console/install/install.sh' in setup
    assert 'sudo /opt/openrvdas/' not in setup
    assert 'install.sh --check' in setup
    assert 'Django and React' in setup and 'UDP' in setup
    assert 'location /console/' not in setup


@contextmanager
def running_nginx(nginx, root, main, listener):
    fd = listener.fileno()
    with (root / 'nginx-stderr').open('w+') as errors:
        process = subprocess.Popen(
            [nginx, '-p', str(root) + '/', '-c', str(main)],
            stderr=errors, text=True, pass_fds=(fd,),
            env=os.environ | {'NGINX': f'{fd};'},
        )
        try:
            # The inherited socket queues this request until the worker is ready.
            opener = build_opener(ProxyHandler({}))
            address = f'http://127.0.0.1:{listener.getsockname()[1]}'
            with pytest.raises(HTTPError) as response:
                opener.open(f'{address}/', timeout=5)
            assert response.value.code == 404
            response.value.close()
            yield process.pid
            if process.poll() is not None:
                errors.seek(0)
                pytest.fail(errors.read())
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize('app_route', ('uwsgi_pass unix:/tmp/django.sock;',
                                       'try_files $uri /index.html;'), ids=['django', 'react'])
def test_real_197_runtime_probe_through_django_and_react_nginx(nginx_install, app_route):
    root, main, site, run = nginx_install
    nginx = shutil.which('nginx')
    assert nginx is not None, 'nginx is required to run the #197 integration test'
    tools = root / 'bin'
    (tools / 'nginx').unlink()
    (tools / 'ps').unlink()
    (tools / 'systemctl').write_text(
        '#!/bin/sh\ncase "$1" in\n'
        ' show) echo "$TEST_MASTER";;\n'
        ' reload) kill -HUP "$TEST_MASTER";;\n'
        ' is-active) kill -0 "$TEST_MASTER";;\nesac\n')
    shutil.copyfile(SECURITY / 'check_cds.py', release_file(root, 'security/check_cds.py'))
    shutil.copyfile(SECURITY / 'probe_cds.py', release_file(root, 'security/probe_cds.py'))
    dist = root / 'deployment/contrib/deepsignal/console/dist'
    dist.mkdir(parents=True)
    (dist / 'index.html').write_text('<script type="module" src="/console/app.js"></script>')
    (dist / 'app.js').write_text(BUNDLE)
    (root / 'cached_data_server.conf').write_text(
        '[program:cached_data_server]\n'
        'command=python3 server/cached_data_server.py '
        '--udp 6225,6226 --udp_interface 127.0.0.1\n')
    with (socket.socket() as listener,
          socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_one,
          socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_two):
        udp_one.bind(('127.0.0.1', 6225))
        udp_two.bind(('127.0.0.1', 6226))
        listener.bind(('0.0.0.0', 0))
        listener.listen()
        port = listener.getsockname()[1]
        main.write_text(
            'daemon off; error_log stderr; pid nginx.pid;\n'
            'events {}\nhttp { access_log off;\n'
            'client_body_temp_path client_body; proxy_temp_path proxy;\n'
            'fastcgi_temp_path fastcgi; uwsgi_temp_path uwsgi; scgi_temp_path scgi;\n'
            'include sites/*.conf;\n'
            f'server {{ listen {port}; server_name app.example; '
            f'location / {{ {app_route} }} location = / {{ return 404; }} }}\n'
            '}\n')
        with running_nginx(nginx, root, main, listener) as master:
            asyncio.run(exercise_live_gate(site, run, master, port, root / 'deployment'))


async def exercise_live_gate(site, run, master, port, deployment):
    from contrib.deepsignal.security.cds_gateway import ReadOnlyGateway
    from contrib.deepsignal.security.probe_cds import PROBE_FIELD, lan_address
    from server.cached_data_server import RecordCache, WebSocketConnection
    import websockets

    origin = f'http://ship.example:{port}'
    alias = f'http://alias.example:{port}'
    options = {'origins': (origin, alias), 'TEST_MASTER': str(master), 'TEST_PROC': '/proc',
               'TEST_SYSTEM_PATH': f'{deployment.parent / "bin"}:/usr/bin:/bin'}
    address = lan_address()
    flags = ('--openrvdas-root', str(deployment), '--probe-address', address)
    publishes = []

    class ObservedCache(RecordCache):
        def cache_record(self, record):
            publishes.append(record)
            super().cache_record(record)

    cache = ObservedCache()
    cache.cache_record({'timestamp': 1, 'fields': {'temperature': 19.1}})
    publishes.clear()

    async def cached_data(websocket):
        await WebSocketConnection(websocket, cache, 0).serve_requests()

    async with websockets.serve(cached_data, '127.0.0.1', 8766):
        gateway = ReadOnlyGateway()
        async with websockets.serve(gateway.handler, '127.0.0.1', 8767):
            for mode in ((), ('--check',)):
                result = await asyncio.to_thread(run, *flags, *mode, **options)
                assert result.returncode == 0, result.stdout + result.stderr
                assert 'live publish through the gateway is refused' in result.stdout
                assert 'live subscribe through the gateway returns data' in result.stdout
                assert 'nginx refuses a WebSocket with a foreign Origin' in result.stdout
                for label in ('TCP 8766', 'TCP 8767', 'UDP 6225', 'UDP 6226',
                              'alternate WebSocket routes', 'served bundle'):
                    assert f'PASS: {label}' in result.stdout
                assert 'proxy_pass http://127.0.0.1:8767;' in site.read_text()
            opener = build_opener(ProxyHandler({}))
            request = Request(f'http://127.0.0.1:{port}/console/app.js',
                              headers={'Host': f'alias.example:{port}'})
            with opener.open(request, timeout=5) as response:
                assert response.headers.get_content_type() == 'application/javascript'
                assert response.read() == BUNDLE.encode()
            async with websockets.connect(f'ws://alias.example:{port}/cds-ws',
                                          host='127.0.0.1', proxy=None, origin=alias) as ws:
                await ws.send(json.dumps({'type': 'fields'}))
                assert json.loads(await ws.recv())['status'] == 200
            with pytest.raises(websockets.exceptions.InvalidStatus) as refused:
                async with websockets.connect(f'ws://foreign.example:{port}/cds-ws',
                                              host='127.0.0.1', proxy=None,
                                              origin=f'http://foreign.example:{port}'):
                    pass
            assert refused.value.response.status_code == 403
            bundle = deployment / 'contrib/deepsignal/console/dist/app.js'
            bundle.write_text(BUNDLE.replace('/cds-ws', '/old-ws'))
            stale = await asyncio.to_thread(run, *flags, '--check', **options)
            assert stale.returncode != 0 and 'FAIL: served bundle' in stale.stdout
            bundle.write_text(BUNDLE)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as exposed:
                exposed.bind((address, 6225))
                result = await asyncio.to_thread(run, *flags, '--check', **options)
            assert result.returncode != 0
            assert 'FAIL: UDP 6225' in result.stdout and 'PASS: UDP 6226' in result.stdout
        assert cache.data['temperature'] == [(1, 19.1)]
        assert len(publishes) == 4
        assert all(record['fields'].keys() == {PROBE_FIELD} for record in publishes)
        assert len({record['fields'][PROBE_FIELD] for record in publishes}) == 4
        removed = await asyncio.to_thread(run, *flags, '--uninstall', **options)
        assert removed.returncode == 0, removed.stdout + removed.stderr
        async with websockets.serve(cached_data, '127.0.0.1', 8767):
            result = await asyncio.to_thread(run, *flags, **options)
            assert result.returncode != 0
            assert 'FAIL: publish: cache changed after the gateway publish attempt' in result.stdout
            assert not site.exists()


def test_runtime_probe_runs_after_reload_and_during_self_check(nginx_install):
    root, _, site, run = nginx_install
    (root / 'bin/python3').write_text('#!/bin/sh\nexit 99\n')
    settings = ('--probe-address', '192.0.2.10', '--probe-source', '192.0.2.11')
    config = root / 'cached_data_server.conf'
    expected = ['--cds-supervisor-config', str(config), *settings,
                '--origin', 'http://ship.example:8080', '--origin', 'http://alias.example:8080']
    installed = run(*settings)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert json.loads((root / 'probe-args').read_text()) == expected
    assert (root / 'probe-python').read_text() == sys.executable
    assert (root / 'probe-reloads').read_text().splitlines() == ['1']
    original = site.read_bytes()
    checked = run('--check', *settings, PROBE_STATUS='1')
    assert checked.returncode == 1
    assert 'runtime CDS probe called' in checked.stdout
    assert site.read_bytes() == original
    assert (root / 'probe-reloads').read_text().splitlines() == ['1', '1']
    site.unlink()
    failed_install = run(*settings, PROBE_STATUS='1')
    assert failed_install.returncode == 1
    assert 'runtime CDS probe called' in failed_install.stdout
    assert 'restored' in failed_install.stderr and not site.exists()
    assert (root / 'probe-reloads').read_text().splitlines() == ['1', '1', '2']
    assert (root / 'reloads').read_text().splitlines() == ['reload'] * 3


def test_probe_supervisor_udp_ports_protect_inventory_without_flags(nginx_install):
    root, _, site, run = nginx_install
    (root / 'cached_data_server.conf').write_text(
        '[program:cached_data_server]\n'
        'command=python3 server/cached_data_server.py '
        '--udp 6225,6226 --udp_interface 192.0.2.50\n')
    extra = site.with_name('other.conf')
    extra.write_text('server { location /feed { proxy_pass http://192.0.2.50:6225; } }')
    result = run()
    assert result.returncode != 0
    assert 'targets CDS port 6225' in result.stderr
    assert not site.exists() and not (root / 'probe-args').exists()


def test_refuses_service_writable_runtime_probe_before_execution(nginx_install):
    root, _, site, run = nginx_install
    probe = release_file(root, 'security/probe_cds.py')
    result = run(SERVICE_WRITABLE=str(probe))
    assert result.returncode == 1
    assert str(probe) in result.stderr and 'root-owned' in result.stderr
    assert not site.exists() and not (root / 'probe-args').exists()
