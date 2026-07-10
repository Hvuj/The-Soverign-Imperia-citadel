"""Tests for tools/build_workspace_intelligence_index.discover_repos — content-based
repo discovery (item 7 / G3): wired to workspace_discoverer's signature detection so
the index is not purely glob-based, and every discovered repo is annotated."""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_workspace_intelligence_index as bwii  # noqa: E402
from build_workspace_intelligence_index import discover_repos  # noqa: E402


def _make_repo(base: Path, name: str, *, git: bool = False, pyproject: bool = False) -> Path:
    repo = base / name
    repo.mkdir()
    if git:
        (repo / ".git").mkdir()
    if pyproject:
        (repo / "pyproject.toml").write_text("[project]\nname = \"x\"\n", encoding="utf-8")
    return repo


def test_wildcard_default_skips_noise_dirs_without_signature(tmp_path: Path):
    _make_repo(tmp_path, "real-repo", pyproject=True)
    _make_repo(tmp_path, "just-a-folder")

    repos = discover_repos(tmp_path, {"repo_include_globs": ["*"], "repo_exclude_globs": []})
    names = {r["name"] for r in repos}
    assert "real-repo" in names
    assert "just-a-folder" not in names


def test_git_only_repo_still_included(tmp_path: Path):
    _make_repo(tmp_path, "git-only", git=True)

    repos = discover_repos(tmp_path, {"repo_include_globs": ["*"], "repo_exclude_globs": []})
    assert {r["name"] for r in repos} == {"git-only"}


def test_content_signature_annotates_languages(tmp_path: Path):
    _make_repo(tmp_path, "py-repo", pyproject=True)

    repos = discover_repos(tmp_path, {"repo_include_globs": ["*"], "repo_exclude_globs": []})
    repo = next(r for r in repos if r["name"] == "py-repo")
    assert "python" in repo["languages"]
    assert "frameworks" in repo


def test_explicit_non_wildcard_include_bypasses_signature_gate(tmp_path: Path):
    _make_repo(tmp_path, "no-signature-but-named")

    repos = discover_repos(
        tmp_path, {"repo_include_globs": ["no-signature-but-named"], "repo_exclude_globs": []},
    )
    assert {r["name"] for r in repos} == {"no-signature-but-named"}


def test_write_workspace_discovery_produces_consumer_schema(tmp_path: Path, monkeypatch):
    """bi_logic_discoverer.py and corporate_spine_compiler.py both read
    .claude/state/workspace-discovery.json as {"projects": [...]} — verify the build
    pipeline now writes that file itself instead of leaving it to an orphaned tool."""
    _make_repo(tmp_path, "py-repo", pyproject=True)
    monkeypatch.setattr(bwii, "ROOT", tmp_path)

    repos = discover_repos(tmp_path, {"repo_include_globs": ["*"], "repo_exclude_globs": []})
    bwii._write_workspace_discovery(repos)

    out = tmp_path / ".claude" / "state" / "workspace-discovery.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "projects" in data
    proj = next(p for p in data["projects"] if p["root_path"] == str(tmp_path / "py-repo"))
    assert "python" in proj["languages"]
    assert proj["build_system"] == "detected"
