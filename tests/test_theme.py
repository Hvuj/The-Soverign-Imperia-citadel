"""tests/test_theme.py â€” Cinematic banner content tests."""
import io
from unittest.mock import patch

from citadel.commands._theme import (
    _INIT_LINES,
    _BANNER_LINES,
    print_init_banner,
    print_up_banner,
)


def test_up_banner_contains_we_are_many():
    assert any("We are many" in line for line in _BANNER_LINES)


def test_up_banner_contains_node_count():
    assert any("4,192" in line for line in _BANNER_LINES)


def test_up_banner_contains_convergence():
    assert any("Convergence complete" in line for line in _BANNER_LINES)


def test_init_banner_contains_booting():
    assert any("Booting Citadel core engine" in line for line in _INIT_LINES)


def test_init_banner_contains_firewalls():
    assert any("Security firewalls detected" in line for line in _INIT_LINES)


def test_init_banner_contains_warn():
    assert any("[WARN]" in line for line in _INIT_LINES)


def test_print_up_banner_outputs_all_lines(capsys):
    with patch("citadel.commands._theme.time") as mock_time:
        mock_time.sleep = lambda _: None
        print_up_banner()
    captured = capsys.readouterr()
    for line in _BANNER_LINES:
        if line:
            assert line in captured.out


def test_print_init_banner_outputs_all_lines(capsys):
    with patch("citadel.commands._theme.time") as mock_time:
        mock_time.sleep = lambda _: None
        print_init_banner()
    captured = capsys.readouterr()
    for line in _INIT_LINES:
        assert line in captured.out
