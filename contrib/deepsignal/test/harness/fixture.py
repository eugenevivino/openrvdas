"""Launch a disposable, stock OpenRVDAS replay stack for DeepSignal tests."""

import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

import websockets
import yaml


ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = Path(__file__).with_name("cruise.yaml")
DEFAULT_STATE_DIR = Path(tempfile.gettempdir()) / "deepsignal-console-fixture"
REPLAYS = {
    "MWX1": ROOT / "test/NBP1406/mwx1/raw/NBP1406_mwx1-2014-08-01",
    "S330": ROOT / "test/NBP1406/s330/raw/NBP1406_s330-2014-08-01",
    "KNUD": ROOT / "test/NBP1406/knud/raw/NBP1406_knud-2014-08-01",
}
LOGGER_FIELDS = {
    "mwx1": {"MwxAirTemp", "MwxPortRelWindDir", "MwxPortRelWindSpeed"},
    "s330": {"S330HeadingTrue", "S330CourseTrue", "S330SpeedKt"},
    "knud1": {"KnudDepthLF"},
    "true_winds": {"PortTrueWindDir", "PortTrueWindSpeed", "PortApparentWindDir"},
}
READY_FIELDS = {"status:logger_status"}.union(*LOGGER_FIELDS.values())


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _process_tree(roots):
    """Return fixture roots and descendants from one process snapshot."""
    snapshot = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid=,command="],
        capture_output=True, text=True, check=False)
    if snapshot.returncode:
        raise OSError(f"could not list fixture processes: {snapshot.stderr.strip()}")
    children = {}
    commands = {}
    for line in snapshot.stdout.splitlines():
        columns = line.split(maxsplit=2)
        if len(columns) != 3:
            continue
        pid, parent, command = columns
        pid = int(pid)
        commands[pid] = command
        children.setdefault(int(parent), []).append(pid)

    pending = list(roots)
    found = {}
    while pending:
        pid = pending.pop()
        if pid in commands and pid not in found:
            found[pid] = commands[pid]
            pending.extend(children.get(pid, ()))
    return found


async def _request(url, request):
    async with websockets.connect(url) as websocket:
        await websocket.send(json.dumps(request))
        return json.loads(await websocket.recv())


