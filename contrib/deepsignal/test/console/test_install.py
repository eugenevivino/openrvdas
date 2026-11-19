"""Tests for the DeepSignal Console nginx installer."""

import pytest

from contrib.deepsignal.console.install import test_owned_site


nginx_install = test_owned_site.nginx_install


def test_installs_once_in_dedicated_site_and_is_idempotent(nginx_install):
    _, main, site, install = nginx_install
    original = main.read_bytes()
    assert install().returncode == 0
    installed = site.read_bytes()
    assert installed.count(b'server {') == 1
    assert b'alias /srv/openrvdas/contrib/deepsignal/console/dist/;' in installed
    assert install().returncode == 0
    assert site.read_bytes() == installed
    assert main.read_bytes() == original


def test_failed_nginx_test_restores_original(nginx_install):
    root, main, site, install = nginx_install
    before = main.read_bytes()
    site.write_bytes(b'')
    result = install(NGINX_TEST_EXIT='1')
    assert result.returncode != 0
    assert site.read_bytes() == b''
    assert list(site.parent.iterdir()) == [site]
    assert main.read_bytes() == before
    assert (root / 'reloads').read_bytes() == b''
    assert 'restored' in result.stderr


def test_dry_run_writes_nothing(nginx_install):
    root, main, site, install = nginx_install
    before = main.read_bytes()
    result = install('--dry-run', offline=True)
    assert result.returncode == 0, result.stderr
    assert b'location = /cds-ws' in result.stdout.encode()
    assert main.read_bytes() == before
    assert list(site.parent.iterdir()) == []
    assert (root / 'reloads').read_bytes() == b''


def test_uninstall_removes_only_owned_site(nginx_install):
    root, _, site, install = nginx_install
    other = site.with_name('other.conf')
    original = b'server { listen 80; }\n'
    other.write_bytes(original)
    assert install().returncode == 0
    assert install('--uninstall').returncode == 0
    assert not site.exists()
    assert other.read_bytes() == original
    assert (root / 'reloads').read_text().splitlines() == ['reload', 'reload']


def test_real_run_refuses_non_root(nginx_install):
    _, main, site, install = nginx_install
    before = main.read_bytes()
    result = install(FAKE_UID='1000')
    assert result.returncode != 0
    assert 'Run this installer as root' in result.stderr
    assert main.read_bytes() == before
    assert not site.exists()


def test_missing_auto_detected_conf_has_plain_message(nginx_install):
    _, main, site, install = nginx_install
    site.parent.rmdir()
    result = install('--dry-run', default_site=True)
    assert result.returncode != 0
    assert 'No nginx configuration found' in result.stderr
    assert str(main.parent / 'sites-enabled') in result.stderr
    assert str(main.parent / 'conf.d') in result.stderr


@pytest.mark.parametrize('with_nginx', [True, False], ids=['packaged', 'offline'])
def test_d_fix1_installer_preview_uses_system_nginx(nginx_install, with_nginx):
    root, _, site, install = nginx_install
    tools = root / 'bin'
    system = root / 'system'
    system.mkdir()
    if with_nginx:
        (tools / 'nginx').rename(system / 'nginx')
    else:
        (tools / 'nginx').unlink()
    (tools / 'dirname').symlink_to('/usr/bin/dirname')
    stub = root / 'nginx_stub.py'
    stub.write_text(stub.read_text().replace(
        'files = sorted', '(root / "dumped").touch()\nfiles = sorted'))
    result = install('--dry-run', PATH=str(tools), TEST_NGINX_PATH=str(system))
    assert result.returncode == 0, result.stderr
    assert (root / 'dumped').exists() is with_nginx
    assert not site.exists()


@pytest.mark.parametrize('layout', ['custom', 'unverified', 'missing-systemctl'])
def test_d_fix1_installer_uses_running_nginx(nginx_install, layout):
    root, _, site, install = nginx_install
    tools = root / 'bin'
    binary = tools / 'nginx-custom'
    (tools / 'nginx').rename(binary)
    for name in ('dirname', 'wc', 'awk'):
        (tools / name).symlink_to(f'/usr/bin/{name}')
    if layout != 'unverified':
        exe = root / 'proc/123/exe'
        exe.unlink()
        exe.symlink_to(binary)
    result = install(PATH=str(tools), MASTER_BINARY=str(binary),
                     TEST_SYSTEM_PATH=str(root if layout == 'missing-systemctl' else tools))
    if layout == 'custom':
        assert result.returncode == 0, result.stderr
        assert site.exists()
        assert (root / 'reloads').read_text() == 'reload\n'
    else:
        expected = 'nginx master executable' if layout == 'unverified' else 'systemctl'
        assert result.returncode == 1 and expected in result.stderr
        assert not site.exists()
        assert (root / 'reloads').read_text() == ''
