"""commands/legion_run.py — `citadel run` CLI shim.

Thin wrapper over `tools/legion_orchestrator.py` (imported via `_tools_bridge`,
the same DRY pattern `services/corporate.py` uses for `build_workspace_intelligence
_index`), so the parallel multi-process legion engine ships with the installed
package like every other bundled tool instead of duplicating its logic here.
"""

from citadel.services._tools_bridge import import_tool


def run(
    task: str,
    *,
    workspace: str | None = None,
    max_workers: int = 4,
    company: str | None = None,
    dry_run: bool = False,
    no_ui: bool = False,
    autonomous: bool = False,
    smoke: bool = False,
    dashboard: bool = True,
    mode: str = "task",
    permission_mode: str | None = None,
) -> int:
    orchestrator = import_tool("legion_orchestrator")
    return orchestrator.run(
        task,
        workspace=workspace,
        max_workers=max_workers,
        company=company,
        dry_run=dry_run,
        no_ui=no_ui,
        autonomous=autonomous,
        smoke=smoke,
        dashboard=dashboard,
        mode=mode,
        permission_mode=permission_mode,
    )
