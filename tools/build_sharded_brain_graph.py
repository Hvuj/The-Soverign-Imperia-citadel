#!/usr/bin/env python3
"""build_sharded_brain_graph.py — hierarchical O(1) brain graph (per-repo shards + pointer root).

A single flat graph over the whole workspace's git history bloats badly (12k+ commit nodes). This
builds a sharded structure instead:

  docs/brain/graphs/<repo>.json      per-repo shard: that repo's real structure + commit nodes
  docs/brain/graph-shard-index.json  O(1) index: {repo_id: {path, node_count, by_type, ...}}
  docs/brain/repos-graph.json        compact pointer graph: one node per repo -> graph_ref shard,
                                      linked to other repos via verified cross-repo import edges

Traversal is lazy: a consumer loads the small pointer graph, and on drill-in resolves a repo to its
shard via the index dict in O(1) and loads only that shard. The existing curated `graph.json`
(agents/topics/directories) is left untouched — this is additive.

Each shard is a real `{nodes, links}` sub-graph, not a commit-only list: it merges
- symbol-level logic nodes + intra-file call edges (`build_logic_nodes.py` output),
- module nodes + import edges (`tools/import_graph.py` output),
- commit/feature/bug nodes (this file's own git-history grouping, as before).
Every category is capped independently and truncation counts are surfaced, never silently
dropped. Building shards no longer requires commit nodes to exist — a repo with zero mined
history still gets a real structural shard; commit nodes are added on top when present.

Repo attribution: commit node frontmatter historically lacks a `repo:` field, so we build a
sha->repo map from `git log` (shas only — cheap) across all git companies x branches in parallel,
then group existing commit nodes by their `commit:` sha. If a node already carries `repo:`, that wins.

Safety contract: never_call_claude, never_edit_production_code (only writes under docs/brain/).
CLI: --build (default) | --status | --json
"""

import argparse
import contextlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _brain_common import ROOT

try:
    from citadel import paths as vp
    from citadel.services.corporate import Company, Legion
    _HAVE_LEGION = True
except Exception:
    _HAVE_LEGION = False

COMMITS_DIR = ROOT / "docs" / "brain" / "nodes" / "commits"
SHARDS_DIR = ROOT / "docs" / "brain" / "graphs"
SHARD_INDEX = ROOT / "docs" / "brain" / "graph-shard-index.json"
REPOS_GRAPH = ROOT / "docs" / "brain" / "repos-graph.json"
CROSS_REPO_EDGES = ROOT / "docs" / "brain" / "workspace" / "cross-repo-edges.json"
_DEFAULT_BRANCHES = ["dev", "main", "master"]
_MAX_COMMITS = 2000
_MAX_MODULE_NODES_PER_REPO = 1000
_MAX_LOGIC_NODES_PER_REPO = 2000


def _all_companies() -> list["Company"]:
    if not _HAVE_LEGION:
        return []
    try:
        return Legion.discover().companies()
    except Exception:
        return []


def _git_companies() -> list[tuple[str, Path]]:
    if not _HAVE_LEGION:
        return []
    try:
        legion = Legion.discover()
        return [(c.repo_id, Path(c.path)) for c in legion.git_companies()]
    except Exception:
        return []


def _branches() -> list[str]:
    if not _HAVE_LEGION:
        return _DEFAULT_BRANCHES
    try:
        return vp.workspace_config(vp.workspace_root()).get("branches", _DEFAULT_BRANCHES)
    except Exception:
        return _DEFAULT_BRANCHES


def _shas_for(job: tuple[str, Path, str]) -> tuple[str, list[str]]:
    repo_id, path, branch = job
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "log", branch, "--no-merges",
             "--pretty=format:%H", f"--max-count={_MAX_COMMITS}"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return repo_id, []
        return repo_id, [s for s in r.stdout.split("\n") if s.strip()]
    except (OSError, subprocess.SubprocessError):
        return repo_id, []


