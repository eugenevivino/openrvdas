"""The static checker only verifies exact bytes of the installer-owned site."""

import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


CHECKER = Path(__file__).resolve().parents[2] / 'security/check_cds.py'
INSTALL = CHECKER.parents[1] / 'console/install/install.sh'
RENDER = ['/bin/sh', str(INSTALL), '--render', '--origin', 'https://ship.example',
          '--ssl-certificate', '/etc/nginx/ship.pem',
          '--ssl-certificate-key', '/etc/nginx/ship.key']


@pytest.fixture
def python_without_websockets(tmp_path):
    python = tmp_path / 'python3'
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -S "$@"\n')
    python.chmod(0o755)
    return python


def test_checker_matches_only_rendered_site_and_rejects_source_option(
        tmp_path, python_without_websockets):
    site = tmp_path / 'deepsignal-console.conf'
    render = subprocess.run(
        RENDER, env=os.environ | {
            'PATH': str(python_without_websockets.parent) + os.pathsep + os.environ['PATH'],
            'DEEPSIGNAL_PYTHON': sys.executable,
        },
        text=True, capture_output=True, check=False,
    )
    assert render.returncode == 0, render.stderr
    site.write_text(render.stdout, encoding='utf-8')
    command = [sys.executable, str(CHECKER), '--site-only', '--nginx-site', str(site),
               '--origin', 'https://ship.example', '--ssl-certificate', '/etc/nginx/ship.pem',
               '--ssl-certificate-key', '/etc/nginx/ship.key']
    assert subprocess.run(command, capture_output=True, check=False).returncode == 0
    for suffix in (b'\n', b'\nlocation /extra { proxy_pass http://127.0.0.1:8767; }\n'):
        site.write_bytes(render.stdout.encode() + suffix)
        assert subprocess.run(command, capture_output=True, check=False).returncode == 1
    result = subprocess.run([*command, '--console-source', str(tmp_path)],
                            capture_output=True, check=False)
    assert result.returncode == 2
    assert b'unrecognized arguments' in result.stderr


@pytest.mark.parametrize('available', [False, True], ids=['missing', 'no-websockets'])
def test_installer_rejects_unusable_selected_python(python_without_websockets, available):
    python = (python_without_websockets if available
              else python_without_websockets.with_name('missing-python'))
    result = subprocess.run(
        RENDER, env=os.environ | {'DEEPSIGNAL_PYTHON': str(python)},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ''
    assert str(python) in result.stderr
    assert ('websockets' if available else 'missing or not executable') in result.stderr
