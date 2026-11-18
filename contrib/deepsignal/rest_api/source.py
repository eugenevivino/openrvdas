"""Data sources for the DeepSignal REST API."""

import asyncio
import json
from typing import Protocol

import websockets


class SourceUnavailable(RuntimeError):
    """Raised when the CachedDataServer cannot answer a request."""


class DataSource(Protocol):
    """Read-only operations required by the REST server."""

    def fields(self):
        """Return available field names."""

    def describe(self, names):
        """Return metadata keyed by field name."""

    def series(self, name, seconds):
        """Return ``(timestamp, value)`` pairs for one field."""


class CDSSource:
    """Synchronous read-only adapter for a CachedDataServer websocket."""

    def __init__(self, uri="ws://127.0.0.1:8766", timeout=5):
        self.uri = uri
        self.timeout = timeout

    async def _exchange(self, requests):
        async with websockets.connect(self.uri) as websocket:
            responses = []
            for request in requests:
                await websocket.send(json.dumps(request))
                raw = await asyncio.wait_for(websocket.recv(), self.timeout)
                response = json.loads(raw)
                if response.get("status") != 200:
                    raise SourceUnavailable(response.get("error", "CDS request failed"))
                responses.append(response)
            return responses

    def _run(self, requests):
        try:
            return asyncio.run(self._exchange(requests))
        except SourceUnavailable:
            raise
        except (OSError, TimeoutError, ValueError,
                websockets.exceptions.WebSocketException) as error:
            raise SourceUnavailable("CDS is unreachable: %s" % error) from error

    def fields(self):
        return self._run([{"type": "fields"}])[0].get("data", [])

    def describe(self, names):
        request = {"type": "describe", "fields": list(names)}
        return self._run([request])[0].get("data", {})

    def series(self, name, seconds):
        requests = [
            {"type": "subscribe", "fields": {name: {"seconds": seconds}}},
            {"type": "ready"},
        ]
        response = self._run(requests)[1]
        return response.get("data", {}).get(name, [])
