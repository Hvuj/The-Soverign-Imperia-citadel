"""commands/workers.py — `citadel workers [--watch]` — live daemon + subagent status.

Thin entry point over `tools/worker_status.py` (DIP: the real reduction logic lives
in the tool so the statusline can import it too without depending on the packaged
CLI). One-shot by default; `--watch` clears and redraws every `--interval` seconds.
"""

import sys
from pathlib import Path

from citadel import paths as vp
from citadel.services._tools_bridge import import_tool


def run(workspace: str | None = None, *, watch: bool = False, interval: float = 1.5, as_json: bool = False) -> int:
    ws = Path(workspace).expanduser().resolve() if workspace else vp.workspace_root()

    try:
        worker_status = import_tool("worker_status")
    except Exception as exc:
        print(f"ERROR: could not load tools/worker_status.py: {exc}", file=sys.stderr)
        return 1

    if watch:
        worker_status.watch(ws, interval)
        return 0

    status = worker_status.build_status(ws)
    if as_json:
        import json
        print(json.dumps(status, indent=2))
    else:
        print(worker_status.render_text(status))
    return 0
