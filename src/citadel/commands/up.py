"""commands/up.py — `citadel up`

Replaces .claude/scripts/claude-start-smart.sh. Brings up the full Citadel
brain (daemons, indexes, lint, health, UI) then launches Claude Code.

Fully self-contained: all tools are resolved from the installed sovereign-imperia-citadel
package, so this command works in ANY workspace after `citadel init`.
"""

import json
import os
import re
import shutil
import socket
import sys
import time
from pathlib import Path

from citadel._terminal import reset_terminal_input_modes
from citadel.commands import _daemons
from citadel.commands._runner import (
    _daemon_path,
    daemon_alive,
    run_tool,
    start_daemon,
)
from citadel.commands._theme import print_up_banner
from citadel.paths import is_unsafe_placement, resolve_home


def _ensure_workspace_trusted(ws: Path) -> None:
    """Prepare *ws* in ~/.claude.json so Claude Code launches cleanly and unattended.

    Sets two things in the project's ~/.claude.json entry (the real file Claude Code
    reads these from — NOT the symlinked .claude/settings.local.json):

    1. ``hasTrustDialogAccepted = true`` — otherwise Claude Code prints
       "Ignoring N permissions.allow entries … this workspace has not been trusted"
       and drops every allow-rule + additionalDirectory the scaffold installed, because
       an unattended `citadel up` launch never gets to click the trust dialog.

    2. ``enabledMcpjsonServers`` ← this workspace's own .mcp.json servers — otherwise
       Claude Code prompts "New MCP server found … use it?" every startup and then fails
       to persist the answer with "one or more of your MCP server choices could not be
       saved (check permissions on .claude/settings.local.json)": its atomic save can't
       write through the .claude → .citadel/.claude symlink. Pre-enabling here means it
       never prompts and never needs that write. Only the workspace's OWN local servers
       are enabled (not a blanket enableAllProjectMcpServers).

    Best-effort: never raises — a malformed/unwritable ~/.claude.json must not block launch.
    """
    try:
        cfg_path = Path.home() / ".claude.json"
        data: dict = {}
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:  # never block launch: cp1252/UnicodeDecodeError, JSON errors, IO — all tolerated
                return
        entry = data.setdefault("projects", {}).setdefault(str(ws), {})

        changed = False
        if entry.get("hasTrustDialogAccepted") is not True:
            entry["hasTrustDialogAccepted"] = True
            entry.setdefault("hasCompletedProjectOnboarding", True)
            changed = True

        mcp_path = ws / ".mcp.json"
        if mcp_path.exists():
            try:
                servers = list(json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers", {}))
            except Exception:
                servers = []
            if servers:
                enabled = list(entry.get("enabledMcpjsonServers") or [])
                merged = sorted(set(enabled) | set(servers))
                if merged != enabled:
                    entry["enabledMcpjsonServers"] = merged
                    changed = True

        if not changed:
            return
        tmp = cfg_path.with_suffix(".json.citadel-tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(cfg_path)
        print(f"[trust] workspace trusted + MCP servers pre-approved in {cfg_path.name}")
    except OSError:
        pass


def _configure_effort(
    ws: Path, model: str, perm: str, effort_explicit: bool, resolved_effort: str, *, dry_run: bool = False
) -> None:
    """Reconcile the session's starting effort level against Claude Code's lock.

    Claude Code treats a present `CLAUDE_CODE_EFFORT_LEVEL` env var as a hard lock:
    once set, in-session `/effort <level>` is rejected outright regardless of the
    env var's value ("CLAUDE_CODE_EFFORT_LEVEL=auto overrides this session"). It does
    NOT apply the same lock to the `effortLevel` field in settings.json/settings.local.json
    — that field seeds the starting default and is still overridable by `/effort`.

    So: for the plan-mode + latest-Opus combo — and only when the resolved effort is
    the non-explicit "auto" default — seed "auto" via settings.local.json instead of
    the env var, so `/effort` keeps working in-session. Every other case (an explicit
    `--effort`/`CITADEL_EFFORT_LEVEL` choice, or a non-plan or non-Opus launch) keeps the
    env var pin unchanged, since those should not be user-overridable mid-session.

    `dry_run` skips the settings.local.json write (no filesystem mutation on a dry run)
    but still reflects the resolved env-var state so `_print_dry_run_claude_cmd` is accurate.
    """
    is_plan_opus_combo = perm == "plan" and model.startswith("opus")
    if is_plan_opus_combo and not effort_explicit:
        os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
        if not dry_run:
            _seed_effort_level_setting(ws, resolved_effort)
        print(f"[effort] {resolved_effort} (default) — plan+Opus session, /effort may override")
    else:
        os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = resolved_effort


def _seed_effort_level_setting(ws: Path, level: str) -> None:
    """Best-effort read-modify-write of `effortLevel` into settings.local.json.

    Writes straight to the real (non-symlinked) path — on a scaffolded workspace
    `.claude` is a symlink to `.citadel/.claude`, and Claude Code's own atomic save is
    documented (see `_ensure_workspace_trusted`) to have trouble writing through that
    symlink. We sidestep the same class of problem by never routing our write through
    the `.claude` symlink. Never raises: a malformed/unwritable settings file must not
    block launch, and the harness's own default effort still applies if this no-ops.
    """
    try:
        settings_path = ws / ".citadel" / ".claude" / "settings.local.json"
        if not settings_path.exists():
            settings_path = ws / ".claude" / "settings.local.json"
        if not settings_path.exists():
            return
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return
        if not isinstance(data, dict):
            return
        if data.get("effortLevel") == level:
            return
        data["effortLevel"] = level
        tmp = settings_path.with_suffix(".json.citadel-tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(settings_path)
    except OSError:
        pass


def _start_incremental_brain_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="incremental_brain_daemon.py",
        ws=ws,
        daemon_args=["--watch"],
        pidfile_rel=".claude/state/incremental-brain-daemon.pid",
        out_rel=".claude/state/incremental-brain-daemon.out.log",
        err_rel=".claude/state/incremental-brain-daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[1/11] incremental brain daemon: {status}")


def _start_workspace_intelligence_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="workspace_intelligence_daemon.py",
        ws=ws,
        daemon_args=["--quiet"],
        pidfile_rel=".claude/state/workspace-intelligence/daemon.pid",
        out_rel=".claude/state/workspace-intelligence/daemon.out.log",
        err_rel=".claude/state/workspace-intelligence/daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[2/11] workspace intelligence daemon: {status}")


def _start_outcome_miner_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="outcome_miner_daemon.py",
        ws=ws,
        daemon_args=["--watch"],
        pidfile_rel=".claude/state/outcome-miner-daemon.pid",
        out_rel=".claude/state/outcome-miner-daemon-stdout.log",
        err_rel=".claude/state/outcome-miner-daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[3/11] outcome miner daemon: {status}")


