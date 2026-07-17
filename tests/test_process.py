"""Regression tests for non-signaling process liveness checks."""

import os
import sys

import pytest

from citadel import _process


def test_pid_is_alive_rejects_non_positive_pids():
    assert not _process.pid_is_alive(0)
    assert not _process.pid_is_alive(-1)


def test_pid_is_alive_reports_current_process():
    assert _process.pid_is_alive(os.getpid())


def test_windows_pid_probe_never_calls_os_kill(monkeypatch):
    monkeypatch.setattr(_process.sys, "platform", "win32")
    monkeypatch.setattr(_process, "_windows_pid_is_alive", lambda pid: pid == 43210)

    def fail_if_signaled(*_args):
        raise AssertionError("Windows PID probes must not call os.kill")

    monkeypatch.setattr(_process.os, "kill", fail_if_signaled)

    assert _process.pid_is_alive(43210)
    assert not _process.pid_is_alive(12345)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process APIs")
def test_windows_process_command_line_reports_current_process():
    command_line = _process.process_command_line(os.getpid())

    assert command_line
    assert "pytest" in command_line.lower() or "python" in command_line.lower()
    assert os.getpid() in {pid for pid, _command in _process.iter_process_command_lines()}
