"""Exercise the shipped console against a real local cache."""

from base64 import b64encode
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import copytree
import sys
from threading import Thread
from time import time

import pytest
import yaml

sys.path.append(str(Path(__file__).resolve().parents[4]))
from contrib.deepsignal.console.demo_cache import LocalCachedDataServer  # noqa: E402


CONSOLE = Path(__file__).resolve().parents[2] / 'console'
DIST = CONSOLE / 'dist'


@pytest.mark.lead_run
def test_console_live(tmp_path):
    playwright = pytest.importorskip(
        'playwright.sync_api',
        reason='browser test, run by lead outside the sandbox',
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
            weather_path = console / 'pages/example.yaml'
            preset = CONSOLE / 'src/modules/example/example.yaml'
            weather = yaml.safe_load(preset.read_text(encoding='utf-8'))
            for tile in weather['tiles']:
                tile['period'] = 5
            weather_path.write_text(yaml.safe_dump(weather), encoding='utf-8')

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
    # Humidity has two readings outside the history window, so CDS initially
    # returns no humidity. The console should recover the latest on its own.
    now = time()
    cache.cache_record({'fields': {
        'MwxAirTemp': [(now, 19.06)],
        'MwxAirRelHumid': [(now - 321, 60.2), (now - 320, 63.9)],
    }})
    page.emulate_media(color_scheme='light')
    page.goto(f'http://127.0.0.1:{http_port}/console/')
    values = page.locator('.value')
    freshness = page.locator('.freshness .status')
    quality = page.locator('.quality .status')
    playwright.expect(values).to_have_text(['19.1 °C', '—'])
    playwright.expect(page.locator('.last-reading')).to_contain_text('Last: 63.9 % at ')
    playwright.expect(page.locator('.live')).to_contain_text('Live')

    updated = time()
    cache.cache_record({'timestamp': updated, 'fields': {
        'MwxAirTemp': 21.2, 'MwxAirRelHumid': 65.5, 'MwxAirTemp_QC': 3,
    }})
    playwright.expect(values).to_have_text(['21.2 °C', '65.5 %'])
    playwright.expect(quality).to_have_text(['SUSPECT', 'NOT EVALUATED'])
    playwright.expect(freshness).to_have_text(['LIVE', 'LIVE'])

    # Advance only the display's source-age clock. Chromium's native frame
    # scheduling stays active for the Night reload check.
    set_display_time = '(seconds) => { Date.now = () => seconds * 1000 }'
    page.evaluate(set_display_time, updated + 12)
    playwright.expect(freshness).to_have_text(['AGING', 'AGING'])
    page.evaluate(set_display_time, updated + 28)
    playwright.expect(freshness).to_have_text(['STALE', 'STALE'])
    playwright.expect(values).to_have_text(['21.2 °C', '65.5 %'])
    playwright.expect(quality.first).to_have_text('SUSPECT')
    playwright.expect(page.locator('.live')).to_contain_text('Waiting for current data')
    playwright.expect(page.get_by_text('Research system monitoring')).to_be_visible()
    check_night(playwright, page)


def check_night(playwright, page):
    page.get_by_role('button', name='Night', exact=True).click()
    red = page.get_by_role('button', name='Red', exact=True)
    playwright.expect(red).to_have_attribute('aria-pressed', 'true')
    screenshot = b64encode(page.screenshot()).decode('ascii')
    offending_pixel = page.evaluate('''async (png) => {
        const image = await createImageBitmap(new Blob(
            [Uint8Array.from(atob(png), (byte) => byte.charCodeAt(0))], {type: 'image/png'}));
        const canvas = new OffscreenCanvas(image.width, image.height);
        const context = canvas.getContext('2d');
        context.drawImage(image, 0, 0);
        const {data} = context.getImageData(0, 0, image.width, image.height);
        for (let i = 0; i < data.length; i += 4) {
            const r = data[i], g = data[i + 1], b = data[i + 2];
            if (100 * g > 15 * r || 100 * b > 15 * r) {
                const pixel = i / 4;
                return {x: pixel % image.width, y: Math.floor(pixel / image.width), r, g, b};
            }
        }
        return null;
    }''', screenshot)
    assert offending_pixel is None, f'Night red pixel exceeds channel limits: {offending_pixel}'

    page.add_init_script('''
        window.firstConsoleFrame = new Promise((resolve) => {
            requestAnimationFrame(() => {
                const root = document.documentElement;
                resolve({mode: root.dataset.mode, palette: root.dataset.nightPalette,
                    background: getComputedStyle(root).backgroundColor});
            });
        });
    ''')
    page.reload()
    assert page.evaluate('window.firstConsoleFrame') == {
        'mode': 'night', 'palette': 'red', 'background': 'rgb(0, 0, 0)',
    }

    # The same boot palette should survive a reload with a config error.
    page.route('**/console.yaml', lambda route: route.fulfill(status=503))
    page.reload()
    assert page.evaluate('window.firstConsoleFrame') == {
        'mode': 'night', 'palette': 'red', 'background': 'rgb(0, 0, 0)',
    }
    playwright.expect(page.get_by_role('alert')).to_contain_text('console.yaml')
    muted = page.evaluate("""() => getComputedStyle(document.documentElement)
        .getPropertyValue('--muted').match(/\\d+/g).map(Number)""")
    assert muted[0] >= 150
    assert 100 * max(muted[1:]) <= 15 * muted[0]