class Fixture:
    """Context manager owning a CachedDataServer and LoggerManager stack."""

    def __init__(self, port=0, speed=1.0, seconds=None, temp_dir=None):
        if speed <= 0:
            raise ValueError("speed must be greater than zero")
        self.port = port or _free_port()
        self.speed = speed
        self.seconds = seconds
        self._provided_dir = temp_dir is not None
        self.temp_dir = Path(temp_dir) if temp_dir else Path(
            tempfile.mkdtemp(prefix="deepsignal-fixture-"))
        self.processes = []
        self.ready = False

    @property
    def ws_url(self):
        return f"ws://127.0.0.1:{self.port}"

    def _scaled_replay(self, name, source, started_at):
        destination = self.temp_dir / f"{name.lower()}.log"
        first = None
        output = []
        for line in source.read_text(errors="surrogateescape").splitlines(True):
            stamp, separator, record = line.partition(" ")
            try:
                parsed = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                output.append(line)
                continue
            first = first or parsed
            scaled = started_at + (parsed - first) / self.speed
            rendered = scaled.isoformat(timespec="microseconds").replace("+00:00", "Z")
            output.append(f"{name.lower()} {rendered}{separator}{record}")
        destination.write_text("".join(output), errors="surrogateescape")
        return destination

    def _write_config(self):
        config = TEMPLATE.read_text()
        started_at = datetime.datetime.now(datetime.timezone.utc)
        for name, source in REPLAYS.items():
            config = config.replace(f"__{name}_FILE__",
                                    str(self._scaled_replay(name, source, started_at)))
        config = config.replace("__DEVICE_DEFINITIONS__", str(
            ROOT / "test/NBP1406/devices/nbp_devices.yaml"))
        config = config.replace("__DATA_SERVER__", f"127.0.0.1:{self.port}")
        path = self.temp_dir / "cruise.yaml"
        path.write_text(config)
        return path

    def _spawn(self, command, log_name):
        log = (self.temp_dir / log_name).open("w")
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        self.processes.append((process, log))
        return process

    def start(self):
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        cache = self._spawn([
            sys.executable, "-m", "contrib.deepsignal.test.harness.fixture",
            "_cache", "--port", str(self.port)], "cache.log")
        self._wait_for_cache(cache)
        self._wait_for_ready(self._start_manager())
        return self

    def _start_manager(self):
        config = self._write_config()
        return self._spawn([
            sys.executable, "server/logger_manager.py", "--database", "memory",
            "--config", str(config), "--mode", "replay", "--no-console",
            "--interval", "0.1", "--data_server_websocket",
            f"127.0.0.1:{self.port}", "--stderr_file_pattern",
            str(self.temp_dir / "{logger}.stderr")], "manager.log")

    def _wait_for_cache(self, process):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("CachedDataServer exited; see cache.log")
            try:
                asyncio.run(_request(self.ws_url, {"type": "fields"}))
                return
            except (OSError, TimeoutError):
                time.sleep(0.05)
        raise TimeoutError("CachedDataServer did not listen within 10 seconds")

    def _wait_for_ready(self, manager):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if manager.poll() is not None:
                raise RuntimeError("LoggerManager exited; see manager.log")
            try:
                fields = asyncio.run(_request(self.ws_url, {"type": "fields"}))["data"]
                if READY_FIELDS.issubset(fields):
                    self.ready = True
                    print(f"READY {self.ws_url} loggers={len(LOGGER_FIELDS)} "
                          f"fields={len(fields)}", flush=True)
                    return
            except (OSError, KeyError, TimeoutError):
                pass
            time.sleep(0.1)
        raise TimeoutError("fixture did not publish records within 30 seconds")

    def _processes_by_pid(self):
        roots = [process.pid for process, _ in self.processes
                 if process.poll() is None]
        return _process_tree(roots)

    def logger_pids(self):
        return sorted(self._processes_by_pid())

    def logger_processes(self):
        configs = yaml.safe_load(TEMPLATE.read_text())["modes"]["replay"]
        names = {config: logger for logger, config in configs.items()}
        loggers = {}
        for pid, command in self._processes_by_pid().items():
            title = command.split(maxsplit=1)[0]
            prefix, _, config = title.rpartition("/logger_runner.py:")
            if prefix and config in names:
                loggers[names[config]] = pid
        return loggers

    def kill_logger(self, name, sig=signal.SIGTERM):
        pid = self.logger_processes().get(name)
        if pid is None:
            raise KeyError(f"logger not running: {name}")
        os.kill(pid, sig)
        return pid

    def stop(self):
        for process, _ in reversed(self.processes):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 5
        for process, log in reversed(self.processes):
            try:
                process.wait(max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            log.close()
        self.processes.clear()
        self.ready = False
        if not self._provided_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.stop()
            raise

    def __exit__(self, *_exc):
        self.stop()


def _down(state_dir):
    state_file = Path(state_dir) / "pids.json"
    if not state_file.exists():
        return
    for pid in json.loads(state_file.read_text()):
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    state_file.unlink(missing_ok=True)


def _run_cache(port):
    """Run the stock cache without its CLI's unrelated optional UDP imports."""
    from contrib.deepsignal.test.harness import ws_compat

    ws_compat.apply()
    from server.cached_data_server import CachedDataServer

    serve = websockets.serve

    def serve_loopback(**options):
        # The stock cache supplies host="" and exposes no bind option.
        options["host"] = "127.0.0.1"
        return serve(**options)

    websockets.serve = serve_loopback
    server = CachedDataServer(port=port, interval=0.05)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    up = subparsers.add_parser("up")
    up.add_argument("--port", type=int, default=0)
    up.add_argument("--speed", type=float, default=1.0)
    up.add_argument("--seconds", type=float)
    up.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    down = subparsers.add_parser("down")
    down.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    cache = subparsers.add_parser("_cache", help=argparse.SUPPRESS)
    cache.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "_cache":
        _run_cache(args.port)
        return 0
    if args.command == "down":
        _down(args.state_dir)
        return 0

    args.state_dir.mkdir(parents=True, exist_ok=True)
    with Fixture(args.port, args.speed, args.seconds) as fixture:
        state_file = args.state_dir / "pids.json"
        state_file.write_text(json.dumps([process.pid for process, _ in fixture.processes]))
        try:
            if args.seconds is None:
                while True:
                    time.sleep(1)
            else:
                time.sleep(args.seconds)
        except KeyboardInterrupt:
            pass
        finally:
            state_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
