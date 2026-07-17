"""Regression tests for daemon state paths and the managed ``.claude`` link."""

from types import SimpleNamespace

from citadel.commands import _runner


def test_daemon_path_bypasses_root_claude_when_managed_target_exists(tmp_path):
    managed = tmp_path / ".citadel" / ".claude"
    managed.mkdir(parents=True)

    result = _runner._daemon_path(tmp_path, ".claude/state/example.pid")

    assert result == managed / "state" / "example.pid"


def test_daemon_path_does_not_remap_unrelated_workspace_path(tmp_path):
    result = _runner._daemon_path(tmp_path, "logs/example.pid")

    assert result == tmp_path / "logs" / "example.pid"


def test_start_daemon_writes_state_without_touching_root_claude(tmp_path, monkeypatch):
    managed = tmp_path / ".citadel" / ".claude"
    managed.mkdir(parents=True)
    # A file here models an unusable/broken root link.  Startup must only use
    # the real managed target once it is available.
    (tmp_path / ".claude").write_text("do not traverse", encoding="utf-8")

    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "worker.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(_runner, "_tools_dir", lambda: tools)
    monkeypatch.setattr(_runner, "_lower_priority", lambda _pid: None)
    proc = SimpleNamespace(pid=43210)
    monkeypatch.setattr(_runner.subprocess, "Popen", lambda *args, **kwargs: proc)

    pid = _runner.start_daemon(
        "worker.py",
        tmp_path,
        [],
        ".claude/state/worker.pid",
        ".claude/state/worker.out.log",
        ".claude/state/worker.err.log",
    )

    assert pid == proc.pid
    assert (managed / "state" / "worker.pid").read_text() == str(proc.pid)
    assert (managed / "state" / "worker.out.log").exists()
    assert (managed / "state" / "worker.err.log").exists()
    assert (tmp_path / ".claude").is_file()


def test_start_daemon_can_skip_onedrive_tool_stat(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tool = tools / "cloud-placeholder-worker.py"
    monkeypatch.setattr(_runner, "_tools_dir", lambda: tools)
    monkeypatch.setattr(_runner, "_lower_priority", lambda _pid: None)
    monkeypatch.setattr(_runner.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(pid=54321))

    def fail_if_statted():
        raise AssertionError("the UI launch must not stat its OneDrive-backed script")

    monkeypatch.setattr(type(tool), "exists", lambda self: fail_if_statted() if self == tool else False)

    pid = _runner.start_daemon(
        tool.name,
        tmp_path,
        [],
        ".claude/state/worker.pid",
        ".claude/state/worker.out.log",
        ".claude/state/worker.err.log",
        check_tool=False,
    )

    assert pid == 54321
