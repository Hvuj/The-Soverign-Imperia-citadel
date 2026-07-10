#!/usr/bin/env python3
"""legion_self_heal.py — detect and repair known The Sovereign Imperia Citadel init failure classes.

Runs early in `citadel up` boot so broken hooks/config are surfaced (and, with
--fix, safely repaired) before daemons, preflight, and Claude Code start.

Failure classes detected:
  - malformed_json:        settings*.json and .claude/**/*.json that do not parse.
  - missing_hook_script:   a hook command in settings.json points at a file that is absent.
  - unguarded_git_in_hook: a hook uses `set -e`/`pipefail` and calls git without a guard,
                           while the workspace root is NOT a git repo (the class that caused
                           "Failed with non-blocking status code: No stderr output").
  - hook_syntax_error:     a shell hook fails `bash -n`.
  - duplicate_divergent_hook: an unreferenced `.claude/<name>.sh` duplicate that diverges from
                           the `.claude/hooks/<name>.sh` copy actually wired in settings.json.

Modes:
  --check (default): report only; never mutate. Exit 0 (add --strict to exit 1 on findings).
  --fix:             apply safe, reversible repairs — quarantine divergent duplicates, append a
                     `|| true` guard to unguarded git calls, strip a trailing comma / default an
                     empty file for recoverable malformed JSON, and write a no-op stub for a
                     missing hook script. Each repair is copy-on-write (`.bak_heal`) with rollback
                     if the repaired file fails its own validation (`bash -n` / `json.loads`).
  --json:            machine-readable output.
  --status:          print a summary of the last recorded self-heal run.

Every finding and action is appended to .claude/state/self-heal.ndjson.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from _brain_common import ROOT, STATE

HOOKS_DIR = ROOT / ".claude" / "hooks"
SETTINGS_FILES = [".claude/settings.json", ".claude/settings.local.json"]
SELF_HEAL_LOG = STATE / "self-heal.ndjson"
QUARANTINE_DIR = STATE / "self-heal" / "quarantine"

_SET_E_RE = re.compile(r"^\s*set\s+-\w*e\w*", re.MULTILINE)
_GIT_CALL_RE = re.compile(r"^\s*[^#\n]*\bgit\s", re.MULTILINE)
_GUARD_TOKENS = ("rev-parse --is-inside-work-tree", "|| true", "is-inside-work-tree")
_PATH_IN_CMD_RE = re.compile(r"(?:\$\{?CLAUDE_PROJECT_DIR\}?/)?([\w./-]+\.(?:sh|py))")


@dataclass(slots=True)
class Finding:
    kind: str
    severity: str
    path: str
    detail: str
    action: str = "reported"


def _is_git_repo(root: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip() == "true":
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return (root / ".git").exists()


def _hook_commands(settings: dict) -> list[str]:
    commands: list[str] = []
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                cmd = hook.get("command")
                if cmd:
                    commands.append(cmd)
    return commands


def _referenced_scripts(settings: dict) -> set[str]:
    refs: set[str] = set()
    for cmd in _hook_commands(settings):
        for m in _PATH_IN_CMD_RE.finditer(cmd):
            refs.add(m.group(1))
    return refs


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _repair_malformed_json(path: Path) -> str | None:
    """Best-effort recoverable repair: empty file → `{}`, or strip trailing commas.

    Returns the action string on success, or None if the file needs manual repair
    (left untouched — still reported).
    """
    backup = path.with_suffix(path.suffix + ".bak_heal")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        candidate = "{}\n"
    else:
        candidate = _TRAILING_COMMA_RE.sub(r"\1", raw)
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if candidate == raw:
        return None
    shutil.copy2(path, backup)
    try:
        path.write_text(candidate, encoding="utf-8")
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        shutil.copy2(backup, path)
        backup.unlink(missing_ok=True)
        return None
    backup.unlink(missing_ok=True)
    return "repaired (trailing comma stripped / defaulted to {})"


def check_malformed_json(do_fix: bool) -> list[Finding]:
    findings: list[Finding] = []
    targets: list[Path] = []
    for rel in SETTINGS_FILES:
        p = ROOT / rel
        if p.exists():
            targets.append(p)
    brain = ROOT / ".claude" / "brain"
    if brain.exists():
        targets.extend(sorted(brain.glob("*.json")))
    targets.extend(sorted((ROOT / ".claude").glob("*.json")))
    for p in targets:
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            f = Finding(
                "malformed_json", "high", p.relative_to(ROOT).as_posix(),
                f"does not parse as JSON: {exc}",
            )
            if do_fix:
                action = _repair_malformed_json(p)
                if action:
                    f.action = action
                else:
                    f.action = "reported (needs manual repair — not auto-recoverable)"
            findings.append(f)
    return findings


def _stub_hook_script(rel: str) -> str:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".py":
        body = '#!/usr/bin/env python3\n"""Auto-stubbed by legion_self_heal — no-op pending manual implementation."""\nimport sys\nsys.exit(0)\n'
    else:
        body = "#!/usr/bin/env bash\n# Auto-stubbed by legion_self_heal — no-op pending manual implementation.\nexit 0\n"
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | 0o111)
    return f"stubbed no-op at {rel} — needs manual implementation"


def check_missing_hook_scripts(settings: dict, do_fix: bool) -> list[Finding]:
    findings: list[Finding] = []
    for rel in sorted(_referenced_scripts(settings)):
        if not (ROOT / rel).exists():
            f = Finding(
                "missing_hook_script", "high", rel,
                "referenced by settings.json hooks but file does not exist",
            )
            if do_fix:
                f.action = _stub_hook_script(rel)
            findings.append(f)
    return findings


def _bash_syntax_ok(path: Path) -> bool | None:
    """Best-effort `bash -n` syntax check.

    Returns True (valid), False (a real syntax error), or None (could not validate on this
    platform — no bash, or only WSL bash which cannot translate a native Windows path). Callers
    MUST treat None as "unknown", never as a failure, so Windows never falsely rolls back a good
    repair or reports a phantom syntax error just because a POSIX bash isn't usable here.
    """
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        r = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 0:
        return True
    err = (r.stderr or "").lower()
    # WSL path-translation failure, or bash can't open a file that actually exists → can't validate.
    if path.exists() and ("failed to translate" in err or "no such file" in err or "cannot open" in err):
        return None
    return False


def _repair_unguarded_git(path: Path) -> str | None:
    """Append `|| true` to unguarded git call lines so `set -e` can't abort the hook.

    Validated with `bash -n` where a usable POSIX bash exists; rolled back only on a *real*
    syntax failure (never when validation was merely unavailable — see `_bash_syntax_ok`).
    """
    backup = path.with_suffix(path.suffix + ".bak_heal")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        if not _GIT_CALL_RE.match(line) or any(tok in line for tok in _GUARD_TOKENS):
            continue
        stripped = line.rstrip("\n")
        newline = "\n" if line.endswith("\n") else ""
        lines[i] = f"{stripped} || true{newline}"
        changed = True
    if not changed:
        return None
    shutil.copy2(path, backup)
    path.write_text("".join(lines), encoding="utf-8")
    if _bash_syntax_ok(path) is False:  # only roll back on a REAL syntax error, not "can't validate"
        shutil.copy2(backup, path)
        backup.unlink(missing_ok=True)
        return None
    backup.unlink(missing_ok=True)
    return "repaired (appended `|| true` guard to unguarded git call)"


def check_unguarded_git_in_hooks(is_git: bool, do_fix: bool) -> list[Finding]:
    findings: list[Finding] = []
    if is_git or not HOOKS_DIR.exists():
        return findings
    for p in sorted(HOOKS_DIR.glob("*.sh")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if not _SET_E_RE.search(text) or not _GIT_CALL_RE.search(text):
            continue
        if any(tok in text for tok in _GUARD_TOKENS):
            continue
        f = Finding(
            "unguarded_git_in_hook", "high", p.relative_to(ROOT).as_posix(),
            "uses `set -e` and calls git without a repo guard while the root is not a "
            "git repo — will abort with empty stderr. Guard with rev-parse or `|| true`.",
        )
        if do_fix:
            action = _repair_unguarded_git(p)
            if action:
                f.action = action
            else:
                f.action = "reported (auto-repair produced invalid syntax — rolled back)"
        findings.append(f)
    return findings


def check_hook_syntax() -> list[Finding]:
    findings: list[Finding] = []
    if not HOOKS_DIR.exists():
        return findings
    for p in sorted(HOOKS_DIR.glob("*.sh")):
        # Only flag a REAL syntax error. `None` (no usable POSIX bash / WSL path-translation
        # failure) is not a hook bug — skip silently so the check is clean on Windows.
        if _bash_syntax_ok(p) is False:
            findings.append(Finding(
                "hook_syntax_error", "high", p.relative_to(ROOT).as_posix(),
                "bash -n reported a syntax error",
            ))
    return findings


def check_duplicate_divergent_hooks(settings: dict, do_fix: bool) -> list[Finding]:
    findings: list[Finding] = []
    claude_dir = ROOT / ".claude"
    if not HOOKS_DIR.exists():
        return findings
    referenced = _referenced_scripts(settings)
    for root_copy in sorted(claude_dir.glob("*.sh")):
        canonical = HOOKS_DIR / root_copy.name
        if not canonical.exists():
            continue
        rel_root = str(root_copy.relative_to(ROOT))
        if rel_root in referenced:
            continue
        try:
            same = root_copy.read_bytes() == canonical.read_bytes()
        except OSError:
            continue
        if same:
            continue
        f = Finding(
            "duplicate_divergent_hook", "medium", rel_root,
            f"unreferenced duplicate diverges from {canonical.relative_to(ROOT)} "
            "(risk of editing the wrong copy)",
        )
        if do_fix:
            f.action = _quarantine(root_copy)
        findings.append(f)
    return findings


def _quarantine(path: Path) -> str:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    dest = QUARANTINE_DIR / path.name
    if dest.exists():
        dest = QUARANTINE_DIR / f"{path.stem}.{path.stat().st_mtime_ns}{path.suffix}"
    shutil.move(str(path), str(dest))
    return f"quarantined to {dest.relative_to(ROOT)}"


@dataclass(slots=True)
class Report:
    ts: str
    is_git_repo: bool
    mode: str
    findings: list[dict] = field(default_factory=list)

    @property
    def high(self) -> int:
        return sum(1 for f in self.findings if f["severity"] == "high")


_REQUIRED_STATE_DIRS = ("context-capsules", "validation-results", "learning-candidates")


def check_required_state_dirs(do_fix: bool) -> list[Finding]:
    findings: list[Finding] = []
    state = ROOT / ".claude" / "state"
    for d in _REQUIRED_STATE_DIRS:
        p = state / d
        if p.exists():
            continue
        f = Finding("missing_state_dir", "low", p.relative_to(ROOT).as_posix(),
                    "required state dir absent (created at full boot)")
        if do_fix:
            p.mkdir(parents=True, exist_ok=True)
            f.action = "created"
        findings.append(f)
    return findings


def run(do_fix: bool, now: str) -> Report:
    settings = {}
    settings_path = ROOT / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = {}

    is_git = _is_git_repo(ROOT)
    findings: list[Finding] = []
    findings += check_malformed_json(do_fix)
    findings += check_missing_hook_scripts(settings, do_fix)
    findings += check_unguarded_git_in_hooks(is_git, do_fix)
    findings += check_hook_syntax()
    findings += check_duplicate_divergent_hooks(settings, do_fix)
    findings += check_required_state_dirs(do_fix)

    report = Report(
        ts=now, is_git_repo=is_git,
        mode="fix" if do_fix else "check",
        findings=[asdict(f) for f in findings],
    )
    _log_report(report)
    return report


def _log_report(report: Report) -> None:
    SELF_HEAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": report.ts, "mode": report.mode, "is_git_repo": report.is_git_repo,
        "finding_count": len(report.findings), "high": report.high,
        "findings": report.findings,
    }
    with SELF_HEAL_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _print_status() -> None:
    if not SELF_HEAL_LOG.exists():
        print("legion_self_heal: no runs recorded yet")
        return
    last = ""
    for line in SELF_HEAL_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
    if not last:
        print("legion_self_heal: no runs recorded yet")
        return
    rec = json.loads(last)
    print(f"legion_self_heal: last run {rec['ts']} mode={rec['mode']} "
          f"findings={rec['finding_count']} high={rec['high']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Detect/repair The Sovereign Imperia Citadel init failure classes.")
    ap.add_argument("--fix", action="store_true", help="Apply safe reversible repairs.")
    ap.add_argument("--check", action="store_true", help="Report only (default).")
    ap.add_argument("--strict", action="store_true", help="Exit 1 when findings exist.")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.status:
        _print_status()
        return

    now = datetime.now(UTC).isoformat()
    report = run(do_fix=args.fix, now=now)

    if args.as_json:
        print(json.dumps(asdict(report), indent=2))
    elif not args.quiet:
        print(f"legion_self_heal: {report.mode} — {len(report.findings)} finding(s), "
              f"{report.high} high (git_repo={report.is_git_repo})")
        for f in report.findings:
            icon = {"high": "✗", "medium": "!", "low": "·"}.get(f["severity"], "?")
            print(f"  [{icon}] {f['kind']} {f['path']}: {f['detail']} → {f['action']}")

    sys.exit(1 if (args.strict and report.findings) else 0)


if __name__ == "__main__":
    main()
