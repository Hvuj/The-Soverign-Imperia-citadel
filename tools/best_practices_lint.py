#!/usr/bin/env python3
"""best_practices_lint.py — Verify Citadel best-practices infrastructure is complete.

Checks:
1. scripts/mandatory-auto-lint.sh exists and is executable
2. scripts/claude-start-smart.sh exists and is executable
3. All grounding/output/prompt tools exist and compile
4. All required .claude/rules/ files exist and have content
5. All required .claude/schemas/ schemas exist
6. .claude/brain/prompt-template-registry.json exists and is valid
7. docs/ai-context/system/ has all 3 policy docs
8. State directories exist: context-capsules/, validation-results/, learning-candidates/
9. Daemons do not import AI providers
10. No secrets in .claude/brain/ configs

Exit 0 = pass, exit 1 = fail.
"""

import argparse
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])

REQUIRED_RULES = [
    "grounding.md",
    "output-consistency.md",
    "prompt-leak-policy.md",
    "bi-logic.md",
    "brain-graph.md",
    "feature-learning.md",
]

REQUIRED_SCHEMAS = [
    "ask-response.schema.json",
    "execution-manifest.schema.json",
    "provider-plan.schema.json",
    "provider-review.schema.json",
    "validation-result.schema.json",
    "learning-candidate.schema.json",
    "system-health.schema.json",
    "workspace-summary.schema.json",
    "workspace-repo.schema.json",
    "workspace-dir.schema.json",
    "workspace-module.schema.json",
    "workspace-file.schema.json",
    "workspace-source-range.schema.json",
    "claim-verification.schema.json",
    "quote-extraction.schema.json",
    "provider-status.schema.json",
    "scale-prediction.schema.json",
    "legion-run-ledger.schema.json",
    "legion-current-run.schema.json",
    "bi-understanding.schema.json",
    "benchmark-report.schema.json",
]

REQUIRED_SYSTEM_DOCS = [
    "grounding-policy.md",
    "output-consistency-policy.md",
    "prompt-leak-policy.md",
]

REQUIRED_STATE_DIRS = [
    "context-capsules",
    "validation-results",
    "learning-candidates",
]

Citadel_TOOLS_TO_COMPILE = [
    "grounding_quote_extractor.py",
    "grounding_claim_verifier.py",
    "output_normalizer.py",
    "prompt_leak_output_filter.py",
    "grounding_lint.py",
    "output_schema_lint.py",
    "prompt_leak_lint.py",
]

DAEMON_FILES_NO_AI = [
    "tools/workspace_intelligence_daemon.py",
    "tools/incremental_brain_daemon.py",
]

AI_IMPORT_PATTERN = re.compile(
    r"^\s*(import|from)\s+(anthropic|openai|citadel_model_fallback|claude_cli)",
    re.MULTILINE,
)

_SECRET_PATTERN = re.compile(
    r"(API_KEY|SECRET_KEY|PASSWORD|ACCESS_TOKEN)\s*=\s*[A-Za-z0-9_\-]{8,}",
    re.IGNORECASE,
)

BANNED_TYPING_GENERICS = frozenset(
    {"List", "Dict", "Set", "FrozenSet", "Tuple", "Type", "Optional", "Union"}
)

PY_STYLE_DIRS = ["src", "tools", "tests"]

_EXEMPT_COMMENT_PREFIXES = (
    "#!", "# -*-", "# type:", "#type:", "# noqa", "#noqa",
    "# ty:", "#ty:", "# pragma", "#pragma",
)

SH_STYLE_DIRS = [".claude", "scripts"]


def _check(name: str, status: str, message: str) -> dict:
    return {"name": name, "status": status, "message": message}


def check_scripts_executable() -> list[dict]:
    checks = []
    for script in ["scripts/mandatory-auto-lint.sh", "scripts/claude-start-smart.sh"]:
        path = ROOT / script
        if not path.exists():
            checks.append(_check(f"script_{path.name}", "fail", f"{script} does not exist"))
        elif not os.access(path, os.X_OK):
            checks.append(_check(f"script_{path.name}", "fail", f"{script} is not executable"))
        else:
            checks.append(_check(f"script_{path.name}", "pass", f"{script} exists and is executable"))
    return checks


def check_tools_compile() -> list[dict]:
    checks = []
    for tool_name in Citadel_TOOLS_TO_COMPILE:
        path = ROOT / "tools" / tool_name
        if not path.exists():
            checks.append(_check(f"compile_{tool_name}", "fail", f"tools/{tool_name} does not exist"))
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            checks.append(_check(f"compile_{tool_name}", "pass", f"tools/{tool_name} compiles OK"))
        except py_compile.PyCompileError as exc:
            checks.append(_check(f"compile_{tool_name}", "fail",
                                 f"tools/{tool_name} compile error: {exc}"))
    return checks


