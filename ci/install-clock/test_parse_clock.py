"""Tests for counting installer prompts in a captured log."""

from pathlib import Path

from parse_clock import count_prompts


HERE = Path(__file__).parent


def test_counts_three_prompts_from_saved_log_excerpt():
    install_log = (HERE / "install-log-excerpt.txt").read_text()

    assert count_prompts(install_log) == 3
