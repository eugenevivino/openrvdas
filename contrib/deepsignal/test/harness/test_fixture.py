"""Integration tests for the DeepSignal stock-stack fixture."""

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import websockets
import yaml

from contrib.deepsignal.test.harness import fixture as harness, ws_compat
from contrib.deepsignal.test.harness.fixture import Fixture
from logger.transforms.parse_transform import ParseTransform


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


def _component_specs(config, class_name):
    """Yield all component specs named *class_name* from nested config."""
    if isinstance(config, dict):
        if config.get("class") == class_name:
            yield config
        for value in config.values():
            yield from _component_specs(value, class_name)
    elif isinstance(config, list):
        for value in config:
            yield from _component_specs(value, class_name)


def test_generated_config_points_all_cache_writers_at_fixture_port(tmp_path):
    fixture = Fixture(port=43210, temp_dir=tmp_path)
    config = yaml.safe_load(fixture._write_config().read_text())

    writers = list(_component_specs(config, "CachedDataWriter"))
    assert len(writers) == 4
    assert {writer["kwargs"]["data_server"] for writer in writers} == {
        "127.0.0.1:43210"
    }


def test_scaled_replay_record_parses_into_fields(tmp_path):
    fixture = Fixture(port=43210, temp_dir=tmp_path)
    config = yaml.safe_load(fixture._write_config().read_text())
    replay = config["configs"]["mwx1-replay"]["readers"][0]["kwargs"][
        "filebase"
    ]
    record = Path(replay).read_text(errors="surrogateescape").splitlines()[0]
    parsed = ParseTransform(
        definition_path=config["configs"]["mwx1-replay"]["transforms"][0][
            "kwargs"
        ]["definition_path"]
    ).transform(record)

    assert parsed["data_id"] == "mwx1"
    assert parsed["fields"]["MwxAirTemp"] == 19.07


def test_replay_timestamps_match_wall_clock_and_keep_scaled_intervals(tmp_path):
    fixture = Fixture(port=43210, speed=2, temp_dir=tmp_path)
    before = time.time()
    fixture._write_config()
    replay = (tmp_path / "mwx1.log").read_text().splitlines()
    first, second = (datetime.fromisoformat(line.split()[1]).timestamp()
                     for line in replay[:2])

    assert before <= first <= time.time()
    assert second - first == pytest.approx(0.487 / 2, abs=1e-6)


def test_cache_worker_binds_only_loopback(monkeypatch):
    from server import cached_data_server

    stock_server = cached_data_server.CachedDataServer

    def serve(*, ws_handler, host, port, loop):
        assert host == "127.0.0.1"
        assert port == 43210

    def cache_server(*, port, interval):
        loop = SimpleNamespace(is_running=lambda: False,
                               run_until_complete=lambda _server: None,
                               run_forever=lambda: None)
        server = SimpleNamespace(port=port, event_loop=loop,
                                 _serve_websocket_data=None, quit=lambda: None)
        stock_server._run_websocket_server(server)
        return server

    # Keep the stock listener method in the test without opening a socket.
    monkeypatch.setattr(cached_data_server, "CachedDataServer", cache_server)
    monkeypatch.setattr(websockets, "serve", serve)
    monkeypatch.setattr(ws_compat, "apply", lambda: None)

    def stop(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(harness, "time", SimpleNamespace(sleep=stop))
    harness._run_cache(43210)


def test_ready_waits_for_each_logger_to_publish(tmp_path, monkeypatch, capsys):
    fixture = Fixture(port=43210, temp_dir=tmp_path)
    original_fields = {"MwxAirTemp", "MwxPortRelWindDir", "MwxPortRelWindSpeed",
                       "status:logger_status"}
    complete = {"S330HeadingTrue", "S330CourseTrue", "S330SpeedKt", "KnudDepthLF",
                "PortTrueWindDir", "PortTrueWindSpeed", "PortApparentWindDir"}
    fields = iter([original_fields, original_fields | complete])

    async def request(_url, _message):
        assert not fixture.ready
        assert not capsys.readouterr().out
        return {"data": list(next(fields))}

    monkeypatch.setattr(harness, "_request", request)
    fixture._wait_for_ready(SimpleNamespace(poll=lambda: None))

    assert fixture.ready
    assert "loggers=4 fields=11" in capsys.readouterr().out


def test_true_winds_subscribes_to_course(tmp_path):
    fixture = Fixture(port=43210, temp_dir=tmp_path)
    config = yaml.safe_load(fixture._write_config().read_text())
    winds = config["configs"]["true_winds-on"]
    fields = winds["readers"][0]["kwargs"]["subscription"]["fields"]
    transform = winds["writers"][0]["kwargs"]["transforms"][0]["kwargs"]

    assert transform["course_field"] in fields


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
