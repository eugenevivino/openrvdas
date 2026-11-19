#!/usr/bin/env python3
"""Check that the Cached Data Server is reachable only through its gateway."""

import argparse
import asyncio
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
    r'''\s+|\#[^\n]*|[{};]|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|'''
    r'''(?:\$\{[^{}\s]+\}|\\.|[^\s{};'"\\])+''', re.DOTALL)


def _nginx_directives(contents):
    if '\0' in contents:
        raise ValueError('unexpected null byte')
    blocks = []
    words = []
    position = 0
    while position < len(contents):
        match = _NGINX_TOKEN.match(contents, position)
        if match is None:
            raise ValueError('unrecognized nginx token')
        token = match[0]
        position = match.end()
        if token.isspace() or token.startswith('#'):
            continue
        if token == '}':
            if words or not blocks:
                raise ValueError('unexpected nginx block close')
            blocks.pop()
        elif token in ('{', ';'):
            if not words:
                raise ValueError('empty nginx directive')
            directive = tuple(words)
            yield tuple(blocks), directive, token == '{'
            if token == '{':
                blocks.append(directive)
            words.clear()
        else:
            words.append(token[1:-1] if token[0] in "\"'" else token)
    if words or blocks:
        raise ValueError('incomplete nginx configuration')


def _cds_location(directive):
    return directive in (('location', '/cds-ws'), ('location', '=', '/cds-ws'),
                         ('location', '^~', '/cds-ws'))


def _unsafe_upstream(target, ports):
    if target.startswith(('unix:', 'http://unix:', 'https://unix:')):
        return False
    if '$' in target or '\\' in target:
        return True
    try:
        endpoint = urlsplit(target if '://' in target else f'//{target}')
        return endpoint.port in ports
    except ValueError:
        return True


def _nginx_uses_relay(contents, gateway_port, cds_port, udp_port):
    routes = []
    relays = 0
    possible_overrides = set()
    ports = {cds_port} if udp_port is None else {cds_port, udp_port}
    allowed = {f'http://127.0.0.1:{gateway_port}', f'http://localhost:{gateway_port}'}
    for blocks, directive, is_block in _nginx_directives(contents):
        name, *args = directive
        if is_block and _cds_location(directive):
            routes.append((blocks, directive))
        if name == 'include' or (name == 'location' and args and args[0] in ('~', '~*')):
            possible_overrides.add(blocks)
        if not is_block and (name.endswith('_pass') or name == 'server'):
            if not args or _unsafe_upstream(args[0], ports):
                return False
        if name == 'listen' and 'udp' in args[1:]:
            port = args[0].rsplit(':', 1)[-1]
            if not port.isdecimal() or int(port) == udp_port:
                return False
        if any(_cds_location(block) for block in blocks):
            if name == 'proxy_pass' and not is_block and _cds_location(blocks[-1]):
                if len(args) != 1 or args[0] not in allowed:
                    return False
                relays += 1
            elif name.endswith('_pass') or name in (
                    'include', 'rewrite', 'try_files', 'error_page'):
                return False

    if len(routes) != 1 or relays != 1:
        return False
    parents, route = routes[0]
    return route[1] != '/cds-ws' or parents not in possible_overrides


def check_nginx(config, gateway_port=8767, *, cds_port=8766, udp_port=None):
    try:
        contents = Path(config).read_text(encoding='utf-8')
        safe = _nginx_uses_relay(contents, gateway_port, cds_port, udp_port)
    except (OSError, ValueError):
        return False, (f'FAIL: nginx CDS gateway configuration {config} cannot be read or parsed. '
                       'Fix: install the cds-ws.conf security template.')
    if not safe:
        return False, (f'FAIL: nginx configuration {config} does not verify a read-only /cds-ws '
                       f'route. Fix: proxy /cds-ws to 127.0.0.1:{gateway_port} '
                       'and remove direct CDS routes.')
    return True, f'PASS: nginx /cds-ws points to the read-only gateway in {config}.'


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

    # Verify the checked-in URL builder, override guard, and active config wiring.
    builder = re.search(r'^function relayUrl\([^\n]+\) \{\n([^\n]+\n)\}',
                        contents, re.MULTILINE)
    loader = re.search(r'^export async function loadConsole\([^\n]+\) \{\n',
                       contents, re.MULTILINE)
    expected_builder = "  return `${protocol === 'https:' ? 'wss:' : 'ws:'}//${host}/cds-ws`\n"
    expected_loader = (
        "  const raw = parseConsole((await fetchFile('console.yaml', signal))!, window.location)\n"
        '  const websocket = relayUrl(window.location)\n'
        '  if (new URL(raw.websocket).href !== new URL(websocket).href) {\n'
        "    throw new Error('console.yaml: Use the same-origin /cds-ws read-only relay. "
        "Remove the websocket setting to use it automatically.')\n"
        '  }\n'
        '  const config: ConsoleConfig = {\n'
        '    ship: raw.ship, shipTimezone: raw.ship_timezone, websocket, pages: raw.pages,')
    if (len(contents) == read_limit or builder is None or builder[1] != expected_builder or
            loader is None or not contents.startswith(expected_loader, loader.end())):
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


async def check_live(gateway_url, cds_url):
    probe = 'deepsignal_gateway_self_test'
    publish_data = {'timestamp': time.time(), 'fields': {probe: 1}}
    publish = {'type': 'publish', 'data': publish_data}
    try:
        async with websockets.connect(gateway_url) as gateway:
            await gateway.send(json.dumps(publish))
            response = json.loads(await asyncio.wait_for(gateway.recv(), 3))
            refused = response.get('status') == 403
        publish_line = ('PASS: live publish through the gateway is refused.' if refused else
                        'FAIL: gateway accepted a live publish. Fix: run the read-only gateway.')

        async with websockets.connect(cds_url) as cds:
            await cds.send(json.dumps(publish))
            await asyncio.wait_for(cds.recv(), 3)
        async with websockets.connect(gateway_url) as gateway:
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
    return [(publish_line.startswith('PASS:'), publish_line),
            (subscribe_line.startswith('PASS:'), subscribe_line)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--cds-port', type=int, default=8766)
    parser.add_argument('--gateway-port', type=int, default=8767)
    parser.add_argument('--gateway-url', default='ws://127.0.0.1:8767')
    parser.add_argument('--cds-url', default='ws://127.0.0.1:8766')
    parser.add_argument('--nginx-config',
                        default='/etc/nginx/conf.d/cds-ws.conf')
    parser.add_argument('--nginx-react-config', metavar='PATH',
                        help='also check the React nginx configuration')
    parser.add_argument('--console-source', metavar='PATH',
                        help='inspect src/pages.ts in the deployed console checkout')
    parser.add_argument('--udp-port', type=int)
    parser.add_argument('--udp-interface')
    args = parser.parse_args()

    checks = [check_cds_listener(port=args.cds_port),
              check_udp_listener(args.udp_port, args.udp_interface)]
    configs = [args.nginx_config]
    if args.nginx_react_config is not None:
        configs.append(args.nginx_react_config)
    for config in dict.fromkeys(configs):
        checks.append(check_nginx(config, args.gateway_port,
                                  cds_port=args.cds_port, udp_port=args.udp_port))
    if args.console_source is not None:
        checks.append(check_console_source(args.console_source))
    if all(ok for ok, unused_line in checks):
        checks.extend(asyncio.run(check_live(args.gateway_url, args.cds_url)))
    for unused_ok, line in checks:
        print(line)
    raise SystemExit(0 if all(ok for ok, unused_line in checks) else 1)


if __name__ == '__main__':
    main()
