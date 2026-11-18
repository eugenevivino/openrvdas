"""Count the interactive installer prompts present in a captured log."""

import argparse
from pathlib import Path


# Literal portions of the read -p and yes_no prompts on the Ubuntu/default
# path through utils/install_openrvdas.sh.  Keep these strings aligned with
# the installer: a changed or unexpected prompt must make the clock job fail.
PROMPT_STRINGS = (
    "Name to assign to host (",
    "Use existing clone at ",
    "OpenRVDAS install root? (",
    "Repository to install from? (",
    "Repository branch to install? (",
    "HTTP/HTTPS proxy to use (",
    "OpenRVDAS user to create? (",
    "Activate the OpenRVDAS venv when ",
    "OpenRVDAS database password for user ",
    "Use SSL and secure websockets? ",
    "Port on which to serve web console? (",
    "Install and configure ufw? ",
    "Start the OpenRVDAS server on boot? ",
    "Do you want to install this script?",
    "Run simulate:simulate_nbp on boot?",
    "Port for the CachedDataServer? (",
    "Which web UI would you like to install? (",
    "Enable Supervisor Web-interface? ",
    "Take automatic snapshots of the cruise definition?",
)


def count_prompts(install_log):
    """Return the number of recognized prompts shown in *install_log*."""
    return sum(install_log.count(prompt) for prompt in PROMPT_STRINGS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("install_log", type=Path)
    args = parser.parse_args()
    print(count_prompts(args.install_log.read_text(errors="replace")))


if __name__ == "__main__":
    main()
