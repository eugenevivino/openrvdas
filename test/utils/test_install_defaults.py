"""Tests for the installer's non-interactive defaults mode."""

import re
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "utils" / "install_openrvdas.sh"
BEGIN = "# BEGIN prompt helpers"
END = "# END prompt helpers"

BASE_QUESTIONS = (
    "OpenRVDAS install root?",
    "Repository to install from?",
    "Repository branch to install?",
    "HTTP/HTTPS proxy to use",
    "Existing user to set system up for?",
    "OpenRVDAS user to create?",
    "Activate the OpenRVDAS venv when",
    "OpenRVDAS database password for user",
    "Use SSL and secure websockets?",
    "Port on which to serve web console?",
    "Do you already have a .key and a .crt file to use for this server?",
    "Path and name of .crt file?",
    "Path and name of .key file?",
    "Path and name of .crt file to create?",
    "Path and name of .key file to create?",
    "Install and configure firewalld?",
    "Additional TCP ports to open?",
    "Additional UDP ports to open?",
    "Install and configure ufw?",
    "Start the OpenRVDAS server on boot?",
    "Do you want to install this script?",
    "Run simulate:simulate_nbp on boot?",
    "Port for the CachedDataServer?",
    "Which web UI would you like to install?",
    "Expose FastAPI OpenAPI docs (/docs, /redoc) via nginx?",
    "Admin username?",
    "Enable Supervisor Web-interface?",
    "Port on which to serve web interface?",
    "Enable Supervisor Web-interface user/pass?",
    "Username?",
    "Password?",
    "Take automatic snapshots of the cruise definition?",
    "Directory for snapshots?",
)


def _helpers() -> str:
    script = SCRIPT.read_text()
    return script.split(BEGIN, 1)[1].split(END, 1)[0]


def _run_helpers(body: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f"{_helpers()}\n{body}"],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def test_prompt_helpers_accept_defaults_without_stdin():
    result = _run_helpers(
        'ACCEPT_DEFAULTS=yes; prompt_value VALUE "Value?" "alpha"; '
        'echo "value=$VALUE"; yes_no "Continue?" no; echo "yes_no=$YES_NO_RESULT"'
    )
    assert result.returncode == 0
    assert "value=alpha" in result.stdout
    assert "yes_no=no" in result.stdout
    assert "default accepted: alpha" in result.stdout
    assert "default accepted: no" in result.stdout


def test_yes_no_remains_interactive_without_defaults():
    result = _run_helpers(
        'ACCEPT_DEFAULTS=no; yes_no "Continue?" yes; echo "$YES_NO_RESULT"',
        "n\n",
    )
    assert result.returncode == 0
    assert result.stdout.endswith("no\n")


def test_all_prompts_use_helpers_and_base_questions_remain():
    script = SCRIPT.read_text()
    outside_helpers = re.sub(f"{BEGIN}.*?{END}", "", script, flags=re.DOTALL)
    assert "read -p" not in outside_helpers
    for question in BASE_QUESTIONS:
        assert question in script
