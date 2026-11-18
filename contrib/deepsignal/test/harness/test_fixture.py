"""Integration tests for the DeepSignal stock-stack fixture."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time

import pytest
import websockets

from contrib.deepsignal.test.harness.fixture import Fixture


async def _latest_values(url, wanted, timeout=30):
    """Subscribe to *wanted* and return the first value seen for each field."""
    values = {}
    async with websockets.connect(url) as websocket:
        await websocket.send(json.dumps({
            "type": "subscribe",
            "fields": {field: {"seconds": -1} for field in wanted},
        }))
        deadline = time.monotonic() + timeout
        while wanted - values.keys() and time.monotonic() < deadline:
            await websocket.send(json.dumps({"type": "ready"}))
            reply = json.loads(await asyncio.wait_for(websocket.recv(), 2))
            data = reply.get("data", {})
            for field, samples in data.items():
                if samples:
                    values[field] = samples[-1][1]
    return values


@pytest.mark.slow
def test_up_reaches_ready_within_30_seconds(capsys):
    with Fixture(seconds=2) as fixture:
        assert fixture.ws_url.startswith("ws://127.0.0.1:")
        assert fixture.ready
    assert "READY ws://127.0.0.1:" in capsys.readouterr().out


@pytest.mark.slow
def test_cache_has_temperature_and_running_status():
    with Fixture() as fixture:
        values = asyncio.run(_latest_values(
            fixture.ws_url, {"MwxAirTemp", "status:logger_status"}))
        assert "MwxAirTemp" in values
        statuses = values["status:logger_status"]
        assert statuses
        assert all(status["status"] == "RUNNING"
                   for status in statuses.values())


@pytest.mark.slow
def test_down_leaves_no_child_processes(tmp_path):
    fixture = Fixture(temp_dir=tmp_path)
    fixture.start()
    pids = fixture.logger_pids()
    assert pids
    fixture.stop()
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, signal.SIGCONT)

    result = subprocess.run(
        [sys.executable, "-m", "contrib.deepsignal.test.harness.fixture",
         "down", "--state-dir", str(tmp_path)],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
