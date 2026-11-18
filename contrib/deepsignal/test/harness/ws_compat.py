"""Compatibility for legacy websocket handlers used by the test fixture."""

import asyncio
import functools
import inspect

import websockets


_WRAPPED = "_deepsignal_legacy_handler_compat"


def _handler_arity(handler):
    """Return the number of positional parameters declared by *handler*."""
    try:
        parameters = inspect.signature(handler).parameters.values()
    except (TypeError, ValueError):
        return None
    return sum(parameter.kind in (parameter.POSITIONAL_ONLY,
                                  parameter.POSITIONAL_OR_KEYWORD)
               for parameter in parameters)


def _adapt_handler(handler):
    if _handler_arity(handler) != 2:
        return handler

    @functools.wraps(handler)
    async def adapted(connection):
        return await handler(connection, connection.request.path)

    return adapted


def _wrap_serve(original):
    @functools.wraps(original)
    def compatible_serve(*args, **kwargs):
        positional = list(args)
        if positional:
            handler = positional.pop(0)
        elif "handler" in kwargs:
            handler = kwargs.pop("handler")
        elif "ws_handler" in kwargs:
            handler = kwargs.pop("ws_handler")
        else:
            return original(*args, **kwargs)

        handler = _adapt_handler(handler)
        requested_loop = kwargs.pop("loop", None)

        async def start_server():
            running_loop = asyncio.get_running_loop()
            if requested_loop is not None and requested_loop is not running_loop:
                raise RuntimeError("websocket server started on the wrong event loop")
            return await original(handler, *positional, **kwargs)

        return start_server()

    setattr(compatible_serve, _WRAPPED, True)
    return compatible_serve


def apply():
    """Enable legacy two-argument handlers with websockets 14 and newer.

    Versions before 14 already support the legacy handler contract, so this
    function deliberately does nothing with those versions.
    """
    major = int(websockets.__version__.split(".", 1)[0])
    if major < 14 or getattr(websockets.serve, _WRAPPED, False):
        return

    from websockets.asyncio import server as asyncio_server

    wrapped = _wrap_serve(asyncio_server.serve)
    asyncio_server.serve = wrapped
    websockets.serve = wrapped
