"""Tests for tools/legion_shell.py — governed read-only shell runner (default-deny)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "legion_shell.py"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    (tmp_path / "hello.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    return tmp_path


def test_allows_readonly_grep(ws: Path):
    r = _run(ws, "--json", "grep", "alpha", "hello.txt")
    out = json.loads(r.stdout)
    assert out["allowed"] is True  # governance: grep is allowlisted (read-only)
    if out.get("error"):  # binary not runnable here (e.g. no `grep` on native Windows)
        pytest.skip(f"grep not available on this platform: {out['error']}")
    assert "alpha" in out["stdout"]


def test_allows_git_read_subcommand(ws: Path):
    out = json.loads(_run(ws, "--json", "git", "status").stdout)
    assert out["allowed"] is True


def test_denies_destructive_rm(ws: Path):
    out = json.loads(_run(ws, "--json", "rm", "-rf", "hello.txt").stdout)
    assert out["allowed"] is False
    assert (ws / "hello.txt").exists()


def test_denies_mutating_git(ws: Path):
    out = json.loads(_run(ws, "--json", "git", "push", "origin", "main").stdout)
    assert out["allowed"] is False
    assert "mutating git" in out["reason"]


def test_denies_unknown_binary(ws: Path):
    out = json.loads(_run(ws, "--json", "curl", "http://evil").stdout)
    assert out["allowed"] is False