def check_required_rules() -> list[dict]:
    checks = []
    rules_dir = ROOT / ".claude" / "rules"
    for rule_file in REQUIRED_RULES:
        path = rules_dir / rule_file
        if not path.exists():
            checks.append(_check(f"rule_{rule_file}", "fail",
                                 f".claude/rules/{rule_file} does not exist"))
        else:
            content = path.read_text(errors="replace").strip()
            if len(content) < 50:
                checks.append(_check(f"rule_{rule_file}", "fail",
                                     f".claude/rules/{rule_file} appears to be a stub"))
            else:
                checks.append(_check(f"rule_{rule_file}", "pass",
                                     f".claude/rules/{rule_file} exists ({len(content)} chars)"))
    return checks


def check_required_schemas() -> dict:
    schemas_dir = ROOT / ".claude" / "schemas"
    missing = [s for s in REQUIRED_SCHEMAS if not (schemas_dir / s).exists()]
    if missing:
        return _check("required_schemas", "fail",
                      f"{len(missing)}/{len(REQUIRED_SCHEMAS)} schemas missing: {missing[:3]}...")
    return _check("required_schemas", "pass",
                  f"All {len(REQUIRED_SCHEMAS)} required schemas present in .claude/schemas/")


def check_template_registry() -> dict:
    path = ROOT / ".claude" / "brain" / "prompt-template-registry.json"
    if not path.exists():
        return _check("template_registry", "fail",
                      ".claude/brain/prompt-template-registry.json does not exist")
    try:
        data = json.loads(path.read_text())
        template_count = len(data.get("templates", {}))
        return _check("template_registry", "pass",
                      f".claude/brain/prompt-template-registry.json valid ({template_count} templates)")
    except json.JSONDecodeError as exc:
        return _check("template_registry", "fail",
                      f".claude/brain/prompt-template-registry.json invalid JSON: {exc}")


def check_system_docs() -> list[dict]:
    checks = []
    system_dir = ROOT / "docs" / "ai-context" / "system"
    for doc in REQUIRED_SYSTEM_DOCS:
        path = system_dir / doc
        if not path.exists():
            checks.append(_check(f"system_doc_{doc}", "fail",
                                 f"docs/ai-context/system/{doc} does not exist"))
        else:
            checks.append(_check(f"system_doc_{doc}", "pass",
                                 f"docs/ai-context/system/{doc} exists"))
    return checks


def check_state_dirs() -> list[dict]:
    checks = []
    state_dir = ROOT / ".claude" / "state"
    for d in REQUIRED_STATE_DIRS:
        path = state_dir / d
        if not path.exists():
            checks.append(_check(f"state_dir_{d}", "fail",
                                 f".claude/state/{d}/ does not exist"))
        else:
            checks.append(_check(f"state_dir_{d}", "pass",
                                 f".claude/state/{d}/ exists"))
    return checks


def check_daemons_no_ai() -> list[dict]:
    checks = []
    for daemon_rel in DAEMON_FILES_NO_AI:
        path = ROOT / daemon_rel
        if not path.exists():
            checks.append(_check(f"daemon_no_ai_{path.name}", "warn",
                                 f"{daemon_rel} not found — skipping AI import check"))
            continue
        text = path.read_text(errors="replace")
        matches = AI_IMPORT_PATTERN.findall(text)
        if matches:
            checks.append(_check(f"daemon_no_ai_{path.name}", "fail",
                                 f"{daemon_rel} imports AI provider: {matches[:2]}"))
        else:
            checks.append(_check(f"daemon_no_ai_{path.name}", "pass",
                                 f"{daemon_rel} does not import AI providers"))
    return checks


def check_no_secrets_in_brain_configs() -> dict:
    brain_dir = ROOT / ".claude" / "brain"
    if not brain_dir.exists():
        return _check("no_secrets_in_brain", "warn", ".claude/brain/ does not exist")
    found = []
    for p in brain_dir.glob("*.json"):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if _SECRET_PATTERN.search(text):
            found.append(p.name)
    if found:
        return _check("no_secrets_in_brain", "fail",
                      f"Potential secrets found in .claude/brain/ configs: {found}")
    return _check("no_secrets_in_brain", "pass",
                  "No secret patterns found in .claude/brain/ JSON configs")


def _iter_py_files():
    for rel in PY_STYLE_DIRS:
        base = ROOT / rel
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            parts = set(p.parts)
            if "__pycache__" in parts or ".venv" in parts:
                continue
            yield p


