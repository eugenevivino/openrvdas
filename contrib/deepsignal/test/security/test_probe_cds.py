"""Regression tests for the external CDS runtime probe."""

import asyncio
import errno
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest


@pytest.fixture
def probe():
    from contrib.deepsignal.security import probe_cds
    return probe_cds


def supervisor_config(tmp_path, options):
    path = tmp_path / 'cached_data_server.conf'
    path.write_text('[program:cached_data_server]\n'
                    'command=python3 server/cached_data_server.py ' + options + '\n')
    return path


def test_probe_reads_all_configured_udp_ports(probe, tmp_path, monkeypatch):
    path = supervisor_config(tmp_path, '--udp "%(ENV_CDS_UDP_PORTS)s" '
                             '--udp_interface "%(ENV_CDS_UDP_INTERFACE)s"')
    monkeypatch.setenv('CDS_UDP_PORTS', '9999')
    monkeypatch.setattr(probe, 'supervisor_environment', lambda: {
        'CDS_UDP_PORTS': '6225,239.12.34.56:6226,6227',
        'CDS_UDP_INTERFACE': '192.0.2.10',
    })
    assert probe.configured_udp_ports(path) == (6225, 6226, 6227)
    assert probe.configured_udp_ports(supervisor_config(tmp_path, '--port=8766')) == ()


@pytest.mark.parametrize('options', [
    '--udp 6225,unexpected --udp_interface 192.0.2.10',
    '--udp 6225 --udp=6226 --udp_interface 192.0.2.10',
    '--udp 6225 --udp_interface 0.0.0.0',
    '--ud 6225 --udp_interface 192.0.2.10',
    '--udp "%(ENV_MISSING)s" --udp_interface 192.0.2.10',
    '--port 8866',
    '--host 0.0.0.0 --allow-non-loopback',
])
def test_probe_rejects_unclassifiable_supervisor_config(probe, tmp_path, options, monkeypatch):
    monkeypatch.setattr(probe, 'supervisor_environment', dict)
    with pytest.raises(ValueError):
        probe.configured_udp_ports(supervisor_config(tmp_path, options))


ADDRESS = '192.0.2.10'
SOURCE = '192.0.2.11'
ORIGINS = ('http://ship.example:8080', 'http://alias.example:8080')


@pytest.mark.parametrize('address', ['127.0.0.1', '0.0.0.0', '239.0.0.1', 'ship.example'])
def test_probe_rejects_non_lan_addresses(probe, address):
    with pytest.raises(ValueError):
        probe.lan_address(address)


@pytest.mark.parametrize('error', [None, errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ETIMEDOUT])
def test_probe_requires_tcp_refusal_on_both_ports(probe, monkeypatch, error):
    calls = []

    def connect(target, timeout, source_address):
        calls.append((target, source_address))
        if error is not None:
            raise OSError(error, 'simulated connect result')
        return DummySocket()

    monkeypatch.setattr(socket, 'create_connection', connect)
    for port in (8766, 8767):
        if error == errno.ECONNREFUSED:
            probe.tcp_refused(ADDRESS, SOURCE, port)
        else:
            with pytest.raises((OSError, ValueError)):
                probe.tcp_refused(ADDRESS, SOURCE, port)
    assert calls == [((ADDRESS, port), (SOURCE, 0)) for port in (8766, 8767)]


class DummySocket:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@pytest.mark.parametrize('error', [None, errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ETIMEDOUT])
def test_probe_requires_udp_refusal_from_each_port(probe, monkeypatch, error):
    calls = []

    class Datagram(DummySocket):
        def settimeout(self, timeout):
            assert timeout > 0

        def bind(self, addr):
            assert addr == (SOURCE, 0)

        def connect(self, addr):
            calls.append(addr)

        def send(self, data):
            assert data == b''
            return len(data)

        def recv(self, size):
            if error is not None:
                raise OSError(error, 'simulated UDP reply')
            return b''

    monkeypatch.setattr(socket, 'socket', lambda family, kind: Datagram())
    for port in (6225, 6226, 6227):
        if error == errno.ECONNREFUSED:
            probe.udp_refused(ADDRESS, SOURCE, port)
        else:
            with pytest.raises((OSError, ValueError)):
                probe.udp_refused(ADDRESS, SOURCE, port)
    assert calls == [(ADDRESS, port) for port in (6225, 6226, 6227)]


