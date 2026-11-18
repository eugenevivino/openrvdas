#!/usr/bin/env python3
"""Check that the Cached Data Server is reachable only through its gateway."""

import argparse
import asyncio
import json
import re
import subprocess
import time

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


def check_nginx(config, gateway_port=8767):
    try:
        with open(config, encoding='utf-8') as config_file:
            contents = config_file.read()
    except OSError:
        return False, ('FAIL: nginx CDS gateway configuration cannot be read. '
                       'Fix: install the cds-ws.conf security template.')
    location = re.search(r'location\s+(?:=\s+)?/cds-ws\s*\{(.*?)\}', contents, re.DOTALL)
    expected = r'proxy_pass\s+http://(?:127\.0\.0\.1|localhost):%d\s*;' % gateway_port
    if location is None or re.search(expected, location.group(1)) is None:
        return False, ('FAIL: nginx /cds-ws does not point to the read-only gateway. '
                       'Fix: proxy /cds-ws to 127.0.0.1:%d.' % gateway_port)
    return True, 'PASS: nginx /cds-ws points to the read-only gateway.'


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cds-port', type=int, default=8766)
    parser.add_argument('--gateway-port', type=int, default=8767)
    parser.add_argument('--gateway-url', default='ws://127.0.0.1:8767')
    parser.add_argument('--cds-url', default='ws://127.0.0.1:8766')
    parser.add_argument('--nginx-config',
                        default='/etc/nginx/conf.d/cds-ws.conf')
    parser.add_argument('--udp-port', type=int)
    parser.add_argument('--udp-interface')
    args = parser.parse_args()

    checks = [check_cds_listener(port=args.cds_port),
              check_udp_listener(args.udp_port, args.udp_interface),
              check_nginx(args.nginx_config, args.gateway_port)]
    checks.extend(asyncio.run(check_live(args.gateway_url, args.cds_url)))
    for unused_ok, line in checks:
        print(line)
    raise SystemExit(0 if all(ok for ok, unused_line in checks) else 1)


if __name__ == '__main__':
    main()
