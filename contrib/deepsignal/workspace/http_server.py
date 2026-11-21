"""Disposable loopback fixture UI/API. Never bind to a vessel network."""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import time

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute, Mount
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from .service import Workspace, LIMITS


def create_app(workspace, origin='http://127.0.0.1:8765'):
    token = secrets.token_urlsafe(32)
    authority = origin.removeprefix('http://')
    epoch = time.time() - 6
    console = Path(__file__).resolve().parents[1] / 'console'
    service_slot = asyncio.Lock()

    def permitted(headers):
        return (headers.get('host') == authority and
                headers.get('origin') in (None, origin) and
                headers.get('sec-fetch-site') not in ('cross-site', 'same-site'))

    async def session(request):
        if not permitted(request.headers):
            return Response(status_code=403)
        return JSONResponse({'token': token}, headers={'Cache-Control': 'no-store'})

    async def call(request):
        if (not permitted(request.headers) or
                not secrets.compare_digest(request.headers.get('x-deepsignal-token', ''), token)):
            return Response(status_code=403)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return Response(status_code=415)
        try:
            body = bytearray()
            async with asyncio.timeout(3):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > LIMITS['request_bytes']:
                        return Response(status_code=413)
            value = json.loads(body)
            if not isinstance(value, dict) or set(value) != {'method', 'arguments'}:
                return Response(status_code=400)
            if service_slot.locked():
                return Response(status_code=429, headers={'Retry-After': '1'})
            async with service_slot:
                result = await run_in_threadpool(workspace.call, value['method'], value['arguments'])
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except (ValueError, RecursionError, TimeoutError):
            return Response(status_code=400)

    async def config(request):
        return Response('''ship: SIMULATED Fixture Vessel
ship_timezone: UTC
pages: []
history: 300
night_palette: red
qc_suffix: _QC
modules: {}
period:
  FixtureTemperature: 1
  FixtureConductivity: 1
''', media_type='application/yaml', headers={'Cache-Control': 'no-store'})

    async def cache(socket):
        if not permitted(socket.headers):
            await socket.close(code=1008)
            return
        await socket.accept()
        fields = {'FixtureTemperature': (9, 'degree_Celsius'),
                  'FixtureConductivity': (42, 'mS/cm')}
        stages = {'sensor': 'UNKNOWN', 'endpoint': 'UNKNOWN', 'raw_traffic': 'OK',
                  'parser': 'FAILED', 'time': 'UNKNOWN', 'calibration': 'UNKNOWN',
                  'derived': 'FAILED', 'store': 'UNKNOWN', 'root': 'parser'}
        for stage, value in stages.items():
            fields['ds_chain:fixture-temperature:' + stage] = (value, None)
        subscribed = []
        try:
            while True:
                raw = await asyncio.wait_for(socket.receive_text(), timeout=30)
                if len(raw) > 8192:
                    await socket.close(code=1009)
                    return
                request = json.loads(raw)
                kind = request.get('type')
                if kind == 'fields':
                    data = list(fields)
                elif kind == 'describe':
                    data = {name: {'description': 'SIMULATED fixture evidence',
                                   **({'units': unit} if unit else {})} for name, (_, unit) in fields.items()}
                elif kind == 'subscribe':
                    requested = request.get('fields', {})
                    if not isinstance(requested, dict) or len(requested) > 64:
                        await socket.close(code=1008)
                        return
                    subscribed = [name for name in requested if name in fields]
                    data = {}
                elif kind == 'ready':
                    await asyncio.sleep(0.5)
                    kind = 'data'
                    data = {name: [[epoch - 1 if name == 'FixtureTemperature' else time.time(), fields[name][0]]]
                            for name in subscribed}
                else:
                    await socket.close(code=1008)
                    return
                await socket.send_json({'type': kind, 'status': 200, 'data': data})
        except (WebSocketDisconnect, TimeoutError, ValueError):
            return

    return Starlette(routes=[
        Route('/api/workspace/session', session),
        Route('/api/workspace/call', call, methods=['POST']),
        Route('/console/console.yaml', config),
        WebSocketRoute('/cds-ws', cache),
        Mount('/console', StaticFiles(directory=console / 'dist', html=True)),
    ])


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('use an unprivileged loopback port')
    app = create_app(Workspace(args.state), origin=f'http://127.0.0.1:{args.port}')
    uvicorn.run(app, host='127.0.0.1', port=args.port, workers=1,
                # Static module/font loading needs browser burst capacity; the
                # separate application slot still admits only one service call.
                limit_concurrency=32, timeout_keep_alive=3, ws_max_size=8192,
                ws_max_queue=4, log_level='warning')


if __name__ == '__main__':
    main()
