#!/usr/bin/env python3
"""Daemon health check (read-only).

Checks:
  1. Daemon pid alive via incremental_brain_daemon.py --status.
  2. Incremental brain snapshot freshness (< 10 minutes is healthy).
  3. Watch roots configured.
  4. Static assertion: daemon source does not call Claude CLI.
  5. Static assertion: daemon source does not write to production paths.

Never starts or stops any daemon. Exits non-zero with compact findings if unhealthy.
"""
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from _brain_common import ROOT, STATE, load_json

_DAEMON_SCRIPT = ROOT / "tools" / "incremental_brain_daemon.py"
_SNAPSHOT_PATH = STATE / "incremental-brain-snapshot.json"
_PID_PATH = STATE / "incremental-brain-daemon.pid"
_DAEMON_CONFIG_PATH = ROOT / ".claude" / "daemon" / "incremental-brain-config.json"
_WORKSPACE_DISCOVERY_PATH = STATE / "workspace-discovery.json"

_STALE_THRESHOLD_SECONDS = 600

_FORBIDDEN_DAEMON_PATTERNS = [
    (re.compile(r'\bclaude\b.*--model', re.IGNORECASE), "claude --model invocation"),
    (re.compile(r'subprocess.*\bclaude\b', re.IGNORECASE), "subprocess claude call"),
    (re.compile(r'os\.system.*\bclaude\b', re.IGNORECASE), "os.system claude call"),
]


def _discovered_repo_write_patterns() -> list[tuple[re.Pattern, str]]:
    """Workspace-agnostic production-path check: flag a hardcoded write path into any
    DISCOVERED sibling repo (a "company" of the legion), never one specific client
    name. Built from workspace-discovery.json (workspace_discoverer.py output) so it
    adapts to whatever workspace Citadel is pointed at."""
    data = load_json(_WORKSPACE_DISCOVERY_PATH, {})
    patterns: list[tuple[re.Pattern, str]] = []
    for proj in data.get("projects", []):
        rp = proj.get("root_path")
        if not rp:
            continue
        name = Path(rp).name
        patterns.append((
            re.compile(rf'\b{re.escape(name)}/', re.IGNORECASE),
            f"production path write ({name}/)",
        ))
    return patterns


_MIN_WATCHED_ROOTS = {".claude", "docs", "tools"}


def _check_daemon_pid(errors: list[str], warnings: list[str]) -> None:
    """Check if the daemon process is alive using --status."""
    if not _DAEMON_SCRIPT.exists():
        errors.append(f"Daemon script not found: {_DAEMON_SCRIPT.relative_to(ROOT)}")
        return

    if not _PID_PATH.exists():
        warnings.append("WARN: daemon pid file not found — daemon may not be running")
        return

    try:
        pid_text = _PID_PATH.read_text().strip()
        pid = int(pid_text)
    except (ValueError, OSError):
        errors.append(f"Cannot read daemon pid from {_PID_PATH}")
        return

    try:
        import os
        os.kill(pid, 0)
    except ProcessLookupError:
        warnings.append(f"WARN: daemon pid {pid} not alive — may need restart via scripts/incremental-brain-daemon-start.sh")
    except PermissionError:
        pass


def _check_snapshot_freshness(errors: list[str], warnings: list[str]) -> None:
    """Check snapshot exists and file is recent.

    The snapshot is a raw fingerprint dict (path→[mtime_ns, size]), not a timestamped object.
    We use the file's own mtime as the freshness indicator.
    """
    if not _SNAPSHOT_PATH.exists():
        warnings.append("WARN: incremental-brain-snapshot.json not found — daemon has not run yet")
        return

    try:
        snapshot = json.loads(_SNAPSHOT_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        errors.append("Cannot read incremental-brain-snapshot.json")
        return

    if not isinstance(snapshot, dict):
        errors.append("incremental-brain-snapshot.json has unexpected format")
        return

    try:
        file_mtime = _SNAPSHOT_PATH.stat().st_mtime
        now = datetime.now(UTC).timestamp()
        age = now - file_mtime
        if age > _STALE_THRESHOLD_SECONDS:
            warnings.append(
                f"WARN: brain snapshot is {int(age)}s old (>{_STALE_THRESHOLD_SECONDS}s) — "
                "daemon may be idle or stopped"
            )
    except OSError:
        warnings.append("WARN: cannot stat incremental-brain-snapshot.json")


def _check_watched_roots(errors: list[str], warnings: list[str]) -> None:
    """Check daemon config has expected watched roots (prefix match — sub-paths count)."""
    cfg = load_json(_DAEMON_CONFIG_PATH, {})
    roots = cfg.get("watch_roots", [])
    if not roots:
        roots = [".claude", "docs", "tools"]

    def _covered(root: str) -> bool:
        return any(r == root or r.startswith(root + "/") or root.startswith(r + "/") for r in roots)

    missing_roots = {r for r in _MIN_WATCHED_ROOTS if not _covered(r)}
    if missing_roots:
        warnings.append(f"WARN: daemon config missing expected watch roots: {sorted(missing_roots)}")


def _check_daemon_source_safety(errors: list[str], warnings: list[str]) -> None:
    """Static safety check: daemon source must not call Claude or write production paths."""
    if not _DAEMON_SCRIPT.exists():
        return

    try:
        source = _DAEMON_SCRIPT.read_text()
    except OSError:
        errors.append(f"Cannot read daemon source: {_DAEMON_SCRIPT.name}")
        return

    for pattern, description in _FORBIDDEN_DAEMON_PATTERNS + _discovered_repo_write_patterns():
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if pattern.search(line):
                errors.append(
                    f"Daemon source safety violation ({description}) at line {i}: {stripped[:80]}"
                )
                break


def check() -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors are fatal; warnings are advisory."""
    errors: list[str] = []
    warnings: list[str] = []

    _check_daemon_pid(errors, warnings)
    _check_snapshot_freshness(errors, warnings)
    _check_watched_roots(errors, warnings)
    _check_daemon_source_safety(errors, warnings)

    return errors, warnings


def main() -> None:
    errors, warnings = check()
    for w in warnings:
        print(w)
    for e in errors:
        print(f"ERROR: {e}")

    if errors:
        print(f"Status: Fail ({len(errors)} error(s), {len(warnings)} warning(s))")
        sys.exit(1)
    elif warnings:
        print(f"Status: Pass with warnings ({len(warnings)} warning(s))")
    else:
        print("Status: Pass")


if __name__ == "__main__":
    main()
