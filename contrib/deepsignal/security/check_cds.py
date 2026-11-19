#!/usr/bin/env python3
"""Check that the Cached Data Server is reachable only through its gateway."""

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
import glob
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from urllib.parse import urlsplit

import websockets


def _run(runner, command):
    try:
        result = runner(command, capture_output=True, text=True, check=False)
    except OSError:
        return ''
    return result if isinstance(result, str) else result.stdout


def check_cds_listener(runner=subprocess.run, port=8766):
    output = _run(runner, ['ss', '-ltn'])
    addresses = _listener_addresses(output, port)
    if not addresses:
        return False, ('FAIL: live-data server is not listening on port %d. '
                       'Fix: start the cached data server.' % port)
    unsafe = [address for address in addresses if not _is_loopback(address)]
    if unsafe:
        return False, ('FAIL: live-data server is listening on all network addresses '
                       '(%s:%d). Anyone on the ship network can change what displays show. '
                       'Fix: start it with --host 127.0.0.1.' % (unsafe[0], port))
    return True, 'PASS: live-data server is listening only on loopback.'


def check_udp_listener(port=None, interface=None, runner=subprocess.run):
    if port is None:
        return True, 'PASS: no UDP live-data feed is configured.'
    output = _run(runner, ['ss', '-lun'])
    addresses = _listener_addresses(output, port)
    if (not interface or not addresses or
            any(not _is_named(address, interface) for address in addresses)):
        return False, ('FAIL: UDP live-data feed is not bound to its named interface. '
                       'Anyone on the ship network can inject display data. '
                       'Fix: start it with --udp_interface and the feed interface address.')
    return True, 'PASS: UDP live-data feed is bound to its named interface.'


_NGINX_TOKEN = re.compile(
    rb'''[ \t\r\n]+|\#[^\n]*|[{};]|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|'''
    rb'''(?:\$\{[^{}\s]+\}|\\.|[^ \t\r\n{};'"\\])+''', re.DOTALL)


@dataclass(eq=False)
class _Directive:
    words: tuple
    is_block: bool
    selected: bool


def _nginx_directives(contents, selected_offset):
    if b'\0' in contents:
        raise ValueError('unexpected null byte')
    blocks = []
    words = []
    position = 0
    word_end = None
    quoted = False
    while position < len(contents):
        match = _NGINX_TOKEN.match(contents, position)
        if match is None:
            raise ValueError('unrecognized nginx token')
        token = match[0]
        position = match.end()
        if token[:1] in (b' ', b'\t', b'\r', b'\n', b'#'):
            continue
        if token == b'}':
            if words or not blocks:
                raise ValueError('unexpected nginx block close')
            blocks.pop()
        elif token in (b'{', b';'):
            if not words:
                raise ValueError('empty nginx directive')
            directive = _Directive(tuple(words), token == b'{', match.start() == selected_offset)
            yield tuple(blocks), directive
            if directive.is_block:
                blocks.append(directive)
            words.clear()
        else:
            if match.start() == word_end and not (quoted and token == b')'):
                raise ValueError('ambiguous adjacent nginx tokens')
            quoted = token[:1] in (b'"', b"'")
            word_end = position
            value = token[1:-1] if quoted else token
            words.append(value.decode('utf-8'))
    if words or blocks:
        raise ValueError('incomplete nginx configuration')


def _cds_location(directive):
    return directive in (('location', '/cds-ws'), ('location', '=', '/cds-ws'),
                         ('location', '^~', '/cds-ws'))


