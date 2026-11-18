"""Serve the console and forward CDS traffic for loopback browser tests."""

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from http import HTTPStatus
from mimetypes import guess_type
from urllib.parse import unquote, urlsplit

from websockets.exceptions import WebSocketException
from websockets.legacy.client import connect
from websockets.legacy.server import serve


async def _serve_static(directory, request, _headers):
    if request == "/cds-ws":
        return None
    path = unquote(urlsplit(request).path)
    if path.startswith("/console/") and "\0" not in path:
        relative = path.removeprefix("/console/") or "index.html"
        asset = (directory / relative).resolve()
        if asset.is_relative_to(directory) and asset.is_file():
            content_type = guess_type(asset.name)[0] or "application/octet-stream"
            return HTTPStatus.OK, [("Content-Type", content_type)], asset.read_bytes()
    return HTTPStatus.NOT_FOUND, [("Content-Type", "text/plain")], b"Not found\n"


async def _forward(source, destination):
    async for message in source:
        await destination.send(message)


async def _relay(cache_url, browser):
    try:
        async with connect(cache_url, open_timeout=5, close_timeout=1) as cache:
            tasks = [asyncio.create_task(_forward(browser, cache)),
                     asyncio.create_task(_forward(cache, browser))]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, TimeoutError, WebSocketException):
        await browser.close(code=1011, reason="Fixture cache connection closed")


@contextmanager
def serve_console(directory, cache_url):
    """Yield a port serving /console/ and /cds-ws on the same loopback origin."""
    directory = directory.resolve()
    started = Future()

    async def run():
        async with serve(partial(_relay, cache_url), "127.0.0.1", 0,
                         process_request=partial(_serve_static, directory),
                         close_timeout=1) as server:
            stop = asyncio.get_running_loop().create_future()
            started.set_result((server.sockets[0].getsockname()[1], stop))
            await stop

    def run_in_thread():
        try:
            asyncio.run(run())
        except Exception as error:
            if not started.done():
                started.set_exception(error)
            raise

    with ThreadPoolExecutor(max_workers=1) as executor:
        server_task = executor.submit(run_in_thread)
        port, stop = started.result()
        try:
            yield port
        finally:
            stop.get_loop().call_soon_threadsafe(stop.set_result, None)
            server_task.result()
