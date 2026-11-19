"""Exercise the shipped console against a real local cache."""

from base64 import b64encode
import json
from pathlib import Path
import re
from time import time
from urllib.parse import urlsplit

import pytest
import yaml

from contrib.deepsignal.console.demo_cache import LocalCachedDataServer
from contrib.deepsignal.test.console.browser_server import serve_console


CONSOLE = Path(__file__).resolve().parents[2] / 'console'
DIST = CONSOLE / 'dist'


def serve_dist_asset(route, configuration):
    name = urlsplit(route.request.url).path.removeprefix('/console/')
    if name == 'console.yaml':
        route.fulfill(body=configuration, content_type='application/yaml')
    else:
        path = DIST / (name or 'index.html')
        if path.is_file():
            route.fulfill(path=path)
        else:
            route.fulfill(status=404)


@pytest.mark.lead_run
@pytest.mark.parametrize(('origin', 'socket_scheme'), [
    pytest.param('http://demo-console.test:8080', 'ws', id='http'),
    pytest.param('https://pilot-console.test', 'wss', id='https'),
])
@pytest.mark.parametrize('source', ['readme', 'sample'])
def test_d_fix1_documented_relay(origin, socket_scheme, source):
    from playwright.sync_api import expect, sync_playwright

    sample = (DIST / 'console.yaml').read_text(encoding='utf-8')
    if source == 'readme':
        readme = (CONSOLE / 'README.md').read_text(encoding='utf-8')
        demo = readme.split('### Try it without a ship\n', 1)[1].split('\n### ', 1)[0]
        # Apply any inline YAML setting the workstation instructions give the operator.
        overrides = re.findall(r'`(websocket:[^`]+)`', demo)
        configuration = '\n'.join([sample, *overrides])
    else:
        assert sample == (CONSOLE / 'public' / 'console.yaml').read_text(encoding='utf-8')
        # Enable any commented websocket example in the shipped configuration.
        configuration = re.sub(r'^# (websocket: .+)$', r'\1', sample, flags=re.MULTILINE)

    host = urlsplit(origin).netloc
    expected = f'{socket_scheme}://{host}/cds-ws'
    socket_urls = []

    def capture_socket(socket):
        socket_urls.append(socket.url)

        def reply(message):
            request = json.loads(message)['type']
            catalog = {'fields': [], 'describe': {}}
            if request in catalog:
                socket.send(json.dumps({'type': request, 'status': 200, 'data': catalog[request]}))

        socket.on_message(reply)

    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page()
            # Fulfill both origins entirely in Playwright, including any unexpected socket.
            page.route('**/*', lambda route: route.abort())
            page.route(f'{origin}/console/**', lambda route: serve_dist_asset(route, configuration))
            page.route_web_socket('**/*', capture_socket)
            page.goto(f'{origin}/console/')
            connected = page.get_by_text('Waiting for current data', exact=True)
            alert = page.get_by_role('alert')
            expect(connected.or_(alert).first).to_be_visible(timeout=5_000)
            assert socket_urls[:1] == [expected], alert.all_text_contents()
        finally:
            browser.close()

    if source == 'sample':
        comments = '\n'.join(line for line in sample.splitlines() if line.startswith('#'))
        documented = re.findall(r'wss?://\S+', comments)
        assert expected in {url.replace('<browser-host>', host) for url in documented}


@pytest.mark.lead_run
def test_console_live():
    playwright = pytest.importorskip(
        'playwright.sync_api',
        reason='browser test, run by lead outside the sandbox',
    )
    assert (DIST / 'index.html').is_file(), 'Run npm run build before the live test'

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        cache = LocalCachedDataServer(port=0, interval=0.1)
        try:
            config = yaml.safe_load((DIST / 'console.yaml').read_text(encoding='utf-8'))
            config['period'] = {'MwxAirTemp': 5, 'MwxAirRelHumid': 5}
            with serve_console(DIST, f'ws://127.0.0.1:{cache.port}') as http_port:
                page = browser.new_page()
                try:
                    page.route('**/console.yaml', lambda route: route.fulfill(
                        body=yaml.safe_dump(config), content_type='application/yaml'))
                    check_readings(playwright, page, http_port, cache)
                finally:
                    page.close()
        finally:
            cache.quit()
            browser.close()


def check_readings(playwright, page, http_port, cache):
    # Humidity has two readings outside the history window, so CDS initially
    # returns no humidity. The console should recover the latest on its own.
    now = time()
    cache.cache_record({'fields': {
        'MwxAirTemp': [(now, 19.06)],
        'MwxAirRelHumid': [(now - 321, 60.2), (now - 320, 63.9)],
    }})
    page.emulate_media(color_scheme='light')
    with page.expect_websocket(lambda ws: ws.url == f'ws://127.0.0.1:{http_port}/cds-ws'):
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
    offending_pixel = first_pixel_outside_night_red(page, page.screenshot())
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


def first_pixel_outside_night_red(page, screenshot):
    return page.evaluate('''async (png) => {
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
    }''', b64encode(screenshot).decode('ascii'))


@pytest.mark.lead_run
def test_night_red_constrains_browser_painted_color_and_preserves_neutral():
    from playwright.sync_api import sync_playwright, expect

    ship = 'R/V Pilot \N{LARGE GREEN CIRCLE}'
    configuration = yaml.safe_load((DIST / 'console.yaml').read_text(encoding='utf-8'))
    configuration.update(ship=ship, websocket='ws://console.test/cds-ws')
    config_text = yaml.safe_dump(configuration)

    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(color_scheme='light')
            page.route('http://console.test/console/**', lambda route: serve_dist_asset(
                route, config_text))
            page.route_web_socket('ws://console.test/cds-ws', lambda _socket: None)
            page.goto('http://console.test/console/')
            ship_label = page.get_by_text(ship, exact=True)
            expect(ship_label).to_be_visible()
            page.get_by_role('button', name='Night', exact=True).click()
            neutral = page.get_by_role('button', name='Neutral', exact=True)
            neutral.click()
            expect(neutral).to_have_attribute('aria-pressed', 'true')
            assert first_pixel_outside_night_red(page, ship_label.screenshot()) is not None

            red = page.get_by_role('button', name='Red', exact=True)
            red.click()
            expect(red).to_have_attribute('aria-pressed', 'true')
            offending_pixel = first_pixel_outside_night_red(page, page.screenshot())
            assert offending_pixel is None, offending_pixel
        finally:
            browser.close()
