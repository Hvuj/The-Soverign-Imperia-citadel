"""cli.py — `citadel` command-line entry point.

Primary flow:
  init          Set up a workspace once (scaffold + full auto-learn)
  up            Bring the Citadel online — boot brain + daemons + UI, launch the session
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
        local_first=getattr(args, "local_first", False),
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


def _cmd_do(args: argparse.Namespace) -> int:
    """Run a task The Sovereign way — free local Ollama first, escalate to the cloud only if needed.

    With `--file`, The Sovereign edits that file locally, verifies the change in a sandbox (via `--verify`,
    or a Python syntax check for .py), and only writes it back — and only calls it done — when it verifies.
    """
    import os
    import shlex
    import sys
    from pathlib import Path

    from citadel.services.execute import LocalConfidence, SovereignRunner

    ws = Path(args.workspace).resolve() if getattr(args, "workspace", None) else Path.cwd()
    task = " ".join(args.task).strip()
    model = getattr(args, "model", None) or os.environ.get("CITADEL_OLLAMA_MODEL")
    confidence = LocalConfidence(path=ws / ".claude" / "state" / "local-confidence.jsonl")
    targets = getattr(args, "file", None)

    if targets:
        from citadel.services.execute import (
            Blueprint,
            CloudClaudeExecutor,
            LocalCodingExecutor,
            OllamaEngine,
            sovereign_run,
            verify_by_command,
        )
        py_targets = [t for t in targets if t.endswith(".py")]
        if getattr(args, "verify", None):
            verify = verify_by_command(shlex.split(args.verify))
        elif py_targets:
            check = "import ast;" + "".join(f"ast.parse(open({t!r}).read());" for t in py_targets)
            verify = verify_by_command([sys.executable, "-c", check])
        else:
            verify = None
        local = LocalCodingExecutor(
            OllamaEngine(), ws, verify=verify or (lambda _sb: (True, "no verifier")), model=model or "",
        )
        blueprint = Blueprint(task_id="do", instruction=task, allowed_files=list(targets), assigned_tier="cheap")
        result = sovereign_run(
            blueprint, "simple_function", local=local, cloud=CloudClaudeExecutor(), confidence=confidence,
        )
    else:
        result = SovereignRunner(confidence=confidence, model_override=model).run(task)

    print(f"◆ The Sovereign — {result.status}")
    if result.output:
        print(result.output)
    if result.status != "pass" and result.reason:
        print(f"  ({result.reason})")
    return 0 if result.status == "pass" else 1


def _cmd_ask(args: argparse.Namespace) -> int:
    """Answer a question grounded in the local index — retrieval + answer are 0 tokens (local model).

    A repeat question is served from the content-hash-gated cache (free) only while every cited file is
    unchanged; edit a cited file and the next ask re-answers with the new content.
    """
    import os
    from pathlib import Path

    from citadel.services.execute.local.engine import OllamaEngine, RunSpec
    from citadel.services.retrieval.answer_cache import AnswerCache
    from citadel.services.retrieval.ask import answer_question
    from citadel.services.retrieval.service import RetrievalService

    ws = Path(args.workspace).resolve() if getattr(args, "workspace", None) else Path.cwd()
    question = " ".join(args.question).strip()
    gen_model = getattr(args, "model", None) or os.environ.get("CITADEL_OLLAMA_MODEL", "qwen2.5-coder:7b")

    engine = OllamaEngine()
    service = RetrievalService.for_workspace(ws)
    cache = AnswerCache(path=ws / ".claude" / "state" / "retrieval" / "answer-cache.json")

    def generate(prompt: str) -> str:
        return engine.generate(prompt, RunSpec(model=gen_model, n_gpu_layers=-1, n_ctx=8192, max_tokens=768))

    result = answer_question(question, service=service, generate=generate, workspace=ws, cache=cache)
    tag = "cached · 0 tokens" if result["cached"] else ("grounded" if result["grounded"] else "ungrounded")
    print(f"◆ The Sovereign — {tag}")
    print(result["answer"])
    if result["citations"]:
        print("\nsources:")
        for c in dict.fromkeys(f"{c['path']}" for c in result["citations"]):
            print(f"  - {c}")
    return 0


def _cmd_optimize(args: argparse.Namespace) -> int:
    """Optimize a file locally, verified before trust. Your code is propose-only (prints a diff) unless
    --apply; the Citadel's own code auto-applies behind its verifier. Zero cloud tokens."""
    import os
    import shlex
    import sys
    from pathlib import Path

    from citadel.services.execute.coding import verify_by_command
    from citadel.services.execute.local.engine import OllamaEngine, RunSpec
    from citadel.services.execute.optimizer import CodeOptimizer, is_system_path, update_optimizer_stats
    from citadel.services.execute.verdict import VerdictLedger

    ws = Path(args.workspace).resolve() if getattr(args, "workspace", None) else Path.cwd()
    rel = args.path.replace("\\", "/")
    model = getattr(args, "model", None) or os.environ.get("CITADEL_OLLAMA_MODEL", "qwen2.5-coder:7b")
    verify = verify_by_command(shlex.split(args.verify)) if getattr(args, "verify", None) else None
    ledger = VerdictLedger(ws / ".citadel" / "state" / "verdicts")
    optimizer = CodeOptimizer(
        OllamaEngine(), ws, verify=verify, ledger=ledger, model=model,
        run_spec=RunSpec(model=model, n_gpu_layers=-1, n_ctx=8192, max_tokens=2048),
    )
    auto = True if getattr(args, "apply", False) else (True if is_system_path(rel) else False)
    result = optimizer.optimize(rel, auto_apply=auto)
    stats = update_optimizer_stats(ws / ".claude" / "state" / "retrieval" / "optimizer-stats.json", result)

    if result.applied:
        print(f"◆ The Sovereign — optimized + applied {rel} (verified)")
        print(result.diff)
    elif result.proposed:
        print(f"◆ The Sovereign — proposed optimization for {rel} (verified in sandbox; not applied)")
        print(result.diff)
        print("  run again with --apply to accept.")
    else:
        print(f"◆ The Sovereign — no verified optimization for {rel} ({result.status}: {result.detail})")
    print(f"  [optimizer: {stats['applied']} applied · {stats['proposed']} proposed · {stats['rejected']} rejected]")
    return 0 if result.status == "pass" else 1


