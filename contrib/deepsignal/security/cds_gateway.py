#!/usr/bin/env python3
"""Read-only WebSocket gateway for the Cached Data Server."""

import argparse
import asyncio
import json
import logging
import time

import websockets


ALLOWED_TYPES = frozenset(('fields', 'describe', 'subscribe', 'ready'))
LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 8767
MAX_FRAME_BYTES = 64 * 1024
MAX_UPSTREAM_FRAME_BYTES = 1024 * 1024
MAX_FIELDS = 200
MAX_CONNECTIONS = 50
RATE = 4.0
BURST = 20.0


class ReadOnlyGateway:
    """Relay safe CDS requests without exposing its publish operation."""

    def __init__(self, upstream='ws://127.0.0.1:8766', host=LISTEN_HOST,
                 port=LISTEN_PORT, allowed_types=ALLOWED_TYPES):
        self.upstream = upstream
        self.host = host
        self.port = port
        self.allowed_types = frozenset(allowed_types) if allowed_types else frozenset()
        self._connections = 0
        self._connection_lock = asyncio.Lock()

    @staticmethod
    def _headers(websocket):
        request = getattr(websocket, 'request', None)
        if request is not None:
            return request.headers
        return getattr(websocket, 'request_headers', {})

    async def handler(self, websocket, unused_path=None):
        """Handle one browser connection and its matching CDS connection."""
        async with self._connection_lock:
            if self._connections >= MAX_CONNECTIONS:
                await websocket.close(1008, 'too many connections')
                return
            self._connections += 1

        headers = self._headers(websocket)
        user = headers.get('X-DS-User', '')
        role = headers.get('X-DS-Role', '')
        peer = getattr(websocket, 'remote_address', None)
        logging.info('CDS gateway connect peer=%s user=%s role=%s', peer, user, role)
        try:
            async with websockets.connect(self.upstream,
                                          max_size=MAX_UPSTREAM_FRAME_BYTES) as upstream:
                await self._relay(websocket, upstream)
        except (OSError, websockets.exceptions.ConnectionClosed):
            if not getattr(websocket, 'closed', False):
                await websocket.close(1011, 'live-data server unavailable')
        finally:
            async with self._connection_lock:
                self._connections -= 1
            logging.info('CDS gateway disconnect peer=%s user=%s role=%s',
                         peer, user, role)

    async def _relay(self, client, upstream):
        subscriptions = set()
        tokens = BURST
        updated = time.monotonic()

        async def client_to_server():
            nonlocal tokens, updated
            async for message in client:
                now = time.monotonic()
                tokens = min(BURST, tokens + ((now - updated) * RATE))
                updated = now
                if tokens < 1.0:
                    await client.close(1008, 'message rate limit exceeded')
                    return
                tokens -= 1.0

                size = len(message) if isinstance(message, bytes) else len(message.encode())
                if size > MAX_FRAME_BYTES:
                    await self._refuse(client, None)
                    continue
                try:
                    request = json.loads(message)
                except (ValueError, TypeError, RecursionError):
                    await self._refuse(client, None)
                    continue
                request_type = request.get('type') if isinstance(request, dict) else None
                if not isinstance(request_type, str):
                    await self._refuse(client, None)
                    continue
                if request_type not in self.allowed_types:
                    await self._refuse(client, request_type)
                    continue
                if request_type == 'subscribe':
                    fields = request.get('fields', {})
                    if not isinstance(fields, dict):
                        await self._refuse(client, request_type)
                        continue
                    if any('*' in field for field in fields):
                        await client.close(1008, 'wildcard subscriptions are disabled')
                        return
                    proposed = subscriptions | set(fields)
                    if len(proposed) > MAX_FIELDS:
                        await client.close(1008, 'subscribed field limit exceeded')
                        return
                    subscriptions.clear()
                    subscriptions.update(proposed)
                await upstream.send(message)

        async def server_to_client():
            async for message in upstream:
                await client.send(message)

        tasks = [asyncio.create_task(client_to_server()),
                 asyncio.create_task(server_to_client())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        results = await asyncio.gather(*done, *pending, return_exceptions=True)
        # Either relay task can observe the locally initiated upstream close first.
        if any(isinstance(exc, websockets.exceptions.ConnectionClosed)
               and exc.sent is not None and exc.sent.code == 1009 and not exc.rcvd_then_sent
               for exc in results):
            await client.close(1009, 'live-data server reply exceeds size limit')

    @staticmethod
    async def _refuse(websocket, request_type):
        response = {'type': request_type, 'status': 403,
                    'error': 'read-only connection'}
        await websocket.send(json.dumps(response, separators=(',', ':')))

    async def serve(self):
        """Run until cancelled."""
        if self.host != LISTEN_HOST or self.port != LISTEN_PORT:
            raise ValueError(f'gateway must listen on {LISTEN_HOST}:{LISTEN_PORT}')
        async with websockets.serve(self.handler, LISTEN_HOST, LISTEN_PORT,
                                    max_size=MAX_FRAME_BYTES):
            await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--host', default=LISTEN_HOST, choices=(LISTEN_HOST,))
    parser.add_argument('--port', type=int, default=LISTEN_PORT, choices=(LISTEN_PORT,))
    parser.add_argument('--upstream', default='ws://127.0.0.1:8766')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    gateway = ReadOnlyGateway(args.upstream, args.host, args.port)
    asyncio.run(gateway.serve())


if __name__ == '__main__':
    main()
