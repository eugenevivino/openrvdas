import asyncio
from contextlib import asynccontextmanager, suppress
import json
import socket
import struct
from unittest import mock
from urllib.parse import urlsplit

import pytest
import websockets

from contrib.deepsignal.security.cds_gateway import MAX_FRAME_BYTES
from contrib.deepsignal.security.cds_gateway import ReadOnlyGateway
from logger.writers.cached_data_writer import CachedDataWriter
from server.cached_data_server import RecordCache, WebSocketConnection


async def run_gateway_test(test, send_data=None):
    received = []

    async def upstream(websocket):
        async for message in websocket:
            received.append(message)
            request = json.loads(message)
            if request['type'] == 'subscribe':
                await websocket.send('{"type":"subscribe","status":200}')
            elif request['type'] == 'ready':
                if send_data is None:
                    await websocket.send('{"type":"data","data":{"temperature":[[1,2]]}}')
                else:
                    await send_data(websocket)

    # Run the real WebSocket handshakes and framing over local socket pairs.
    loop = asyncio.get_running_loop()
    factories = {}
    gateway_ready = asyncio.Event()
    websocket_connect = websockets.connect

    async def create_server(factory, host, port, **kwargs):
        assert host == '127.0.0.1'
        factories[port] = factory
        if port == 8767:
            gateway_ready.set()
        return mock.Mock(get_loop=lambda: loop, is_serving=lambda: True, sockets=(),
                         wait_closed=mock.AsyncMock())

    @asynccontextmanager
    async def connect(url, **kwargs):
        client, server = socket.socketpair()
        with client, server:
            transport, _ = await loop.connect_accepted_socket(factories[urlsplit(url).port], server)
            try:
                async with websocket_connect(url, sock=client, **kwargs) as websocket:
                    yield websocket
            finally:
                transport.close()

    with mock.patch.object(loop, 'create_server', create_server):
        with mock.patch.object(websockets, 'connect', connect):
            async with websockets.serve(upstream, '127.0.0.1', 8766):
                gateway = asyncio.create_task(ReadOnlyGateway().serve())
                try:
                    await asyncio.wait_for(gateway_ready.wait(), 2)
                    await test('ws://127.0.0.1:8767', received)
                finally:
                    gateway.cancel()
                    with suppress(asyncio.CancelledError):
                        await gateway


@pytest.mark.parametrize('host', ['', '0.0.0.0', '::', '192.0.2.10', 'example.invalid'])
def test_gateway_refuses_non_loopback_listen_address(host):
    async def test():
        with mock.patch.object(websockets, 'serve', side_effect=AssertionError('attempted bind')):
            with pytest.raises(ValueError, match='127.0.0.1'):
                await ReadOnlyGateway(host=host).serve()
    asyncio.run(test())


def test_gateway_refuses_other_listen_port():
    async def test():
        with mock.patch.object(websockets, 'serve', side_effect=AssertionError('attempted bind')):
            with pytest.raises(ValueError, match='8767'):
                await ReadOnlyGateway(port=8768).serve()
    asyncio.run(test())


def test_publish_refused_through_gateway():
    async def test(url, received):
        async with websockets.connect(url) as websocket:
            await websocket.send('{"type":"publish","data":{"fields":{"bad":1}}}')
            assert json.loads(await websocket.recv())['status'] == 403
        assert received == []
    asyncio.run(run_gateway_test(test))


def test_subscribe_passes_through():
    async def test(url, received):
        async with websockets.connect(url) as websocket:
            subscribe = '{"type":"subscribe","fields":{"temperature":{}}}'
            await websocket.send(subscribe)
            assert await websocket.recv() == '{"type":"subscribe","status":200}'
            await websocket.send('{"type":"ready"}')
            expected = '{"type":"data","data":{"temperature":[[1,2]]}}'
            assert await websocket.recv() == expected
        assert received[0] == subscribe
    asyncio.run(run_gateway_test(test))


