"""The daemon-start watchdog: a filesystem op that blocks (e.g. a OneDrive placeholder stall — which raises
nothing, it just hangs) must not hang `citadel up`. start_daemon runs the spawn in a watchdog thread and
returns None (a non-fatal skip) if it exceeds the budget."""

import time
from pathlib import Path

from citadel.commands import _runner


def test_start_daemon_skips_a_stalled_start(monkeypatch):
    monkeypatch.setattr(_runner, "_DAEMON_START_TIMEOUT", 0.3)

    def _hang(*_a, **_k):
        time.sleep(30)  # simulate a blocked filesystem op that never returns

    monkeypatch.setattr(_runner, "_start_daemon_inner", _hang)

    t0 = time.perf_counter()
    pid = _runner.start_daemon("x.py", Path("."), [], ".claude/state/x.pid",
                               ".claude/state/x.out", ".claude/state/x.err")
    elapsed = time.perf_counter() - t0

    assert pid is None                     # stalled start → skipped, not hung
    assert elapsed < 3.0                   # returned promptly at the watchdog budget, not after 30s


def test_start_daemon_returns_pid_on_fast_start(monkeypatch):
    monkeypatch.setattr(_runner, "_start_daemon_inner", lambda *a, **k: 4242)
    pid = _runner.start_daemon("x.py", Path("."), [], ".claude/state/x.pid",
                               ".claude/state/x.out", ".claude/state/x.err")
    assert pid == 4242                     # normal path unchanged


def test_ensure_dir_is_memoized(tmp_path, monkeypatch):
    calls: list[Path] = []
    real_mkdir = Path.mkdir

    def _counting_mkdir(self, *a, **k):
        calls.append(self)
        return real_mkdir(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", _counting_mkdir)
    monkeypatch.setattr(_runner, "_created_dirs", set())
    d = tmp_path / "state"
    _runner._ensure_dir(d)
    _runner._ensure_dir(d)                 # second call is a cache hit
    _runner._ensure_dir(d)
    assert calls.count(d) == 1             # mkdir probed the OneDrive path once, not three times