def _start_git_history_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="git_history_daemon.py",
        ws=ws,
        daemon_args=["--watch", "--quiet"],
        pidfile_rel=".claude/state/git-history-daemon.pid",
        out_rel=".claude/state/git-history-daemon.out.log",
        err_rel=".claude/state/git-history-daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[3b/11] git-history daemon: {status}")


def _start_ram_cache_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="ram_cache_daemon.py",
        ws=ws,
        daemon_args=["--watch", "--warm", "--quiet"],
        pidfile_rel=".claude/state/ram-cache-daemon.pid",
        out_rel=".claude/state/ram-cache-daemon.out.log",
        err_rel=".claude/state/ram-cache-daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[3c/11] RAM cache daemon: {status}")


def _start_bug_record_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="bug_record_daemon.py",
        ws=ws,
        daemon_args=["--watch", "--quiet"],
        pidfile_rel=".claude/state/bug-record-daemon.pid",
        out_rel=".claude/state/bug-record-daemon.out.log",
        err_rel=".claude/state/bug-record-daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[3d/11] bug-record daemon: {status}")


def _start_zombie_worker_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="zombie_worker_daemon.py",
        ws=ws,
        daemon_args=["--watch"],
        pidfile_rel=".claude/state/zombie-worker-daemon.pid",
        out_rel=".claude/state/zombie-worker-daemon.out.log",
        err_rel=".claude/state/zombie-worker-daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[3e/11] zombie worker daemon: {status}")


