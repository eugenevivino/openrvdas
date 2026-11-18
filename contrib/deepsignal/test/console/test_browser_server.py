"""Verify the browser tests' HTTP and CDS endpoints share one origin."""

import asyncio
from http.client import HTTPConnection
import json
from time import time

import websockets

from contrib.deepsignal.console.demo_cache import LocalCachedDataServer


def test_browser_server_serves_dist_and_relays_cache(tmp_path):
    from contrib.deepsignal.test.console.browser_server import serve_console

    index = b"<!doctype html><title>Console fixture</title>"
    (tmp_path / "index.html").write_bytes(index)
    cache = LocalCachedDataServer(port=0, interval=0.1)
    try:
        cache.cache_record({"timestamp": time(), "fields": {"MwxAirTemp": 19.06}})
        with serve_console(tmp_path, f"ws://127.0.0.1:{cache.port}") as port:
            http = HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                http.request("GET", "/console/")
                response = http.getresponse()
                assert response.status == 200
                assert response.getheader("Content-Type").startswith("text/html")
                assert response.read() == index
            finally:
                http.close()

            async def read_fields():
                async with websockets.connect(f"ws://127.0.0.1:{port}/cds-ws") as ws:
                    await ws.send(json.dumps({"type": "fields"}))
                    return json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

            reply = asyncio.run(read_fields())
            assert reply == {"type": "fields", "status": 200, "data": ["MwxAirTemp"]}
    finally:
        cache.quit()
