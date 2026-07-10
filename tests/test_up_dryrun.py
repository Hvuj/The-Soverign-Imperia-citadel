"""tests/test_up_dryrun.py — up dry-run: banner printed, no daemons, no execvp."""
from unittest.mock import patch, MagicMock

import pytest

from citadel.commands import up as up_mod


def test_up_dryrun_returns_zero(tmp_path, capsys):
    """dry_run=True returns 0, prints banner and the claude command, does not exec."""

    with patch("citadel.commands._theme.time") as mock_time, \
         patch("citadel.commands.up.start_daemon") as mock_daemon, \
         patch("citadel.commands.up.run_tool") as mock_tool, \
         patch("os.execvp") as mock_exec:

        mock_time.sleep = lambda _: None

        rc = up_mod.run("legion", str(tmp_path), dry_run=True, no_ui=True)

    assert rc == 0

    mock_daemon.assert_not_called()
    mock_tool.assert_not_called()
    mock_exec.assert_not_called()

    captured = capsys.readouterr()
    assert "We are many" in captured.out
    assert "dry-run" in captured.out
    assert "claude" in captured.out
    assert "opusplan" in captured.out or "CLAUDE_MODEL" in captured.out or "opusplan" in captured.out


def test_up_dryrun_banner_lines(tmp_path, capsys):
    """All themed banner lines appear in the dry-run output."""
    from citadel.commands._theme import _BANNER_LINES

    with patch("citadel.commands._theme.time") as mock_time, \
         patch("citadel.commands.up.start_daemon"), \
         patch("citadel.commands.up.run_tool"), \
         patch("os.execvp"):

        mock_time.sleep = lambda _: None
        up_mod.run("legion", str(tmp_path), dry_run=True, no_ui=True)

    captured = capsys.readouterr()
    for line in _BANNER_LINES:
        if line.strip():
            assert line in captured.out, f"Banner line missing: {line!r}"


def test_up_missing_workspace_errors(capsys):
    rc = up_mod.run("legion", "/nonexistent/path/xyz", dry_run=True, no_ui=True)
    assert rc == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err