def _start_embedder_daemon(ws: Path) -> None:
    pid = start_daemon(
        tool_name="embedder_daemon.py",
        ws=ws,
        daemon_args=["--watch"],
        pidfile_rel=".claude/state/embedder-daemon.pid",
        out_rel=".claude/state/embedder-daemon.out.log",
        err_rel=".claude/state/embedder-daemon.err.log",
    )
    status = f"pid={pid}" if pid else "FAILED (optional)"
    print(f"[3f/11] embedder z-worker: {status}")


def _run_self_heal(ws: Path) -> None:
    ok = run_tool("legion_self_heal.py", ws, ["--fix", "--quiet"])
    print(f"[self-heal] init self-heal: {'OK' if ok else 'WARN (non-fatal)'}")


def _build_prompt_usage_index(ws: Path) -> None:
    ok = run_tool("prompt_usage_miner.py", ws, ["--mine"])
    print(f"[prompt-usage] learned reuse index: {'OK' if ok else 'WARN'}")


def _run_preflight(ws: Path) -> None:
    ok = run_tool("brain_preflight.py", ws, ["--bootstrap"])
    print(f"[4/11] cold-start preflight: {'OK' if ok else 'WARN (non-fatal)'}")


def _build_brain_search_index(ws: Path, step: int) -> None:
    ok = run_tool("build_brain_search_index.py", ws, ["--quiet"])
    print(f"[{step}/14] brain search index: {'OK' if ok else 'WARN'}")


def _build_implementation_cache_index(ws: Path) -> None:
    ok = run_tool("build_implementation_cache_index.py", ws, ["--quiet"])
    print(f"[6/14] implementation cache index: {'OK' if ok else 'WARN'}")


def _build_workspace_intelligence_index(ws: Path) -> None:
    ok = run_tool("build_workspace_intelligence_index.py", ws, ["--quiet", "--skip-if-locked"])
    print(f"[7/14] workspace intelligence index: {'OK' if ok else 'WARN'}")


def _build_repo_style_profiles(ws: Path) -> None:
    ok = run_tool("repo_style_profiler.py", ws, ["--quiet"])
    print(f"[style-profiler] per-repo Python-version profiles: {'OK' if ok else 'WARN'}")


def _run_git_history_sweep(ws: Path) -> None:
    """Mine git history synchronously (bounded, `--sweep`) before commit/graph builds run.

    `_start_git_history_daemon` above only starts the continuous `--watch` miner in the
    background — it hasn't mined anything by the time this function runs. Without this
    synchronous sweep, `_build_commit_index` and `_build_sharded_brain_graph` would run
    against zero commit nodes on every fresh boot, so per-repo shards would carry no git
    history until the background daemon happened to catch up on its own schedule.
    """
    ok = run_tool("git_history_daemon.py", ws, ["--sweep", "--quiet"])
    print(f"[7b/14] git history sweep: {'OK' if ok else 'WARN'}")


def _build_logic_nodes(ws: Path) -> None:
    ok = run_tool("build_logic_nodes.py", ws, ["--quiet"])
    print(f"[7c/14] line-level logic nodes: {'OK' if ok else 'WARN'}")


def _build_cross_repo_edges(ws: Path) -> None:
    ok = run_tool("build_cross_repo_edges.py", ws, ["--quiet"])
    print(f"[7d/14] cross-repo import edges: {'OK' if ok else 'WARN'}")


def _build_commit_index(ws: Path) -> None:
    ok = run_tool("build_commit_index.py", ws, ["--quiet"])
    print(f"[8/14] commit knowledge index: {'OK' if ok else 'WARN'}")


def _build_brain_graph(ws: Path) -> None:
    ok = run_tool("build_brain_graph.py", ws)
    print(f"[9/14] brain graph: {'OK' if ok else 'WARN'}")


def _build_sharded_brain_graph(ws: Path) -> None:
    ok = run_tool("build_sharded_brain_graph.py", ws, ["--build"])
    print(f"[9b/14] sharded per-repo graph: {'OK' if ok else 'WARN'}")


