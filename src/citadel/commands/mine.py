"""commands/mine.py — `citadel mine [--branch BRANCH]` — git-history miner.

Mines every git company (workspace repo) across the configured branches
(dev/main/master by default), aggregating commit brain nodes with line-level
function linkage into the legion's own brain. `--branch` restricts to one branch.
"""

import os
from pathlib import Path

from citadel import paths as vp
from citadel.mine_engine import mine_all


def run(workspace: str | None = None, *, branch: str | None = None) -> int:
    ws = Path(workspace).expanduser().resolve() if workspace else vp.workspace_root()
    os.environ["CITADEL_WORKSPACE"] = str(ws)

    branches = [branch] if branch else None
    scope = vp.workspace_config(ws)
    shown = branches or scope["branches"]
    include_paths = scope.get("repo_include_paths")
    if include_paths:
        print(f"[citadel mine] scope: {len(include_paths)} .code-workspace folders  branches: {', '.join(shown)}")
    else:
        print(f"[citadel mine] scan_root: {scope['scan_root']}  branches: {', '.join(shown)}")

    summary = mine_all(ws, branches=branches)

    print(
        f"[citadel mine] {summary.repos_seen} git repos, "
        f"{summary.branches_mined} (repo,branch) mined, "
        f"{summary.commits} commits → {summary.nodes_written} brain nodes."
    )
    return 0
