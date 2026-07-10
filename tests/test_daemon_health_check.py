"""Tests for tools/daemon_health_check.py — workspace-agnostic production-path
safety check (G2): flags a hardcoded write into any DISCOVERED sibling repo, not one
hardcoded client name.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "daemon_health_check.py"


def _run(ws: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL)], cwd=str(ws), env=env,
        capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    (tmp_path / ".claude" / "daemon").mkdir(parents=True)
    return tmp_path


def _write_discovery(ws: Path, repo_names: list) -> None:
    discovery = {
        "projects": [
            {"root_path": str(ws.parent / name), "languages": ["python"], "frameworks": [],
             "build_system": "detected"}
            for name in repo_names
        ]
    }
    (ws / ".claude" / "state" / "workspace-discovery.json").write_text(
        json.dumps(discovery), encoding="utf-8"
    )


def _write_daemon_source(ws: Path, body: str) -> None:
    (ws / "tools" / "incremental_brain_daemon.py").write_text(body, encoding="utf-8")


def test_clean_daemon_source_passes(ws: Path):
    _write_discovery(ws, ["acme-widgets"])
    _write_daemon_source(ws, "def main():\n    pass\n")
    r = _run(ws)
    assert "Daemon source safety violation" not in r.stdout


def test_hardcoded_discovered_repo_write_flagged(ws: Path):
    _write_discovery(ws, ["acme-widgets"])
    _write_daemon_source(ws, 'path = "${HOME}/work/acme-widgets/output.json"\n')
    r = _run(ws)
    assert "Daemon source safety violation" in r.stdout
    assert "acme-widgets/" in r.stdout
    assert r.returncode == 1


def test_undiscovered_repo_name_not_flagged(ws: Path):
    _write_discovery(ws, ["acme-widgets"])
    _write_daemon_source(ws, 'path = "${HOME}/work/some-other-repo/output.json"\n')
    r = _run(ws)
    assert "Daemon source safety violation" not in r.stdout


def test_no_discovery_file_flags_nothing_extra(ws: Path):
    _write_daemon_source(ws, 'path = "${HOME}/work/acme-widgets/output.json"\n')
    r = _run(ws)
    assert "Daemon source safety violation" not in r.stdout
