"""Real Chromium journey against an owned disposable loopback fixture server."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-python', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='workspace-browser-') as directory:
        scratch = Path(directory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
        with (scratch / 'server.log').open('wb') as log:
            process = subprocess.Popen([args.server_python, '-B', '-m',
                'contrib.deepsignal.workspace.http_server', '--state', str(scratch / 'state.sqlite3'),
                '--port', str(port)], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(50):
                    if process.poll() is not None:
                        raise RuntimeError('Owned fixture server exited before readiness')
                    try:
                        with urlopen(base + '/api/workspace/session', timeout=0.2) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError('Owned fixture server readiness timeout')
                with sync_playwright() as driver:
                    browser = driver.chromium.launch()
                    try:
                        page = browser.new_page(viewport={'width': 1366, 'height': 768})
                        page.goto(base + '/console/#workspace-explorer')
                        expect(page.get_by_role('button', name='Load selected data')).to_be_visible()
                        page.get_by_role('button', name='Refresh health evidence').click()
                        expect(page.get_by_role('table').get_by_text('STALE · age 7 s')).to_be_visible()
                        page.get_by_role('button', name='Load selected data').click()
                        page.get_by_role('button', name='Analyze frozen dataset').click()
                        expect(page.get_by_role('heading', name='Deterministic analysis')).to_be_visible()
                        nav = page.get_by_role('navigation', name='Investigation workflow')
                        nav.get_by_role('link', name='Configuration Workbench', exact=True).click()
                        page.get_by_role('button', name='Load configuration snapshot').click()
                        page.get_by_label('Supported parser pattern').select_option('TEMP={temperature:g}')
                        page.get_by_role('button', name='Create parser draft').click()
                        page.get_by_role('button', name='Validate draft').click()
                        page.get_by_role('button', name='Replay baseline and draft').click()
                        expect(page.get_by_label('Replay input')).to_contain_text('[0, 6)')
                        expect(page.get_by_text('PASS for declared fixture checks', exact=True)).to_be_visible()
                        nav.get_by_role('link', name='Investigations', exact=True).click()
                        page.get_by_role('button', name='Save investigation').click()
                        page.get_by_role('button', name='Prepare watch handoff').click()
                        expect(page.get_by_label('Watch handoff report')).to_contain_text('SIMULATED')
                        expect(page.get_by_label('Watch handoff report')).to_contain_text('"mean": 15')
                        nav.get_by_role('link', name='Connections and System', exact=True).click()
                        page.get_by_role('button', name='Inspect capabilities').click()
                        expect(page.get_by_label('System capabilities')).to_contain_text('live_control')
                        page.set_viewport_size({'width': 390, 'height': 844})
                        expect(page.get_by_role('button', name='Inspect capabilities')).to_be_visible()
                        print(json.dumps({'status': 'PASS', 'browser': 'Chromium',
                            'scope': 'real loopback UI/service workflow, synthetic data only',
                            'workflow': ['health', 'query', 'analysis', 'draft', 'validation', 'replay', 'handoff', 'connections']}))
                    finally:
                        browser.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    main()
