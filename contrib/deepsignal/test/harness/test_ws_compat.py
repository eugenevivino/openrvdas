"""Tests for the fixture's websockets compatibility shim."""

import asyncio

import pytest
import websockets

from contrib.deepsignal.test.harness import ws_compat


@pytest.fixture
def original_serve():
    modules = [websockets]
    try:
        import websockets.asyncio.server as server
    except ModuleNotFoundError as exc:
        if exc.name not in ("websockets.asyncio", "websockets.asyncio.server"):
            raise
    else:
        modules.append(server)

    originals = {module: module.serve for module in modules}
    yield originals

    # The dependent restoration fixture tears down before this check.
    leaked = [f"{module.__name__}.serve" for module, serve in originals.items()
              if module.serve is not serve]
    assert not leaked, f"serve leaked after test: {', '.join(leaked)}"


@pytest.fixture(autouse=True)
def restore_serve(original_serve):
    with pytest.MonkeyPatch.context() as patch:
        for module, serve in original_serve.items():
            patch.setattr(module, "serve", serve)
        yield


async def _exchange(handler, path="/fixture?source=test", positional=False,
                    **serve_options):
    if positional:
        server = await websockets.serve(handler, "127.0.0.1", 0,
                                        **serve_options)
    else:
        server = await websockets.serve(
            handler=handler, host="127.0.0.1", port=0, **serve_options)
    port = server.sockets[0].getsockname()[1]
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}{path}") as client:
            await client.send("hello")
            return await client.recv()
    finally:
        server.close()
        await server.wait_closed()


def test_one_argument_handler_receives_message():
    ws_compat.apply()

    async def handler(connection):
        message = await connection.recv()
        request = getattr(connection, "request", None)
        path = connection.path if request is None else request.path
        await connection.send(f"{path} {message}")

    assert asyncio.run(_exchange(handler, compression=None)) == (
        "/fixture?source=test hello")


def test_legacy_two_argument_handler_receives_path():
    ws_compat.apply()

    async def handler(connection, path):
        message = await connection.recv()
        await connection.send(f"{path} {message}")

    assert asyncio.run(_exchange(handler, positional=True)) == (
        "/fixture?source=test hello")


@pytest.mark.parametrize("import_path", ["websockets", "websockets.asyncio.server"])
def test_apply_is_idempotent(import_path):
    module = pytest.importorskip(import_path)
    ws_compat.apply()
    first = module.serve
    ws_compat.apply()
    assert module.serve is first


def test_apply_is_no_op_before_websockets_14(monkeypatch):
    """websockets before 14 natively accepts two-argument handlers."""
    sentinel = object()
    monkeypatch.setattr(websockets, "__version__", "13.1")
    monkeypatch.setattr(websockets, "serve", sentinel)

    ws_compat.apply()

    assert websockets.serve is sentinel