def _effective_directives(config, site, snapshot, offset, dump):
    prefix = config.parent
    active = set()
    visited = set()
    site_stat = site.stat() if site is not None else None

    def read(path, context):
        metadata = path.stat()
        identity = (metadata.st_dev, metadata.st_ino)
        if identity in active or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f'invalid nginx include: {path}')
        visited.add(path)
        selected = site_stat is not None and os.path.samestat(metadata, site_stat)
        contents = (snapshot if selected else path).read_bytes()
        active.add(identity)
        for blocks, directive in _nginx_directives(contents, offset if selected else None):
            if directive.words[0] != 'include':
                yield context + blocks, directive
                continue
            if directive.is_block or len(directive.words) != 2:
                raise ValueError('invalid nginx include')
            pattern = directive.words[1]
            if not pattern or '$' in pattern or '\\' in pattern:
                raise ValueError('unresolved nginx include')
            if any(construct in pattern for construct in ('[:', '[=', '[.')):
                raise ValueError('unsupported nginx include wildcard')
            pattern = str(prefix / pattern)
            paths = sorted(glob.glob(pattern)) if glob.has_magic(pattern) else [pattern]
            for included in paths:
                yield from read(Path(included), context + blocks)
        active.remove(identity)

    yield from read(config, ())
    if dump is not None:
        headers = re.findall(rb'^# configuration file (/[^\n]+):$', dump.read_bytes(),
                             re.MULTILINE)
        if not headers or {Path(os.fsdecode(path)) for path in headers} - visited:
            raise ValueError('could not account for every file reported by nginx -T')


def _unsafe_upstream(target, ports):
    if '$' in target or '\\' in target:
        return True
    if target.startswith(('unix:', 'http://unix:', 'https://unix:')):
        return False
    try:
        endpoint = urlsplit(target if '://' in target else f'//{target}')
        return not endpoint.hostname or endpoint.port in ports
    except ValueError:
        return True


_ORIGIN_GUARD = ('if', '($http_origin', '!=', '$scheme://$http_host', ')')
_ORIGIN_VARIABLE = re.compile(r'\$\{?(?:http_origin|http_host|scheme)\}?', re.IGNORECASE)
_ORIGIN_CAPTURE = re.compile(r"""\(\?(?:P?<|')(?:http_origin|http_host|scheme)[>']""",
                             re.IGNORECASE)
_VARIABLE_ARGUMENT = {
    'auth_request_set': 0, 'geo': -1, 'js_set': 0, 'js_var': 0,
    'map': -1, 'perl_set': 0, 'set': 0, 'split_clients': -1,
}
_NO_RELAY = 'PASS: selected nginx server has no /cds-ws relay.'


def _guarded_relay(route, parents, children, allowed):
    guard = []
    targets = []
    for directive in children[route]:
        name, *args = directive.words
        if directive.is_block:
            if (directive.words != _ORIGIN_GUARD or
                    [(child.words, child.is_block) for child in children[directive]] !=
                    [(('return', '403'), False)]):
                return False
            guard.append(directive)
        elif name == 'proxy_pass':
            targets.append(args)
        elif (name.endswith('_pass') or name in
              ('pass', 'rewrite', 'try_files', 'error_page', 'return', 'break', 'set')):
            return False
    if len(guard) != 1 or len(targets) != 1 or tuple(targets[0]) not in allowed:
        return False
    siblings = children[parents[-1] if parents else None]
    if route.words[1] == '/cds-ws' and any(
            entry.words[:2] in (('location', '~'), ('location', '~*')) for entry in siblings):
        return False
    for parent in parents:
        for entry in children[parent]:
            name, *args = entry.words
            if (name in ('rewrite', 'if', 'return') or
                    (name == 'error_page' and '403' in args[:-1])):
                return False
    return True


