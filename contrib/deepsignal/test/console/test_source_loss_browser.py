"""Browser coverage for source-loss visibility and recovery."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
from shutil import copytree
from threading import Thread

import pytest
import yaml

from contrib.deepsignal.test.harness.fixture import Fixture
from contrib.deepsignal.test.harness.test_source_loss import restart_manager


DIST = Path(__file__).resolve().parents[2] / "console" / "dist"


@pytest.mark.lead_run
def test_console_shows_stale_then_live_after_logger_recovery(tmp_path):
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="browser test, run by lead outside the sandbox",
    )
    assert (DIST / "index.html").is_file(), "Run npm run build first"

    with Fixture() as fixture:
        console = copytree(DIST, tmp_path / "console")
        config_path = console / "console.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["websocket"] = fixture.ws_url
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

        handler = partial(SimpleHTTPRequestHandler, directory=tmp_path)
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as httpd:
            serving = Thread(target=httpd.serve_forever, daemon=True)
            serving.start()
            try:
                with playwright.sync_playwright() as driver:
                    browser = driver.chromium.launch()
                    page = browser.new_page()
                    try:
                        page.goto(
                            f"http://127.0.0.1:{httpd.server_port}/console/"
                        )
                        tile = page.locator(".tile").filter(
                            has_text="MwxAirTemp"
                        )
                        freshness = tile.get_by_role("group", name="Freshness")
                        playwright.expect(freshness).to_have_text("LIVE", timeout=10_000)
                        fixture.kill_logger("mwx1", signal.SIGKILL)
                        playwright.expect(freshness).to_have_text("STALE", timeout=10_000)
                        restart_manager(fixture)
                        playwright.expect(freshness).to_have_text("LIVE", timeout=60_000)
                    finally:
                        page.close()
                        browser.close()
            finally:
                httpd.shutdown()
                serving.join()
