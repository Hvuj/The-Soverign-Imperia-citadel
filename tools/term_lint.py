#!/usr/bin/env python3
"""Term-lint (masterplan §1) — fail the build if a banned BRAND token appears in authored source.

Banned brands carry stale architectural assumptions. `swarm` and `VIREN` are dead product/brand names.
(`LEGION` is deferred to the Phase-6 rename — the codebase still uses `legion_*` internally by decision,
so it is not banned yet.) Historical/design docs under `docs/history/` and `docs/citadel/` are exempt (as
is the authoritative `SYSTEM-DESIGN.md`, which must be able to name the brands it retired), as are generated
caches and the runtime `.claude/` instance (its settings embed absolute workspace paths that may
incidentally contain the folder name — not authored source). Exit 0 = clean, 1 = violations. `--test` runs
an isolated self-check.
"""

import argparse
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BANNED = re.compile(r"\b(swarm|VIREN)\b", re.IGNORECASE)
_SCAN_SUFFIXES = {".py", ".sh", ".js", ".json", ".md", ".txt", ".yaml", ".yml", ".toml"}
_EXEMPT_DIR_PARTS = {".git", ".venv", ".claude", "__pycache__", "node_modules", "state", "brain"}
_EXEMPT_PREFIXES = ("docs/history/", "docs/citadel/")
_EXEMPT_FILES = {"term_lint.py", "test_term_lint.py", "SYSTEM-DESIGN.md"}


def _exempt(path: Path, base: Path) -> bool:
    if path.name in _EXEMPT_FILES:
        return True
    if set(path.parts) & _EXEMPT_DIR_PARTS:
        return True
    rel = str(path.relative_to(base)).replace("\\", "/")
    return rel.startswith(_EXEMPT_PREFIXES)


def scan(root: Path | None = None) -> list[tuple[str, int, str]]:
    base = Path(root) if root is not None else _ROOT
    violations: list[tuple[str, int, str]] = []
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        if _exempt(path, base):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(base)).replace("\\", "/")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _BANNED.search(line):
                violations.append((rel, lineno, line.strip()[:160]))
    return violations


def _run_self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "src").mkdir()
        (base / "src" / "bad.py").write_text("MODE = 'swarm dispatch'\n", encoding="utf-8")
        (base / "src" / "brand.py").write_text("NAME = 'VIREN legion'\n", encoding="utf-8")
        (base / "src" / "ok.py").write_text("NAME = 'the citadel legion'\n", encoding="utf-8")
        (base / "docs" / "history").mkdir(parents=True)
        (base / "docs" / "history" / "old.md").write_text("VIREN swarm era\n", encoding="utf-8")
        files = {f for f, _, _ in scan(base)}
        assert "src/bad.py" in files, files
        assert "src/brand.py" in files, files
        assert "src/ok.py" not in files, files
        assert not any("history" in f for f in files), files
        print("term_lint --test PASS")
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="term_lint", description="Fail on banned brand tokens in authored source.")
    ap.add_argument("--test", action="store_true", help="Run isolated self-test.")
    args = ap.parse_args(argv)
    if args.test:
        return _run_self_test()
    violations = scan()
    if not violations:
        print("term_lint: clean — no banned brand tokens in authored source.")
        return 0
    print(f"term_lint: {len(violations)} violation(s) — banned brand token (masterplan §1):")
    for path, lineno, text in violations:
        print(f"  {path}:{lineno}: {text}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
