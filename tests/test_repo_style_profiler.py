"""Tests for tools/repo_style_profiler.py — per-repo Python-version style profile (item 7)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "repo_style_profiler.py"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    return tmp_path


def _write_discovery(ws: Path, repo_names: list) -> None:
    discovery = {
        "projects": [
            {"root_path": str(ws / "repos" / name), "languages": ["python"], "frameworks": []}
            for name in repo_names
        ]
    }
    (ws / ".claude" / "state" / "workspace-discovery.json").write_text(
        json.dumps(discovery), encoding="utf-8"
    )


def test_no_discovery_file_writes_empty_profiles(ws: Path):
    r = _run(ws, "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {}


def test_reads_requires_python_from_pyproject(ws: Path):
    repo = ws / "repos" / "modern-repo"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    _write_discovery(ws, ["modern-repo"])

    r = _run(ws, "--json")
    assert r.returncode == 0, r.stderr
    profiles = json.loads(r.stdout)
    assert profiles["modern-repo"]["py_version"] == ">=3.12"
    assert profiles["modern-repo"]["source"] == "pyproject.toml:requires-python"
    assert "PEP 604 unions: X | Y, not typing.Union/Optional" in profiles["modern-repo"]["idioms"]
    assert "PEP 695 generic syntax (type Alias = ...)" in profiles["modern-repo"]["idioms"]


def test_falls_back_to_python_version_file(ws: Path):
    repo = ws / "repos" / "legacy-repo"
    repo.mkdir(parents=True)
    (repo / ".python-version").write_text("3.9\n", encoding="utf-8")
    _write_discovery(ws, ["legacy-repo"])

    r = _run(ws, "--json")
    profiles = json.loads(r.stdout)
    assert profiles["legacy-repo"]["py_version"] == "3.9"
    assert profiles["legacy-repo"]["source"] == ".python-version"
    assert "PEP 585 builtin generics: list[str]/dict[str,int], not typing.List/Dict" in profiles["legacy-repo"]["idioms"]
    assert "PEP 604 unions: X | Y, not typing.Union/Optional" not in profiles["legacy-repo"]["idioms"]


def test_unknown_version_missing_files_has_no_idioms(ws: Path):
    repo = ws / "repos" / "no-marker-repo"
    repo.mkdir(parents=True)
    _write_discovery(ws, ["no-marker-repo"])

    r = _run(ws, "--json")
    profiles = json.loads(r.stdout)
    assert profiles["no-marker-repo"]["py_version"] is None
    assert profiles["no-marker-repo"]["idioms"] == []


def test_writes_output_file(ws: Path):
    repo = ws / "repos" / "modern-repo"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text('requires-python = ">=3.11"\n', encoding="utf-8")
    _write_discovery(ws, ["modern-repo"])

    assert _run(ws).returncode == 0
    out = ws / ".claude" / "state" / "workspace-intelligence" / "style-profiles.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["modern-repo"]["py_version"] == ">=3.11"
