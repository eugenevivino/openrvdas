"""Production-bundle browser coverage for the read-only Stream Health route."""

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import time

import pytest

from contrib.deepsignal.console.demo_cache import LocalCachedDataServer
from contrib.deepsignal.test.console.browser_server import serve_console


DIST = Path(__file__).resolve().parents[2] / "console" / "dist"
INPUT_SOURCE = "isolated stock LocalCachedDataServer, synthetic science/weather ds_chain scalars"


class FixtureTraffic:
    """Observe the app protocol and keep a bounded summary of fixture traffic."""

    def __init__(self, expected_fields):
        self.expected_fields = expected_fields
        self.events = deque(maxlen=32)
        self.socket = None
        self.fallback = False
        self.acknowledged = False
        self.ready_sent = False
        self.first_data_received = False
        self.streaming = False

    def attach(self, socket):
        if not socket.url.endswith("/cds-ws"):
            return
        self.socket = socket
        socket.on("framesent", self.sent)
        socket.on("framereceived", self.received)

    def sent(self, payload):
        frame = json.loads(payload)
        kind = frame.get("type")
        if kind == "subscribe":
            fields = frame["fields"]
            # The fixture leaves ambient adapter fields empty, so core retries their
            # backfill at seconds=-1 while retaining the chain's history requests.
            self.fallback = self.expected_fields.keys() <= fields.keys() and any(
                name not in self.expected_fields and spec["seconds"] == -1
                for name, spec in fields.items()
            )
            self.acknowledged = False
            self.ready_sent = False
            self.first_data_received = False
            self.streaming = False
            self.events.append(["send", kind, {
                name: fields[name]["seconds"] for name in self.expected_fields if name in fields
            }, self.fallback])
        elif kind in {"fields", "describe"}:
            self.events.append(["send", kind])
        elif kind == "ready" and not self.ready_sent:
            self.ready_sent = True
            self.events.append(["send", kind])

    def received(self, payload):
        frame = json.loads(payload)
        kind, status = frame.get("type"), frame.get("status")
        summary = ["receive", kind, status]
        if kind == "subscribe":
            self.acknowledged = status == 200
        elif kind == "fields" and status == 200:
            summary.append(sorted(set(frame["data"]) & self.expected_fields.keys()))
        elif kind == "data" and status == 200:
            self.streaming = self.fallback and self.acknowledged and self.ready_sent
            data = {
                name: [value for _, value in frame["data"][name]
                       if value in self.expected_fields[name]]
                for name in self.expected_fields if name in frame["data"]
            }
            if self.first_data_received and not data:
                return
            self.first_data_received = True
            summary.append(data)
        self.events.append(summary)

    def wait_for_streaming(self):
        assert self.socket is not None, "Console did not open the fixture WebSocket"
        if not self.streaming:
            self.socket.wait_for_event("framereceived", predicate=lambda _: self.streaming,
                                       timeout=5000)


@pytest.mark.lead_run
def test_stream_health_navigation_updates_and_evidence(record_property, tmp_path):
    from playwright import sync_api as playwright

    assert (DIST / "index.html").is_file(), "Run npm run build before the browser test"
    tested_commit = os.environ.get("STREAM_HEALTH_TESTED_COMMIT") or os.environ.get("GITHUB_SHA")
    if tested_commit:
        record_property("tested_commit", tested_commit)
    record_property("input_source", INPUT_SOURCE)

    now = time() - 1
    old = {
        "ds_chain:science:root": "parser",
        "ds_chain:science:time": "OK",
    }
    stale = {
        "ds_chain:science:store": "OK",
        "ds_chain:weather:root": "endpoint",
        "ds_chain:science:sensor": "FAILED",
    }
    live = {
        "ds_chain:weather:store": "OFF",
        "ds_chain:weather:endpoint": "UNKNOWN",
        "ds_chain:weather:sensor": "DEGRADED",
    }
    science_update = {
        "ds_chain:science:sensor": "OK",
        "ds_chain:science:store": "DEGRADED",
        "ds_chain:science:root": "store",
    }
    weather_update = {"ds_chain:weather:root": None, "ds_chain:weather:sensor": "OK"}
    traffic = FixtureTraffic({
        name: (report, science_update.get(name), weather_update.get(name))
        for name, report in (old | stale | live).items()
    })
    cache = LocalCachedDataServer(port=0, interval=0.1)
    try:
        for timestamp, fields in [(now - 400, old), (now - 45, stale), (now, live)]:
            cache.cache_record({"timestamp": timestamp, "fields": fields})
        with (serve_console(DIST, f"ws://127.0.0.1:{cache.port}") as port,
              playwright.sync_playwright() as driver):
            browser = driver.chromium.launch()
            try:
                page = browser.new_page()
                page.on("websocket", traffic.attach)
                # Fix browser wall time so freshness assertions are independent of startup time.
                page.clock.set_fixed_time(datetime.fromtimestamp(now + 1, timezone.utc))
                check_stream_health(playwright, page, port, traffic, cache, now,
                                    science_update, weather_update, tmp_path)
            finally:
                browser.close()
    finally:
        cache.quit()


