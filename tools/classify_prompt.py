import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd())).resolve()
STATE = ROOT / ".claude/state"
STATE.mkdir(parents=True, exist_ok=True)


def safe_input():
    raw = sys.stdin.read()
    try: return json.loads(raw) if raw.strip() else {}
    except Exception: return {"raw": raw[:2000]}


def write_nd(name, rec):
    rec["ts"] = datetime.now(UTC).isoformat()
    with (STATE / name).open("a", encoding="utf-8") as f: f.write(json.dumps(rec, sort_keys=True) + "\n")


# Agnostic: only generic, framework-neutral signals. Domain/data-stack vocabulary is learned per
# workspace, not shipped.
KEYWORDS = {
    "workflow-only":    ["verify workflow", "completion gate", "auditor", "hook", "agent workflow"],
    "code-change":      ["implement", "fix", "refactor", "change code", "bug", "feature"],
    "data-heavy":       ["data", "dataset", "pipeline", "etl", "transform", "schema", "batch"],
    "validation":       ["test", "validate", "reproducer", "ci"],
    "memory-update":    ["memory", "remember", "what worked", "what did not work", "ai-context"],
    "graph-update":     ["graph", "brain", "node", "directory brain", "visual"],
    "directory-map":    ["directory", "folder", "map dir", "dir brain"],
    "fast-path-reuse":  ["reuse", "cached", "already implemented", "pattern", "fast path"],
    "performance":      ["vectorize", "optimize", "throughput", "speed", "profile",
                         "benchmark", "bottleneck", "slow", "parallel", "memory usage", "compute",
                         "efficiency", "latency", "hot loop", "cpu", "gpu"],
}

LABEL_TO_UNIT = {
    "performance": "performance",
    "data-heavy":  "core",
}
_UNIT_PRIORITY = ["performance", "core"]


def classify_intent(p: str) -> str:
    """Shared intent vocabulary — mirrors brain_search.intent()."""
    t = p.lower()
    if any(x in t for x in ["fix", "error", "failed", "traceback", "bug"]): return "debugging"
    if any(x in t for x in ["add", "change", "implement", "build", "refactor"]): return "implementation"
    if any(x in t for x in ["test", "validate", "verify", "check"]): return "validation"
    if any(x in t for x in ["docs", "documentation", "learn this"]): return "docs_ingestion"
    if re.search(r'\b(bi|metric|kpi)\b', t): return "bi"
    return "question"


def get_prompt(d):
    for k in ["prompt", "user_prompt", "message", "text"]:
        if isinstance(d.get(k), str): return d[k]
    return json.dumps(d, ensure_ascii=False)


def classify(p):
    low = p.lower(); labels = []; scores = {}
    for lab, words in KEYWORDS.items():
        s = sum(low.count(w) for w in words)
        if s: labels.append(lab); scores[lab] = s
    if not labels: labels = ["general"]
    intent = classify_intent(p)
    unit = "core"
    matched_units = {LABEL_TO_UNIT[lab] for lab in labels if lab in LABEL_TO_UNIT}
    for u in _UNIT_PRIORITY:
        if u in matched_units:
            unit = u; break
    return {
        "labels": labels,
        "scores": scores,
        "intent": intent,
        "unit": unit,
        "fast_path_possible": any(x in labels for x in ["code-change", "data-heavy", "bi", "validation", "fast-path-reuse"]),
        "prompt_preview": p[:600],
    }


d = safe_input()
r = classify(get_prompt(d))
r["raw_event_keys"] = sorted(d.keys()) if isinstance(d, dict) else []
(STATE / "current-task.json").write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8")
write_nd("prompt-ledger.ndjson", r)
print("{}")
