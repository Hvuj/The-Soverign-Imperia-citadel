"""Tests for tools/zombie_worker.py — zero-token deterministic improvement proposals."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "zombie_worker.py"

_COMPLEX_FN = "def messy(x):\n" + "".join(
    f"    if x == {i}:\n        for j in range({i}):\n            x += j\n" for i in range(12)
) + "    return x\n"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    src = tmp_path / "target"
    src.mkdir()
    (src / "messy.py").write_text(_COMPLEX_FN, encoding="utf-8")
    return tmp_path


def test_zombie_files_complexity_proposal(ws: Path):
    r = _run(ws, "--once", "--path", str(ws / "target"), "--json")
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout)
    assert result["complexity_hotspots"] >= 1
    assert len(result["proposed"]) >= 1

    files = list((ws / ".claude" / "state" / "feature-improvements").glob("*.json"))
    assert files
    rec = json.loads(files[0].read_text())
    assert rec["source"] == "zombie"
    assert rec["rice_score"] > 0
    assert rec["evidence"]["kind"] in ("complexity", "lint")


def test_zombie_dedups_by_target(ws: Path):
    _run(ws, "--once", "--path", str(ws / "target"))
    _run(ws, "--once", "--path", str(ws / "target"))
    files = list((ws / ".claude" / "state" / "feature-improvements").glob("*.json"))
    targets = [json.loads(f.read_text())["target"] for f in files]
    assert len(targets) == len(set(targets))
