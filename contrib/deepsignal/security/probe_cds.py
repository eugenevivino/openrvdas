#!/usr/bin/env python3
"""Probe the installed CDS gate through its LAN address and loopback CDS."""

import argparse
import asyncio
import base64
import configparser
from html.parser import HTMLParser
import http.client
from ipaddress import IPv4Address
import json
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import ssl
import subprocess
import time
from urllib.parse import urlsplit

import websockets
from websockets.exceptions import WebSocketException


SUPERVISOR_CONFIG = '/etc/supervisor/conf.d/cached_data_server.conf'
SUPERVISORCTL_PATH = '/usr/bin:/bin:/usr/local/bin'
CDS_PORT, GATEWAY_PORT = 8766, 8767
PROBE_FIELD = 'deepsignal_gateway_self_test'
TIMEOUT = 3
WS_PATH = '/cds-ws'
WS_OPTIONS = dict(open_timeout=TIMEOUT, close_timeout=1, proxy=None, max_size=65536)
ERRORS = (OSError, ValueError, http.client.HTTPException, WebSocketException)


def supervisor_environment():
    """Use the environment Supervisor actually passed to the CDS."""
    binary = shutil.which('supervisorctl', path=SUPERVISORCTL_PATH)
    if binary is None:
        raise FileNotFoundError('supervisorctl is required to read the running CDS environment')
    result = subprocess.run([binary, 'pid', 'cached_data_server'], cwd='/',
                            capture_output=True, check=True, timeout=TIMEOUT)
    pid = result.stdout.strip()
    if not re.fullmatch(rb'[1-9][0-9]*', pid) or pid == b'1':
        raise ValueError('cannot identify the running cached_data_server process')
    variables = Path(f'/proc/{pid.decode()}/environ').read_bytes().split(b'\0')
    return {key.decode(): value.decode() for entry in variables
            for key, _, value in [entry.partition(b'=')]
            if key in (b'CDS_UDP_PORTS', b'CDS_UDP_INTERFACE')}


def configured_udp_ports(path):
    config = configparser.ConfigParser(interpolation=None)
    try:
        with Path(path).open(encoding='utf-8') as stream:
            config.read_file(stream)
        command = config['program:cached_data_server']['command']
        if '\n' in command or 'command' in config.defaults():
            raise ValueError('expected a single explicit cached_data_server command')
        if '%' in command:
            environment = supervisor_environment()
            substitutions = {'ENV_' + key: shlex.quote(value) for key, value in environment.items()}
            # The shipped command quotes these placeholders. Match only a whole
            # argument and reject every other Supervisor interpolation.
            command = re.sub(r'"%\((ENV_CDS_UDP_PORTS|ENV_CDS_UDP_INTERFACE)\)s"',
                             lambda match: substitutions[match[1]], command)
            if '%' in command:
                raise ValueError('unsupported Supervisor command interpolation')
        executable, script, *options = shlex.split(command)
        if (not re.fullmatch(r'python3(?:\.\d+)?', Path(executable).name) or
                Path(script).parts[-2:] != ('server', 'cached_data_server.py')):
            raise ValueError('expected a direct Python cached_data_server.py command')
        parser = argparse.ArgumentParser(allow_abbrev=False, add_help=False, exit_on_error=False)
        for name in ('host', 'udp', 'udp_interface', 'disk_cache', 'stderr_file'):
            parser.add_argument('--' + name)
        for name in ('port', 'max_records'):
            parser.add_argument('--' + name, type=int)
        for name in ('back_seconds', 'min_back_records', 'cleanup_interval', 'interval'):
            parser.add_argument('--' + name, type=float)
        parser.add_argument('-v', '--verbosity', action='count')
        values, unexpected = parser.parse_known_args(options)
        flags = [item.partition('=')[0] for item in options if item.startswith('--')
                 and item.partition('=')[0] != '--verbosity']
        if unexpected or len(set(flags)) != len(flags):
            raise ValueError('unexpected or repeated CDS command arguments')
        if values.port not in (None, CDS_PORT) or values.host not in (None, '127.0.0.1'):
            raise ValueError('expected the CDS on 127.0.0.1:8766')
        if values.udp is None and values.udp_interface is None:
            return ()
        interface = IPv4Address(values.udp_interface or '')
        if not values.udp or interface.is_unspecified or interface.is_multicast or (
                interface == IPv4Address('255.255.255.255')):
            raise ValueError('CDS UDP requires ports and a unicast instrument interface')
        ports = []
        for item in values.udp.split(','):
            group, separator, port = item.rpartition(':')
            if (not re.fullmatch(r'[0-9]{1,5}', port) or not 1 <= int(port) <= 65535 or
                    separator and not IPv4Address(group).is_multicast):
                raise ValueError('expected a UDP port or MULTICAST_GROUP:PORT')
            ports.append(int(port))
        return tuple(dict.fromkeys(ports))
    except (configparser.Error, KeyError, OSError, ValueError, argparse.ArgumentError,
            subprocess.SubprocessError) as exc:
        raise ValueError(f'{path}: {exc}') from exc


