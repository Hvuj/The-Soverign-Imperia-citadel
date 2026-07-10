"""Tests for tools/scope_guard.py — workspace-agnostic /scripts path exception (G2).

Verifies the ambiguous-"scripts"-path guard no longer trusts a hardcoded client repo
name; it instead consults the discovered workspace (workspace-discovery.json) so any
"<repo>/scripts" path is allowed only for repos the legion has actually found.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "scope_guard.py"


def _run(ws: Path, command: str) -> dict:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ws)}
    r = subprocess.run(
        [sys.executable, str(TOOL)], input=payload,
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _decision(resp: dict) -> str:
    hso = resp.get("hookSpecificOutput")
    if not hso:
        return "allow"
    return hso.get("permissionDecision", "allow")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    return tmp_path


def _write_discovery(ws: Path, repo_names: list) -> None:
    discovery = {
        "projects": [
            {"root_path": str(ws / name), "languages": ["python"], "frameworks": [], "build_system": "detected"}
            for name in repo_names
        ]
    }
    (ws / ".claude" / "state" / "workspace-discovery.json").write_text(
        json.dumps(discovery), encoding="utf-8"
    )


def test_root_scripts_path_always_allowed(ws: Path):
    cmd = "git" + " rm " + "/scripts/foo.sh"
    assert _decision(_run(ws, cmd)) == "allow"


def test_undiscovered_repo_scripts_path_denied(ws: Path):
    _write_discovery(ws, ["acme-repo"])
    cmd = "git" + " rm " + "other-repo/scripts/foo.sh"
    assert _decision(_run(ws, cmd)) == "deny"


def test_discovered_repo_scripts_path_allowed(ws: Path):
    _write_discovery(ws, ["acme-repo"])
    cmd = "git" + " rm " + "acme-repo/scripts/foo.sh"
    assert _decision(_run(ws, cmd)) == "allow"


def test_no_discovery_file_denies_repo_scripts_path(ws: Path):
    cmd = "git" + " rm " + "some-repo/scripts/foo.sh"
    assert _decision(_run(ws, cmd)) == "deny"


def test_ordinary_command_allowed(ws: Path):
    assert _decision(_run(ws, "ls -la")) == "allow"
