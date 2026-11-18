"""Run the DeepSignal fixture long enough to detect leaks and backlogs."""

import argparse
import asyncio
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

import websockets

from contrib.deepsignal.test.harness.fixture import Fixture


def _median(values):
    return statistics.median(values) if values else None


def _process_names(fixture):
    """Return stable display names and PIDs for fixture processes."""
    processes = {
        "cache": fixture.processes[0][0].pid,
        "logger-manager": fixture.processes[1][0].pid,
    }
    roots = set(processes.values())
    for pid in fixture.logger_pids():
        if pid in roots:
            continue
        try:
            command = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        except OSError:
            continue
        marker = b"logger_runner.py:"
        if marker not in command:
            continue
        name = command.split(marker, 1)[1].split(b"\0", 1)[0].decode(
            errors="replace")
        processes[f"logger:{name}"] = pid
    return processes


def _rss(pid):
    result = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True,
        text=True, check=False)
    if result.returncode or not result.stdout.strip():
        return None
    return int(result.stdout.strip())


class _ClientStats:
    def __init__(self):
        self.messages = 0
        self.lags = []

    def take(self, seconds):
        result = {
            "messages_per_s": self.messages / seconds,
            "max_receive_lag_s": max(self.lags, default=0.0),
        }
        self.messages = 0
        self.lags.clear()
        return result


async def _console_client(url, stats, deadline, reconnect_s=None):
    """Subscribe like the console and optionally reconnect periodically."""
    while time.monotonic() < deadline:
        reconnect_at = (time.monotonic() + reconnect_s
                        if reconnect_s else deadline)
        try:
            async with websockets.connect(url) as websocket:
                await websocket.send(json.dumps({"type": "fields"}))
                fields_reply = json.loads(await websocket.recv())
                fields = fields_reply.get("data", [])
                await websocket.send(json.dumps({
                    "type": "subscribe",
                    "fields": {field: {"seconds": 300} for field in fields},
                }))
                await websocket.recv()
                first_timestamp = None
                first_received = None
                while (time.monotonic() < deadline and
                       time.monotonic() < reconnect_at):
                    await websocket.send(json.dumps({"type": "ready"}))
                    reply = json.loads(await asyncio.wait_for(
                        websocket.recv(), timeout=2))
                    received = time.time()
                    for values in reply.get("data", {}).values():
                        for timestamp, _value in values:
                            stats.messages += 1
                            if first_timestamp is None:
                                first_timestamp = timestamp
                                first_received = received
                            expected = first_received + timestamp - first_timestamp
                            stats.lags.append(max(0.0, received - expected))
        except (OSError, TimeoutError, websockets.ConnectionClosed):
            await asyncio.sleep(0.1)


async def _collect(fixture, hours, warmup_min, sample_s, clients):
    started = time.monotonic()
    deadline = started + hours * 3600
    warmup_end = started + warmup_min * 60
    processes = _process_names(fixture)
    stats = {f"client-{index + 1}": _ClientStats()
             for index in range(clients)}
    stats["reconnecting-client"] = _ClientStats()
    tasks = [asyncio.create_task(
        _console_client(fixture.ws_url, client_stats, deadline))
             for client_stats in stats.values()]
    tasks[-1].cancel()
    tasks[-1] = asyncio.create_task(_console_client(
        fixture.ws_url, stats["reconnecting-client"], deadline, 600))
    samples = []
    previous = started
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(min(sample_s, max(0, deadline - time.monotonic())))
            now = time.monotonic()
            interval = max(now - previous, 0.001)
            samples.append({
                "elapsed_s": round(now - started, 3),
                "after_warmup": now >= warmup_end,
                "processes": {
                    name: {"pid": pid, "rss_kb": (rss := _rss(pid)),
                           "alive": rss is not None}
                    for name, pid in processes.items()
                },
                "clients": {name: value.take(interval)
                            for name, value in stats.items()},
            })
            previous = now
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return samples


def collect_soak_samples(hours, warmup_min, sample_s, clients):
    """Start the real fixture and return periodic measurements."""
    with Fixture() as fixture:
        return asyncio.run(_collect(
            fixture, hours, warmup_min, sample_s, clients))


def build_report(samples, configuration):
    """Summarize samples and apply the soak acceptance thresholds."""
    measured = [sample for sample in samples
                if sample.get("after_warmup", True)]
    process_names = sorted({name for sample in measured
                            for name in sample["processes"]})
    client_names = sorted({name for sample in measured
                           for name in sample["clients"]})
    summary = {"processes": {}, "clients": {}}
    reasons = []
    for name in process_names:
        details = [sample["processes"].get(name, {}) for sample in measured]
        alive = all(detail.get("alive", False) for detail in details)
        rss_values = [detail.get("rss_kb") for detail in details]
        rss_values = [value for value in rss_values if value is not None]
        first = _median(rss_values[:10])
        last = _median(rss_values[-10:])
        growth = ((last - first) * 100 / first
                  if first not in (None, 0) and last is not None else None)
        summary["processes"][name] = {
            "alive": alive,
            "first_10_median_rss_kb": first,
            "last_10_median_rss_kb": last,
            "rss_growth_percent": growth,
        }
        if not alive:
            reasons.append(f"{name} process died")
        elif growth is not None and growth > 5:
            reasons.append(f"{name} RSS grew {growth:.1f}%")
    for name in client_names:
        client_samples = [sample["clients"].get(name, {})
                          for sample in measured]
        lag = _median([item.get("max_receive_lag_s", 0)
                       for item in client_samples])
        rate = _median([item.get("messages_per_s", 0)
                        for item in client_samples])
        summary["clients"][name] = {
            "median_messages_per_s": rate,
            "median_max_receive_lag_s": lag,
        }
        if lag is not None and lag > 5:
            reasons.append(f"{name} median receive lag was {lag:.1f} s")
    return {
        "configuration": configuration,
        "samples": samples,
        "summary": summary,
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warmup-min", type=float, default=30)
    parser.add_argument("--sample-s", type=float, default=60)
    parser.add_argument("--clients", type=int, default=3)
    args = parser.parse_args(argv)
    configuration = {"hours": args.hours, "warmup_min": args.warmup_min,
                     "sample_s": args.sample_s, "clients": args.clients}
    if (args.hours <= 0 or args.warmup_min < 0 or args.sample_s <= 0 or
            args.clients < 1 or not math.isfinite(args.hours)):
        parser.error("durations must be valid and clients must be positive")
    try:
        samples = collect_soak_samples(**configuration)
        report = build_report(samples, configuration)
        exit_code = 0 if report["verdict"] == "PASS" else 1
    except (OSError, RuntimeError, TimeoutError) as error:
        report = {"configuration": configuration, "samples": [],
                  "summary": {}, "verdict": "COULD_NOT_RUN",
                  "reasons": [str(error)]}
        exit_code = 2
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