@pytest.mark.parametrize('status', [403, 101, 404, 502])
def test_probe_requires_foreign_origin_403_including_matching_host(probe, monkeypatch, status):
    calls = []

    def upgrade(address, source, origin, path, request_origin, host=None):
        calls.append((address, source, origin, path, request_origin, host))
        return status if host else 403

    monkeypatch.setattr(probe, 'upgrade_status', upgrade)
    if status == 403:
        probe.foreign_origin(ADDRESS, SOURCE, ORIGINS)
    else:
        with pytest.raises(ValueError, match='403'):
            probe.foreign_origin(ADDRESS, SOURCE, ORIGINS)
    for address, source, origin, path, request_origin, host in calls:
        assert (address, source, path) == (ADDRESS, SOURCE, '/cds-ws')
        assert origin in ORIGINS and request_origin not in ORIGINS
        if host:
            assert request_origin == f'http://{host}'
    assert {call[2] for call in calls if not call[-1]} == set(ORIGINS)
    assert any(call[-1] for call in calls)


@pytest.mark.parametrize('status', [404, 101, 502])
def test_probe_checks_alternate_websocket_routes(probe, monkeypatch, status):
    calls = []

    def upgrade(address, source, origin, path, request_origin):
        calls.append((origin, path, request_origin))
        return status if path == '/cds-ws/' else 404

    monkeypatch.setattr(probe, 'upgrade_status', upgrade)
    if status == 404:
        probe.other_routes(ADDRESS, SOURCE, ORIGINS)
    else:
        with pytest.raises(ValueError, match='/cds-ws/'):
            probe.other_routes(ADDRESS, SOURCE, ORIGINS)
    assert all(path != '/cds-ws' and origin == request for origin, path, request in calls)
    assert set(ORIGINS) <= {origin for origin, path, request in calls}


class CachedData:
    def __init__(self, field, mode):
        self.field = field
        self.mode = mode
        self.writes = []
        self.commands = []

    def connect(self, url, **kwargs):
        is_loopback = url == 'ws://127.0.0.1:8766'
        if not is_loopback:
            assert url == 'ws://ship.example:8080/cds-ws'
            assert kwargs['host'] == ADDRESS
            assert kwargs['local_addr'] == (SOURCE, 0)
            assert kwargs['origin'] == ORIGINS[0]
            assert kwargs['proxy'] is None
        return CDSConnection(self, is_loopback)


class CDSConnection:
    def __init__(self, cds, is_loopback):
        self.cds = cds
        self.is_loopback = is_loopback
        self.command = None

    @property
    def request(self):
        return SimpleNamespace(path='/' if self.is_loopback else '/cds-ws')

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def send(self, raw):
        request = self.command = json.loads(raw)
        self.cds.commands.append((self.is_loopback, request))
        if request['type'] == 'publish':
            if self.is_loopback or self.cds.mode in ('accepted', 'mutated'):
                data = request['data']
                self.cds.writes.append([data['timestamp'], data['fields'][self.cds.field]])

    async def recv(self):
        kind = self.command['type']
        if kind == 'publish' and not self.is_loopback and self.cds.mode != 'accepted':
            return json.dumps({'type': 'publish', 'status': 403, 'error': 'read-only connection'})
        if kind != 'ready':
            return json.dumps({'type': kind, 'status': 200})
        sample = self.cds.writes[-1].copy()
        if not self.is_loopback:
            if self.cds.mode == 'stale':
                sample[0] -= 60
            elif self.cds.mode == 'wrong nonce':
                sample[1] += '0'
            elif self.cds.mode == 'malformed':
                return '[]'
        return json.dumps({'type': 'data', 'status': 200, 'data': {self.cds.field: [sample]}})


@pytest.mark.parametrize('mode',
                         ['good', 'stale', 'wrong nonce', 'malformed', 'accepted', 'mutated'])