def check_stream_health(playwright, page, port, traffic, cache, now,
                        science_update, weather_update, tmp_path):
    rows = page.get_by_test_id("stream-health-row")
    try:
        page.goto(f"http://127.0.0.1:{port}/console/")
        page.get_by_role("link", name="Stream Health").click()
        playwright.expect(page.get_by_role("heading", name="Stream Health")).to_be_visible()
        playwright.expect(rows).to_have_count(2)
        science = rows.filter(has=page.get_by_role("heading", name="science", exact=True))
        weather = rows.filter(has=page.get_by_role("heading", name="weather", exact=True))

        # Seeing initial values does not prove the queued backfill subscribe reached
        # CDS. Wait for data after its acknowledgement before publishing recovery.
        traffic.wait_for_streaming()
        playwright.expect(science.locator(".stream-root strong")).to_have_text("Unknown")
        playwright.expect(science.locator(".stream-root small")).to_have_text("Missing")
        expect_stage(playwright, science, "sensor", "UNKNOWN", "Stale · Last reported: FAILED")
        expect_stage(playwright, science, "store", "UNKNOWN", "Stale · Last reported: OK")
        expect_stage(playwright, science, "time", "UNKNOWN", "Missing")
        expect_stage(playwright, science, "endpoint", "UNKNOWN", "Missing")
        playwright.expect(weather.locator(".stream-root strong")).to_have_text("Unknown")
        playwright.expect(weather.locator(".stream-root small")).to_have_text(
            "Stale · Last reported: endpoint"
        )
        expect_stage(playwright, weather, "endpoint", "UNKNOWN", "Current")
        expect_stage(playwright, weather, "store", "OFF", "Current")
        assert weather.locator(".stream-stage-label").all_text_contents() == [
            "sensor", "endpoint", "raw_traffic", "parser", "time", "calibration",
            "derived", "store",
        ]

        traffic.events.append(["publish", "science recovery"])
        cache.cache_record({"timestamp": now + 0.25, "fields": science_update})
        playwright.expect(science.locator(".stream-root strong")).to_have_text("store")
        playwright.expect(science.locator(".stream-root small")).to_have_text("Current")
        expect_stage(playwright, science, "sensor", "OK", "Current")
        expect_stage(playwright, science, "store", "DEGRADED", "Current")

        traffic.events.append(["publish", "weather recovery"])
        cache.cache_record({"timestamp": now + 0.5, "fields": weather_update})
        playwright.expect(weather.locator(".stream-root strong")).to_have_text("None reported")
        playwright.expect(weather.locator(".stream-root small")).to_have_text("Current")
        expect_stage(playwright, weather, "sensor", "OK", "Current")
        playwright.expect(science.locator(".stream-root strong")).to_have_text("store")
    except (AssertionError, playwright.Error):
        diagnostics = tmp_path / "stream-health-failure.json"
        diagnostics.write_text(json.dumps({
            "source": INPUT_SOURCE,
            "rows": rows.all_text_contents(),
            "websocket": list(traffic.events),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Stream Health fixture DOM and CDS summary: {diagnostics}")
        raise


def expect_stage(playwright, row, name, state, evidence):
    stage = row.locator(f'[data-stage="{name}"]')
    playwright.expect(stage.locator(".stream-state")).to_have_text(state)
    playwright.expect(stage.locator("small")).to_have_text(evidence)
