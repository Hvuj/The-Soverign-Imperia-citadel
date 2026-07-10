"""mine_engine.py — orchestrate git-history mining across all companies x branches.

Shared by `citadel mine` (one-shot) and tools/git_history_daemon.py (continuous). For
each git company (workspace repo) and each configured branch that actually exists, it
mines new commits incrementally, writes commit brain nodes (with line-level function
linkage), and advances the per-(repo, branch) state. Read-only w.r.t. the repos.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from citadel import paths as vp
from citadel.git_history_miner import (
    branch_head_sha,
    get_last_sha,
    load_miner_state,
    mine_history,
    save_repo_branch_state,
    write_brain_nodes,
)
from citadel.services.corporate import Legion

_REPO_SEG = re.compile(r"[A-Za-z0-9._-]+")


@dataclass
class MineSummary:
    repos_seen: int = 0
    branches_mined: int = 0
    commits: int = 0
    nodes_written: int = 0
    per_repo: dict[str, int] = field(default_factory=dict)


def _state_file(ws: Path) -> Path:
    return vp.state_dir(ws) / "state" / "git-miner-state.json"


def touched_repos(ws: Path | None = None, *, scan_root: Path | None = None) -> set[str]:
    """Repo ids touched this session, inferred from the tool-batch ledger.

    Reads `.claude/state/tool-batches.ndjson` (session-scoped, populated by the
    PostToolBatch hook), scans each record's text for absolute paths under scan_root,
    and maps `<scan_root>/<repo>/…` → repo id. This is the signal that makes git mining
    lazy: mine only the repos you actually worked in. Empty set on any read error.
    """
    ws = ws or vp.workspace_root()
    scan_root = scan_root or vp.workspace_config(ws)["scan_root"]
    ledger = vp.claude_dir(ws) / "state" / "tool-batches.ndjson"
    if not ledger.exists():
        return set()
    prefix = str(scan_root).rstrip("/") + "/"
    found: set[str] = set()
    try:
        for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
            if prefix not in line:
                continue
            idx = 0
            while True:
                hit = line.find(prefix, idx)
                if hit == -1:
                    break
                m = _REPO_SEG.match(line, hit + len(prefix))
                if m:
                    found.add(m.group(0))
                idx = hit + len(prefix)
    except OSError:
        return set()
    return found


def mine_all(
    ws: Path | None = None,
    *,
    branches: list[str] | None = None,
    link_functions: bool = True,
    only_repos: set[str] | None = None,
    quiet: bool = False,
    max_commits: int | None = 2000,
) -> MineSummary:
    """Mine git companies x present branches. Returns a compact summary.

    When `only_repos` is given, mines just those company ids (lazy on-touch mining);
    None mines every git company (the daily safety sweep).

    `max_commits=None` mines each (repo, branch) branch's entire history with no cap —
    used for a one-time full sweep (e.g. `citadel init`). The default 2000 bounds
    routine/incremental mining (`citadel mine`, the continuous daemon).
    """
    ws = ws or vp.workspace_root()
    scope = vp.workspace_config(ws)
    branches = branches if branches is not None else scope["branches"]
    nodes_dir = ws / "docs" / "brain" / "nodes"
    state_file = _state_file(ws)

    legion = Legion.discover()
    summary = MineSummary()

    companies = [
        c for c in legion.git_companies()
        if only_repos is None or c.repo_id in only_repos
    ]
    summary.repos_seen = len(companies)
    if not companies:
        return summary

    state = load_miner_state(state_file)
    jobs: list[tuple[str, Path, str, str | None]] = []
    for company in companies:
        for branch in branches:
            if branch_head_sha(company.path, branch) is None:
                continue
            last = get_last_sha(state, company.repo_id, branch)
            jobs.append((company.repo_id, company.path, branch, last))

    def _mine(job: tuple[str, Path, str, str | None]) -> tuple[str, str, list]:
        repo_id, path, branch, last = job
        nodes = mine_history(
            path, branch, last_mined_sha=last,
            repo_id=repo_id, link_functions=link_functions,
            max_commits=max_commits,
        )
        return repo_id, branch, nodes

    workers = max(2, min(8, (os.cpu_count() or 2)))
    if workers > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_mine, jobs))
    else:
        results = [_mine(j) for j in jobs]

    for repo_id, branch, nodes in results:
        if not nodes:
            continue
        written = write_brain_nodes(nodes, nodes_dir)
        save_repo_branch_state(state_file, repo_id, branch, nodes[0].sha)
        summary.branches_mined += 1
        summary.commits += len(nodes)
        summary.nodes_written += len(written)
        summary.per_repo[repo_id] = summary.per_repo.get(repo_id, 0) + len(nodes)
        if not quiet:
            print(f"  [mine] {repo_id}@{branch}: {len(nodes)} new commits")
    return summary