def _cmd_army(args: argparse.Namespace) -> int:
    """Decompose a goal into atomic tasks and run them on a concurrent, lease-governed local worker pool.
    The small tasks execute free on the local tier — zero cloud tokens for the ones a small model nails."""
    import os
    import uuid
    from pathlib import Path

    from citadel.services.army import JobQueue, TaskForge, WorkerPool
    from citadel.services.execute import Blueprint, LocalExecutor, OllamaEngine

    ws = Path(args.workspace).resolve() if getattr(args, "workspace", None) else Path.cwd()
    goal = " ".join(args.goal).strip()
    model = getattr(args, "model", None) or os.environ.get("CITADEL_OLLAMA_MODEL", "qwen2.5-coder:7b")
    tasks = TaskForge().forge(goal)
    queue = JobQueue(f"army-{uuid.uuid4().hex[:8]}")
    for t in tasks:
        queue.enqueue({"id": t.id, "instruction": t.instruction, "tier": t.tier})

    executor = LocalExecutor(engine=OllamaEngine(), model_override=model)

    def run_fn(task: dict) -> tuple[str, str]:
        result = executor.execute(Blueprint(task_id=task["id"], instruction=task["instruction"], assigned_tier="cheap"))
        return result.status, (result.output or "")

    pool = WorkerPool(queue, run_fn=run_fn, concurrency=int(getattr(args, "concurrency", 0) or 4))
    print(f"◆ The Sovereign — forged {len(tasks)} atomic task(s); dispatching to the army")
    outcomes = pool.run(now=0.0)
    free = sum(1 for o in outcomes if o.tier == "local")
    passed = sum(1 for o in outcomes if o.status == "pass")
    for o in outcomes:
        print(f"  [{o.status}] t={o.task_id} ({o.tier}) — {o.output[:80].splitlines()[0] if o.output else ''}")
    print(f"  {passed}/{len(outcomes)} passed · {free} ran free on the local tier (0 cloud tokens)")
    return 0 if passed == len(outcomes) else 1


def _cmd_setup(args: argparse.Namespace) -> int:
    from citadel.commands.setup import run_setup
    return run_setup(args)


