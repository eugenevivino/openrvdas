"""Operator checks for the ten shipped console modules."""

from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from time import time

import pytest
import yaml

from contrib.deepsignal.console.demo_cache import LocalCachedDataServer
from contrib.deepsignal.test.console.browser_server import serve_console


DIST = Path(__file__).resolve().parents[2] / "console" / "dist"
pytestmark = pytest.mark.lead_run


@pytest.fixture
def pilot(tmp_path):
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="browser test, run by lead outside the sandbox",
    )
    assert (DIST / "index.html").is_file(), "Run npm run build first"
    now = int(time())

    with ExitStack() as stack:
        directory = Path(stack.enter_context(TemporaryDirectory(dir=tmp_path)))
        console = shutil.copytree(DIST, directory / "console")
        config_file = console / "console.yaml"
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        cache = LocalCachedDataServer(port=0, interval=0.1)
        stack.callback(cache.quit)
        port = stack.enter_context(serve_console(console, f"ws://127.0.0.1:{cache.port}"))
        driver = stack.enter_context(playwright.sync_playwright())
        browser = driver.chromium.launch()
        stack.callback(browser.close)
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        stack.callback(page.close)
        page.clock.set_fixed_time(datetime.fromtimestamp(now, tz=timezone.utc))

        def publish(fields, *, offset=0, descriptions=None):
            record = {"timestamp": now + offset, "fields": fields}
            if descriptions:
                record["metadata"] = {"fields": descriptions}
            cache.cache_record(record)

        def open_console(page_id, *, pages=None, tiles=None, **settings):
            config.update(pages=pages if pages is not None else [page_id], **settings)
            config_file.write_text(yaml.safe_dump(config), encoding="utf-8")
            if tiles is not None:
                page_file = console / "pages" / f"{page_id}.yaml"
                page_file.write_text(
                    yaml.safe_dump({"title": "Pilot", "tiles": tiles}), encoding="utf-8",
                )
            page.goto(f"http://127.0.0.1:{port}/console/#{page_id}")
            return page, playwright.expect

        yield now, publish, open_console


def number_tile(label, field, unit):
    return {"type": "number", "label": label, "field": field, "unit": unit, "period": 1}


def reading_tile(page, label):
    return page.locator(".tile").filter(has=page.get_by_role("heading", name=label, exact=True))


def test_auto_pages_builds_bridge_from_catalog_metadata(pilot):
    _, publish, open_console = pilot
    publish({"PilotBearing": 87}, descriptions={
        "PilotBearing": {"description": "True heading from GPS", "units": "degrees"},
    })
    page, expect = open_console("example", pages=[], period={"PilotBearing": 10})
    page.get_by_role("link", name="Bridge (auto)", exact=True).click()
    expect(page.get_by_role("heading", name="Bridge (auto)", level=1, exact=True)).to_be_visible()
    tile = reading_tile(page, "True heading from GPS")
    expect(tile.locator(".value")).to_have_text("87.0 degrees")
    expect(tile.get_by_text("Source PilotBearing", exact=True)).to_be_visible()


def test_bridge_displays_relative_wind_and_switches_dial_orientation(pilot):
    _, publish, open_console = pilot
    wind = {"Avg1mPortTrueWindSpeed": 12.5, "Avg1mPortTrueWindDir": 100, "S330HeadingTrue": 60}
    publish(wind)
    page, expect = open_console("bridge", period=dict.fromkeys(wind, 10))
    expect(page.get_by_text("40° starboard", exact=True)).to_be_visible()
    expect(page.get_by_role("img", name="Wind direction dial, north up")).to_be_visible()
    page.get_by_role("button", name="Ship up", exact=True).click()
    expect(page.get_by_role("img", name="Wind direction dial, ship up")).to_be_visible()


def test_chart_plots_history_and_updates_current_quality(pilot):
    now, publish, open_console = pilot
    publish({"TsgTemp": [(now - 15, 10), (now - 5, 20)], "TsgTemp_QC": 3}, offset=-5)
    page, expect = open_console("science")
    chart = page.get_by_role("region", name="Sea surface temperature")
    expect(chart.locator("canvas")).to_be_visible()
    expect(chart.locator(".chart-range span")).to_have_text(["21.20 degC", "8.80 degC"])
    expect(chart.locator(".chart-current")).to_have_text("20.00 degC")
    expect(chart.get_by_text("SUSPECT")).to_be_visible()
    publish({"TsgTemp": 15, "TsgTemp_QC": 1})
    expect(chart.locator(".chart-current")).to_have_text("15.00 degC")
    expect(chart.get_by_text("PASS")).to_be_visible()


def test_example_weather_preset_displays_the_two_configured_readings(pilot):
    _, publish, open_console = pilot
    publish({"MwxAirTemp": 19.06, "MwxAirRelHumid": 64.5})
    page, expect = open_console("example")
    expect(page.get_by_role("heading", name="Weather", exact=True)).to_be_visible()
    expect(reading_tile(page, "Air temperature").locator(".value")).to_have_text("19.1 °C")
    expect(reading_tile(page, "Relative humidity").locator(".value")).to_have_text("64.5 %")


