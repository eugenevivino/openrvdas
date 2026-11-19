"""Regression tests for the installer-owned nginx site."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


INSTALL = Path(__file__).resolve().parent
TEMPLATE = INSTALL.parents[1] / 'security/nginx/deepsignal-console.conf.template'


@pytest.fixture
def nginx_install(tmp_path):
    root = tmp_path.resolve()
    main = root / 'nginx.conf'
    main.write_text('events {} http { include sites/*.conf; }\n', encoding='utf-8')
    sites = root / 'sites'
    sites.mkdir()
    tools = root / 'bin'
    tools.mkdir()
    commands = {
        'id': 'echo "${FAKE_UID:-0}"',
        'stat': 'for path do :; done\n'
                'case "$path" in\n'
                '  "$SERVICE_OWNED") echo "1000 755" ;;\n'
                '  "$SERVICE_WRITABLE") echo "0 775" ;;\n'
                '  *) echo "0 755" ;;\n'
                'esac',
        'nginx': f'exec {shlex.quote(sys.executable)} "$TEST_ROOT/nginx_stub.py" "$@"',
        'systemctl': 'case "$1" in\n'
                     ' show) echo 123;;\n'
                     ' reload) echo reload >> "$TEST_ROOT/reloads"; exit "${RELOAD_STATUS:-0}";;\n'
                     ' is-active) exit "${ACTIVE_STATUS:-0}";;\n'
                     ' *) exit 1;;\nesac',
        'ps': 'case "$3" in\n'
              ' -p) echo "nginx: master process $TEST_ROOT/bin/nginx -c '
              '${MASTER_CONFIG:-$TEST_ROOT/nginx.conf}";;\n'
              ' *) wc -l < "$TEST_ROOT/reloads" | '
              'awk \'{print 124+$1, "nginx: worker process"}\';;\n'
              'esac',
        'python3': f'exec {shlex.quote(sys.executable)} "$@"',
        'ss': 'echo "LISTEN 0 128 127.0.0.1:8766 0.0.0.0:*"',
    }
    for name, body in commands.items():
        tool = tools / name
        tool.write_text(f'#!/bin/sh\n{body}\n', encoding='utf-8')
        tool.chmod(0o755)
    (root / 'reloads').touch()
    release = root / 'release/contrib/deepsignal'
    installer = release / 'console/install/install.sh'
    installer.parent.mkdir(parents=True)
    for name in ('install.sh', 'install_site.py', 'nginx_inventory.py', 'nginx-site.awk'):
        if (INSTALL / name).is_file():
            shutil.copyfile(INSTALL / name, installer.with_name(name))
    shutil.copytree(TEMPLATE.parent, release / 'security/nginx')
    checker = release / 'security/check_cds.py'
    checker.write_text(
        'import json, os, sys\n'
        'from pathlib import Path\n'
        'root = Path(os.environ["TEST_ROOT"])\n'
        '(root / "checker-args").write_text(json.dumps(sys.argv[1:]))\n'
        'print("#197 checker called")\n'
        'sys.exit(int(os.environ.get("CHECKER_STATUS", 0)))\n',
        encoding='utf-8',
    )
    (root / 'nginx_stub.py').write_text(
        'import os, sys\n'
        'from pathlib import Path\n'
        'root = Path(os.environ["TEST_ROOT"])\n'
        'if sys.argv[1] == "-t":\n'
        '    sys.exit(int(os.environ.get("NGINX_TEST_EXIT", "0")))\n'
        'if sys.argv[1] != "-T": sys.exit(2)\n'
        'files = sorted((root / "sites").glob("*.conf"))\n'
        'files += [Path(p) for p in os.environ.get("DUMP_FILES", "").splitlines()]\n'
        'for path in [root / "nginx.conf", *files]:\n'
        '    print(f"# configuration file {path}:")\n'
        '    print(path.read_text())\n'
        'if os.environ.get("EXTRA_DUMP"): print(os.environ["EXTRA_DUMP"])\n',
        encoding='utf-8',
    )
    site = sites / 'deepsignal-console.conf'

    def run(*args, offline=False, default_site=False,
            origins=('http://ship.example:8080', 'http://alias.example:8080'), **env):
        path = str(tools) + os.pathsep + os.environ['PATH']
        if offline:
            (tools / 'nginx').unlink()
            # This PATH deliberately has no nginx even on the Linux runner.
            for name in ('dirname', 'stat'):
                target = tools / name
                if not target.exists():
                    target.symlink_to('/usr/bin/' + name)
            path = str(tools)
        origin_args = [arg for origin in origins for arg in ('--origin', origin)]
        site_args = [] if default_site else ['--nginx-conf', str(site)]
        return subprocess.run(
            ['/bin/sh', str(installer), *site_args,
             '--nginx-main', str(main), '--openrvdas-root', '/srv/openrvdas',
             *origin_args, *args],
            env=os.environ | {'PATH': path, 'TEST_ROOT': str(root), **env},
            timeout=60,
            text=True, capture_output=True, check=False,
        )

    return root, main, site, run


def test_rendered_site_is_exact_template_with_literal_origins(nginx_install):
    _, _, site, run = nginx_install
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    expected = TEMPLATE.read_bytes()
    for key, value in {
        'LISTEN': '8080',
        'SERVER_NAMES': 'ship.example alias.example',
        'TLS': '',
        'CONSOLE_DIST': '/srv/openrvdas/contrib/deepsignal/console/dist/',
        'ORIGINS': r'\A(?:http://ship\.example:8080|http://alias\.example:8080)\z',
    }.items():
        expected = expected.replace(f'@@{key}@@'.encode(), value.encode())
    assert site.read_bytes() == expected
    assert expected.count(b'location = /cds-ws {') == 1
    assert b'proxy_pass http://127.0.0.1:8767;' in expected
    assert b'$http_host' not in expected
    assert b'$scheme' not in expected


@pytest.mark.parametrize('offline', [False, True])
@pytest.mark.parametrize('config', [
    'server { location /other { proxy_pass http://127.0.0.1:8767; } }',
    'server { location /raw { proxy_pass http://127.0.0.1:8766; } }',
    'server { listen 8768; }',
    'server { include missing.conf; }',
    'server { location /raw { proxy_pass http://$backend; } }',
    'server { location / { proxy_pass http://example.org; }',
    'server { mystery_route example.org; }',
    'upstream discovered { server example.org service=cds resolve; }',
])
def test_refuses_unowned_http_config_without_writes(nginx_install, config, offline):
    root, main, site, run = nginx_install
    extra = site.parent / 'other.conf'
    extra.write_text(config + '\n', encoding='utf-8')
    before = {p: p.read_bytes() for p in (main, extra)}
    result = run(*(('--dry-run',) if offline else ()), offline=offline)
    assert result.returncode != 0
    assert str(extra) in result.stderr
    assert {p: p.read_bytes() for p in before} == before
    assert list(site.parent.iterdir()) == [extra]
    assert (root / 'reloads').read_bytes() == b''


@pytest.mark.parametrize('stream', [
    'server { listen 9000; proxy_pass 127.0.0.1:8766; }',
    'server { listen 8767; proxy_pass 127.0.0.1:9000; }',
    'server { listen 6224-6226 udp; proxy_pass 127.0.0.1:9000; }',
    'upstream feed { server 127.0.0.1:6225; } '
    'server { listen 7225 udp; proxy_pass feed; }',
    'server { listen 7225 udp; proxy_pass 127.0.0.1:6225; }',
])
def test_refuses_stream_references_to_any_cds_port(nginx_install, stream):
    root, main, site, run = nginx_install
    original = main.read_text() + f'stream {{ {stream} }}\n'
    main.write_text(original, encoding='utf-8')
    result = run('--udp-port', '6225', '--udp-port', '6226', '--udp-interface', '10.0.0.2')
    assert result.returncode != 0
    assert str(main) in result.stderr
    assert main.read_text() == original
    assert list(site.parent.iterdir()) == []
    assert (root / 'reloads').read_bytes() == b''


def test_inventory_lists_unaccounted_dump_files_and_does_not_write(nginx_install):
    root, main, site, run = nginx_install
    extra = root / 'unaccounted.conf'
    before = main.read_bytes()
    result = run(EXTRA_DUMP=f'# configuration file {extra}:\nserver {{ listen 8767; }}')
    assert result.returncode != 0
    assert str(extra) in result.stderr
    assert main.read_bytes() == before
    assert list(site.parent.iterdir()) == []


def test_idempotent_install_reloads_and_confirms(nginx_install):
    root, _, site, run = nginx_install
    for _ in range(2):
        result = run()
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'reload confirmed' in result.stdout
        if _ == 0:
            installed = site.stat()
    assert (root / 'reloads').read_text().splitlines() == ['reload', 'reload']
    assert site.stat().st_ino == installed.st_ino
    assert site.stat().st_mtime_ns == installed.st_mtime_ns


def test_reload_failure_cannot_report_success(nginx_install):
    root, _, site, run = nginx_install
    result = run(RELOAD_STATUS='1')
    assert result.returncode != 0
    assert 'reload' in result.stderr
    assert 'reload confirmed' not in result.stdout
    assert not site.exists()
    assert (root / 'reloads').read_text().splitlines() == ['reload', 'reload']
    assert 'Could not confirm the nginx rollback reload' in result.stderr


def test_refuses_main_config_different_from_running_service(nginx_install):
    root, main, site, run = nginx_install
    active = root / 'different.conf'
    active.write_text('events {} http { server { listen 8766; } }\n')
    before = main.read_bytes(), active.read_bytes()
    result = run(MASTER_CONFIG=str(active))
    assert result.returncode != 0
    assert str(main) in result.stderr and str(active) in result.stderr
    assert (main.read_bytes(), active.read_bytes()) == before
    assert not site.exists()
    assert (root / 'reloads').read_bytes() == b''


def test_inventory_reports_every_conflicting_file(nginx_install):
    root, main, site, run = nginx_install
    first = site.with_name('first.conf')
    second = site.with_name('second.conf')
    first.write_text('server { listen 8766; }\n')
    second.write_text('upstream gateway { server 127.0.0.1:8767; }\n')
    before = {path: path.read_bytes() for path in (main, first, second)}
    result = run()
    assert result.returncode != 0
    assert str(first) in result.stderr and str(second) in result.stderr
    assert {path: path.read_bytes() for path in before} == before
    assert not site.exists()
    assert (root / 'reloads').read_bytes() == b''


def test_refuses_alias_include_before_creating_site(nginx_install):
    root, main, site, run = nginx_install
    alias = root / 'another'
    alias.symlink_to(site.parent, target_is_directory=True)
    before = b'events {} http { include sites/*.conf; include another/*.conf; }\n'
    main.write_bytes(before)
    result = run()
    assert result.returncode != 0
    assert 'included through an alias' in result.stderr
    assert main.read_bytes() == before
    assert list(site.parent.iterdir()) == []
    assert (root / 'reloads').read_bytes() == b''
