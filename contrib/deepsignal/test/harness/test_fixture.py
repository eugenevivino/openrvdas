"""Integration tests for the DeepSignal stock-stack fixture."""

import asyncio
from contextlib import ExitStack
from datetime import datetime
import json
import os
from pathlib import Path
import select
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
from logger.listener.listen import ListenerFromLoggerConfig
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


def test_prepared_replay_record_parses_into_fields(tmp_path):
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


@pytest.fixture
def replay_clock(monkeypatch):
    clock = SimpleNamespace(elapsed=0.0)

    def advance(seconds):
        clock.elapsed += seconds

    def wall():
        return 1_700_000_000 + clock.elapsed

    monkeypatch.setattr(time, "time", wall)
    monkeypatch.setattr(time, "monotonic", lambda: 100 + clock.elapsed)
    monkeypatch.setattr(time, "sleep", advance)
    return SimpleNamespace(advance=advance, wall=wall)


def _replay_reader(config, name):
    readers = config["configs"][f"{name}-replay"]["readers"]
    return ListenerFromLoggerConfig({"readers": readers}).reader


@pytest.mark.parametrize("startup_delay", [
    pytest.param(0.25, id="normal-start"),
    pytest.param(3.25, id="delayed-start"),
])
@pytest.mark.parametrize("speed", [1, 2])
def test_replay_clock_anchors_at_first_emission(tmp_path, replay_clock, startup_delay, speed):
    fixture = Fixture(port=43210, speed=speed, temp_dir=tmp_path)
    config = yaml.safe_load(fixture._write_config().read_text())
    replay_clock.advance(startup_delay / 2)
    reader = _replay_reader(config, "mwx1")
    replay_clock.advance(startup_delay / 2)

    first = _record_time(reader.read())
    first_age = replay_clock.wall() - first
    assert _record_time(reader.read()) - first == pytest.approx(0.487 / speed, abs=1e-6)
    assert _record_time(reader.read()) - first == pytest.approx(0.544 / speed, abs=1e-6)
    second = _record_time(reader.read())
    assert second - first == pytest.approx(0.995 / speed, abs=1e-6)
    assert [first_age, replay_clock.wall() - second] == pytest.approx([0, 0], abs=1e-6)

    # Model a blocked downstream consumer before the next read and again after it.
    replay_clock.advance(1.5)
    assert _record_time(reader.read()) - first == pytest.approx(1.488 / speed, abs=1e-6)
    assert _record_time(reader.read()) - first == pytest.approx(1.544 / speed, abs=1e-6)
    record = reader.read()
    assert _record_time(record) - first == pytest.approx(2 / speed, abs=1e-6)
    replay_clock.advance(0.25)
    parse = ParseTransform(**config["configs"]["mwx1-replay"]["transforms"][0]["kwargs"])
    parsed = parse.transform(record)
    assert parsed["fields"]["MwxAirTemp"] == 19.11
    assert replay_clock.wall() - parsed["timestamp"] == pytest.approx(
        1.75 + (0.995 - 2) / speed, abs=1e-6)


def _record_time(record):
    return datetime.fromisoformat(record.split()[1]).timestamp()


