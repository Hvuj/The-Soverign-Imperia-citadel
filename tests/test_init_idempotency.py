"""Regression coverage for version-aware ``citadel init`` idempotency."""

import os
from types import SimpleNamespace

import pytest

from citadel import __version__
from citadel.commands import init as init_command


def _fail_if_initializer_runs(_ws):
    raise AssertionError("the initializer must not run for an existing same-version install")


def test_same_version_init_reports_already_installed_without_reinitializing(tmp_path, monkeypatch, capsys):
    parent = tmp_path / "project"
    marker = parent / "citadel-home" / ".citadel" / "version"
    marker.parent.mkdir(parents=True)
    marker.write_text(f"{__version__}\n", encoding="utf-8")
    monkeypatch.setattr(init_command, "_scaffold_citadel_dir", _fail_if_initializer_runs)

    assert init_command.run(str(parent)) == 0

    output = capsys.readouterr().out
    assert "already installed" in output
    assert f"version {__version__}" in output
    assert "--force" in output


def test_complete_pre_marker_install_is_preserved_without_reinitializing(tmp_path, monkeypatch, capsys):
    parent = tmp_path / "project"
    ws = parent / "citadel-home"
    citadel_dir = ws / ".citadel"
    (citadel_dir / ".claude").mkdir(parents=True)
    (citadel_dir / "config.toml").write_text("[workspace]\n", encoding="utf-8")
    (citadel_dir / "CLAUDE.md").write_text("# Citadel\n", encoding="utf-8")
    monkeypatch.setattr(init_command, "_scaffold_citadel_dir", _fail_if_initializer_runs)

    assert init_command.run(str(parent)) == 0

    assert not (citadel_dir / "version").exists()
    output = capsys.readouterr().out
    assert "already installed" in output
    assert "version unknown" in output


def test_different_version_requires_force_without_reinitializing(tmp_path, monkeypatch, capsys):
    parent = tmp_path / "project"
    marker = parent / "citadel-home" / ".citadel" / "version"
    marker.parent.mkdir(parents=True)
    installed_version = "0.0.0-previous"
    marker.write_text(f"{installed_version}\n", encoding="utf-8")
    monkeypatch.setattr(init_command, "_scaffold_citadel_dir", _fail_if_initializer_runs)

    assert init_command.run(str(parent)) != 0

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert installed_version in output
    assert __version__ in output
    assert "--force" in output


def test_unreadable_version_marker_requires_force(tmp_path, monkeypatch, capsys):
    parent = tmp_path / "project"
    marker = parent / "citadel-home" / ".citadel" / "version"
    marker.mkdir(parents=True)
    monkeypatch.setattr(init_command, "_scaffold_citadel_dir", _fail_if_initializer_runs)

    assert init_command.run(str(parent)) != 0

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "unreadable" in output
    assert "--force" in output


def test_force_bypasses_same_version_guard(tmp_path, monkeypatch):
    parent = tmp_path / "project"
    marker = parent / "citadel-home" / ".citadel" / "version"
    marker.parent.mkdir(parents=True)
    marker.write_text(f"{__version__}\n", encoding="utf-8")
    monkeypatch.setattr(init_command, "_scaffold_citadel_dir", _fail_if_initializer_runs)

    with pytest.raises(AssertionError, match="initializer must not run"):
        init_command.run(str(parent), force=True)


def _stub_successful_init(monkeypatch, *, integrity_ok):
    monkeypatch.setenv("CITADEL_WORKSPACE", "test-value-restored-by-monkeypatch")

    def scaffold(ws):
        (ws / ".citadel").mkdir(parents=True)

    def create_root_claude_dir(ws):
        (ws / ".claude" / "state").mkdir(parents=True)

    def run_tool(tool_name, *args, **kwargs):
        if tool_name == "scaffold_integrity_lint.py":
            return integrity_ok
        return True

    monkeypatch.setattr(init_command, "_scaffold_citadel_dir", scaffold)
    monkeypatch.setattr(init_command, "_copy_claude_template", lambda *args, **kwargs: None)
    monkeypatch.setattr(init_command, "_copy_claude_md", lambda *args, **kwargs: None)
    monkeypatch.setattr(init_command, "_copy_mcp_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(init_command, "_ensure_root_symlinks", create_root_claude_dir)
    monkeypatch.setattr(init_command, "_ensure_bundled_dir_symlinks", lambda *args, **kwargs: None)
    monkeypatch.setattr(init_command, "_bootstrap_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(init_command, "_seed_docs", lambda *args, **kwargs: None)
    monkeypatch.setattr(init_command, "run_tool", run_tool)
    monkeypatch.setattr(
        init_command,
        "mine_all",
        lambda *args, **kwargs: SimpleNamespace(
            repos_seen=0,
            branches_mined=0,
            commits=0,
            nodes_written=0,
        ),
    )


def test_successful_init_records_current_version(tmp_path, monkeypatch):
    parent = tmp_path / "project"
    parent.mkdir()
    _stub_successful_init(monkeypatch, integrity_ok=True)

    assert init_command.run(str(parent)) == 0

    marker = parent / "citadel-home" / ".citadel" / "version"
    assert marker.read_text(encoding="utf-8") == f"{__version__}\n"
    assert os.environ["CITADEL_WORKSPACE"] == str(parent / "citadel-home")


def test_failed_integrity_check_does_not_record_current_version(tmp_path, monkeypatch):
    parent = tmp_path / "project"
    parent.mkdir()
    _stub_successful_init(monkeypatch, integrity_ok=False)

    assert init_command.run(str(parent)) == 0

    marker = parent / "citadel-home" / ".citadel" / "version"
    assert not marker.exists()
