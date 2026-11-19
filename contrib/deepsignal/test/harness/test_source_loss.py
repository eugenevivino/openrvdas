"""Exercise source-loss visibility and operator recovery in the stock stack."""

import asyncio
import json
import os
import signal
from statistics import median
import sys
import time

import pytest
import websockets

from contrib.deepsignal.test.harness.fixture import Fixture

FIELD = "MwxAirTemp"


def is_stale(source_time, now, intervals):
    """Apply the console freshness rule using the latest 20 intervals."""
    recent = intervals[-20:]
    if not recent:
        return False
    return now - source_time > 5 * median(recent)


async def _subscribe(url, fields):
    websocket = await websockets.connect(url)
    await websocket.send(json.dumps({
        "type": "subscribe",
        "fields": {field: {"seconds": -1} for field in fields},
    }))
    reply = json.loads(await asyncio.wait_for(websocket.recv(), 2))
    assert reply["status"] == 200, reply
    return websocket


async def _read(websocket, timeout=2):
    await websocket.send(json.dumps({"type": "ready"}))
    reply = await asyncio.wait_for(websocket.recv(), timeout)
    return json.loads(reply).get("data", {})


async def _next_timestamp(websocket, field, after=None, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for timestamp, _value in (await _read(websocket)).get(field, []):
            if after is None or timestamp > after:
                return timestamp, time.monotonic()
        await asyncio.sleep(0.05)
    raise TimeoutError(f"no new {field} record within {timeout} seconds")


def restart_manager(fixture):
    """Restart the stock manager on the existing cache for a recovery check."""
    manager, _log = fixture.processes[-1]
    manager.send_signal(signal.SIGINT)
    manager.wait(timeout=5)
    fixture._start_manager()


async def _verify_logger_loss(websocket, killed_at, last_stamp, intervals):
    stale = False
    reported_loss = False
    while not (stale and reported_loss):
        data = await _read(websocket)
        observed = time.monotonic()
        for stamp, _ in data.get(FIELD, []):
            if stamp > last_stamp:
                assert observed <= killed_at + 2, "mwx1 published after the in-flight allowance"
                last_stamp = stamp
        for _stamp, status in data.get("status:logger_status", []):
            if status.get("mwx1", {}).get("status") == "STARTING":
                assert observed <= killed_at + 15, "manager reported logger loss late"
                reported_loss = True
        if not stale:
            assert observed <= killed_at + 10, "field did not become STALE"
            stale = is_stale(last_stamp, time.time(), intervals)
        if not reported_loss:
            assert observed <= killed_at + 15, "manager did not report mwx1 as STARTING"
    return last_stamp


async def _exercise_logger_loss(fixture):
    websocket = await _subscribe(fixture.ws_url, {FIELD, "status:logger_status"})
    try:
        timestamps = []
        received = []
        for _ in range(21):
            stamp, observed = await _next_timestamp(
                websocket, FIELD, timestamps[-1] if timestamps else None)
            timestamps.append(stamp)
            received.append(observed)
        arrival_intervals = [right - left for left, right in zip(received, received[1:])]
        assert 0.5 < median(arrival_intervals) < 1.5
        intervals = [right - left for left, right in zip(timestamps, timestamps[1:])]

        old_pid = fixture.kill_logger("mwx1", signal.SIGKILL)
        killed_at = time.monotonic()
        last_stamp = await _verify_logger_loss(
            websocket, killed_at, timestamps[-1], intervals)
        assert "mwx1" not in fixture.logger_processes()
        restart_manager(fixture)
        resumed, received_at = await _next_timestamp(
            websocket, FIELD, last_stamp,
            timeout=max(0.1, killed_at + 60 - time.monotonic()))
        assert resumed > last_stamp
        assert received_at <= killed_at + 60
        assert fixture.logger_processes()["mwx1"] != old_pid
    finally:
        await websocket.close()


@pytest.mark.slow
def test_logger_loss_becomes_stale_and_recovers():
    with Fixture() as fixture:
        asyncio.run(_exercise_logger_loss(fixture))


async def _wait_for_disconnect(websocket, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            await _read(websocket, timeout=0.5)
        except TimeoutError:
            continue
        except (websockets.ConnectionClosed, OSError):
            return
    raise AssertionError("client did not observe the cache connection drop")


async def _reconnect_for_data(url, timeout=30):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            websocket = await _subscribe(url, {FIELD})
            try:
                return await _next_timestamp(websocket, FIELD, timeout=2)
            finally:
                await websocket.close()
        except (OSError, TimeoutError, websockets.WebSocketException) as exc:
            error = exc
            await asyncio.sleep(0.1)
    raise AssertionError("reconnecting client received no data") from error


async def _exercise_cache_loss(fixture):
    websocket = await _subscribe(fixture.ws_url, {FIELD})
    await _next_timestamp(websocket, FIELD)
    cache, cache_log = fixture.processes[0]
    os.killpg(cache.pid, signal.SIGTERM)
    cache.wait(timeout=5)
    await _wait_for_disconnect(websocket)
    await websocket.close()

    replacement = fixture._spawn([
        sys.executable, "-m", "contrib.deepsignal.test.harness.fixture",
        "_cache", "--port", str(fixture.port),
    ], "cache-restarted.log")
    deadline = time.monotonic() + 10
    while True:
        if replacement.poll() is not None:
            raise AssertionError("restarted cache exited")
        try:
            probe = await websockets.connect(fixture.ws_url)
            await probe.close()
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise AssertionError("restarted cache did not listen")
            await asyncio.sleep(0.05)
    assert await _reconnect_for_data(fixture.ws_url)
    cache_log.close()


@pytest.mark.slow
def test_cache_loss_disconnects_and_reconnecting_client_recovers():
    with Fixture() as fixture:
        asyncio.run(_exercise_cache_loss(fixture))
