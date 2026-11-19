from configparser import ConfigParser
from inspect import signature
from pathlib import Path
import runpy
import shlex
import socket
import sys
from unittest import mock

import pytest

from server import cached_data_server
from server.cached_data_server import CachedDataServer


def test_host_is_passed_to_websocket_server():
    server = CachedDataServer.__new__(CachedDataServer)
    server.port = 8766
    server.host = '127.0.0.1'
    server.event_loop = mock.Mock()
    server.event_loop.is_running.return_value = True
    server._serve_websocket_data = mock.Mock()
    with mock.patch('server.cached_data_server.websockets.serve') as serve:
        with mock.patch('server.cached_data_server.asyncio.ensure_future'):
            server._run_websocket_server()
    assert serve.call_args.kwargs['host'] == '127.0.0.1'


def test_default_host_is_loopback():
    assert signature(CachedDataServer).parameters['host'].default == '127.0.0.1'


def test_positional_interval_is_preserved():
    with mock.patch('threading.Thread.start'), mock.patch('asyncio.set_event_loop'):
        server = CachedDataServer(8766, 0.25)
    assert server.interval == 0.25
    assert server.host == '127.0.0.1'


class TCPStartupReached(Exception):
    pass


def run_cli(args):
    path = cached_data_server.__file__
    with mock.patch.object(sys, 'argv', [path, *args]):
        with mock.patch('asyncio.new_event_loop', side_effect=TCPStartupReached):
            runpy.run_path(path, run_name='__main__')


def test_cds_cli_defaults_to_port_8766():
    with pytest.raises(TCPStartupReached):
        run_cli([])
    assert signature(CachedDataServer).parameters['port'].default == 8766


@pytest.mark.parametrize('host', ['', '0.0.0.0', '::', '192.0.2.10', 'example.invalid'])
def test_cds_cli_refuses_unsafe_host_without_override(host, capsys):
    with pytest.raises(SystemExit) as error:
        run_cli(['--port', '8766', '--host', host])
    assert error.value.code == 2
    assert '--host' in capsys.readouterr().err


@pytest.mark.parametrize('host', ['0.0.0.0', '::', '192.0.2.10'])
def test_cds_cli_allows_explicit_non_loopback_override(host):
    with pytest.raises(TCPStartupReached):
        run_cli(['--port', '8766', '--host', host, '--allow-non-loopback'])


def test_cds_cli_refuses_abbreviated_override(capsys):
    with pytest.raises(SystemExit) as error:
        run_cli(['--port', '8766', '--host', '0.0.0.0', '--allow-non-loop'])
    assert error.value.code == 2
    assert 'unrecognized arguments: --allow-non-loop' in capsys.readouterr().err


@pytest.mark.parametrize('host', [None, '0.0.0.0', '192.0.2.10'])
def test_cds_constructor_refuses_unsafe_host(host):
    with mock.patch('threading.Thread.start') as start:
        with pytest.raises(ValueError, match='host'):
            CachedDataServer(8766, host=host)
    start.assert_not_called()


@pytest.mark.parametrize('interface', [None, '', '0.0.0.0', '::', 'instrument.invalid'])
def test_cds_cli_refuses_udp_without_specific_interface(interface, capsys):
    udp_args = [] if interface is None else ['--udp_interface', interface]
    with pytest.raises(SystemExit) as error:
        run_cli(['--port', '8766', '--udp', '6221,6224', *udp_args])
    assert error.value.code == 2
    assert '--udp_interface' in capsys.readouterr().err


@pytest.mark.parametrize('udp', ['', '6221,', '6221,0', '239.1.2.3:extra:6224', '192.0.2.1:6224'])
def test_cds_cli_refuses_invalid_udp_spec(udp, capsys):
    with pytest.raises(SystemExit) as error:
        run_cli(['--port', '8766', '--udp', udp, '--udp_interface', '192.0.2.42'])
    assert error.value.code == 2
    assert '--udp' in capsys.readouterr().err


def test_cds_binds_every_udp_port_to_configured_interface_before_tcp():
    sockets = [mock.Mock() for _ in range(3)]
    with mock.patch('logger.readers.udp_reader.socket.socket', side_effect=sockets):
        with pytest.raises(TCPStartupReached):
            run_cli(['--port', '8766', '--udp', '6221,6224,239.1.2.3:6225',
                     '--udp_interface', '192.0.2.42'])
    sockets[0].bind.assert_called_once_with(('192.0.2.42', 6221))
    sockets[1].bind.assert_called_once_with(('192.0.2.42', 6224))
    sockets[2].bind.assert_called_once_with(('239.1.2.3', 6225))
    sockets[2].setsockopt.assert_any_call(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                         socket.inet_aton('239.1.2.3') + socket.inet_aton('192.0.2.42'))


def test_cds_refuses_startup_if_any_udp_port_fails_to_bind(capsys):
    first, second = mock.Mock(), mock.Mock()
    second.bind.side_effect = OSError('address already in use')
    with mock.patch('logger.readers.udp_reader.socket.socket', side_effect=[first, second]):
        with pytest.raises(SystemExit) as error:
            run_cli(['--port', '8766', '--udp', '6221,6224', '--udp_interface', '192.0.2.42'])
    assert error.value.code == 2
    assert '6224' in capsys.readouterr().err
    first.close.assert_called_once()


def test_shipped_supervisor_config_pins_cds_bindings():
    config = ConfigParser()
    root = Path(cached_data_server.__file__).resolve().parents[1]
    config.read(root / 'contrib/deepsignal/security/supervisor/cached_data_server.conf')
    command = config.get('program:cached_data_server', 'command', vars={
        'ENV_CDS_UDP_PORTS': '6221,6224', 'ENV_CDS_UDP_INTERFACE': '192.0.2.42',
    })
    assert shlex.split(command) == [
        'python3', 'server/cached_data_server.py', '--port', '8766', '--host', '127.0.0.1',
        '--udp', '6221,6224', '--udp_interface', '192.0.2.42',
        '--disk_cache', '/var/tmp/openrvdas/disk_cache', '--max_records', '8640', '-v',
    ]