def check_python_style() -> list[dict]:
    import ast

    future_offenders: list[str] = []
    generic_offenders: list[str] = []
    for p in _iter_py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError):
            continue
        rel = p.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "__future__" and any(a.name == "annotations" for a in node.names):
                    future_offenders.append(f"{rel}:{node.lineno}")
                elif node.module == "typing":
                    for a in node.names:
                        if a.name in BANNED_TYPING_GENERICS:
                            generic_offenders.append(f"{rel}:{node.lineno} ({a.name})")
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "typing"
                and node.attr in BANNED_TYPING_GENERICS
            ):
                generic_offenders.append(f"{rel}:{node.lineno} (typing.{node.attr})")

    checks = []
    if future_offenders:
        checks.append(_check(
            "py_no_future_annotations", "fail",
            f"{len(future_offenders)} file(s) use `from __future__ import annotations` "
            f"(redundant on 3.12, makes annotations lazy strings): {future_offenders[:5]}",
        ))
    else:
        checks.append(_check(
            "py_no_future_annotations", "pass",
            "No `from __future__ import annotations` in src/tools/tests",
        ))
    if generic_offenders:
        checks.append(_check(
            "py_pep585_generics", "fail",
            f"{len(generic_offenders)} deprecated typing generic(s) — use PEP 585 builtins "
            f"(list/dict/...) and PEP 604 (X | None): {generic_offenders[:5]}",
        ))
    else:
        checks.append(_check(
            "py_pep585_generics", "pass",
            "No deprecated typing.List/Dict/... generics in src/tools/tests",
        ))
    return checks


def _is_exempt_comment(comment_text: str) -> bool:
    stripped = comment_text.strip()
    return any(stripped.startswith(p) for p in _EXEMPT_COMMENT_PREFIXES)


