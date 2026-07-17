"""PID validation regressions for ``citadel down``."""

from citadel.commands import down


def _run_with_pid(tmp_path, monkeypatch, pid_text, command_line):
    state = tmp_path / ".citadel" / ".claude" / "state"
    state.mkdir(parents=True)
    pidfile = state / "incremental-brain-daemon.pid"
    pidfile.write_text(pid_text, encoding="utf-8")
    terminated = []
    monkeypatch.setattr(down, "process_command_line", lambda _pid: command_line)
    monkeypatch.setattr(down._daemons, "terminate_many", lambda pids, _grace: terminated.extend(pids) or set())
    monkeypatch.setattr(down._daemons, "find_citadel_daemon_procs", lambda **_kwargs: [])

    assert down.run(workspace=str(tmp_path)) == 0
    return pidfile, terminated


def test_down_rejects_non_positive_pidfile(tmp_path, monkeypatch):
    pidfile, terminated = _run_with_pid(tmp_path, monkeypatch, "-1", "python tools/incremental_brain_daemon.py")

    assert not pidfile.exists()
    assert terminated == []


def test_down_does_not_signal_uninspectable_pid(tmp_path, monkeypatch):
    pidfile, terminated = _run_with_pid(tmp_path, monkeypatch, "43210", None)

    assert not pidfile.exists()
    assert terminated == []