def test_health_displays_a_logger_failure_then_recovery(pilot):
    _, publish, open_console = pilot
    publish({"status:logger_status": {"mwx1": {"config": "pilot", "status": "FAILED"}}}, offset=-1)
    page, expect = open_console("health")
    logger = page.get_by_test_id("logger-mwx1")
    expect(logger.get_by_text("✕ Failed", exact=True)).to_be_visible()
    expect(page.get_by_test_id("summary-failed")).to_have_text("✕ Failed 1")
    publish({"status:logger_status": {"mwx1": {"config": "pilot", "status": "RUNNING"}}})
    expect(logger.get_by_text("● OK", exact=True)).to_be_visible()
    expect(page.get_by_test_id("summary-failed")).to_have_text("✕ Failed 0")


def test_kiosk_night_pins_the_page_until_operator_holds_exit(pilot):
    now, _, open_console = pilot
    page, expect = open_console("example", pages=["example", "bridge"],
                                modules={"kiosk-night": {"kiosk_page": "example"}})
    exit_button = page.get_by_role("button", name="Exit kiosk (hold for two seconds)")
    tabs = page.locator("nav[aria-label='Pages']")
    expect(exit_button).to_be_visible()
    expect(tabs).to_be_hidden()
    page.keyboard.press("2")
    expect(page.get_by_role("heading", name="Weather", exact=True)).to_be_visible()
    exit_button.click()
    expect(exit_button).to_be_visible()
    exit_button.hover()
    page.mouse.down()
    page.clock.set_fixed_time(datetime.fromtimestamp(now + 3, tz=timezone.utc))
    page.mouse.up()
    expect(tabs).to_be_visible()
    page.keyboard.press("2")
    expect(page.get_by_role("heading", name="Bridge", exact=True)).to_be_visible()


def test_map_displays_no_data_for_unpaired_coordinates_then_shows_a_fix(pilot):
    now, publish, open_console = pilot
    publish({"PilotLat": [(now - 3, 44.5)], "PilotLon": [(now - 2, -124.2)]})
    page, expect = open_console("pilot", tiles=[
        {"type": "map", "lat": "PilotLat", "lon": "PilotLon", "window": "5 m", "wide": True},
        number_tile("Latitude", "PilotLat", "°"),
        number_tile("Longitude", "PilotLon", "°"),
    ])
    latitude = reading_tile(page, "Latitude")
    expect(latitude.locator(".value")).to_have_text("44.5 °")
    expect(latitude.get_by_role("group", name="Freshness")).to_have_text("AGING")
    expect(reading_tile(page, "Longitude").locator(".value")).to_have_text("-124.2 °")
    no_position = page.get_by_text("× Position NO DATA · Coordinates aging 3 sec", exact=True)
    expect(no_position).to_be_visible()
    publish({"PilotLat": 44.6, "PilotLon": -124.3})
    expect(page.get_by_text(re.compile("Position .*NO DATA"))).to_be_hidden()
    page.get_by_role("button", name="Ship track map").click()
    expect(page.get_by_text("44.60000°, -124.30000°", exact=True)).to_be_visible()


def test_number_distinguishes_live_fail_from_missing_quality(pilot):
    _, publish, open_console = pilot
    publish({"PilotDepth": 12.7, "PilotDepth_QC": 4}, offset=-1)
    page, expect = open_console("pilot", tiles=[number_tile("Depth", "PilotDepth", "m")])
    tile = reading_tile(page, "Depth")
    freshness = tile.get_by_role("group", name="Freshness")
    quality = tile.get_by_role("group", name="Data quality")
    expect(freshness).to_have_text("LIVE")
    expect(quality).to_have_text("FAIL")
    expect(tile.locator(".value")).to_have_text("12.7 m")
    publish({"PilotDepth": 12.8, "PilotDepth_QC": 9})
    expect(quality).to_have_text("MISSING")
    expect(tile.locator(".value")).to_have_text("\N{EM DASH}")
    expect(freshness).to_have_text("LIVE")


def test_self_test_reports_live_logger_and_cruise_mode(pilot):
    _, publish, open_console = pilot
    publish({
        "status:logger_status": {"mwx1": {"config": "pilot", "status": "RUNNING"}},
        "status:cruise_mode": {"active_mode": "Underway"},
    })
    page, expect = open_console("self-test")
    checks = page.get_by_role("region", name="Connection checks")
    logger = checks.get_by_text("Logger status", exact=True).locator("..")
    expect(logger.get_by_role("img", name="Pass state")).to_be_visible()
    expect(logger.get_by_text("1 loggers", exact=True)).to_be_visible()
    cruise = checks.get_by_text("Cruise mode", exact=True).locator("..")
    expect(cruise.get_by_role("img", name="Pass state")).to_be_visible()
    expect(cruise.get_by_text("Underway", exact=True)).to_be_visible()


def test_stale_banner_names_the_sensor_and_clears_after_recovery(pilot):
    _, publish, open_console = pilot
    publish({"PilotDepth": 13}, offset=-8, descriptions={
        "PilotDepth": {"description": "Pilot depth", "logger": "knud1"},
    })
    page, expect = open_console("pilot", tiles=[number_tile("Depth", "PilotDepth", "m")],
                                modules={"stale-banner": {"stale_grace_s": 6}})
    banner = page.get_by_role("region", name="Sensor alerts")
    caution = banner.get_by_role("button", name=re.compile("Caution .*Pilot depth stale"))
    expect(caution).to_contain_text("Check the cable and port.")
    caution.click()
    expect(banner.get_by_text("PilotDepth", exact=True)).to_be_visible()
    publish({"PilotDepth": 14})
    expect(reading_tile(page, "Depth").locator(".value")).to_have_text("14.0 m")
    expect(banner).to_be_hidden()
