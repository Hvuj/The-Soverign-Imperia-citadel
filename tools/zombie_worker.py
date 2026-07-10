#!/usr/bin/env python3
"""zombie_worker.py — The Sovereign Imperia Citadel Z zombie worker (zero-token, CPU/RAM only).

A "dumb" worker that experiments deterministically — never calling a hosted model — to discover how
to improve the system and existing features, then files RICE-scored proposals into the
feature-improvement store. Signals used (all offline): ruff violations, stdlib-`ast` cyclomatic-ish
complexity, and (best-effort) type-error counts. Proposals are deduped by target so repeated runs
don't flood.

Safety contract: never_call_claude; never_edit_production_code (only writes proposals via the store).

CLI: --once [--path DIR ...] [--max N] | --json
"""

import argparse
import ast
import json
import subprocess
from pathlib import Path

import feature_improvement_store as store
from _brain_common import ROOT

_COMPLEXITY_BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                      ast.BoolOp, ast.ExceptHandler, ast.comprehension, ast.With)
_COMPLEXITY_THRESHOLD = 18
_MAX_PROPOSALS = 3


def _iter_py(paths: list[Path]):
    for base in paths:
        if not base.exists():
            continue
        if base.is_file() and base.suffix == ".py":
            yield base
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts or ".venv" in p.parts:
                continue
            yield p


def _ruff_violations(paths: list[Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        r = subprocess.run(
            ["ruff", "check", "--output-format=json", *[str(p) for p in paths]],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return counts
    for item in data:
        fname = item.get("filename", "")
        if fname:
            counts[fname] = counts.get(fname, 0) + 1
    return counts


def _complexity_hotspots(paths: list[Path]) -> list[dict]:
    hotspots: list[dict] = []
    for p in _iter_py(paths):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            score = 1 + sum(1 for n in ast.walk(node) if isinstance(n, _COMPLEXITY_BRANCH))
            if score >= _COMPLEXITY_THRESHOLD:
                hotspots.append({"file": _rel(p), "func": node.name,
                                 "line": node.lineno, "score": score})
    hotspots.sort(key=lambda h: -h["score"])
    return hotspots


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def run_once(scan_paths: list[Path] | None = None, max_proposals: int = _MAX_PROPOSALS) -> dict:
    scan_paths = scan_paths or [ROOT / "tools", ROOT / "src"]
    existing_targets = {r.get("target") for r in store.list_proposals()}

    ruff_counts = _ruff_violations(scan_paths)
    hotspots = _complexity_hotspots(scan_paths)

    candidates: list[dict] = []
    for f, n in sorted(ruff_counts.items(), key=lambda kv: -kv[1]):
        candidates.append({"kind": "lint", "target": _rel(Path(f)), "magnitude": n,
                           "detail": f"{n} ruff violations"})
    for h in hotspots:
        candidates.append({"kind": "complexity", "target": h["file"], "magnitude": h["score"],
                           "detail": f"function {h['func']} (line {h['line']}) complexity {h['score']}"})

    proposed = []
    for c in candidates:
        if len(proposed) >= max_proposals:
            break
        if c["target"] in existing_targets:
            continue
        existing_targets.add(c["target"])
        lines = _lines(c["target"])
        rice = {"reach": max(1, lines / 100), "impact": min(5, c["magnitude"] / 5),
                "confidence": 0.6, "effort": max(0.5, lines / 200)}
        if c["kind"] == "complexity":
            title = f"Reduce complexity in {c['target']}"
            how = ["Extract helper functions to cut branch/nesting count",
                   "Add focused unit tests around the refactor", "Re-run ruff + pytest"]
            gain = "Lower complexity → easier maintenance, fewer bugs"
        else:
            title = f"Fix {c['magnitude']} lint issues in {c['target']}"
            how = ["Run `ruff check --fix` then review", "Address remaining manual violations",
                   "Re-run the lint gate"]
            gain = "Clean lint → consistent style, fewer defects"
        proposed.append(store.propose(
            title, source="zombie", target=c["target"],
            scope_e2e=f"Refactor/clean {c['target']} ({c['detail']})",
            why=c["detail"], how=how, expected_gain=gain,
            perf_scale_reasoning="Deterministic static signal; no runtime cost.",
            rice=rice, evidence={"kind": c["kind"], "magnitude": c["magnitude"]}))

    return {"scanned": [str(p) for p in scan_paths],
            "ruff_hotspots": len(ruff_counts), "complexity_hotspots": len(hotspots),
            "proposed": [p["id"] for p in proposed]}


def _lines(rel: str) -> int:
    p = ROOT / rel
    try:
        return len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 100


def main() -> None:
    ap = argparse.ArgumentParser(description="Zombie worker: zero-token improvement proposer.")
    ap.add_argument("--once", action="store_true", help="Run one experiment cycle (default)")
    ap.add_argument("--path", action="append", default=[], help="Scan path(s); default tools/ + src/")
    ap.add_argument("--max", type=int, default=_MAX_PROPOSALS)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    paths = [Path(p) for p in args.path] or None
    result = run_once(paths, args.max)
    print(json.dumps(result, indent=2) if args.as_json else json.dumps(result))


if __name__ == "__main__":
    main()