def lan_address(address=None):
    if address is None:
        # Selecting a source address this way sends no datagram.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(('192.0.2.1', 9))
            address = route.getsockname()[0]
    ip = IPv4Address(address)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise ValueError('supply a non-loopback unicast IPv4 address with --probe-address')
    return str(ip)


def tcp_refused(address, source, port):
    try:
        with socket.create_connection((address, port), TIMEOUT, (source, 0)):
            raise ValueError(f'{address}:{port} accepted a TCP connection')
    except ConnectionRefusedError:
        return


def udp_refused(address, source, port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
        datagram.settimeout(TIMEOUT)
        datagram.bind((source, 0))
        datagram.connect((address, port))
        try:
            # An empty datagram contains no instrument record.
            datagram.send(b'')
            datagram.recv(1)
        except ConnectionRefusedError:
            return
        except TimeoutError as exc:
            raise TimeoutError(f'{address}:{port} did not explicitly refuse UDP') from exc
    raise ValueError(f'{address}:{port} answered over UDP')


class LanHTTPConnection(http.client.HTTPConnection):
    def __init__(self, address, source, origin, default_vhost=False):
        super().__init__(origin.netloc, timeout=TIMEOUT, source_address=(source, 0))
        self.address = address
        self.tls = origin.scheme == 'https'
        self.default_vhost = default_vhost
        if self.tls and origin.port is None:
            self.port = 443

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout,
                                        self.source_address)
        try:
            if self.tls:
                context = ssl.create_default_context()
                # Suppress SNI to exercise the default HTTPS vhost. Its chain
                # must still be trusted, although the invented Host has no cert.
                context.check_hostname = not self.default_vhost
                name = None if self.default_vhost else self.host
                sock = context.wrap_socket(sock, server_hostname=name)
            self.sock = sock
        except BaseException:
            sock.close()
            raise


def upgrade_status(address, source, origin, path, request_origin, host=None):
    endpoint = urlsplit(origin)
    connection = LanHTTPConnection(address, source, endpoint, default_vhost=host is not None)
    try:
        connection.request('GET', path, headers={
            'Host': host or endpoint.netloc, 'Origin': request_origin,
            'Connection': 'Upgrade', 'Upgrade': 'websocket', 'Sec-WebSocket-Version': '13',
            'Sec-WebSocket-Key': base64.b64encode(secrets.token_bytes(16)).decode(),
        })
        return connection.getresponse().status
    finally:
        connection.close()


def foreign_origin(address, source, origins):
    endpoint = urlsplit(origins[0])
    host = 'cds-probe-' + secrets.token_hex(8) + '.invalid'
    if endpoint.port is not None:
        host += f':{endpoint.port}'
    foreign = f'{endpoint.scheme}://{host}'
    attempts = [(origin, None) for origin in origins] + [(origins[0], host)]
    failures = []
    for origin, request_host in attempts:
        target = request_host or origin
        try:
            status = upgrade_status(address, source, origin, WS_PATH, foreign, request_host)
            if status != 403:
                failures.append(f'{target} returned HTTP {status}, expected 403')
        except ERRORS as exc:
            failures.append(f'{target}: {str(exc) or type(exc).__name__}')
    if failures:
        raise ValueError(', '.join(failures))


def other_routes(address, source, origins):
    failures = []
    for origin in origins:
        for path in ('/', '/cds-ws/', '/ws', '/console/cds-ws'):
            try:
                status = upgrade_status(address, source, origin, path, origin)
                if status not in (200, 400, 401, 403, 404, 405):
                    failures.append(f'{origin}{path} returned unexpected HTTP {status}')
            except ERRORS as exc:
                failures.append(f'{origin}{path}: {str(exc) or type(exc).__name__}')
    if failures:
        raise ValueError(', '.join(failures))


def checked(label, check, *args):
    try:
        check(*args)
    except ERRORS as exc:
        return False, f'{label}: {str(exc) or type(exc).__name__}'
    return True, label


def unique_object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError('duplicate key in CDS response')
    return obj