def test_probe_fresh_subscribe_and_refused_publish(probe, monkeypatch, mode):
    cds = CachedData(probe.PROBE_FIELD, mode)
    monkeypatch.setattr(probe.websockets, 'connect', cds.connect)
    for _ in range(2):
        results = asyncio.run(probe.cache_checks(ADDRESS, SOURCE, ORIGINS[0]))
        assert len(results) == 2
        assert results[0][0] == (mode not in ('stale', 'wrong nonce', 'malformed'))
        assert results[1][0] == (mode not in ('accepted', 'mutated'))
    seeds = [request['data'] for local, request in cds.commands
             if local and request['type'] == 'publish']
    assert len(seeds) == 2
    assert seeds[0]['fields'] != seeds[1]['fields']
    attempts = [request['data'] for local, request in cds.commands
                if not local and request['type'] == 'publish']
    assert len(attempts) == 2
    assert all(attempt['fields'] != seed['fields'] for attempt, seed in zip(attempts, seeds))


BUNDLE = (
    'function url({protocol:e,host:t}){return`${e===`https:`?`wss:`:`ws:`}//${t}/cds-ws`}'
    'async function load(e){let t=parse(await get(`console.yaml`,e),window.location),'
    'n=url(window.location);if(new URL(t.websocket).href!==new URL(n).href)'
    'throw Error(`console.yaml: Use the same-origin /cds-ws read-only relay.`);'
    'let r={ship:t.ship,shipTimezone:t.ship_timezone,websocket:n,pages:t.pages};'
    'return{config:r,files:[]}}'
)


@pytest.mark.parametrize('mode', ['good', 'stale', 'rewritten', 'missing', 'external', 'html'])
def test_probe_checks_served_bundle_entrypoint(probe, monkeypatch, mode):
    calls = []
    script = '/console/assets/index-probe.js'
    entry = 'https://other.example/index.js' if mode == 'external' else script
    index = ('' if mode == 'missing' else
             f'<script type="module" crossorigin src="{entry}"></script>')
    bundle = BUNDLE
    if mode == 'stale':
        bundle = bundle.replace('}//${t}/cds-ws`', '}//${t}:8766/`')
    if mode == 'rewritten':
        bundle = bundle.replace('return{config:r', 'r.websocket=`ws://wrong:8766`;return{config:r')

    def fetch(address, source, origin, path, content_types):
        calls.append((address, source, origin, path))
        if path == '/console/':
            return index
        assert path == script and 'application/javascript' in content_types
        if mode == 'html':
            raise ValueError('served unexpected content type')
        return bundle

    monkeypatch.setattr(probe, 'fetch_text', fetch)
    if mode == 'good':
        probe.served_bundle(ADDRESS, SOURCE, ORIGINS[0])
    else:
        with pytest.raises(ValueError):
            probe.served_bundle(ADDRESS, SOURCE, ORIGINS[0])
    paths = ['/console/'] if mode in ('missing', 'external') else ['/console/', script]
    assert calls == [(ADDRESS, SOURCE, ORIGINS[0], path) for path in paths]


def test_probe_emits_all_failures_and_checks_every_port(probe, monkeypatch, tmp_path, capsys):
    path = supervisor_config(tmp_path, '--udp 6225,6226 --udp_interface 192.0.2.50')
    calls = []

    def udp(address, source, port):
        calls.append((address, source, port))
        if port == 6225:
            raise TimeoutError('unconfirmed\nrefusal')

    async def cache(*args):
        return [(False, 'subscribe: wrong timestamp'), (True, 'publish: cache unchanged')]

    monkeypatch.setattr(probe, 'tcp_refused', lambda *args: None)
    monkeypatch.setattr(probe, 'udp_refused', udp)
    monkeypatch.setattr(probe, 'foreign_origin', lambda *args: None)
    monkeypatch.setattr(probe, 'other_routes', lambda *args: None)
    monkeypatch.setattr(probe, 'cache_checks', cache)
    monkeypatch.setattr(probe, 'served_bundle', lambda *args: None)
    assert probe.main(['--cds-supervisor-config', str(path), '--origin', ORIGINS[0],
                       '--probe-address', ADDRESS, '--probe-source', SOURCE]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert 'FAIL: UDP 6225: unconfirmed refusal' in lines
    assert 'PASS: UDP 6226' in lines
    assert 'FAIL: subscribe: wrong timestamp' in lines
    assert f'PASS: served bundle ({ORIGINS[0]})' in lines
    assert calls == [(ADDRESS, SOURCE, 6225), (ADDRESS, SOURCE, 6226)]


def test_probe_is_in_installer_trust_list():
    install = Path(__file__).resolve().parents[2] / 'console/install/install.sh'
    assert '"$security_dir/probe_cds.py"' in install.read_text()