def test_replay_clock_aligns_staggered_sources_and_resets_for_new_manager(tmp_path, replay_clock):
    fixture = Fixture(port=43210, speed=2, temp_dir=tmp_path)
    config = yaml.safe_load(fixture._write_config().read_text())
    first = _record_time(_replay_reader(config, "s330").read())

    replay_clock.advance(0.4)
    mwx = _record_time(_replay_reader(config, "mwx1").read())
    assert mwx - first == pytest.approx(-0.011 / 2, abs=1e-6)
    assert replay_clock.wall() - mwx == pytest.approx(0.4 + 0.011 / 2, abs=1e-6)
    knud = _record_time(_replay_reader(config, "knud1").read())
    assert knud - first == pytest.approx(1.549 / 2, abs=1e-6)
    assert replay_clock.wall() - knud == pytest.approx(0, abs=1e-6)

    config = yaml.safe_load(fixture._write_config().read_text())
    replay_clock.advance(3.25)
    first = _record_time(_replay_reader(config, "mwx1").read())
    assert first - replay_clock.wall() == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("stock_host", [
    pytest.param(None, id="stock-default"),
    pytest.param("::1", id="ipv6-loopback"),
])
def test_cache_worker_binds_only_loopback(monkeypatch, stock_host):
    from server import cached_data_server

    stock_server = cached_data_server.CachedDataServer
    bind_addresses = []

    def serve(*, ws_handler, host, port, loop):
        bind_addresses.append((host, port))

    def cache_server(*, port, interval):
        loop = SimpleNamespace(is_running=lambda: False,
                               run_until_complete=lambda _server: None,
                               run_forever=lambda: None)
        host = cached_data_server.DEFAULT_HOST if stock_host is None else stock_host
        server = SimpleNamespace(host=host, port=port, event_loop=loop,
                                 _serve_websocket_data=None, quit=lambda: None)
        stock_server._run_websocket_server(server)
        return server

    # Keep the stock listener method in the test without opening a socket.
    monkeypatch.setattr(cached_data_server, "CachedDataServer", cache_server)
    monkeypatch.setattr(websockets, "serve", serve)
    if stock_host is None:
        monkeypatch.setattr(cached_data_server.websockets, "serve", serve)
    else:
        # The stock fallback imports the same top-level module as the fixture.
        monkeypatch.setattr(cached_data_server, "websockets", websockets)
    monkeypatch.setattr(ws_compat, "apply", lambda: None)

    def stop(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(harness, "time", SimpleNamespace(sleep=stop))
    harness._run_cache(43210)

    assert bind_addresses == [("127.0.0.1", 43210)]


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


@pytest.mark.parametrize("start_method", [
    pytest.param("fork", id="linux-fork-default"),
    pytest.param("spawn", id="spawn-default"),
])
def test_replay_worker_starts_with_either_platform_default(tmp_path, monkeypatch, start_method):
    # Model the platform default before the manager selects its own context.
    # A forked worker cannot continue if an inherited native lock is held.
    (tmp_path / "sitecustomize.py").write_text(
        "import multiprocessing.context as context\n"
        "import os\n"
        "context._default_context._default_context = "
        f"context._concrete_contexts[{start_method!r}]\n"
        "os.register_at_fork(after_in_child=lambda: os._exit(70))\n",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path), prepend=os.pathsep)
    fixture = Fixture(port=43210, temp_dir=tmp_path)
    config_file = fixture._write_config()
    config = yaml.safe_load(config_file.read_text())
    output = tmp_path / "replayed.fifo"
    replay = config["configs"]["mwx1-replay"]
    del replay["transforms"]
    replay["writers"] = [{"class": "TextFileWriter", "kwargs": {"filename": str(output)}}]
    config["configs"] = {"mwx1-replay": replay}
    config["loggers"] = {"mwx1": config["loggers"]["mwx1"]}
    config["modes"]["replay"] = {"mwx1": "mwx1-replay"}
    config_file.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(fixture, "_write_config", lambda: config_file)

    with ExitStack() as cleanup:
        os.mkfifo(output, 0o600)
        cleanup.callback(output.unlink)
        reader = os.open(output, os.O_RDONLY | os.O_NONBLOCK)
        cleanup.callback(os.close, reader)
        # Keep the FIFO from reporting EOF before the worker opens its writer.
        writer = os.open(output, os.O_WRONLY | os.O_NONBLOCK)
        cleanup.callback(os.close, writer)
        cleanup.callback(fixture.stop)
        manager = fixture._start_manager()

        deadline = time.monotonic() + 5
        pending = b""
        while (remaining := deadline - time.monotonic()) > 0:
            readable, _, _ = select.select([reader], [], [], remaining)
            assert manager.poll() is None, f"Stock manager exited. See {tmp_path / 'manager.log'}"
            if not readable:
                break
            *records, pending = (pending + os.read(reader, 4096)).split(b"\n")
            if any(b"MET," in record for record in records):
                return
        pytest.fail("Stock logger worker did not replay a complete MET record within five seconds")


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
