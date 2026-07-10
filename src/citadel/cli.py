"""cli.py — `citadel` command-line entry point.

Primary flow:
  init          Set up a workspace once (scaffold + full auto-learn)
  up            Bring the Citadel online — boot brain + daemons + UI, launch Claude Code
  down          Take the Citadel offline — stop all daemons + UI server, clean pidfiles

Other subcommands:
  run    Run a task across N PARALLEL legion worker processes, each its own
                model + effort, gated by the companies/board/L5/L6 governance stack
  index         Rebuild workspace intelligence indexes
  mine          Run git-history miner only
  workers       Show live daemon + subagent ('worker') status
  brain         Rebuild brain search index
  benchmark     Deterministic best-practices score
  replicate     Decide/execute zero-token feature replication for a task
  companies     List companies, or run the LEGION principle scorecard on a file
"""

import argparse
import sys


def _cmd_init(args: argparse.Namespace) -> int:
    from pathlib import Path

    from citadel.commands._theme import print_init_banner
    from citadel.commands.init import run
    ws = str(Path(args.workspace).expanduser().resolve()) if args.workspace else "."
    print_init_banner()
    return run(ws, branch=args.branch, force=args.force)


def _cmd_up(args: argparse.Namespace, unknown: list[str] | None = None) -> int:
    """`citadel up` — bring the Citadel online (boot brain + daemons + UI, launch Claude Code)."""
    from citadel.commands.up import run
    return run(
        "legion",
        workspace=getattr(args, "workspace", None),
        dry_run=getattr(args, "dry_run", False),
        no_ui=getattr(args, "no_ui", False),
        restart=getattr(args, "restart", False),
        passthrough=unknown or [],
        effort=getattr(args, "effort", None),
    )


def _cmd_down(args: argparse.Namespace) -> int:
    """`citadel down` — take the Citadel offline (stop daemons + UI, clean pidfiles)."""
    from citadel.commands.down import run
    return run(workspace=getattr(args, "workspace", None))


def _cmd_legion_run(args: argparse.Namespace) -> int:
    from citadel.commands.legion_run import run
    return run(
        " ".join(args.task),
        workspace=getattr(args, "workspace", None),
        max_workers=getattr(args, "max_workers", 4),
        company=getattr(args, "company", None),
        dry_run=getattr(args, "dry_run", False),
        no_ui=getattr(args, "no_ui", False),
        autonomous=getattr(args, "autonomous", False),
        smoke=getattr(args, "smoke", False),
        dashboard=not getattr(args, "no_dashboard", False),
        mode=getattr(args, "mode", "task"),
        permission_mode=getattr(args, "permission_mode", None),
    )


