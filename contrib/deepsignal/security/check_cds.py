#!/usr/bin/env python3
"""Check that the Cached Data Server is reachable only through its gateway."""

import argparse
import asyncio
from ipaddress import ip_address
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import time
from urllib.parse import urlsplit

import websockets


SS_PATH = '/usr/bin:/usr/sbin:/bin:/sbin'
SS_TIMEOUT = 3


def _run(runner, option):
    binary = shutil.which('ss', path=SS_PATH)
    if runner is None:
        if binary is None:
            return ''
        runner = subprocess.run
    # An injected runner can supply listener output on a host without iproute2.
    try:
        result = runner([binary or '/usr/bin/ss', option], capture_output=True,
                        text=True, check=False, timeout=SS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ''
    if isinstance(result, str):
        return result
    return '' if getattr(result, 'returncode', 0) else result.stdout


def check_cds_listener(runner=None, port=8766):
    output = _run(runner, '-ltn')
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


def check_udp_listener(port=None, interface=None, runner=None):
    if port is None:
        return True, 'PASS: no UDP live-data feed is configured.'
    output = _run(runner, '-lun')
    addresses = _listener_addresses(output, port)
    if (not interface or not addresses or
            any(not _is_named(address, interface) for address in addresses)):
        return False, ('FAIL: UDP live-data feed is not bound to its named interface. '
                       'Anyone on the ship network can inject display data. '
                       'Fix: start it with --udp_interface and the feed interface address.')
    return True, 'PASS: UDP live-data feed is bound to its named interface.'


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
    if address != interface or address == '*':
        return False
    try:
        return not ip_address(address).is_unspecified
    except ValueError:
        return True  # Keep literal matching for interface names.


async def _check_foreign_origin(gateway_url, origin, **options):
    foreign = 'https://foreign-origin.invalid'
    if foreign == origin:
        foreign = 'https://other-origin.invalid'
    try:
        async with websockets.connect(gateway_url, origin=foreign, **options):
            return False, 'FAIL: nginx accepted a WebSocket with a foreign Origin.'
    except websockets.exceptions.InvalidHandshake as exc:
        # websockets exposes HTTP status differently in its legacy and current clients.
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status == 403 or getattr(exc, 'status_code', None) == 403:
            return True, 'PASS: nginx refuses a WebSocket with a foreign Origin.'
    except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException):
        pass
    return False, 'FAIL: nginx did not return HTTP 403 for a foreign Origin.'


async def check_live(gateway_url, cds_url, *, local_nginx=False):
    try:
        endpoint = urlsplit(gateway_url)
        port = endpoint.port
    except ValueError:
        return [(False, 'FAIL: invalid live gateway URL.')]
    options = {'host': '127.0.0.1'} if local_nginx else {}
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
        origin_check.append(await _check_foreign_origin(gateway_url, origin, **options))
        options['origin'] = origin
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
    renderer = runpy.run_path(str(Path(__file__).parent / 'nginx/render_site.py'))
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    renderer['add_site_arguments'](parser)
    parser.add_argument('--site-only', action='store_true')
    parser.add_argument('--cds-port', type=int, default=8766)
    parser.add_argument('--gateway-url')
    parser.add_argument('--local-nginx', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--cds-url', default='ws://127.0.0.1:8766')
    parser.add_argument('--udp-port', action='append', type=int, default=[])
    parser.add_argument('--udp-interface')
    args = parser.parse_args()
    if args.nginx_site is None:
        parser.error('--nginx-site is required')
    if bool(args.udp_port) != bool(args.udp_interface):
        parser.error('supply --udp-port and --udp-interface together')
    if any(not 1 <= port <= 65535 for port in args.udp_port):
        parser.error('--udp-port must be between 1 and 65535')
    try:
        site = renderer['render_site'](args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    checks = [renderer['check_site'](args.nginx_site, site.contents)]
    if not args.site_only and checks[0][0]:
        checks.append(check_cds_listener(port=args.cds_port))
        checks.extend(check_udp_listener(port, args.udp_interface)
                      for port in args.udp_port or [None])
        if all(ok for ok, unused in checks):
            checks.extend(asyncio.run(check_live(args.gateway_url or site.gateway_url,
                                                 args.cds_url, local_nginx=args.local_nginx)))
    for unused_ok, line in checks:
        print(line)
    raise SystemExit(0 if all(ok for ok, unused_line in checks) else 1)


if __name__ == '__main__':
    main()
