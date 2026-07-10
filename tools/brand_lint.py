#!/usr/bin/env python3
"""Brand-agnostic lint.

The Legion is vendor/client/product agnostic.  It may have *learned* from
other tools, but it carries its own reinvented logic — so no external tool,
product, or client name may be hard-coded into Legion-authored source.

This lint scans Legion-AUTHORED source (code, configs, agents, skills, hooks,
docs) and fails if any forbidden token appears.  It deliberately does NOT scan:
  - auto-generated caches / indexes (.claude/state/**, docs/brain/**), which
    legitimately mirror whatever workspace the Legion is pointed at;
  - archived uploads (_uploaded_originals/**);
  - this file itself (it necessarily builds the token patterns).

Auto-discovered content that reflects the analyzed workspace is fine — the
constraint is only on Legion's own hard-coded logic and identity.

Fully auto-discovered token set — nothing here names a specific client/tool/org:
  1. Every sibling repo name from workspace-discovery.json (workspace_discoverer.py /
     build_workspace_intelligence_index.py output) — acme-*, svc-*, caveman,
     whatever the workspace actually contains today.
  2. Each of those repos' own git remote org/namespace segments (e.g. the "acme"
     in `git@gitlab.com:acme/squad-one/acme-core.git`) — read live via
     `git remote get-url`, never hardcoded.
A repo/org appearing tomorrow is caught automatically the next time
workspace-discovery.json is refreshed; nothing needs to be added to this file.

Exit code 0 = clean, 1 = violations found.  `--test` runs a self-check.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_SELF_NAME_TOKENS = {"sovereign-imperia-citadel", "citadel", "citadel", "legion"}

_MIN_TOKEN_LEN = 3


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _discovered_repos(base: Path) -> list[dict]:
    """Every sibling repo the legion has discovered — see workspace_discoverer.py /
    build_workspace_intelligence_index.py, which write this file."""
    data = _load_json(base / ".claude" / "state" / "workspace-discovery.json")
    return [p for p in data.get("projects", []) if p.get("root_path")]


def _org_segments_from_remote(repo_path: str) -> set[str]:
    """Derive the git hosting ORG (top-level namespace only) from a repo's OWN
    remote — e.g. 'git@gitlab.com:acme/squad-one/acme-core.git' -> {'acme'}.
    Fully dynamic: no org/company name is ever hardcoded here. Deeper path segments
    (subgroups like "squad-one"/"devops") are dropped — those are generic team/function
    names, not a distinct identity, and banning them is pure false-positive risk (e.g.
    a subgroup literally named "devops" would ban the ordinary word "DevOps").
    """
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if r.returncode != 0 or not r.stdout.strip():
        return set()
    url = r.stdout.strip()
    if "@" in url and ":" in url.split("@", 1)[1].split("/", 1)[0]:
        path = url.split(":", 1)[1]
    else:
        m = re.match(r"^\w+://[^/]+/(.*)$", url)
        path = m.group(1) if m else ""
    path = path[: -len(".git")] if path.endswith(".git") else path
    segments = [p for p in path.split("/") if p]
    return {segments[0]} if len(segments) >= 2 else set()


def _discovered_tokens(base: Path) -> list[str]:
    """Auto-discover every forbidden token from the actual workspace: repo names
    plus their git remote org/namespace segments. Zero hardcoded identities."""
    tokens: set[str] = set()
    for proj in _discovered_repos(base):
        name = Path(proj["root_path"]).name
        tokens.add(name)
        tokens |= _org_segments_from_remote(proj["root_path"])
    tokens = {t for t in tokens if len(t) >= _MIN_TOKEN_LEN and t.lower() not in _SELF_NAME_TOKENS}
    return sorted(tokens)


def _token_pattern(name: str) -> str:
    """Build a regex fragment matching `name` with "-"/"_" used interchangeably —
    a discovered dir is usually hyphenated ("acme-widgets") while the matching
    Python identifier uses underscores ("acme_widgets_core"). A trailing lookahead
    (not \\b) catches that "_core" continuation too: "_" is a \\w char, so a
    trailing \\b would never fire right after "acme_widgets".
    """
    stem = "[-_]".join(re.escape(part) for part in re.split(r"[-_]", name) if part)
    return rf"\b{stem}(?=[-_]|\b)"


def _build_forbidden_pattern(base: Path) -> re.Pattern | None:
    tokens = _discovered_tokens(base)
    if not tokens:
        return None
    parts = [_token_pattern(t) for t in tokens]
    return re.compile("|".join(parts), re.IGNORECASE)


_EXCLUDED_DIR_PARTS = {
    ".git", ".venv", "__pycache__", "node_modules",
    "state", "brain", "_uploaded_originals", "ai-context",
}

_EXCLUDED_FILES = {
    "brand_lint.py",
    "settings.local.json", "settings.local.README.md",
    "index.json", "keyword-to-nodes.json", "alias-to-nodes.json", "path-to-nodes.json",
    "node-rank.json", "node-to-agents.json", "node-to-capsule.json", "node-to-neighbors.json",
    "node-to-skills.json", "directory-brain-index.json", "topic-to-capsule.json",
}
_EXCLUDED_FILE_PREFIXES = ("knowledge__", "topic__")

_SCAN_SUFFIXES = {".py", ".sh", ".js", ".json", ".md", ".txt", ".yaml", ".yml"}


def _is_excluded(path: Path) -> bool:
    if path.name in _EXCLUDED_FILES:
        return True
    if path.name.startswith(_EXCLUDED_FILE_PREFIXES):
        return True
    parts = set(path.parts)
    if parts & _EXCLUDED_DIR_PARTS:
        return True
    return False


def scan(root: Path | None = None) -> list[tuple[str, int, str]]:
    """Return a list of (relpath, lineno, line) violations.

    The forbidden-token pattern is built fresh from `<root>/.claude/state/
    workspace-discovery.json` on every call — always current, never hardcoded.
    """
    base = Path(root) if root is not None else _ROOT
    forbidden = _build_forbidden_pattern(base)
    if forbidden is None:
        return []
    violations: list[tuple[str, int, str]] = []
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        if _is_excluded(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if forbidden.search(line):
                rel = str(path.relative_to(base))
                violations.append((rel, i, line.strip()[:160]))
    return violations


def _run_self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "tools").mkdir()
        (t / ".claude" / "state").mkdir(parents=True)
        (t / ".claude" / "state" / "workspace-discovery.json").write_text(
            json.dumps({"projects": [
                {"root_path": "/work/acme-widgets", "languages": ["python"], "frameworks": []},
            ]}),
            encoding="utf-8",
        )

        (t / "tools" / "bad.py").write_text("X = 'acme-widgets wrapper'\n", encoding="utf-8")
        (t / "tools" / "hardcoded.py").write_text('SCOPE = "acme_widgets_core/scripts"\n', encoding="utf-8")
        (t / "tools" / "unrelated.py").write_text("X = 'totally-unrelated-name'\n", encoding="utf-8")
        (t / ".claude" / "state" / "idx.json").write_text('{"path":"acme-widgets.py"}\n', encoding="utf-8")
        (t / "docs" / "brain").mkdir(parents=True)
        (t / "docs" / "brain" / "n.md").write_text("acme-widgets commit\n", encoding="utf-8")
        (t / "docs" / "ai-context" / "tech-knowledge").mkdir(parents=True)
        (t / "docs" / "ai-context" / "tech-knowledge" / "k.md").write_text(
            "acme-widgets custom SchemaVal layer\n", encoding="utf-8",
        )
        (t / ".claude" / "node-to-neighbors.json").write_text(
            '{"dir-acme_widgets": []}\n', encoding="utf-8",
        )
        (t / ".claude" / "settings.local.json").write_text(
            '{"permissions": {"allow": ["Bash(git -C acme-widgets status)"]}}\n', encoding="utf-8",
        )

        v = scan(t)
        files = {f for f, _, _ in v}
        assert "tools/bad.py" in files, f"expected discovered-token violation, got {files}"
        assert "tools/hardcoded.py" in files, f"expected underscore-variant violation, got {files}"
        assert "tools/unrelated.py" not in files, f"flagged a non-discovered token: {files}"
        assert not any("state" in f or "brain" in f or "ai-context" in f for f in files), (
            f"generated/knowledge dirs leaked: {files}"
        )
        assert "node-to-neighbors.json" not in {Path(f).name for f in files}, (
            f"generated graph index leaked: {files}"
        )
        assert "settings.local.json" not in {Path(f).name for f in files}, (
            f"local settings leaked: {files}"
        )

        empty = t / "empty"
        (empty / "tools").mkdir(parents=True)
        (empty / "tools" / "x.py").write_text("X = 'acme-widgets'\n", encoding="utf-8")
        assert scan(empty) == [], "scanned with no discovery data present"

        print("brand_lint --test PASS")
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="brand_lint", description="Fail on hard-coded external brand tokens in authored source.")
    ap.add_argument("--test", action="store_true", help="Run isolated self-test.")
    ap.add_argument("--json", action="store_true", help="Emit violations as JSON.")
    args = ap.parse_args(argv)

    if args.test:
        return _run_self_test()

    violations = scan()
    if args.json:
        import json
        print(json.dumps([{"file": f, "line": n, "text": t} for f, n, t in violations], indent=2))
    else:
        if not violations:
            print("brand_lint: clean — no hard-coded external brand tokens in authored source.")
        else:
            print(f"brand_lint: {len(violations)} violation(s) — external brand tokens in authored source:")
            for f, n, t in violations:
                print(f"  {f}:{n}: {t}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
