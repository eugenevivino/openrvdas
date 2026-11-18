"""Exercise the shipped console against a real local cache."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import copytree
import sys
from threading import Thread

import pytest
import yaml

sys.path.append(str(Path(__file__).resolve().parents[4]))
from contrib.deepsignal.console.demo_cache import LocalCachedDataServer  # noqa: E402


DIST = Path(__file__).resolve().parents[2] / 'console' / 'dist'


def test_console_live(tmp_path):
    playwright = pytest.importorskip(
        'playwright.sync_api',
        reason='Python Playwright is not installed; Chromium console test skipped',
    )
    assert (DIST / 'index.html').is_file(), 'Run npm run build before the live test'

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        cache = LocalCachedDataServer(port=0, interval=0.1)
        try:
            console = copytree(DIST, tmp_path / 'console')
            config_path = console / 'console.yaml'
            config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
            config['websocket'] = f'ws://127.0.0.1:{cache.port}'
            config_path.write_text(yaml.safe_dump(config), encoding='utf-8')

            handler = partial(SimpleHTTPRequestHandler, directory=tmp_path)
            with ThreadingHTTPServer(('127.0.0.1', 0), handler) as httpd:
                serving = Thread(target=httpd.serve_forever, daemon=True)
                serving.start()
                try:
                    page = browser.new_page()
                    try:
                        check_readings(playwright, page, httpd.server_port, cache)
                    finally:
                        page.close()
                finally:
                    httpd.shutdown()
                    serving.join()
        finally:
            cache.quit()


def check_readings(playwright, page, http_port, cache):
    # Backfill a reading that was already in the cache before navigation.
    cache.cache_record({'fields': {'MwxAirTemp': 19.06, 'MwxAirRelHumid': 63.9}})
    page.clock.install()
    page.goto(f'http://127.0.0.1:{http_port}/console/')
    playwright.expect(page.locator('.value')).to_have_text(['19.1 °C', '63.9 %'])
    playwright.expect(page.locator('.live')).to_contain_text('Live')

    cache.cache_record({'fields': {'MwxAirTemp': 21.2, 'MwxAirRelHumid': 65.5}})
    playwright.expect(page.locator('.value')).to_have_text(['21.2 °C', '65.5 %'])

    # Leave the server connected and stop publishing. Advance the display clock
    # past the default stale limit without a real-time 30-second wait.
    page.clock.fast_forward(31_000)
    playwright.expect(page.locator('.tile-header .status')).to_have_text(['Stale', 'Stale'])
    playwright.expect(page.locator('.live')).to_contain_text('Waiting for current data')