def _run_provider_detection(ws: Path) -> None:
    ok = run_tool("ai_provider_detection.py", ws)
    print(f"[10/14] AI provider detection: {'OK' if ok else 'WARN'}")


def _run_mandatory_lint(ws: Path) -> None:
    tools = [
        "mandatory_auto_lint.py",
        "grounding_lint.py",
        "output_schema_lint.py",
    ]
    results = []
    for t in tools:
        ok = run_tool(t, ws)
        results.append("✓" if ok else "✗")
    summary = " ".join(results)
    print(f"[11/14] mandatory lint [{summary}]")


def _daemon_status(ws: Path) -> None:
    brain_alive = daemon_alive(".claude/state/incremental-brain-daemon.pid", ws)
    wi_alive = daemon_alive(".claude/state/workspace-intelligence/daemon.pid", ws)
    om_alive = daemon_alive(".claude/state/outcome-miner-daemon.pid", ws)
    gh_alive = daemon_alive(".claude/state/git-history-daemon.pid", ws)

    def sym(b: bool) -> str:
        return "●" if b else "○"

    print(
        f"[12/14] daemon status: brain={sym(brain_alive)} wi={sym(wi_alive)} miner={sym(om_alive)} git={sym(gh_alive)}"
    )


def _wait_for_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Poll until the TCP port accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _ui_port() -> int:
    return int(os.environ.get("CITADEL_UI_PORT", "8765"))