def _nginx_relay(config, gateway_port, cds_port, udp_port, site, snapshot, offset, dump):
    children = defaultdict(list)
    selected = []
    routes = {}
    ports = {cds_port} if udp_port is None else {cds_port, udp_port}
    allowed = {(f'http://127.0.0.1:{gateway_port}',)}
    if site is None:
        allowed.add((f'http://localhost:{gateway_port}',))
    for blocks, directive in _effective_directives(config, site, snapshot, offset, dump):
        parent = blocks[-1] if blocks else None
        children[parent].append(directive)
        name, *args = directive.words
        if args and name in _VARIABLE_ARGUMENT and _ORIGIN_VARIABLE.fullmatch(
                args[_VARIABLE_ARGUMENT[name]]):
            raise ValueError('nginx overrides an Origin guard variable')
        if any(_ORIGIN_CAPTURE.search(arg) for arg in args):
            raise ValueError('nginx captures into an Origin guard variable')
        if directive.selected:
            if not directive.is_block or directive.words != ('server',) or (
                    blocks and tuple(block.words for block in blocks) != (('http',),)):
                raise ValueError('selected nginx block is not an HTTP server')
            selected.append(directive)
        if _cds_location(directive.words):
            if not directive.is_block or parent in routes or (
                    parent is not None and parent.words != ('server',)):
                raise ValueError('ambiguous /cds-ws location')
            routes[parent] = (directive, blocks)
        # Check all upstream members as well as proxy destinations. This covers
        # named upstreams in both http and stream, independent of declaration order.
        if not directive.is_block and (name.endswith('_pass') or name in ('server', 'pass')):
            if not args or _unsafe_upstream(args[0], ports):
                raise ValueError('unsafe nginx upstream destination')
        if name == 'listen' and 'udp' in args[1:]:
            port = args[0].rsplit(':', 1)[-1]
            if not port.isdecimal() or int(port) == udp_port:
                raise ValueError('unsafe nginx UDP listener')

    relays = set()
    for parent, (route, blocks) in routes.items():
        if (route.words == ('location', '=', '/cds-ws') and
                [(child.words, child.is_block) for child in children[route]] ==
                [(('return', '503'), False)]):
            continue
        if not _guarded_relay(route, blocks, children, allowed):
            raise ValueError('unverifiable /cds-ws relay or Origin guard')
        relays.add(parent)
    if site is None:
        return bool(relays)
    if len(selected) != 1:
        raise ValueError('selected nginx server is not loaded exactly once')
    return selected[0] in relays


def check_nginx(config, gateway_port=8767, *, cds_port=8766, udp_port=None,
                site=None, snapshot=None, offset=None, dump=None, allow_missing=False):
    try:
        safe = _nginx_relay(Path(config).absolute(), gateway_port, cds_port, udp_port,
                            site, snapshot, offset, dump)
    except (OSError, ValueError, RecursionError) as exc:
        return False, (f'FAIL: cannot verify the nginx read-only relay in {config}: {exc}. '
                       'Fix: install the cds-ws.conf security template and remove direct '
                       'CDS routes.')
    if not safe and allow_missing:
        return True, _NO_RELAY
    if not safe:
        return False, (f'FAIL: nginx configuration {config} does not verify a read-only /cds-ws '
                       f'route. Fix: proxy /cds-ws to 127.0.0.1:{gateway_port} '
                       'and remove direct CDS routes.')
    return True, f'PASS: nginx /cds-ws points to the read-only gateway in {config}.'


_TS_LITERAL_OR_COMMENT = re.compile(
    r'''//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|'''
    r'''`(?:\\.|[^`\\])*`|/(?:\\.|\[[^\]\n]*\]|[^/\\\n\[])+/[a-z]*''',
    re.DOTALL,
)
_RELAY_BUILDER = """\
function relayUrl({ protocol, host }: Pick<Location, 'protocol' | 'host'>) {
  return `${protocol === 'https:' ? 'wss:' : 'ws:'}//${host}/cds-ws`
}
"""
_CONSOLE_LOADER = """\
export async function loadConsole(signal: AbortSignal) {
  const raw = parseConsole((await fetchFile('console.yaml', signal))!, window.location)
  const websocket = relayUrl(window.location)
  if (new URL(raw.websocket).href !== new URL(websocket).href) {
    throw new Error('console.yaml: Use the same-origin /cds-ws read-only relay. """ \
    """Remove the websocket setting to use it automatically.')
  }
  const config: ConsoleConfig = {
    ship: raw.ship, shipTimezone: raw.ship_timezone, websocket, pages: raw.pages,
    historyS: raw.history, qcSuffix: raw.qc_suffix, nightPalette: raw.night_palette, """ \
    """modules: raw.modules,
  }
  const files = await Promise.all((config.pages.length ? config.pages : """ \
    """await pageIds(signal)).map(async (id) => {
    const file = `pages/${id}.yaml`
    try {
      const text = await fetchFile(file, signal, true)
      if (text === undefined) return undefined
      return { page: { ...parsePage(file, text), source: 'file:' + file } }
    } catch (error) {
      return { page: { id, title: id, source: 'file:' + file, tiles: [] } as Page,
        problem: error instanceof Error ? error.message : String(error) }
    }
  }))
  return { config, files: files.filter((file) => file !== undefined), """ \
    """periods: new Map(Object.entries(raw.period)) }
}

export type LoadedConsole = Awaited<ReturnType<typeof loadConsole>>
"""


