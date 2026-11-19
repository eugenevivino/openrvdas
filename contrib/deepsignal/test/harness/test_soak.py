"""Tests for the DeepSignal long-running soak harness."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from contrib.deepsignal.test.harness import soak
from contrib.deepsignal.test.harness.fixture import Fixture


LOGGER_NAMES = {"mwx1", "s330", "knud1", "true_winds"}


def _samples(first_rss=1000, last_rss=1040, alive=True, lag=0.25, intervals=20):
    samples = []
    for index in range(intervals):
        rss = first_rss if index < 10 else last_rss
        samples.append({
            "elapsed_s": index,
            "processes": {
                "cache": {"rss_kb": rss, "alive": alive},
                **{name: {"rss_kb": 500, "alive": True} for name in
                   {"logger-manager", *(f"logger:{name}" for name in LOGGER_NAMES)}},
            },
            "clients": {
                name: {"messages_per_s": 2.0, "max_receive_lag_s": client_lag}
                for name, client_lag in (
                    ("client-1", lag), ("client-2", 0.25), ("client-3", 0.25),
                    ("reconnecting-client", 0.25))
            },
        })
    return samples


def test_smoke_run_writes_pass_report_with_expected_shape(tmp_path,
                                                          monkeypatch):
    samples = _samples()
    monkeypatch.setattr(soak, "collect_soak_samples",
                        lambda **_kwargs: samples)
    report_path = tmp_path / "soak.json"

    result = soak.main(["--hours", "0.05", "--warmup-min", "0.5",
                        "--sample-s", "5", "--clients", "3",
                        "--report", str(report_path)])

    report = json.loads(report_path.read_text())
    assert result == 0
    assert report["verdict"] == "PASS"
    assert set(report) == {"configuration", "samples", "summary", "verdict",
                           "reasons"}
    assert report["samples"] == samples
    assert report["summary"]["processes"]["cache"]["rss_growth_percent"] == 4


def test_four_percent_rss_growth_passes():
    report = soak.build_report(_samples(last_rss=1040), {})

    assert report["verdict"] == "PASS"
    assert report["reasons"] == []


def test_six_percent_rss_growth_fails():
    report = soak.build_report(_samples(last_rss=1060), {})

    assert report["verdict"] == "FAIL"
    assert "cache RSS grew 6.0%" in report["reasons"][0]


def test_dead_process_fails():
    report = soak.build_report(_samples(alive=False), {})

    assert report["verdict"] == "FAIL"
    assert report["reasons"] == ["cache process died"]


def test_high_client_lag_fails():
    report = soak.build_report(_samples(lag=5.1), {})

    assert report["verdict"] == "FAIL"
    assert "median receive lag was 5.1 s" in report["reasons"][0]


@pytest.mark.parametrize("lag", [0.25, 60.0])
def test_one_active_interval_cannot_hide_29_silent_intervals(lag):
    samples = _samples(lag=lag, intervals=30)
    for sample in samples[1:]:
        sample["clients"]["client-1"] = {
            "messages_per_s": 0.0, "max_receive_lag_s": 0.0,
        }

    report = soak.build_report(samples, {"clients": 3})

    assert report["verdict"] == "FAIL"
    assert report["summary"]["clients"]["client-1"]["median_max_receive_lag_s"] == lag
    assert "client-1 received no new records in most intervals" in report["reasons"]
    if lag > 5:
        assert "client-1 median receive lag was 60.0 s" in report["reasons"]


def test_client_stats_distinguishes_silence_from_zero_lag():
    stats = soak._ClientStats()
    stats.messages = 1
    stats.lags.append(0.0)

    assert stats.take(1) == {"messages_per_s": 1.0, "max_receive_lag_s": 0.0}
    assert stats.take(1) == {"messages_per_s": 0.0, "max_receive_lag_s": None}


@pytest.mark.parametrize("warmup_only", [False, True])
def test_report_rejects_empty_measurements(warmup_only):
    samples = _samples() if warmup_only else []
    for sample in samples:
        sample["after_warmup"] = False

    report = soak.build_report(samples, {"clients": 3})

    assert report["verdict"] == "FAIL"
    assert any("no measurements" in reason for reason in report["reasons"])


@pytest.mark.parametrize("missing_client", [False, True])
def test_report_rejects_a_client_with_zero_records(missing_client):
    samples = _samples()
    for sample in samples:
        if missing_client:
            del sample["clients"]["client-2"]
        else:
            sample["clients"]["client-2"]["messages_per_s"] = 0

    report = soak.build_report(samples, {"clients": 3})

    assert report["verdict"] == "FAIL"
    assert "client-2 received no records" in report["reasons"]


@pytest.mark.parametrize("missing_logger", [False, True])
def test_report_rejects_an_unmeasured_logger(missing_logger):
    samples = _samples()
    for sample in samples:
        if missing_logger:
            del sample["processes"]["logger:true_winds"]
        else:
            sample["processes"]["logger:true_winds"]["rss_kb"] = None

    report = soak.build_report(samples, {})

    assert report["verdict"] == "FAIL"
    assert "logger:true_winds RSS was not measured" in report["reasons"]


def test_soak_discovers_fixture_logger_processes_from_ps(tmp_path, monkeypatch):
    fixture = Fixture(port=43210, temp_dir=tmp_path)
    fixture.processes = [(SimpleNamespace(pid=pid, poll=lambda: None), None)
                         for pid in (8, 10)]
    ps_output = """\
   23    20 openrvdas/server/logger_runner.py:true_winds-on
    8     1 python -m contrib.deepsignal.test.harness.fixture _cache
   10     1 python server/logger_manager.py
   20    10 python multiprocessing.spawn
   21    10 openrvdas/server/logger_runner.py:mwx1-replay
   22    10 openrvdas/server/logger_runner.py:s330-replay
   24    10 openrvdas/server/logger_runner.py:knud1-replay
   40     1 openrvdas/server/logger_runner.py:mwx1-replay
"""
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=ps_output, returncode=0)

    monkeypatch.setattr(soak.subprocess, "run", run)

    assert soak._process_names(fixture) == {
        "cache": 8, "logger-manager": 10, "logger:mwx1": 21, "logger:s330": 22,
        "logger:true_winds": 23, "logger:knud1": 24,
    }
    assert calls == [["ps", "-A", "-o", "pid=,ppid=,command="]]


def test_client_measures_first_record_lag_across_reconnect(monkeypatch):
    field = "MwxAirTemp"
    now = 100.0
    batches = iter([[(94.0, 1)], [(94.0, 1), (101.0, 2)]])

    class Connection:
        async def __aenter__(self):
            self.batch = next(batches)
            return self

        async def __aexit__(self, *_exc):
            pass

        async def send(self, message):
            self.request = json.loads(message)["type"]

        async def recv(self):
            nonlocal now
            if self.request == "fields":
                return json.dumps({"data": [field]})
            if self.request == "ready":
                received = json.dumps({"data": {field: self.batch}})
                now += 10
                return received
            return "{}"

    monkeypatch.setattr(soak.websockets, "connect", lambda _url: Connection())
    monkeypatch.setattr(soak, "time",
                        SimpleNamespace(monotonic=lambda: now - 100, time=lambda: now - 10))
    stats = soak._ClientStats()
    asyncio.run(soak._console_client("ws://fixture", stats, deadline=20, reconnect_s=10))

    assert stats.lags == [6.0, 9.0]
