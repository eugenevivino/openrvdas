"""Tests for the DeepSignal Console nginx installer."""

import os
from pathlib import Path
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[4]
INSTALLER = REPO / "contrib/deepsignal/console/install/install.sh"


@pytest.fixture
def nginx_stub(tmp_path):
    """Put controllable nginx and systemctl stubs first on PATH."""
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "nginx").write_text(
        "#!/bin/sh\nexit \"${NGINX_TEST_EXIT:-0}\"\n", encoding="utf-8"
    )
    (tools / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tools / "id").write_text(
        "#!/bin/sh\n[ \"$1\" = -u ] && { echo \"${FAKE_UID:-0}\"; exit 0; }\n"
        "exec /usr/bin/id \"$@\"\n",
        encoding="utf-8",
    )
    # The checkout stands in for a trusted release when simulating root.
    (tools / "stat").write_text("#!/bin/sh\necho '0 755'\n", encoding="utf-8")
    for command in ("nginx", "systemctl", "id", "stat"):
        (tools / command).chmod(0o755)
    return str(tools)


def run_install(conf, nginx_stub, *args, fail=False, env=None, uid=0):
    command = [
        "bash",
        str(INSTALLER),
        "--openrvdas-root",
        "/srv/openrvdas",
        "--nginx-conf",
        str(conf),
        "--no-reload",
        *args,
    ]
    run_env = os.environ | {
        "FAKE_UID": str(uid),
        "PATH": nginx_stub + os.pathsep + os.environ["PATH"],
    }
    run_env.update(env or {})
    return subprocess.run(
        command, text=True, capture_output=True, check=not fail, env=run_env
    )


@pytest.mark.parametrize(
    "initial",
    [
        "server {\n    listen 80;\n}\n",
        "# RHEL site\nserver {\n    server_name ship;\n}\n",
    ],
)
def test_inserts_once_inside_server_and_is_idempotent(tmp_path, nginx_stub, initial):
    conf = tmp_path / "openrvdas.conf"
    conf.write_text(initial, encoding="utf-8")

    run_install(conf, nginx_stub)
    installed = conf.read_text(encoding="utf-8")
    assert installed.count("# BEGIN deepsignal-console") == 1
    assert installed.index("server {") < installed.index("# BEGIN deepsignal-console")
    assert installed.index("# END deepsignal-console") < installed.rindex("}")
    assert "alias /srv/openrvdas/contrib/deepsignal/console/dist/;" in installed
    run_install(conf, nginx_stub)
    assert conf.read_text(encoding="utf-8") == installed


def test_failed_nginx_test_restores_backup(tmp_path, nginx_stub):
    conf = tmp_path / "openrvdas.conf"
    original = "server {\n}\n"
    conf.write_text(original, encoding="utf-8")

    result = run_install(
        conf, nginx_stub, fail=True, env={"NGINX_TEST_EXIT": "1"}
    )

    assert conf.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("openrvdas.conf.deepsignal-backup-*"))
    assert "restored" in result.stdout.lower()


def test_dry_run_writes_nothing(tmp_path, nginx_stub):
    conf = tmp_path / "openrvdas.conf"
    original = "server {\n}\n"
    conf.write_text(original, encoding="utf-8")
    result = run_install(conf, nginx_stub, "--dry-run")
    assert conf.read_text(encoding="utf-8") == original
    assert "BEGIN deepsignal-console" in result.stdout
    assert not list(tmp_path.glob("*.deepsignal-backup-*"))


def test_uninstall_removes_only_marked_block(tmp_path, nginx_stub):
    conf = tmp_path / "openrvdas.conf"
    original = "server {\n    listen 80;\n}\n"
    conf.write_text(original, encoding="utf-8")
    run_install(conf, nginx_stub)
    run_install(conf, nginx_stub, "--uninstall")
    assert conf.read_text(encoding="utf-8") == original


def test_real_run_refuses_non_root(tmp_path, nginx_stub):
    conf = tmp_path / "openrvdas.conf"
    original = "server {\n}\n"
    conf.write_text(original, encoding="utf-8")

    result = run_install(conf, nginx_stub, fail=True, uid=1000)

    assert conf.read_text(encoding="utf-8") == original
    assert "Run this installer as root" in result.stderr


def test_missing_auto_detected_conf_has_plain_message(tmp_path, nginx_stub):
    result = subprocess.run(
        ["bash", str(INSTALLER), "--dry-run"],
        text=True,
        capture_output=True,
        env=os.environ | {"PATH": nginx_stub + os.pathsep + os.environ["PATH"]},
    )
    assert result.returncode != 0
    assert "No nginx configuration found" in result.stderr
    assert "/etc/nginx/sites-enabled/openrvdas.conf" in result.stderr
    assert "/etc/nginx/conf.d/openrvdas.conf" in result.stderr