def _console_uses_relay(contents):
    # Recognize the supported functions through their closing braces. Mask
    # comments and literals before locating declarations and checking scope.
    code = _TS_LITERAL_OR_COMMENT.sub(
        lambda match: re.sub(r'[^\n]', ' ', match[0]), contents)
    depth = 0
    declarations = []
    for token in re.finditer(
            r'^function relayUrl\b|^export async function loadConsole\b|[{}\x27"`/]',
            code, re.MULTILINE):
        if token[0] == '{':
            depth += 1
        elif token[0] == '}':
            depth -= 1
            if depth < 0:
                return False
        elif depth == 0 and len(token[0]) > 1:
            declarations.append(token.start())
        else:
            return False
    return (depth == 0 and len(declarations) == 2 and
            contents.startswith(_RELAY_BUILDER, declarations[0]) and
            contents[declarations[1]:].rstrip() == _CONSOLE_LOADER.rstrip())


def check_console_source(console):
    source = Path(console) / 'src/pages.ts'
    read_limit = 128 * 1024
    contents = ''
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding='utf-8') as source_file:
            if stat.S_ISREG(os.fstat(fd).st_mode):
                contents = source_file.read(read_limit)
    except (OSError, UnicodeError):
        contents = ''

    if len(contents) == read_limit or not _console_uses_relay(contents):
        return False, (f'FAIL: console source {source} does not verify '
                       'the same-origin /cds-ws URL. Fix: deploy the console source '
                       'with the same-origin relay guard.')
    return True, f'PASS: console source {source} uses the same-origin /cds-ws URL.'


def _split_host_port(value):
    if value.startswith('['):
        end = value.find(']')
        return value[1:end], value[end + 2:]
    return value.rsplit(':', 1)


def _listener_addresses(output, port):
    addresses = []
    for line in output.splitlines():
        columns = line.split()
        for column in columns:
            if ':' not in column:
                continue
            try:
                address, found_port = _split_host_port(column)
            except (ValueError, IndexError):
                continue
            if found_port == str(port):
                addresses.append(address)
                break
    return addresses


def _is_loopback(address):
    return address == 'localhost' or address.startswith('127.') or address == '::1'


def _is_named(address, interface):
    return address == interface and address not in ('0.0.0.0', '*', '::')


async def _check_foreign_origin(gateway_url, origin):
    foreign = 'https://foreign-origin.invalid'
    if foreign == origin:
        foreign = 'https://other-origin.invalid'
    try:
        async with websockets.connect(gateway_url, origin=foreign):
            return False, 'FAIL: nginx accepted a WebSocket with a foreign Origin.'
    except websockets.exceptions.InvalidHandshake as exc:
        # websockets exposes HTTP status differently in its legacy and current clients.
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status == 403 or getattr(exc, 'status_code', None) == 403:
            return True, 'PASS: nginx refuses a WebSocket with a foreign Origin.'
    except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException):
        pass
    return False, 'FAIL: nginx did not return HTTP 403 for a foreign Origin.'


