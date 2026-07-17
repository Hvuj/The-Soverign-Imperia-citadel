"""Regression tests for the optional ``citadel up`` UI startup path."""

from pathlib import Path

from citadel.commands import up as up_mod


def test_ui_start_does_not_stat_tool_in_parent_and_requires_readiness(monkeypatch, capsys):
    seen: dict = {}

    def fake_start_daemon(**kwargs):
        seen.update(kwargs)
        return 4321

    monkeypatch.setattr(up_mod, "start_daemon", fake_start_daemon)
    monkeypatch.setattr(up_mod, "_wait_for_port", lambda *_args, **_kwargs: False)

    assert up_mod._start_ui_server(Path("workspace")) is None
    assert seen["check_tool"] is False
    assert "NOT READY (optional; continuing)" in capsys.readouterr().out


def test_ui_start_returns_url_only_after_port_is_ready(monkeypatch):
    monkeypatch.setenv("CITADEL_UI_PORT", "9876")
    monkeypatch.setattr(up_mod, "start_daemon", lambda **_kwargs: 4321)
    monkeypatch.setattr(up_mod, "_wait_for_port", lambda *_args, **_kwargs: True)

    assert up_mod._start_ui_server(Path("workspace")) == "http://localhost:9876/brain/graph.html"
