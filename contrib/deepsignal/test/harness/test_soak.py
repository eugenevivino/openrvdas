"""Tests for the DeepSignal long-running soak harness."""

import json

from contrib.deepsignal.test.harness import soak


def _samples(first_rss=1000, last_rss=1040, alive=True, lag=0.25):
    samples = []
    for index in range(20):
        rss = first_rss if index < 10 else last_rss
        samples.append({
            "elapsed_s": index,
            "processes": {"cache": {"rss_kb": rss, "alive": alive}},
            "clients": {
                "client-1": {"messages_per_s": 2.0,
                             "max_receive_lag_s": lag}
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