def test_oversize_upstream_frame_refused_and_same_subscription_still_passes():
    limit = 1024 * 1024
    subscribe = '{"type":"subscribe","fields":{"temperature":{"seconds":1}}}'
    data = '{"type":"data","data":{"temperature":[[1,2]]}}'.ljust(limit)
    oversized = True

    async def send_data(upstream):
        if oversized:
            # An unmasked frame header is enough to reject the advertised size.
            upstream.transport.write(struct.pack('!BBQ', 0x81, 127, limit + 1))
            await upstream.wait_closed()
        else:
            await upstream.send(data)

    async def test(url, received):
        nonlocal oversized
        async with websockets.connect(url) as websocket:
            await websocket.send(subscribe)
            assert json.loads(await websocket.recv())['status'] == 200
            await websocket.send('{"type":"ready"}')
            with pytest.raises(websockets.exceptions.ConnectionClosedError) as closed:
                await asyncio.wait_for(websocket.recv(), 2)
            assert closed.value.rcvd.code == 1009
            assert closed.value.rcvd.reason == 'live-data server reply exceeds size limit'
        oversized = False
        async with websockets.connect(url) as websocket:
            await websocket.send(subscribe)
            assert json.loads(await websocket.recv())['status'] == 200
            await websocket.send('{"type":"ready"}')
            assert await asyncio.wait_for(websocket.recv(), 2) == data
        assert received == [subscribe, '{"type":"ready"}'] * 2

    asyncio.run(run_gateway_test(test, send_data))


def test_unknown_type_and_non_json_refused():
    async def test(url, received):
        async with websockets.connect(url) as websocket:
            await websocket.send('{"type":"delete"}')
            assert json.loads(await websocket.recv())['status'] == 403
            await websocket.send('not json')
            assert json.loads(await websocket.recv())['status'] == 403
        assert received == []
    asyncio.run(run_gateway_test(test))


def test_unexpected_request_type_refused():
    async def test(url, received):
        async with websockets.connect(url) as websocket:
            await websocket.send('{"type":[]}')
            assert json.loads(await asyncio.wait_for(websocket.recv(), 2))['status'] == 403
        assert received == []
    asyncio.run(run_gateway_test(test))


@pytest.mark.parametrize('send_payload', [True, False], ids=['whole-message', 'header-only'])
def test_oversize_frame_refused(send_payload):
    async def test(url, received):
        compression = 'deflate' if send_payload else None
        async with websockets.connect(url, compression=compression) as websocket:
            if send_payload:
                await websocket.send('x' * 65537)
            else:
                # Declare a masked text frame and omit its payload. The close
                # must arrive while the gateway has only the length header.
                websocket.transport.write(struct.pack('!BBQ', 0x81, 0xff, 65537))
            with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                await asyncio.wait_for(websocket.recv(), 2)
            assert closed.value.rcvd.code == 1009
        assert received == []
    asyncio.run(run_gateway_test(test))


def test_message_at_size_limit_passes():
    async def test(url, received):
        async with websockets.connect(url, compression=None) as websocket:
            subscribe = '{"type":"subscribe","fields":{"temperature":{}}}'
            subscribe = subscribe.ljust(MAX_FRAME_BYTES)
            await websocket.send(subscribe)
            assert json.loads(await websocket.recv())['status'] == 200
        assert received == [subscribe]
    asyncio.run(run_gateway_test(test))


def test_rate_limit_closes_1008():
    async def test(url, unused_received):
        with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
            async with websockets.connect(url) as websocket:
                for unused_index in range(21):
                    await websocket.send('{"type":"fields"}')
                await websocket.recv()
        assert closed.value.code == 1008
    asyncio.run(run_gateway_test(test))


def test_field_cap():
    async def test(url, unused_received):
        fields = {'field_%d' % index: {} for index in range(201)}
        with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
            async with websockets.connect(url) as websocket:
                await websocket.send(json.dumps({'type': 'subscribe', 'fields': fields}))
                await websocket.recv()
        assert closed.value.code == 1008
    asyncio.run(run_gateway_test(test))


def test_wildcard_that_exceeds_field_cap_is_refused():
    field_names = [f'field_{index}' for index in range(201)]
    cache = RecordCache()
    cache.cache_record({'fields': dict.fromkeys(field_names, 1)})
    cds_connection = WebSocketConnection(None, cache, interval=1)
    assert set(cds_connection.get_matching_field_names('field_*')) == set(field_names)

    async def test(url, received):
        async with websockets.connect(url) as websocket:
            await websocket.send(r'{"type":"subscribe","fields":{"field_\u002a":{}}}')
            with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                await asyncio.wait_for(websocket.recv(), 2)
            assert closed.value.rcvd.code == 1008
        assert received == []
    asyncio.run(run_gateway_test(test))


def test_local_writer_still_publishes():
    with mock.patch('logger.writers.cached_data_writer.threading.Thread.start'):
        writer = CachedDataWriter('8766')
    record = {'fields': {'temperature': 2}}
    writer.write(record)
    assert writer.data_server == 'localhost:8766'
    assert writer.send_queue.get_nowait() == record
