"""Lead-run visual checks for the Bridge preset."""

import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest


DIST = Path(__file__).resolve().parents[2] / "console" / "dist"


@pytest.mark.lead_run
def test_bridge_night_red_and_no_vertical_scroll():
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="browser test, run by lead outside the sandbox",
    )
    assert (DIST / "index.html").is_file(), "Run npm run build before the browser test"
    handler = partial(SimpleHTTPRequestHandler, directory=DIST)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with playwright.sync_playwright() as driver:
                browser = driver.chromium.launch()
                page = browser.new_page(viewport={"width": 1366, "height": 768})
                page.add_init_script("localStorage.setItem('ds.mode', 'night')")
                page.add_init_script("localStorage.setItem('ds.palette', 'red')")
                page.goto(f"http://127.0.0.1:{server.server_port}/#bridge")
                page.wait_for_load_state("networkidle")
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
                browser.close()
        finally:
            server.shutdown()
            thread.join()