async def check_live(gateway_url, cds_url):
    try:
        endpoint = urlsplit(gateway_url)
        port = endpoint.port
    except ValueError:
        return [(False, 'FAIL: invalid live gateway URL.')]
    options = {}
    origin_check = []
    if endpoint.path == '/cds-ws':
        if not endpoint.hostname or endpoint.scheme not in ('ws', 'wss'):
            return [(False, 'FAIL: invalid nginx WebSocket URL.')]
        scheme, default_port = ('https', 443) if endpoint.scheme == 'wss' else ('http', 80)
        host = endpoint.hostname
        if ':' in host:
            host = f'[{host}]'
        if port is not None and port != default_port:
            host = f'{host}:{port}'
        origin = f'{scheme}://{host}'
        options['origin'] = origin
        origin_check.append(await _check_foreign_origin(gateway_url, origin))
        if not origin_check[0][0]:
            return origin_check

    probe = 'deepsignal_gateway_self_test'
    publish_data = {'timestamp': time.time(), 'fields': {probe: 1}}
    publish = {'type': 'publish', 'data': publish_data}
    try:
        async with websockets.connect(gateway_url, **options) as gateway:
            await gateway.send(json.dumps(publish))
            response = json.loads(await asyncio.wait_for(gateway.recv(), 3))
            refused = response.get('status') == 403
        publish_line = ('PASS: live publish through the gateway is refused.' if refused else
                        'FAIL: gateway accepted a live publish. Fix: run the read-only gateway.')

        async with websockets.connect(cds_url) as cds:
            await cds.send(json.dumps(publish))
            await asyncio.wait_for(cds.recv(), 3)
        async with websockets.connect(gateway_url, **options) as gateway:
            subscribe = {'type': 'subscribe', 'fields': {probe: {'seconds': -1}}}
            await gateway.send(json.dumps(subscribe))
            await asyncio.wait_for(gateway.recv(), 3)
            await gateway.send(json.dumps({'type': 'ready'}))
            response = json.loads(await asyncio.wait_for(gateway.recv(), 3))
            subscribed = probe in response.get('data', {})
        if subscribed:
            subscribe_line = 'PASS: live subscribe through the gateway returns data.'
        else:
            subscribe_line = ('FAIL: gateway subscribe returned no data. '
                              'Fix: check the gateway upstream.')
    except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException,
            json.JSONDecodeError):
        publish_line = ('FAIL: live gateway publish check could not connect. '
                        'Fix: start the CDS and read-only gateway.')
        subscribe_line = ('FAIL: live gateway subscribe check could not connect. '
                          'Fix: start the CDS and read-only gateway.')
    return [*origin_check, (publish_line.startswith('PASS:'), publish_line),
            (subscribe_line.startswith('PASS:'), subscribe_line)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--cds-port', type=int, default=8766)
    parser.add_argument('--gateway-port', type=int, default=8767)
    parser.add_argument('--gateway-url', default='ws://127.0.0.1:8767')
    parser.add_argument('--cds-url', default='ws://127.0.0.1:8766')
    parser.add_argument('--nginx-config',
                        default='/etc/nginx/nginx.conf')
    parser.add_argument('--nginx-react-config', metavar='PATH',
                        help='also check the React nginx configuration')
    parser.add_argument('--console-source', metavar='PATH',
                        help='inspect src/pages.ts in the deployed console checkout')
    parser.add_argument('--nginx-site', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--nginx-dump', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--nginx-site-snapshot', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--nginx-server-offset', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--allow-missing-relay', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--nginx-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--udp-port', type=int)
    parser.add_argument('--udp-interface')
    args = parser.parse_args()
    selection = (args.nginx_site, args.nginx_site_snapshot, args.nginx_server_offset)
    if any(value is not None for value in selection) and any(
            value is None for value in selection):
        parser.error('the nginx site, snapshot and server offset must be specified together')
    if args.allow_missing_relay and args.nginx_site is None:
        parser.error('--allow-missing-relay requires a selected nginx server')
    checks = []
    configs = [args.nginx_config]
    if args.nginx_react_config is not None:
        configs.append(args.nginx_react_config)
    for config in dict.fromkeys(configs):
        checks.append(check_nginx(config, args.gateway_port,
                                  cds_port=args.cds_port, udp_port=args.udp_port,
                                  site=args.nginx_site, snapshot=args.nginx_site_snapshot,
                                  offset=args.nginx_server_offset,
                                  dump=args.nginx_dump if config == args.nginx_config else None,
                                  allow_missing=args.allow_missing_relay))
    if not args.nginx_only and all(ok and line != _NO_RELAY for ok, line in checks):
        checks.extend([check_cds_listener(port=args.cds_port),
                       check_udp_listener(args.udp_port, args.udp_interface)])
        if args.console_source is not None:
            checks.append(check_console_source(args.console_source))
        if all(ok for ok, unused_line in checks):
            checks.extend(asyncio.run(check_live(args.gateway_url, args.cds_url)))
    for unused_ok, line in checks:
        print(line)
    raise SystemExit(0 if all(ok for ok, unused_line in checks) else 1)


if __name__ == '__main__':
    main()