def _find_py_comments(source: str) -> list[tokenize.TokenInfo]:
    """Return non-exempt COMMENT tokens in *source*, or [] if it fails to tokenize.

    Uses `tokenize`, not regex, so a `#` inside a string literal is never mistaken
    for a comment, and module/class docstrings (STRING tokens) are never touched.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenizeError, IndentationError, SyntaxError, ValueError):
        return []
    return [t for t in tokens if t.type == tokenize.COMMENT and not _is_exempt_comment(t.string)]


def _strip_py_comments(source: str) -> tuple[str, int]:
    """Remove non-exempt `#` comments from Python source. Returns (new_source, count)."""
    comments = _find_py_comments(source)
    if not comments:
        return source, 0
    lines = source.splitlines(keepends=True)
    for tok in sorted(comments, key=lambda t: t.start[0], reverse=True):
        row, col = tok.start
        line = lines[row - 1]
        before = line[:col]
        if before.strip() == "":
            lines[row - 1] = ""
        else:
            newline = "\n" if line.endswith("\n") else ""
            lines[row - 1] = before.rstrip() + newline
    return "".join(lines), len(comments)


_SH_STANDALONE_COMMENT = re.compile(r"^[ \t]*#(?!!)")


def _strip_sh_comments(source: str) -> tuple[str, int]:
    """Remove standalone full-line `#` comments from shell source.

    Deliberately conservative vs. the Python stripper: trailing same-line comments
    are left alone because `#` also appears inside shell parameter expansion
    (`${var#pattern}`) and quoted strings, which a line-oriented check cannot
    safely distinguish from a real comment. Two lines are exempt, mirroring the
    one-line-docstring allowance for Python: the shebang, and a single
    `<filename> — <purpose>` header comment immediately following it.
    """
    lines = source.splitlines(keepends=True)
    removed = 0
    header_exempt_row = None
    if lines and lines[0].startswith("#!") and len(lines) > 1 and _SH_STANDALONE_COMMENT.match(lines[1]):
        header_exempt_row = 1
    for i, line in enumerate(lines):
        if i == 0 and line.startswith("#!"):
            continue
        if i == header_exempt_row:
            continue
        if _SH_STANDALONE_COMMENT.match(line):
            lines[i] = ""
            removed += 1
    return "".join(lines), removed


def _iter_sh_files():
    for rel in SH_STYLE_DIRS:
        base = ROOT / rel
        if not base.exists():
            continue
        for p in base.rglob("*.sh"):
            parts = set(p.parts)
            if "__pycache__" in parts or ".venv" in parts or "node_modules" in parts or "state" in parts:
                continue
            yield p


def check_no_inline_comments() -> dict:
    """Report-only: count non-exempt inline `#` comments across src/tools/tests + shell hooks.

    Read-only by design (matches every other check in this module) — use
    `python tools/best_practices_lint.py --fix-comments` to apply the same
    tokenize-based removal this counts.
    """
    py_offenders: list[str] = []
    for p in _iter_py_files():
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        comments = _find_py_comments(source)
        if comments:
            py_offenders.append(f"{p.relative_to(ROOT)} ({len(comments)})")

    sh_offenders: list[str] = []
    for p in _iter_sh_files():
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _, removed = _strip_sh_comments(source)
        if removed:
            sh_offenders.append(f"{p.relative_to(ROOT)} ({removed})")

    total = len(py_offenders) + len(sh_offenders)
    if total == 0:
        return _check("no_inline_comments", "pass", "No non-exempt inline comments found")
    return _check(
        "no_inline_comments", "fail",
        f"{len(py_offenders)} Python file(s) + {len(sh_offenders)} shell file(s) have inline "
        f"comments — run `python tools/best_practices_lint.py --fix-comments` to remove them: "
        f"{(py_offenders + sh_offenders)[:5]}",
    )


def fix_inline_comments(*, dry_run: bool = False) -> dict:
    """Strip non-exempt inline comments from every tracked .py/.sh file, verifying each rewrite.

    Each file is only overwritten if the stripped version still compiles (`py_compile`) /
    parses (`bash -n`) — on failure, that file's edit is skipped and reported, never left
    half-applied. `dry_run=True` reports what would change without writing anything.
    """
    changed: list[str] = []
    skipped: list[str] = []

    for p in _iter_py_files():
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        new_source, removed = _strip_py_comments(source)
        if not removed:
            continue
        rel = str(p.relative_to(ROOT))
        try:
            compile(new_source, str(p), "exec")
        except SyntaxError as exc:
            skipped.append(f"{rel}: py_compile failed after strip: {exc}")
            continue
        if not dry_run:
            p.write_text(new_source, encoding="utf-8")
        changed.append(f"{rel} (-{removed})")

    for p in _iter_sh_files():
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        new_source, removed = _strip_sh_comments(source)
        if not removed:
            continue
        rel = str(p.relative_to(ROOT))
        if not dry_run:
            tmp = p.with_suffix(p.suffix + ".citadel-fix-tmp")
            tmp.write_text(new_source, encoding="utf-8")
            result = subprocess.run(["bash", "-n", str(tmp)], capture_output=True, text=True)
            if result.returncode != 0:
                tmp.unlink(missing_ok=True)
                skipped.append(f"{rel}: bash -n failed after strip: {result.stderr.strip()}")
                continue
            tmp.replace(p)
        changed.append(f"{rel} (-{removed})")

    return {"changed": changed, "skipped": skipped, "dry_run": dry_run}


def run_checks() -> list[dict]:
    checks = []
    checks.extend(check_scripts_executable())
    checks.extend(check_tools_compile())
    checks.extend(check_required_rules())
    checks.append(check_required_schemas())
    checks.append(check_template_registry())
    checks.extend(check_system_docs())
    checks.extend(check_state_dirs())
    checks.extend(check_daemons_no_ai())
    checks.append(check_no_secrets_in_brain_configs())
    checks.extend(check_python_style())
    checks.append(check_no_inline_comments())
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint Citadel best-practices infrastructure.")
    parser.add_argument("--pretty", action="store_true", help="Print human-readable output.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    parser.add_argument(
        "--fix-comments", action="store_true",
        help="Strip non-exempt inline `#` comments from src/tools/tests + .claude/scripts "
             "shell hooks, verifying each rewrite (py_compile / bash -n) before writing.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="With --fix-comments, report what would change without writing anything.",
    )
    args = parser.parse_args()

    if args.fix_comments:
        result = fix_inline_comments(dry_run=args.dry_run)
        label = "[dry-run] would change" if args.dry_run else "changed"
        print(f"fix-comments: {label} {len(result['changed'])} file(s), "
              f"skipped {len(result['skipped'])} file(s)")
        for line in result["changed"]:
            print(f"  [~] {line}")
        for line in result["skipped"]:
            print(f"  [!] {line}")
        sys.exit(0 if not result["skipped"] else 1)

    checks = run_checks()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    warned = sum(1 for c in checks if c["status"] == "warn")
    overall = "pass" if failed == 0 else "fail"

    result = {
        "status": overall,
        "checks": checks,
        "summary": {"pass": passed, "fail": failed, "warn": warned},
    }

    if args.pretty or not args.json:
        print(f"best_practices_lint: {overall.upper()} ({passed} pass, {failed} fail, {warned} warn)")
        for c in checks:
            icon = {"pass": "✓", "fail": "✗", "warn": "!"}.get(c["status"], "?")
            print(f"  [{icon}] {c['name']}: {c['message']}")
    else:
        print(json.dumps(result, indent=2))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
