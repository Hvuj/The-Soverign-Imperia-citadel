"""commands/index.py — `citadel index` — rebuild workspace intelligence indexes."""

import subprocess
import sys
from pathlib import Path

from citadel import paths as vp
from citadel.commands._runner import _tools_dir


def run(workspace: str | None = None) -> int:
    import os

    ws = Path(workspace).expanduser().resolve() if workspace else vp.workspace_root()
    os.environ["CITADEL_WORKSPACE"] = str(ws)

    tool = _tools_dir() / "build_workspace_intelligence_index.py"
    if not tool.exists():
        print(f"ERROR: tool not found: {tool}", file=sys.stderr)
        return 1

    print(f"[citadel index] workspace: {ws}")
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    extra_args = ["--workspace", str(ws)] if workspace else []
    result = subprocess.run(
        [sys.executable, str(tool), *extra_args],
        env=env,
    )
    return result.returncode
