"""Tests for tools/build_sharded_brain_graph.py — per-repo shards + O(1) pointer index."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_sharded_brain_graph.py"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=60,
    )


def _commit_node(sha: str, repo: str, ntype: str, title: str) -> str:
    return (f"---\nid: commit-{sha}\ntitle: \"{title}\"\ntype: {ntype}\n"
            f"tags: []\nlinks: []\nfiles: []\nfunctions: []\n"
            f"commit: {sha}\nauthor: x\ndate: 2026-01-01T00:00:00Z\n"
            f"scope: s\nticket: T-1\nrepo: {repo}\n---\n\n## {title}\n")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "brain" / "nodes" / "commits" / "misc"
    d.mkdir(parents=True)
    (d / "commit-aaa.md").write_text(_commit_node("aaa", "repoA", "feature", "a"), encoding="utf-8")
    (d / "commit-bbb.md").write_text(_commit_node("bbb", "repoA", "bug", "b"), encoding="utf-8")
    (d / "commit-ccc.md").write_text(_commit_node("ccc", "repoB", "feature", "c"), encoding="utf-8")
    return tmp_path


def test_build_creates_per_repo_shards_and_index(ws: Path):
    r = _run(ws, "--build", "--json")
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout)
    assert summary["repos"] >= 2
    assert summary["total_nodes"] == 3

    shard_a = json.loads((ws / "docs" / "brain" / "graphs" / "repoA.json").read_text())
    assert shard_a["node_count"] == 2
    shard_b = json.loads((ws / "docs" / "brain" / "graphs" / "repoB.json").read_text())
    assert shard_b["node_count"] == 1


def test_pointer_graph_and_o1_index(ws: Path):
    _run(ws, "--build")
    index = json.loads((ws / "docs" / "brain" / "graph-shard-index.json").read_text())
    assert index["repoA"]["node_count"] == 2
    assert index["repoA"]["path"] == "docs/brain/graphs/repoA.json"

    repos_graph = json.loads((ws / "docs" / "brain" / "repos-graph.json").read_text())
    ids = {n["id"] for n in repos_graph["nodes"]}
    assert "repo:repoA" in ids
    assert "repo:repoB" in ids
    assert all("graph_ref" in n for n in repos_graph["nodes"])
