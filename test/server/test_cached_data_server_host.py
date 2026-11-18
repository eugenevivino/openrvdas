from unittest import mock

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


def test_default_host_keeps_all_interface_behavior():
    assert CachedDataServer.__init__.__defaults__[0] == ''