async def exchange(connection, request, kind, status):
    await asyncio.wait_for(connection.send(json.dumps(request)), TIMEOUT)
    message = await asyncio.wait_for(connection.recv(), TIMEOUT)
    if not isinstance(message, str):
        raise ValueError('expected a CDS text response')
    try:
        response = json.loads(message, object_pairs_hook=unique_object)
    except RecursionError as exc:
        raise ValueError('CDS response nesting is too deep') from exc
    if (not isinstance(response, dict) or response.get('type') != kind or
            type(response.get('status')) is not int or response['status'] != status):
        raise ValueError(f'expected a CDS {kind} response with status {status}')
    return response


def no_redirect(connection, path):
    if connection.request.path != path:
        raise ValueError('unexpected WebSocket redirect')


async def sample(url, path, options):
    async with websockets.connect(url, **options) as connection:
        no_redirect(connection, path)
        request = {'type': 'subscribe',
                   'fields': {PROBE_FIELD: {'seconds': -1, 'back_seconds': -1}}}
        await exchange(connection, request, 'subscribe', 200)
        response = await exchange(connection, {'type': 'ready'}, 'data', 200)
        data = response.get('data')
        if not isinstance(data, dict) or data.keys() != {PROBE_FIELD}:
            raise ValueError('subscription returned unexpected fields')
        samples = data[PROBE_FIELD]
        if (not isinstance(samples, list) or len(samples) != 1 or
                not isinstance(samples[0], list) or len(samples[0]) != 2 or
                type(samples[0][0]) not in (int, float) or not isinstance(samples[0][1], str)):
            raise ValueError('subscription returned an invalid nonce sample')
        return samples[0]


def publish(timestamp, nonce):
    return {'type': 'publish', 'data': {'timestamp': timestamp, 'fields': {PROBE_FIELD: nonce}}}


async def cache_checks(address, source, origin):
    loopback = 'ws://127.0.0.1:8766'
    local = WS_OPTIONS | {'host': '127.0.0.1'}
    gateway = 'ws' + origin[4:] + WS_PATH
    remote = WS_OPTIONS | {'host': address, 'local_addr': (source, 0), 'origin': origin}
    expected = [time.time(), secrets.token_hex(16)]
    try:
        async with websockets.connect(loopback, **local) as connection:
            no_redirect(connection, '/')
            await exchange(connection, publish(*expected), 'publish', 200)
        if await sample(loopback, '/', local) != expected:
            raise ValueError('loopback CDS did not retain the probe nonce and timestamp')
    except ERRORS as exc:
        return [(False, f'subscribe: {str(exc) or type(exc).__name__}'),
                (False, 'publish: could not establish cache baseline')]

    results = []
    try:
        if await sample(gateway, WS_PATH, remote) != expected:
            raise ValueError('gateway returned a stale timestamp or different nonce')
        results.append((True, 'live subscribe through the gateway returns data for this run'))
    except ERRORS as exc:
        results.append((False, f'subscribe: {str(exc) or type(exc).__name__}'))

    refusal_error = None
    try:
        async with websockets.connect(gateway, **remote) as connection:
            no_redirect(connection, WS_PATH)
            attempt = publish(time.time(), secrets.token_hex(16))
            response = await exchange(connection, attempt, 'publish', 403)
            if response.get('error') != 'read-only connection':
                raise ValueError('gateway returned an unexpected publish refusal')
    except ERRORS as exc:
        refusal_error = exc
    try:
        if await sample(loopback, '/', local) != expected:
            raise ValueError('cache changed after the gateway publish attempt')
        if refusal_error is not None:
            raise refusal_error
        results.append((True,
                        'live publish through the gateway is refused and the cache is unchanged'))
    except ERRORS as exc:
        results.append((False, f'publish: {str(exc) or type(exc).__name__}'))
    return results


class ModuleScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'base' and 'href' in attrs:
            raise ValueError('unexpected base URL in the served console page')
        if tag == 'script' and len(attrs) != len(attributes):
            raise ValueError('duplicate script attributes in the served console page')
        if tag == 'script' and (attrs.get('type') or '').strip().lower() == 'module':
            self.paths.append(attrs.get('src'))


def fetch_text(address, source, origin, path, content_types):
    endpoint = urlsplit(origin)
    connection = LanHTTPConnection(address, source, endpoint)
    try:
        connection.request('GET', path, headers={
            'Host': endpoint.netloc, 'Cache-Control': 'no-cache',
        })
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'{path} returned HTTP {response.status}')
        if response.headers.get_content_type() not in content_types:
            raise ValueError(f'{path} returned an unexpected content type')
        limit = 8 * 1024 * 1024
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f'{path} is larger than {limit} bytes')
        if response.length:
            raise ValueError(f'{path} returned an incomplete body')
        return data.decode('utf-8')
    finally:
        connection.close()


