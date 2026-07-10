#!/usr/bin/env python3
"""best_practices_benchmark.py — deterministic, reproducible best-practices score for a repo/workspace.

Scores every Python file through the 8 principle analyzers (KISS/YAGNI/SOLID/DRY/LoD/OOP/CoC/craft,
`tools/principles/*.py`) plus a 9th PEP8 sub-score derived from `ruff check --output-format=json`
counts (reusing `zombie_worker._ruff_violations`), aggregates per-principle (mean + worst) and a
weighted 0-100 composite wiring the previously-dead `.claude/legion/principle-weights.json`, records
lines-of-code, and writes a `benchmark-report.schema.json`-conformant artifact under
`.claude/state/benchmark/`. Zero model tokens — fully deterministic so it can be benchmarked against
other tools (e.g. external, which measures LOC/cost/latency — a different axis; LOC is recorded here
so a later fair A/B is a wiring task, not a rebuild).

CLI: --repo DIR | --workspace [--json] | --external FILE (read a external benchmark JSON)
"""

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from _brain_common import ROOT, STATE, load_json, slug  # noqa: E402
from principles import (  # noqa: E402
    convention,
    craft,
    decoupling,
    dry,
    encapsulation,
    kiss,
    solid,
    yagni,
)
from zombie_worker import _ruff_violations  # noqa: E402

BENCH_DIR = STATE / "benchmark"
WEIGHTS_PATH = ROOT / ".claude" / "legion" / "principle-weights.json"

_ANALYZERS = {
    "simplicity": kiss.analyze_file,
    "frugality": yagni.analyze_file,
    "structure": solid.analyze_file,
    "dryness": dry.analyze_file,
    "decoupling": decoupling.analyze_file,
    "encapsulation": encapsulation.analyze_file,
    "convention": convention.analyze_file,
    "craft": craft.analyze_file,
}
_PEP8_KEY = "pep8"
_EXCLUDE = frozenset({".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
                      "node_modules", "dist", "build", ".mypy_cache"})
_MAX_FILES = 3000


def _py_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*.py"):
        if _EXCLUDE & set(p.parts):
            continue
        files.append(p)
        if len(files) >= _MAX_FILES:
            break
    return files


def _loc(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def _weights() -> dict[str, float]:
    w = load_json(WEIGHTS_PATH, {}) or {}
    weights = {k: float(w.get(k, 1.0)) for k in _ANALYZERS}
    weights[_PEP8_KEY] = float(w.get(_PEP8_KEY, 1.0))
    return weights


def score_repo(root: Path) -> dict:
    """Deterministically score one repo. Returns a benchmark-report.schema.json-shaped dict."""
    files = _py_files(root)
    ruff_counts = _ruff_violations(files)

    per_file: list[dict] = []
    for f in files:
        scores = {name: round(fn(str(f)), 4) for name, fn in _ANALYZERS.items()}
        violations = ruff_counts.get(str(f), ruff_counts.get(str(f.resolve()), 0))
        scores[_PEP8_KEY] = round(1.0 / (1.0 + violations), 4)
        per_file.append({"path": _rel(f, root), "loc": _loc(f), "ruff_violations": violations, "scores": scores})

    keys = [*_ANALYZERS, _PEP8_KEY]
    per_principle: dict[str, dict] = {}
    for k in keys:
        vals = [pf["scores"][k] for pf in per_file] or [1.0]
        per_principle[k] = {"mean": round(sum(vals) / len(vals), 4), "worst": round(min(vals), 4)}

    weights = _weights()
    denom = sum(weights[k] for k in keys) or 1.0
    composite = round(100.0 * sum(weights[k] * per_principle[k]["mean"] for k in keys) / denom, 2)

    return {
        "repo": root.name,
        "generated_at": time.time(),
        "composite": composite,
        "file_count": len(per_file),
        "loc_total": sum(pf["loc"] for pf in per_file),
        "weights": weights,
        "per_principle": per_principle,
        "files": per_file[:500],
    }


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _persist_report(report: dict) -> Path:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(report["generated_at"])
    out = BENCH_DIR / f"{slug(report['repo'])}-{stamp}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (BENCH_DIR / f"{slug(report['repo'])}-latest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def run_benchmark(repo_paths: list[Path], ws: Path, *, max_workers: int = 4, dry_run: bool = False) -> int:  # noqa: ARG001
    """Score repos concurrently (deterministic, zero model tokens) and persist reports."""
    if dry_run:
        print(f"[benchmark] would score {len(repo_paths)} repo(s): {', '.join(p.name for p in repo_paths)}")
        return 0
    cap = max(1, min(max_workers, len(repo_paths)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=cap) as pool:
        reports = list(pool.map(score_repo, repo_paths))
    for report in reports:
        path = _persist_report(report)
        print(f"[benchmark] {report['repo']}: composite {report['composite']}/100 "
              f"({report['file_count']} files, {report['loc_total']} LOC) → {path.name}")
    return 0


def read_external(path: Path) -> dict | None:
    """Read a external benchmark JSON (LOC/cost/latency across arms). Axis differs from Citadel's
    principle score — returned for side-by-side context, not merged into the composite."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic best-practices benchmark score for a repo/workspace.")
    ap.add_argument("--repo", help="Score a single repo directory")
    ap.add_argument("--workspace", action="store_true", help="Score every discovered company/repo")
    ap.add_argument("--max-workers", type=int, default=4)
    ap.add_argument("--external", metavar="FILE", help="Read a external benchmark JSON and print it")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    if args.external:
        print(json.dumps(read_external(Path(args.external)) or {}, indent=2))
        return

    if args.repo:
        report = score_repo(Path(args.repo).expanduser().resolve())
        _persist_report(report)
        print(json.dumps(report, indent=2) if args.as_json
              else f"{report['repo']}: composite {report['composite']}/100")
        return

    if args.workspace:
        from build_workspace_intelligence_index import discover_repos

        from citadel.paths import workspace_config
        scope = workspace_config()
        cfg = {
            "repo_include_globs": scope["repo_include_globs"],
            "repo_include_paths": scope.get("repo_include_paths"),
            "repo_exclude_globs": scope["repo_exclude_globs"],
        }
        repos = [Path(r["path"]) for r in discover_repos(scope["scan_root"], cfg)]
        raise SystemExit(run_benchmark(repos, ROOT, max_workers=args.max_workers))

    ap.error("pass --repo DIR, --workspace, or --external FILE")


if __name__ == "__main__":
    main()
