"""UI startup must avoid realpath and the OneDrive-hosted root junction."""

import runpy
import signal
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
UI_SERVER = TOOLS / "citadel_ui_server.py"


def _load_ui(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> dict:
    workspace.joinpath(".citadel", ".claude", "state").mkdir(parents=True)
    monkeypatch.setenv("CITADEL_WORKSPACE", str(workspace))
    monkeypatch.delitem(sys.modules, "intent_classifier", raising=False)
    monkeypatch.delitem(sys.modules, "legion_model_dispatcher", raising=False)

    def forbid_resolve(_self, *args, **kwargs):
        raise AssertionError("UI startup must not call Path.resolve()/realpath")

    monkeypatch.setattr(Path, "resolve", forbid_resolve)
    loaded = runpy.run_path(str(UI_SERVER), run_name="citadel_ui_server_import_test")
    # runpy returns a snapshot; patch the namespace actually retained by the
    # functions before invoking main(), otherwise the real HTTP server starts.
    return loaded["main"].__globals__


def test_ui_import_never_calls_realpath(monkeypatch, tmp_path):
    original_sys_path = list(sys.path)
    try:
        loaded = _load_ui(monkeypatch, tmp_path)
    finally:
        sys.path[:] = original_sys_path

    assert loaded["ROOT"] == tmp_path
    assert loaded["_CLAUDE_DIR"] == tmp_path / ".citadel" / ".claude"
    assert loaded["CONFIG_PATH"] == tmp_path / ".citadel" / ".claude" / "brain" / "citadel-ask-config.json"
    assert loaded["_workspace_path"](".claude/state/example.json") == (
        tmp_path / ".citadel" / ".claude" / "state" / "example.json"
    )


def test_ui_pidfile_uses_managed_claude_dir(monkeypatch, tmp_path):
    original_sys_path = list(sys.path)
    try:
        loaded = _load_ui(monkeypatch, tmp_path)

        class StopServer(Exception):
            pass

        class FakeServer:
            allow_reuse_address = False
            daemon_threads = False

            def __init__(self, _address, _handler):
                pass

            def serve_forever(self):
                raise StopServer

        loaded.update({
            "_already_healthy": lambda *_args, **_kwargs: False,
            "load_config": lambda: {},
            "build_graph_cache": lambda _cfg: {},
            "build_workspace_index_cache": lambda _cfg: None,
            "ThreadingHTTPServer": FakeServer,
        })
        monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)

        with pytest.raises(StopServer):
            loaded["main"]()
    finally:
        sys.path[:] = original_sys_path

    managed_pid = tmp_path / ".citadel" / ".claude" / "state" / "citadel-ui-server.pid"
    assert managed_pid.is_file()
    assert not (tmp_path / ".claude" / "state" / "citadel-ui-server.pid").exists()
