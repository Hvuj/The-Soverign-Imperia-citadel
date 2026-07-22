"""Windows-safe daemon discovery and shutdown regressions."""

import signal

from citadel.commands import _daemons


def test_windows_termination_does_not_use_posix_process_groups(monkeypatch):
    calls = []
    monkeypatch.setattr(_daemons.sys, "platform", "win32")
    monkeypatch.setattr(_daemons.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(
        _daemons.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(AssertionError("Windows must not call os.getpgid")),
        raising=False,
    )

    assert _daemons._terminate_process(43210)
    assert calls == [(43210, signal.SIGTERM)]


def test_termination_rejects_non_positive_pid(monkeypatch):
    monkeypatch.setattr(
        _daemons.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not signal a non-positive PID")),
    )

    assert not _daemons._terminate_process(0)
    assert not _daemons._terminate_process(-1)


def test_windows_style_tool_paths_are_found(monkeypatch):
    monkeypatch.setattr(
        _daemons,
        "iter_process_command_lines",
        lambda: iter([(43210, r"python C:\work\citadel\tools\embedder_daemon.py")]),
    )

    assert _daemons.find_citadel_daemon_procs() == [(43210, "embedder_daemon")]


def test_daemon_name_in_shell_text_is_not_treated_as_a_daemon(monkeypatch):
    monkeypatch.setattr(
        _daemons,
        "iter_process_command_lines",
        lambda: iter([(43210, 'pwsh -Command "echo citadel_ui_server"')]),
    )

    assert _daemons.find_citadel_daemon_procs() == []