def _cmd_doctor(args: argparse.Namespace) -> int:
    from citadel.commands.setup import run_doctor
    return run_doctor(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="citadel",
        description="The Sovereign Imperia Citadel — workspace-agnostic graph-brain orchestration for your coding sessions.",
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
                       help="Print what would be done without starting daemons or launching the session")
        p.add_argument("--no-ui", action="store_true", dest="no_ui",
                       help="Skip starting the Citadel UI server")
        p.add_argument("--restart", action="store_true", dest="restart",
                       help="Stop existing Citadel processes before starting fresh (clean restart)")
        p.add_argument("--effort", default=None,
                       help="Explicit CLAUDE_CODE_EFFORT_LEVEL for this session (e.g. auto, low, "
                            "medium, high, xhigh, ultracode). Default: auto (Citadel self-manages).")

    # Primary activation flow: `citadel up` / `citadel down`.
    p_up = sub.add_parser("up", help="Bring the Citadel online — boot brain + daemons + UI, launch the session")
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
    p_run.add_argument(
        "--local-first", action="store_true", dest="local_first",
        help="Try each slice free on the local tier first; record attempts (needs a verifier to drop cloud workers)",
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

    p_do = sub.add_parser(
        "do",
        help="Run a task The Sovereign way — free local Ollama first, escalate to the cloud only if needed",
    )
    p_do.add_argument("task", nargs="+", help="What you want done (a question, a check, a small function, ...)")
    p_do.add_argument("--workspace", default=None, help="Workspace path (default: current directory)")
    p_do.add_argument("--model", default=None, help="Ollama model tag for the local tier (or set CITADEL_OLLAMA_MODEL)")
    p_do.add_argument("--file", action="append", default=None,
                      help="Edit this file locally, verified in a sandbox before write-back (repeatable)")
    p_do.add_argument("--verify", default=None, help="Shell command that must exit 0 to accept the local change")
    p_do.set_defaults(func=_cmd_do)

    p_ask = sub.add_parser(
        "ask",
        help="Answer a question grounded in the local index — retrieval + answer cost 0 model tokens",
    )
    p_ask.add_argument("question", nargs="+", help="The question to answer from your codebase")
    p_ask.add_argument("--workspace", default=None, help="Workspace path (default: current directory)")
    p_ask.add_argument("--model", default=None, help="Ollama model for the answer (or set CITADEL_OLLAMA_MODEL)")
    p_ask.set_defaults(func=_cmd_ask)

    p_optimize = sub.add_parser(
        "optimize",
        help="Optimize a file locally, verified before trust — your code is propose-only unless --apply",
    )
    p_optimize.add_argument("path", help="File to optimize (relative to the workspace)")
    p_optimize.add_argument("--workspace", default=None, help="Workspace path (default: current directory)")
    p_optimize.add_argument("--model", default=None, help="Ollama model (or set CITADEL_OLLAMA_MODEL)")
    p_optimize.add_argument("--apply", action="store_true", help="Apply the verified change (default: propose a diff)")
    p_optimize.add_argument("--verify", default=None,
                            help="Shell command that must exit 0 to accept the change (e.g. 'pytest -q')")
    p_optimize.set_defaults(func=_cmd_optimize)

    p_army = sub.add_parser(
        "army",
        help="Decompose a goal into atomic tasks and run them on a concurrent, lease-governed local pool",
    )
    p_army.add_argument("goal", nargs="+", help="The goal to decompose and execute")
    p_army.add_argument("--workspace", default=None, help="Workspace path (default: current directory)")
    p_army.add_argument("--model", default=None, help="Ollama model (or set CITADEL_OLLAMA_MODEL)")
    p_army.add_argument("--concurrency", type=int, default=4, help="Max concurrent workers (VRAM-bounded)")
    p_army.set_defaults(func=_cmd_army)

    p_setup = sub.add_parser(
        "setup",
        help="Auto-install everything The Sovereign needs (Ollama + local model + Python extras)",
    )
    p_setup.add_argument("--model", default=None, help="Local model to pull (default: qwen2.5-coder:7b)")
    p_setup.add_argument("--with-ml", action="store_true", dest="with_ml",
                         help="Also best-effort install llama-cpp-python (needs a compiler/wheel)")
    p_setup.add_argument("--workspace", default=None, help="Workspace path (default: current directory)")
    p_setup.add_argument("--redis-url", dest="redis_url", default=None,
                         help="Point the retrieval layer at this Redis (writes .citadel/config.toml [redis])")
    p_setup.add_argument("--no-redis", dest="no_redis", action="store_true",
                         help="Disable Redis; use the pure-Python on-disk vector store")
    p_setup.add_argument("--mcp", choices=["native", "compose"], default=None,
                         help="Write .mcp.json for the native (stdio) or compose (HTTP + Docker) MCP stack")
    p_setup.set_defaults(func=_cmd_setup)

    p_doctor = sub.add_parser("doctor", help="Report what is installed / missing / how to fix")
    p_doctor.add_argument("--model", default=None, help="Local model to check for (default: qwen2.5-coder:7b)")
    p_doctor.add_argument("--workspace", default=None, help="Workspace to check placement for (default: cwd)")
    p_doctor.add_argument("--repair", action="store_true", help="Quarantine a squatting .claude file + verify the dir")
    p_doctor.set_defaults(func=_cmd_doctor)

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