def _find_claude_bin() -> str | None:
    """Locate Claude Code on PATH or in its standard Windows app bundles."""
    override = os.environ.get("CLAUDE_BIN")
    if override:
        found = shutil.which(override)
        if found:
            return found
        if Path(override).is_file():
            return override

    found = shutil.which("claude")
    if found or sys.platform != "win32":
        return found

    home = Path(os.environ.get("USERPROFILE") or Path.home())
    candidates = [
        home / ".local" / "bin" / "claude.exe",
        home / ".claude" / "local" / "claude.exe",
        home / ".claude" / "bin" / "claude.exe",
    ]
    app_data = os.environ.get("APPDATA")
    if app_data:
        candidates.append(Path(app_data) / "npm" / "claude.cmd")
    candidates.extend(home.glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe"))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.extend(
            Path(local_app_data).glob("Packages/Claude_*/LocalCache/Roaming/Claude/claude-code/*/claude.exe")
        )

    existing = [candidate for candidate in candidates if candidate.is_file()]
    if not existing:
        return None

    def version_key(candidate: Path) -> tuple[int, int, int]:
        matches = re.findall(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", str(candidate))
        return tuple(map(int, matches[-1])) if matches else (0, 0, 0)

    return str(max(existing, key=version_key))


def _start_ui_server(ws: Path) -> str | None:
    """Start the UI server. Returns the ready URL, or None if it failed."""
    pid = start_daemon(
        tool_name="citadel_ui_server.py",
        ws=ws,
        daemon_args=[],
        pidfile_rel=".claude/state/citadel-ui-server.pid",
        out_rel=".claude/state/citadel-ui-server.out.log",
        err_rel=".claude/state/citadel-ui-server.err.log",
        check_tool=False,
    )
    port = _ui_port()
    url = f"http://localhost:{port}/brain/graph.html"
    if pid and _wait_for_port("127.0.0.1", port, timeout=3.0):
        status = f"pid={pid} url={url}"
    elif pid:
        status = f"pid={pid} NOT READY (optional; continuing)"
        url = None
    else:
        status = "FAILED (optional)"
        url = None
    print(f"[13/14] Citadel UI server: {status}")
    return url


def _run_health(ws: Path) -> str:
    """Run the health check with a settle loop.

    Retries up to 3 times (~0.7 s apart) so transient warm-up yellows clear
    before the banner is printed, giving a true steady-state reading.
    When not green, names the offending checks so the output is self-explaining.
    """
    out_path = ws / "docs" / "brain" / "system-status.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    health = "unknown"
    checks: list[dict] = []
    for attempt in range(3):
        if attempt:
            time.sleep(0.7)
        ok = run_tool(
            "citadel_system_health.py",
            ws,
            ["--out", str(out_path), "--quiet"],
        )
        if ok and out_path.exists():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
                health = data.get("overall_status", "unknown")
                checks = data.get("checks", [])
            except Exception:
                pass
        if health == "green":
            break

    if health == "green":
        print(f"[14/14] Citadel health: {health}")
    else:
        non_green = sorted(
            (c for c in checks if c.get("status") != "green"),
            key=lambda c: 0 if c.get("status") == "red" else 1,
        )[:3]
        if non_green:
            detail = ", ".join(f"{c['name']}: {c.get('details', c.get('status', '?'))}" for c in non_green)
            print(f"[14/14] Citadel health: {health} ({detail})")
        else:
            print(f"[14/14] Citadel health: {health}")
    return health


def run(
    _target: str,
    workspace: str | None,
    *,
    dry_run: bool = False,
    no_ui: bool = False,
    restart: bool = False,
    passthrough: list[str] | None = None,
    effort: str | None = None,
) -> int:
    """Run `citadel up`. Returns exit code (0 = success)."""

    # abspath, not .resolve()/realpath: the latter walks OneDrive reparse points and can stall (see _runner)
    ws = Path(os.path.abspath(Path(workspace).expanduser())) if workspace else resolve_home()

    if not ws.exists():
        print(f"ERROR: workspace '{ws}' does not exist.", file=sys.stderr)
        return 1

    unsafe = is_unsafe_placement(ws)
    if unsafe:
        print(f"  [warn] workspace {unsafe}. Daemon starts are watchdog-guarded so `up` won't hang, but for "
              "full reliability move the workspace off OneDrive (e.g. C:\\dev\\).")

    if not (ws / ".citadel" / "config.toml").exists() and not (ws / ".claude").exists():
        print("  [hint] workspace not initialized — run `citadel init` first for full brain setup")

    os.environ["CITADEL_WORKSPACE"] = str(ws)
    os.environ.setdefault("CLAUDE_PROJECT_DIR", str(ws))
    # Turn off the Claude Code TUI's mouse tracking at the source: with mouse mode "off" it never
    # emits the SGR reports (ESC[<…M) that leak as text at the shell prompt, and the terminal's own
    # scrollback keeps working. setdefault so a user who wants in-TUI mouse can opt back in (=0).
    os.environ.setdefault("CLAUDE_CODE_DISABLE_MOUSE", "1")
    claude_bin = _find_claude_bin()
    if claude_bin:
        os.environ["CLAUDE_BIN"] = claude_bin

    effort_explicit = bool(
        effort or os.environ.get("CITADEL_EFFORT_LEVEL") or os.environ.get("CLAUDE_CODE_EFFORT_LEVEL")
    )
    resolved_effort = (
        effort or os.environ.get("CITADEL_EFFORT_LEVEL") or os.environ.get("CLAUDE_CODE_EFFORT_LEVEL") or "auto"
    )
    launch_model = os.environ.get("CLAUDE_MODEL", "opusplan")
    launch_perm = os.environ.get("CLAUDE_PERMISSION_MODE", "plan")
    _configure_effort(ws, launch_model, launch_perm, effort_explicit, resolved_effort, dry_run=dry_run)

    if dry_run:
        pass
    else:
        os.chdir(ws)
        # Clear any mouse-tracking mode a prior Claude Code session left on, so moving the
        # mouse during this multi-second launch doesn't flood the shell with SGR reports.
        reset_terminal_input_modes()

    print_up_banner()

    if dry_run:
        print("[dry-run] would start daemons and indexes — skipping")
        _print_dry_run_claude_cmd(passthrough)
        return 0

    if restart:
        from citadel.commands.down import run as _destroy

        print("[restart] stopping existing Citadel processes before fresh start …")
        _destroy(workspace=str(ws))
        print()

    print(f"The Sovereign Imperia Citadel Z — workspace: {ws}\n")

    state_dir = _daemon_path(ws, ".claude/state")
    state_dir.mkdir(parents=True, exist_ok=True)

    _run_self_heal(ws)

    stray = _daemons.find_citadel_daemon_procs()
    if stray:
        for msg in _daemons.kill_procs(stray):
            print(msg)
    print(f"[preflight] cleared {len(stray)} stray Citadel daemon(s)")

    _start_incremental_brain_daemon(ws)
    _start_workspace_intelligence_daemon(ws)
    _start_outcome_miner_daemon(ws)
    _start_git_history_daemon(ws)
    _start_ram_cache_daemon(ws)
    _start_bug_record_daemon(ws)
    _start_zombie_worker_daemon(ws)
    _start_embedder_daemon(ws)
    _run_preflight(ws)
    _build_brain_search_index(ws, step=5)
    _build_implementation_cache_index(ws)
    _build_workspace_intelligence_index(ws)
    _build_repo_style_profiles(ws)
    _build_logic_nodes(ws)
    _build_cross_repo_edges(ws)
    _run_git_history_sweep(ws)
    _build_commit_index(ws)
    _build_prompt_usage_index(ws)
    _build_brain_graph(ws)
    _build_sharded_brain_graph(ws)
    _run_provider_detection(ws)
    _manifest = state_dir / "execution-manifest.json"
    if not _manifest.exists():
        _manifest.parent.mkdir(parents=True, exist_ok=True)
        _manifest.write_text(
            json.dumps(
                {
                    "task_type": "initialization",
                    "selected_workflow": "init_workflow",
                    "required_agents": [],
                    "required_artifacts": [],
                },
                indent=2,
            )
            + "\n"
        )
    _run_mandatory_lint(ws)
    _daemon_status(ws)

    ui_url = None
    if not no_ui:
        ui_url = _start_ui_server(ws)
    else:
        print("[13/14] Citadel UI server: skipped (--no-ui)")

    _run_health(ws)

    _ensure_workspace_trusted(ws)

    if ui_url:
        print()
        print("─" * 52)
        print(f"  Citadel UI  →  {ui_url}")
        print("─" * 52)

    print()

    if not claude_bin:
        print(
            "ERROR: `claude` not found on PATH.\nInstall it from https://claude.ai/code and ensure it is on your PATH.",
            file=sys.stderr,
        )
        return 1

    model = os.environ.get("CLAUDE_MODEL", "opusplan")
    perm = os.environ.get("CLAUDE_PERMISSION_MODE", "plan")
    cmd = [claude_bin, "--model", model, "--permission-mode", perm, "--ide"] + (passthrough or [])
    # Launch Claude Code from *inside* the workspace so it detects this as the project root and sets
    # $CLAUDE_PROJECT_DIR for every hook + the statusLine. Without this the launch cwd stays wherever the
    # user ran `citadel up`, $CLAUDE_PROJECT_DIR is empty, and every `bash "$CLAUDE_PROJECT_DIR/.claude/…"`
    # hook + the 5s statusLine expands to a bogus `/.claude/…` and fails. (settings.json also carries baked
    # absolute paths as a fallback — see init._bake_project_dir.)
    try:
        os.chdir(ws)
    except OSError as exc:
        print(f"  [warn] could not chdir to workspace ({exc}); hooks rely on baked settings.json paths",
              file=sys.stderr)
    print(f"Launching: {' '.join(cmd)}")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(claude_bin, cmd)
    return 1  # pragma: no cover


def _print_dry_run_claude_cmd(passthrough: list[str] | None) -> None:
    model = os.environ.get("CLAUDE_MODEL", "opusplan")
    perm = os.environ.get("CLAUDE_PERMISSION_MODE", "plan")
    effort = os.environ.get("CLAUDE_CODE_EFFORT_LEVEL")
    parts = ["claude", "--model", model, "--permission-mode", perm, "--ide"] + (passthrough or [])
    if effort is None:
        print(
            "[dry-run] CLAUDE_CODE_EFFORT_LEVEL=unset "
            "(user-controlled via settings.local.json effortLevel; /effort may override)"
        )
    else:
        print(f"[dry-run] CLAUDE_CODE_EFFORT_LEVEL={effort}")
    print(f"[dry-run] would exec: {' '.join(parts)}")
