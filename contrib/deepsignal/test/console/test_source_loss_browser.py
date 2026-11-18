"""Browser coverage for source-loss visibility and recovery."""

from pathlib import Path
import signal

import pytest

from contrib.deepsignal.test.console.browser_server import serve_console
from contrib.deepsignal.test.harness.fixture import Fixture
from contrib.deepsignal.test.harness.test_source_loss import restart_manager


DIST = Path(__file__).resolve().parents[2] / "console" / "dist"


@pytest.mark.lead_run
def test_console_shows_stale_then_live_after_logger_recovery():
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="browser test, run by lead outside the sandbox",
    )
    assert (DIST / "index.html").is_file(), "Run npm run build first"

    with (Fixture() as fixture,
          serve_console(DIST, fixture.ws_url) as port,
          playwright.sync_playwright() as driver):
        browser = driver.chromium.launch()
        try:
            page = browser.new_page()
            url = f"ws://127.0.0.1:{port}/cds-ws"
            with page.expect_websocket(lambda ws: ws.url == url):
                page.goto(f"http://127.0.0.1:{port}/console/")
            tile = page.locator(".tile").filter(has_text="MwxAirTemp")
            freshness = tile.get_by_role("group", name="Freshness")
            playwright.expect(freshness).to_have_text("LIVE", timeout=10_000)
            fixture.kill_logger("mwx1", signal.SIGKILL)
            playwright.expect(freshness).to_have_text("STALE", timeout=10_000)
            restart_manager(fixture)
            playwright.expect(freshness).to_have_text("LIVE", timeout=60_000)
        finally:
            browser.close()
