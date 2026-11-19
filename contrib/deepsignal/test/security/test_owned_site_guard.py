"""The static checker only verifies exact bytes of the installer-owned site."""

import subprocess
import sys
from pathlib import Path


CHECKER = Path(__file__).resolve().parents[2] / 'security/check_cds.py'


def test_checker_matches_only_rendered_site_and_rejects_source_option(tmp_path):
    site = tmp_path / 'deepsignal-console.conf'
    install = CHECKER.parents[1] / 'console/install/install.sh'
    render = subprocess.run(
        ['/bin/sh', str(install), '--render', '--origin', 'https://ship.example',
         '--ssl-certificate', '/etc/nginx/ship.pem',
         '--ssl-certificate-key', '/etc/nginx/ship.key'],
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