_JS_NAME = r'[$A-Za-z_][$\w]*'
_RELAY = re.compile(
    rf'function (?P<relay>{_JS_NAME})\(\{{protocol:(?P<protocol>{_JS_NAME}),'
    rf'host:(?P<host>{_JS_NAME})'
    r'\}\)\{return\x60\$\{(?P=protocol)===\x60https:\x60\?\x60wss:\x60:\x60ws:\x60\}'
    r'//\$\{(?P=host)\}/cds-ws\x60\}'
)


def served_bundle(address, source, origin):
    scripts = ModuleScripts()
    scripts.feed(fetch_text(address, source, origin, '/console/', ('text/html',)))
    scripts.close()
    if len(scripts.paths) != 1 or not re.fullmatch(
            r'/console/(?:assets/)?[\w-]+\.m?js', scripts.paths[0] or '', re.ASCII):
        raise ValueError('expected one same-origin console module entrypoint')
    bundle = fetch_text(address, source, origin, scripts.paths[0],
                        ('application/javascript', 'text/javascript'))
    # Recognize the emitted Vite relay and loader, including the returned
    # configuration. A route string in an error message isn't enough.
    matches = list(_RELAY.finditer(bundle))
    if len(matches) != 1:
        raise ValueError('served bundle lacks the console same-origin WebSocket URL')
    relay = re.escape(matches[0]['relay'])
    loader = re.compile(
        rf'async function {_JS_NAME}\({_JS_NAME}\)\{{let (?P<raw>{_JS_NAME})={_JS_NAME}\(await '
        rf'{_JS_NAME}\(\x60console\.yaml\x60,{_JS_NAME}\),window\.location\),'
        rf'(?P<url>{_JS_NAME})={relay}\(window\.location\);'
        r'if\(new URL\((?P=raw)\.websocket\)\.href!==new URL\((?P=url)\)\.href\)'
        rf'throw Error\(\x60[^\x60]*\x60\);let (?P<config>{_JS_NAME})=\{{'
        r'ship:(?P=raw)\.ship,shipTimezone:(?P=raw)\.ship_timezone,websocket:(?P=url),'
        rf'(?:{_JS_NAME}:(?P=raw)\.{_JS_NAME},?)+\}};return\{{config:(?P=config),'
    )
    if len(list(loader.finditer(bundle))) != 1:
        raise ValueError('served bundle lacks the console same-origin WebSocket configuration')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--origin', action='append', required=True)
    parser.add_argument('--cds-supervisor-config', default=SUPERVISOR_CONFIG)
    parser.add_argument('--probe-address')
    parser.add_argument('--probe-source')
    args = parser.parse_args(argv)
    try:
        ports = configured_udp_ports(args.cds_supervisor_config)
        address = lan_address(args.probe_address)
        source = lan_address(args.probe_source or address)
        for origin in args.origin:
            if not re.fullmatch(r'https?://[a-z0-9.-]+(?::[1-9][0-9]{0,4})?', origin):
                raise ValueError(f'invalid HTTP(S) origin {origin!r}')
            urlsplit(origin).port  # Validate the port before opening connections.
        endpoints = {(urlsplit(origin).scheme, urlsplit(origin).port) for origin in args.origin}
        if len(endpoints) != 1:
            raise ValueError('all origins must use one scheme and port')
    except ERRORS as exc:
        print('FAIL: probe configuration: ' + ' '.join(str(exc).splitlines()))
        return 1
    checks = [checked(f'TCP {port}', tcp_refused, address, source, port)
              for port in (CDS_PORT, GATEWAY_PORT)]
    checks.extend(checked(f'UDP {port}', udp_refused, address, source, port) for port in ports)
    if not ports:
        checks.append((True, 'no CDS UDP ports configured'))
    checks.append(checked('nginx refuses a WebSocket with a foreign Origin',
                          foreign_origin, address, source, args.origin))
    checks.append(checked('alternate WebSocket routes', other_routes, address, source, args.origin))
    checks.extend(asyncio.run(cache_checks(address, source, args.origin[0])))
    checks.extend(checked(f'served bundle ({origin})', served_bundle, address, source, origin)
                  for origin in args.origin)
    for ok, message in checks:
        print(('PASS: ' if ok else 'FAIL: ') + ' '.join(message.splitlines()))
    return int(not all(ok for ok, _ in checks))


if __name__ == '__main__':
    raise SystemExit(main())
