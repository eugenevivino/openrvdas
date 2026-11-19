"""Lead-run visual checks for the Bridge preset."""

import base64
import shutil
from pathlib import Path
from time import time

import pytest

from contrib.deepsignal.console.demo_cache import LocalCachedDataServer
from contrib.deepsignal.test.console.browser_server import serve_console


DIST = Path(__file__).resolve().parents[2] / "console" / "dist"


@pytest.mark.lead_run
def test_bridge_night_red_and_no_vertical_scroll(tmp_path):
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="browser test, run by lead outside the sandbox",
    )
    assert (DIST / "index.html").is_file(), "Run npm run build before the browser test"
    # The shipped console.yaml lists only the example page;
    # serve a copy that lists the Bridge preset.
    console = shutil.copytree(DIST, tmp_path / "console")
    config = console / "console.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("pages: [example]", "pages: [bridge]"),
                      encoding="utf-8")
    assert "pages: [bridge]" in config.read_text(encoding="utf-8")
    cache = LocalCachedDataServer(port=0, interval=0.1)
    try:
        with (serve_console(console, f"ws://127.0.0.1:{cache.port}") as port,
              playwright.sync_playwright() as driver):
            browser = driver.chromium.launch()
            try:
                cache.cache_record({"timestamp": time(), "fields": {"MwxAirTemp": 19.06}})
                check_bridge(playwright, browser, port)
            finally:
                browser.close()
    finally:
        cache.quit()


def check_bridge(playwright, browser, port):
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    page.add_init_script("localStorage.setItem('ds.mode', 'night')")
    page.add_init_script("localStorage.setItem('ds.palette', 'red')")
    page.goto(f"http://127.0.0.1:{port}/console/#bridge")
    playwright.expect(page.get_by_role("heading", name="Bridge", exact=True)).to_be_visible()
    temperature = page.locator(".tile").filter(has_text="MwxAirTemp").locator(".value")
    playwright.expect(temperature).to_have_text("19.1 °C")
    page.evaluate("document.fonts.ready.then(() => true)")
    last_tile = page.locator(".tile-frame").last
    playwright.expect(last_tile.get_by_role("heading", name="Longitude")).to_be_visible()
    playwright.expect(last_tile).to_be_in_viewport(ratio=1)
    assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
    encoded = base64.b64encode(page.screenshot()).decode("ascii")
    bad_pixels = page.evaluate(
        """async data => {
          const image = new Image(); image.src = `data:image/png;base64,${data}`;
          await image.decode();
          const canvas = document.createElement('canvas');
          canvas.width = image.width; canvas.height = image.height;
          const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
          const pixels = context.getImageData(0, 0, image.width, image.height).data;
          let bad = 0;
          for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i + 1] > 0.15 * pixels[i]
                || pixels[i + 2] > 0.15 * pixels[i]) bad++;
          }
          return bad;
        }""",
        encoded,
    )
    assert bad_pixels == 0