def build_sha_repo_map() -> dict[str, str]:
    companies = _git_companies()
    branches = _branches()
    jobs = [(rid, path, br) for rid, path in companies for br in branches]
    sha_repo: dict[str, str] = {}
    if not jobs:
        return sha_repo
    with ThreadPoolExecutor(max_workers=min(16, len(jobs))) as pool:
        for repo_id, shas in pool.map(_shas_for, jobs):
            for sha in shas:
                sha_repo.setdefault(sha, repo_id)
    return sha_repo


def _parse_node(path: Path) -> dict | None:
    try:
        head = path.read_text(encoding="utf-8", errors="replace").split("\n", 40)
    except OSError:
        return None
    rec = {"id": path.stem, "type": "unknown", "title": "", "sha": "", "repo": ""}
    in_fm = False
    for line in head:
        s = line.strip()
        if s == "---":
            if in_fm:
                break
            in_fm = True
            continue
        if not in_fm:
            continue
        if s.startswith("commit:"):
            rec["sha"] = s.split(":", 1)[1].strip()
        elif s.startswith("type:"):
            rec["type"] = s.split(":", 1)[1].strip()
        elif s.startswith("title:"):
            rec["title"] = s.split(":", 1)[1].strip().strip('"')[:120]
        elif s.startswith("repo:"):
            rec["repo"] = s.split(":", 1)[1].strip()
    return rec


def _commit_nodes_by_repo() -> dict[str, list[dict]]:
    """Group existing commit brain-nodes by repo. Empty dict if none have been mined yet."""
    if not COMMITS_DIR.exists():
        return {}
    node_files = list(COMMITS_DIR.rglob("commit-*.md"))
    if not node_files:
        return {}
    sha_repo = build_sha_repo_map()
    with ThreadPoolExecutor(max_workers=16) as pool:
        parsed = [n for n in pool.map(_parse_node, node_files) if n]
    by_repo: dict[str, list[dict]] = {}
    for rec in parsed:
        repo = rec["repo"] or sha_repo.get(rec["sha"], "unattributed")
        by_repo.setdefault(repo, []).append(
            {"id": rec["id"], "type": rec["type"], "title": rec["title"]})
    return by_repo


def _repo_state_dir(repo_id: str) -> Path:
    if _HAVE_LEGION:
        return vp.state_dir() / "state" / "workspace-intelligence" / repo_id
    return ROOT / ".citadel" / "state" / "workspace-intelligence" / repo_id


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _logic_node_shard_parts(repo_id: str) -> tuple[list[dict], list[dict], int]:
    """Symbol-level nodes + intra-file call links from `build_logic_nodes.py` output."""
    data = _load_json(_repo_state_dir(repo_id) / "logic-nodes.json")
    if not data:
        return [], [], 0
    raw_nodes = data.get("nodes", [])
    truncated = len(raw_nodes) - _MAX_LOGIC_NODES_PER_REPO
    raw_nodes = raw_nodes[:_MAX_LOGIC_NODES_PER_REPO]

    id_by_own_name: dict[str, str] = {}
    nodes: list[dict] = []
    for n in raw_nodes:
        own_name = n["qualname"].split(".")[-1]
        id_by_own_name.setdefault(own_name, n["id"])
        nodes.append({
            "id": n["id"], "type": "symbol", "title": n["qualname"],
            "path": n["path"], "kind": n["kind"],
            "start_line": n["start_line"], "end_line": n["end_line"],
        })

    links: list[dict] = []
    for n in raw_nodes:
        for call_name in n.get("calls", []):
            target = id_by_own_name.get(call_name)
            if target and target != n["id"]:
                links.append({"source": n["id"], "target": target, "type": "calls"})

    return nodes, links, max(0, truncated)


def _import_shard_parts(repo_id: str) -> tuple[list[dict], list[dict], int]:
    """Module-level nodes + import-edge links from `tools/import_graph.py` output."""
    data = _load_json(_repo_state_dir(repo_id) / "import-graph.json")
    if not data:
        return [], [], 0
    adjacency: dict[str, list[str]] = data.get("adjacency", {})
    modules = sorted(adjacency)
    truncated = len(modules) - _MAX_MODULE_NODES_PER_REPO
    modules = modules[:_MAX_MODULE_NODES_PER_REPO]
    kept = set(modules)

    def mod_id(m: str) -> str:
        return f"{repo_id}:module:{m}"

    nodes = [{"id": mod_id(m), "type": "module", "title": m} for m in modules]
    links = [
        {"source": mod_id(m), "target": mod_id(t), "type": "imports"}
        for m in modules for t in adjacency.get(m, []) if t in kept and t != m
    ]
    return nodes, links, max(0, truncated)


