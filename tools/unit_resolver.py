#!/usr/bin/env python3
"""unit_resolver.py — Resolve the active Citadel org unit from a prompt.

Units are the internal org-metaphor namespaces (core, performance, …).
Each unit owns its own arsenal: agents, capsules, memory, bug-registry.

Resolution order:
  1. Keyword match against unit_aliases in graph-aware-config.json
  2. Read .claude/state/current-task.json for pre-computed unit from classify_prompt
  3. Fallback: "core"

Zero-token — never calls Claude. Safe to call from daemons and hooks.
"""

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
STATE = ROOT / ".claude" / "state"
CONFIG = ROOT / ".claude" / "brain" / "graph-aware-config.json"

_BUILTIN_UNIT_KEYWORDS: dict[str, list[str]] = {
    "performance": [
        "vectorize", "vectorization", "optimize", "optimization", "throughput",
        "speed", "profile", "profiling", "benchmark", "bottleneck", "slow",
        "performance", "parallel", "parallelism", "memory usage", "compute",
        "cpu", "gpu", "simd", "jit", "numba", "cython", "cffi", "numeric",
        "efficient", "efficiency", "latency", "hot loop", "hot path",
    ],
}


def _load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def resolve(prompt: str, cfg: dict | None = None) -> str:
    """Return the best matching unit for this prompt. Never returns None."""
    if cfg is None:
        cfg = _load_config()

    task_json = STATE / "current-task.json"
    if task_json.exists():
        try:
            task = json.loads(task_json.read_text())
            precomputed = task.get("unit", "")
            if precomputed and precomputed != "core":
                return precomputed
        except (OSError, json.JSONDecodeError):
            pass

    p = prompt.lower()

    unit_aliases: dict[str, list[str]] = cfg.get("unit_aliases", {})
    best_unit, best_score = "core", 0
    for unit, aliases in unit_aliases.items():
        score = 0
        for alias in aliases:
            if re.search(r"(?<![a-z0-9_])" + re.escape(alias.lower()) + r"(?![a-z0-9_])", p):
                score += 1
        if score > best_score:
            best_score, best_unit = score, unit

    for unit, keywords in _BUILTIN_UNIT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in p)
        if score > best_score:
            best_score, best_unit = score, unit

    return best_unit


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve Citadel org unit from a prompt.")
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()
    prompt = " ".join(args.prompt).strip()
    unit = resolve(prompt)
    if args.as_json:
        print(json.dumps({"unit": unit, "prompt_preview": prompt[:80]}))
    else:
        print(unit)


if __name__ == "__main__":
    main()