def _cmd_benchmark(args: argparse.Namespace) -> int:
    """Run the deterministic best-practices benchmark on a repo or the whole workspace."""
    import os
    import subprocess
    from pathlib import Path

    from citadel import paths as vp
    from citadel.commands._runner import _tools_dir

    ws_arg = getattr(args, "workspace_path", None)
    ws = Path(ws_arg).expanduser().resolve() if ws_arg else vp.workspace_root()
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    tool = _tools_dir() / "best_practices_benchmark.py"
    if not tool.exists():
        print(f"ERROR: tool not found: {tool}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(tool)]
    if getattr(args, "repo", None):
        cmd += ["--repo", args.repo]
    else:
        cmd += ["--workspace"]
    return subprocess.run(cmd, env=env).returncode


def _cmd_index(args: argparse.Namespace) -> int:
    from citadel.commands.index import run
    return run(getattr(args, "workspace", None))


def _cmd_mine(args: argparse.Namespace) -> int:
    from citadel.commands.mine import run
    return run(getattr(args, "workspace", None), branch=args.branch)


def _cmd_workers(args: argparse.Namespace) -> int:
    from citadel.commands.workers import run
    return run(
        getattr(args, "workspace", None),
        watch=getattr(args, "watch", False),
        interval=getattr(args, "interval", 1.5),
        as_json=getattr(args, "as_json", False),
    )


def _cmd_brain(args: argparse.Namespace) -> int:
    """Rebuild the brain search index."""
    import os
    import subprocess
    from pathlib import Path

    from citadel import paths as vp
    from citadel.commands._runner import _tools_dir

    ws_arg = getattr(args, "workspace", None)
    ws = Path(ws_arg).expanduser().resolve() if ws_arg else vp.workspace_root()
    os.environ["CITADEL_WORKSPACE"] = str(ws)

    tool = _tools_dir() / "build_brain_search_index.py"
    if not tool.exists():
        print(f"ERROR: tool not found: {tool}", file=sys.stderr)
        return 1

    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    result = subprocess.run([sys.executable, str(tool)], env=env)
    return result.returncode


def _cmd_companies(args: argparse.Namespace) -> int:
    """List the legion's companies, or run the principle scorecard on a file.

    `citadel companies --list` (or with no file) prints the discovered company roster
    via the Legion façade. `citadel companies <file>` runs the existing scorecard.
    """
    import os
    from pathlib import Path

    from citadel import paths as vp

    ws_arg = getattr(args, "workspace", None)
    ws = Path(ws_arg).expanduser().resolve() if ws_arg else vp.workspace_root()
    os.environ["CITADEL_WORKSPACE"] = str(ws)

    if getattr(args, "list", False) or not getattr(args, "file", None):
        return _print_company_roster()

    return _run_company_scorecard(args, ws)


def _print_company_roster() -> int:
    """Print the corporate legion's companies (workspace repos)."""
    from citadel.services.corporate import Legion

    legion = Legion.discover()
    companies = legion.companies()
    git_count = sum(1 for c in companies if c.is_git)
    print(f"LEGION — {len(companies)} companies ({git_count} git repos):")
    for c in companies:
        flag = "git " if c.is_git else "    "
        print(f"  [{flag}] {c.repo_id:<32} py_root={c.python_root}")
    return 0


def _cmd_replicate(args: argparse.Namespace) -> int:
    """Decide whether a task is a proven repeat; optionally execute it zero-token."""
    import json
    import os
    from pathlib import Path

    from citadel import paths as vp
    from citadel.services.reuse import ReplicationExecutor, ReuseDecider

    ws_arg = getattr(args, "workspace", None)
    ws = Path(ws_arg).expanduser().resolve() if ws_arg else vp.workspace_root()
    os.environ["CITADEL_WORKSPACE"] = str(ws)

    decision = ReuseDecider().decide(args.query)
    print(f"query      : {decision.query}")
    print(f"confidence : {decision.confidence}")
    print(f"template   : {decision.template_id or '(none matched)'}")
    print(f"can_execute: {decision.can_execute}")
    if decision.files:
        print(f"files      : {', '.join(decision.files[:6])}")

    if not args.execute:
        if decision.can_execute:
            print("→ zero-token replication available. Re-run with --execute --targets <json>.")
        else:
            print("→ no proven fast path; route to the model / distributed scheduler.")
        return 0

    if not decision.can_execute:
        print("ERROR: --execute requested but no proven template matched.", file=sys.stderr)
        return 1
    if not args.targets:
        print("ERROR: --execute requires --targets <json array of param dicts>.", file=sys.stderr)
        return 1

    raw = args.targets
    if raw.startswith("@"):
        raw = Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    try:
        targets = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: --targets is not valid JSON: {exc}", file=sys.stderr)
        return 1

    assert decision.template_id is not None
    result = ReplicationExecutor(ws).execute(decision.template_id, targets)
    print(f"applied={result.applied} succeeded={result.succeeded} failed={result.failed}")
    return 0 if result.ok else 1


def _run_company_scorecard(args: argparse.Namespace, ws) -> int:
    """Run the LEGION principle scorecard on a target file (legion_companies.py)."""
    import os
    import subprocess

    from citadel.commands._runner import _tools_dir

    tool = _tools_dir() / "legion_companies.py"
    if not tool.exists():
        print(f"ERROR: tool not found: {tool}", file=sys.stderr)
        return 1

    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    cmd = [sys.executable, str(tool), "--file", args.file]
    if getattr(args, "task_id", None):
        cmd += ["--task-id", args.task_id]
    result = subprocess.run(cmd, env=env)
    return result.returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="citadel",
        description="The Sovereign Imperia Citadel — workspace-agnostic graph-brain for Claude Code.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_init = sub.add_parser("init", help="Initialize a workspace (full auto-learn)")
    p_init.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Path to the target workspace / git repo (default: current directory)",
    )
    p_init.add_argument("--branch", default=None, help="Git branch to mine (default: auto-detect)")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing .claude/ files")
    p_init.set_defaults(func=_cmd_init)

    def _add_up_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--workspace", default=None,
                       help="Workspace path (default: auto-detect the citadel-home home)")
        p.add_argument("--dry-run", action="store_true", dest="dry_run",
                       help="Print what would be done without starting daemons or launching Claude")
        p.add_argument("--no-ui", action="store_true", dest="no_ui",
                       help="Skip starting the Citadel UI server")
        p.add_argument("--restart", action="store_true", dest="restart",
                       help="Stop existing Citadel processes before starting fresh (clean restart)")
        p.add_argument("--effort", default=None,
                       help="Explicit CLAUDE_CODE_EFFORT_LEVEL for this session (e.g. auto, low, "
                            "medium, high, xhigh, ultracode). Default: auto (Citadel self-manages).")

    # Primary activation flow: `citadel up` / `citadel down`.
    p_up = sub.add_parser("up", help="Bring the Citadel online — boot brain + daemons + UI, launch Claude Code")
    _add_up_options(p_up)
    p_up.set_defaults(func=_cmd_up)

    p_down = sub.add_parser("down", help="Take the Citadel offline — stop all daemons + UI server, clean pidfiles")
    p_down.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect the citadel-home home)")
    p_down.set_defaults(func=_cmd_down)

    p_run = sub.add_parser(
        "run",
        help="Run a task across N parallel worker processes, each pinned to a company with its own model+effort",
    )
    p_run.add_argument("task", nargs="+", help="Task description")
    p_run.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_run.add_argument(
        "--max-workers", type=int, default=4, dest="max_workers",
        help="Upper bound on concurrent workers (also capped by company count, "
             "CPU headroom, and the efficiency-gate agent-count cap)",
    )
    p_run.add_argument(
        "--company", default=None,
        help="Restrict to companies whose repo_id contains this substring (default: all discovered)",
    )
    p_run.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Print the worker/model/effort plan and governance gate result; spawn nothing",
    )
    p_run.add_argument("--no-ui", action="store_true", dest="no_ui", help="Skip the second-pane dashboard hint")
    p_run.add_argument(
        "--autonomous", action="store_true", dest="autonomous",
        help="Full unattended editing per worker (bypassPermissions). Default: least-privilege dontAsk",
    )
    p_run.add_argument(
        "--smoke", action="store_true", dest="smoke",
        help="Read-only single-worker live check of the spawn/parse/ledger plumbing (no edits, cheap)",
    )
    p_run.add_argument(
        "--no-dashboard", action="store_true", dest="no_dashboard",
        help="Plain scrolling logs instead of the live in-terminal worker table",
    )
    p_run.add_argument(
        "--mode", default="task", choices=["task", "benchmark"], dest="mode",
        help="task (implement) or benchmark (deterministic scoring)",
    )
    p_run.add_argument(
        "--permission-mode", default=None, dest="permission_mode",
        help="Override worker permission mode (default: dontAsk; bypassPermissions with --autonomous)",
    )
    p_run.set_defaults(func=_cmd_legion_run)


    p_bench = sub.add_parser("benchmark", help="Deterministic best-practices score (SOLID/KISS/…/PEP8)")
    p_bench.add_argument("--repo", default=None, help="Score a single repo directory (default: whole workspace)")
    p_bench.add_argument("--workspace", dest="workspace_path", default=None, help="Workspace path (auto-detect)")
    p_bench.set_defaults(func=_cmd_benchmark)

    p_index = sub.add_parser("index", help="Rebuild workspace intelligence indexes")
    p_index.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_index.set_defaults(func=_cmd_index)

    p_mine = sub.add_parser("mine", help="Run git-history miner only")
    p_mine.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_mine.add_argument("--branch", default=None, help="Branch to mine (default: auto-detect)")
    p_mine.set_defaults(func=_cmd_mine)

    p_workers = sub.add_parser("workers", help="Show live daemon + subagent ('worker') status")
    p_workers.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_workers.add_argument("--watch", action="store_true", help="Live-refreshing terminal view")
    p_workers.add_argument("--interval", type=float, default=1.5, help="Refresh interval in seconds (--watch)")
    p_workers.add_argument("--json", dest="as_json", action="store_true", help="Machine-readable output")
    p_workers.set_defaults(func=_cmd_workers)

    p_brain = sub.add_parser("brain", help="Rebuild brain search index")
    p_brain.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_brain.set_defaults(func=_cmd_brain)

    p_rep = sub.add_parser(
        "replicate",
        help="Decide (and optionally execute) zero-token feature replication for a task",
    )
    p_rep.add_argument("query", help="Task description to evaluate for reuse")
    p_rep.add_argument("--execute", action="store_true", help="Apply the matched template")
    p_rep.add_argument("--targets", default=None, help="JSON array of param dicts (or @file.json)")
    p_rep.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_rep.set_defaults(func=_cmd_replicate)

    p_co = sub.add_parser(
        "companies",
        help="List the legion's companies, or run the principle scorecard on a file",
    )
    p_co.add_argument("file", nargs="?", default=None, help="Python file to score (omit to list companies)")
    p_co.add_argument("--list", action="store_true", help="List discovered companies (workspace repos)")
    p_co.add_argument("--workspace", default=None, help="Workspace path (default: auto-detect)")
    p_co.add_argument("--task-id", default=None, help="Optional task ID for scorecard")
    p_co.set_defaults(func=_cmd_companies)

    return parser


def main() -> None:
    # Windows consoles default to a legacy codepage (e.g. cp1252) that cannot encode the
    # arrows/box glyphs used throughout Citadel's output, which would crash on the first such
    # print. Force UTF-8 (replacing anything unmappable) so `citadel` never dies on output.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # already-wrapped or non-reconfigurable stream
            pass

    parser = _build_parser()
    args, unknown = parser.parse_known_args()
    cmd = getattr(args, "command", None)
    # `up` forwards any unrecognized args straight through to Claude Code.
    if cmd != "up" and unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    if cmd == "up":
        sys.exit(_cmd_up(args, unknown))
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
