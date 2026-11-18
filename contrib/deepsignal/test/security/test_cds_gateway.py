import asyncio
import json
import socket
from unittest import mock

import pytest
import websockets

from contrib.deepsignal.security.cds_gateway import MAX_FRAME_BYTES
from contrib.deepsignal.security.cds_gateway import ReadOnlyGateway
from logger.writers.cached_data_writer import CachedDataWriter


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def run_gateway_test(test):
    received = []

    async def upstream(websocket):
        async for message in websocket:
            received.append(message)
            request = json.loads(message)
            if request['type'] == 'subscribe':
                await websocket.send('{"type":"subscribe","status":200}')
            elif request['type'] == 'ready':
                await websocket.send('{"type":"data","data":{"temperature":[[1,2]]}}')

    upstream_port = free_port()
    gateway_port = free_port()
    gateway = ReadOnlyGateway('ws://127.0.0.1:%d' % upstream_port,
                              port=gateway_port)
    async with websockets.serve(upstream, '127.0.0.1', upstream_port):
        async with websockets.serve(gateway.handler, '127.0.0.1', gateway_port,
                                    max_size=None):
            await test('ws://127.0.0.1:%d' % gateway_port, received)


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


def test_unknown_type_and_non_json_refused():
    async def test(url, received):
        async with websockets.connect(url) as websocket:
            await websocket.send('{"type":"delete"}')
            assert json.loads(await websocket.recv())['status'] == 403
            await websocket.send('not json')
            assert json.loads(await websocket.recv())['status'] == 403
        assert received == []
    asyncio.run(run_gateway_test(test))


def test_oversize_frame_refused():
    async def test(url, received):
        async with websockets.connect(url, max_size=None) as websocket:
            await websocket.send('x' * (MAX_FRAME_BYTES + 1))
            assert json.loads(await websocket.recv())['status'] == 403
        assert received == []
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


def test_local_writer_still_publishes():
    with mock.patch('logger.writers.cached_data_writer.threading.Thread.start'):
        writer = CachedDataWriter('8766')
    record = {'fields': {'temperature': 2}}
    writer.write(record)
    assert writer.data_server == 'localhost:8766'
    assert writer.send_queue.get_nowait() == record