def _cross_repo_links() -> list[dict]:
    """Verified cross-repo import edges (`build_cross_repo_edges.py` output) as pointer-graph links."""
    data = _load_json(CROSS_REPO_EDGES)
    if not data:
        return []
    return [
        {"source": f"repo:{e['from_repo']}", "target": f"repo:{e['to_repo']}",
         "type": "imports", "count": e.get("import_count", 0)}
        for e in data.get("edges", [])
    ]


def build() -> dict:
    companies = _all_companies()
    commit_nodes_by_repo = _commit_nodes_by_repo()
    repo_ids = sorted({c.repo_id for c in companies} | set(commit_nodes_by_repo))
    if not repo_ids:
        return {"error": "no companies discovered and no commit nodes", "repos": 0}

    SHARDS_DIR.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    truncation_log: dict[str, dict] = {}

    for repo in repo_ids:
        logic_nodes, logic_links, logic_truncated = _logic_node_shard_parts(repo)
        module_nodes, module_links, module_truncated = _import_shard_parts(repo)
        commit_nodes = commit_nodes_by_repo.get(repo, [])
        for n in commit_nodes:
            n.setdefault("type", "commit")

        nodes = commit_nodes + module_nodes + logic_nodes
        links = module_links + logic_links

        by_type: dict[str, int] = {}
        for n in nodes:
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1

        shard_path = SHARDS_DIR / f"{repo}.json"
        shard_path.write_text(json.dumps(
            {"repo": repo, "node_count": len(nodes), "link_count": len(links),
             "by_type": by_type, "nodes": nodes, "links": links},
            sort_keys=True) + "\n", encoding="utf-8")

        index[repo] = {"path": shard_path.relative_to(ROOT).as_posix(),
                       "node_count": len(nodes), "link_count": len(links), "by_type": by_type}
        if logic_truncated or module_truncated:
            truncation_log[repo] = {"logic_nodes_truncated": logic_truncated,
                                    "module_nodes_truncated": module_truncated}

    SHARD_INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    repo_nodes = [{"id": f"repo:{r}", "type": "repo", "repo": r,
                   "node_count": meta["node_count"], "graph_ref": meta["path"]}
                  for r, meta in sorted(index.items())]
    repo_links = _cross_repo_links()
    REPOS_GRAPH.write_text(json.dumps(
        {"nodes": repo_nodes, "links": repo_links,
         "shard_index": "docs/brain/graph-shard-index.json"},
        indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "repos": len(index),
        "total_nodes": sum(m["node_count"] for m in index.values()),
        "total_links": sum(m["link_count"] for m in index.values()),
        "cross_repo_links": len(repo_links),
        "commit_node_files": sum(len(v) for v in commit_nodes_by_repo.values()),
        "truncated": truncation_log,
        "top": dict(sorted(((r, m["node_count"]) for r, m in index.items()),
                           key=lambda kv: -kv[1])[:8]),
    }


def lookup(repo: str) -> dict | None:
    """O(1) shard resolution: repo -> shard metadata (path + counts), or None."""
    try:
        index = json.loads(SHARD_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return index.get(repo)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the sharded O(1) brain graph.")
    ap.add_argument("--build", action="store_true", help="Build shards + index (default)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    if args.status:
        idx = {}
        with contextlib.suppress(OSError, json.JSONDecodeError):
            idx = json.loads(SHARD_INDEX.read_text(encoding="utf-8"))
        print(f"sharded-graph: {len(idx)} repo shard(s), "
              f"{sum(m.get('node_count', 0) for m in idx.values())} nodes")
        return

    summary = build()
    print(json.dumps(summary, indent=2) if args.as_json else json.dumps(summary))


if __name__ == "__main__":
    main()
