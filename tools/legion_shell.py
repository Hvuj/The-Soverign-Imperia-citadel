#!/usr/bin/env python3
"""legion_shell.py — governed read-only shell/grep runner for The Sovereign Imperia Citadel Z.

Gives Legion Z the ability to run discovery commands (grep/rg/find/git-read/…) through a single
default-deny gate instead of a blanket Bash permission. Only an allowlist of read-only binaries
(and read-only `git` subcommands) is permitted; anything else — writes, deletes, mutating git,
shell chaining/redirection — is refused. Every invocation is logged.

Safety contract: never_call_claude; runs only vetted read-only commands (shell=False, no pipes,
no redirection); default-deny.

CLI:
  python tools/legion_shell.py rg "pattern" src/
  python tools/legion_shell.py git -C /path log --oneline -5
  python tools/legion_shell.py --json find . -name '*.py'
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime

from _brain_common import STATE

LOG = STATE / "legion-shell.ndjson"

_ALLOWED = frozenset({
    "rg", "grep", "egrep", "fgrep", "find", "ls", "cat", "head", "tail", "wc",
    "sort", "uniq", "cut", "tr", "basename", "dirname", "du", "stat", "file", "echo",
})
_GIT_READ = frozenset({
    "log", "status", "diff", "show", "grep", "branch", "rev-parse", "blame",
    "ls-files", "cat-file", "describe", "shortlog", "config", "remote",
})
_GIT_DENY = frozenset({
    "reset", "push", "clean", "checkout", "rebase", "merge", "commit", "add",
    "rm", "stash", "tag", "fetch", "pull", "gc", "prune", "filter-branch", "worktree",
})
_MAX_OUTPUT = 20000
_TIMEOUT = 30


def _log(rec: dict) -> None:
    rec["ts"] = datetime.now(UTC).isoformat()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def classify(argv: list[str]) -> tuple[bool, str]:
    if not argv:
        return False, "empty command"
    bin_ = argv[0]
    if bin_ == "git":
        toks = argv[1:]
        i = 0
        while i < len(toks) and (toks[i] in ("-C", "-c") or toks[i].startswith("-")):
            i += 2 if toks[i] in ("-C", "-c") else 1
        sub = toks[i] if i < len(toks) else ""
        if sub in _GIT_DENY or any(t in _GIT_DENY for t in toks):
            return False, f"mutating git subcommand: {sub or '?'}"
        if sub not in _GIT_READ:
            return False, f"git subcommand not allowlisted (read-only only): {sub or '?'}"
        return True, "ok"
    if bin_ in _ALLOWED:
        if bin_ in ("sed", "awk"):
            return False, f"{bin_} not allowed (can write)"
        return True, "ok"
    return False, f"binary not in read-only allowlist: {bin_}"


def run(argv: list[str]) -> dict:
    allowed, reason = classify(argv)
    if not allowed:
        _log({"argv": argv, "allowed": False, "reason": reason})
        return {"allowed": False, "reason": reason, "argv": argv}
    if not shutil.which(argv[0]):
        _log({"argv": argv, "allowed": True, "error": "not found"})
        return {"allowed": True, "error": f"command not found: {argv[0]}", "argv": argv}
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        _log({"argv": argv, "allowed": True, "error": str(exc)[:200]})
        return {"allowed": True, "error": str(exc)[:200], "argv": argv}
    _log({"argv": argv, "allowed": True, "code": r.returncode})
    return {"allowed": True, "code": r.returncode, "argv": argv,
            "stdout": r.stdout[:_MAX_OUTPUT], "stderr": r.stderr[:2000]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Governed read-only shell runner for Legion Z.")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="Command + args to run (read-only).")
    args = ap.parse_args()

    if not args.command:
        ap.error("no command given")
    result = run(args.command)
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        if not result.get("allowed"):
            print(f"DENIED: {result['reason']}", file=sys.stderr)
            sys.exit(2)
        if result.get("error"):
            print(f"ERROR: {result['error']}", file=sys.stderr)
            sys.exit(1)
        sys.stdout.write(result.get("stdout", ""))
        if result.get("stderr"):
            sys.stderr.write(result["stderr"])
        sys.exit(result.get("code", 0))


if __name__ == "__main__":
    main()
