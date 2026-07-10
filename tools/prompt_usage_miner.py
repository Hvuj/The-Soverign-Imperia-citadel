#!/usr/bin/env python3
"""prompt_usage_miner.py — zero-token learned prompt→context reuse index.

Mines local ledgers (no hosted-model calls) to learn, from history, what each kind of prompt
maps to — so the UserPromptSubmit path can warm-preload a proven classification/context bundle
instead of re-deriving it every turn.

Sources (grounded shapes):
  - .claude/state/prompt-ledger.ndjson : per prompt {intent, unit, labels, scores, prompt_preview, ts}
                                         (NOTE: no session_id/prompt_id values are stored)
  - .claude/state/agent-runs.ndjson    : per subagent {event, agent, session_id, task_type, ts}

Because the prompt ledger has no session key, we key the reuse index on a stable signature of the
prompt text (computed identically here and by any consumer), and separately learn which agents run
per task_type from agent-runs.

Output: .claude/state/prompt-usage-index.json
  { by_signature: {sig: {intent, unit, top_labels, count, sample, last_seen}},
    by_intent:    {intent: {count, top_units, top_labels}},
    agents_by_task_type: {task_type: {agent: count}},
    generated_from: {...}, version }

Safety contract: never_call_claude, never_edit_production_code.
CLI: --mine (default) | --lookup "text" | --status | --json
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from _brain_common import STATE

PROMPT_LEDGER = STATE / "prompt-ledger.ndjson"
AGENT_RUNS = STATE / "agent-runs.ndjson"
USAGE_INDEX = STATE / "prompt-usage-index.json"

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are", "be",
    "this", "that", "it", "as", "at", "by", "from", "you", "i", "we", "can", "do", "does",
    "please", "should", "would", "will", "all", "any", "so", "if", "then", "not", "no",
})
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_TOP_LABELS = 6


def prompt_signature(text: str) -> str:
    tokens = [
        t for t in _TOKEN_RE.findall((text or "").lower())
        if len(t) >= 3 and t not in _STOPWORDS
    ]
    salient = sorted(set(tokens))[:24]
    return hashlib.sha1(" ".join(salient).encode("utf-8")).hexdigest()[:16]


def _iter_ndjson(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def mine() -> dict:
    by_signature: dict[str, dict] = {}
    intent_counts: Counter = Counter()
    intent_units: dict[str, Counter] = {}
    intent_labels: dict[str, Counter] = {}
    prompt_rows = 0

    for rec in _iter_ndjson(PROMPT_LEDGER):
        preview = rec.get("prompt_preview", "")
        if not preview:
            continue
        prompt_rows += 1
        sig = prompt_signature(preview)
        intent = rec.get("intent", "unknown")
        unit = rec.get("unit", "unknown")
        labels = rec.get("labels", []) or []
        ts = rec.get("ts", "")

        entry = by_signature.get(sig)
        if entry is None:
            by_signature[sig] = {
                "signature": sig, "intent": intent, "unit": unit,
                "labels": Counter(labels), "count": 1,
                "sample": preview[:160], "last_seen": ts,
            }
        else:
            entry["count"] += 1
            entry["labels"].update(labels)
            entry["last_seen"] = ts or entry["last_seen"]

        intent_counts[intent] += 1
        intent_units.setdefault(intent, Counter())[unit] += 1
        intent_labels.setdefault(intent, Counter()).update(labels)

    for entry in by_signature.values():
        entry["top_labels"] = [lbl for lbl, _ in entry["labels"].most_common(_TOP_LABELS)]
        del entry["labels"]

    agents_by_task_type: dict[str, Counter] = {}
    agent_rows = 0
    for rec in _iter_ndjson(AGENT_RUNS):
        if rec.get("event") != "subagent-stop":
            continue
        agent = rec.get("agent")
        tt = rec.get("task_type") or "unknown"
        if not agent or agent == "unknown":
            continue
        agent_rows += 1
        agents_by_task_type.setdefault(tt, Counter())[agent] += 1

    by_intent = {
        intent: {
            "count": intent_counts[intent],
            "top_units": [u for u, _ in intent_units[intent].most_common(3)],
            "top_labels": [lbl for lbl, _ in intent_labels[intent].most_common(_TOP_LABELS)],
        }
        for intent in intent_counts
    }

    index = {
        "version": 1,
        "by_signature": by_signature,
        "by_intent": by_intent,
        "agents_by_task_type": {tt: dict(c) for tt, c in agents_by_task_type.items()},
        "generated_from": {"prompt_rows": prompt_rows, "agent_rows": agent_rows},
    }
    _save(index)
    return index


def _save(index: dict) -> None:
    USAGE_INDEX.parent.mkdir(parents=True, exist_ok=True)
    USAGE_INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load() -> dict:
    try:
        return json.loads(USAGE_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def lookup(text: str) -> dict | None:
    """Return the learned context bundle for a prompt, or None on miss. Consumer-facing, zero-token."""
    index = _load()
    if not index:
        return None
    sig = prompt_signature(text)
    entry = index.get("by_signature", {}).get(sig)
    if not entry:
        return None
    intent = entry.get("intent", "unknown")
    by_intent = index.get("by_intent", {}).get(intent, {})
    return {
        "signature": sig, "intent": intent, "unit": entry.get("unit"),
        "top_labels": entry.get("top_labels", []), "count": entry.get("count", 1),
        "intent_top_units": by_intent.get("top_units", []),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Learned prompt->context reuse index miner.")
    ap.add_argument("--mine", action="store_true", help="Rebuild the usage index (default)")
    ap.add_argument("--lookup", metavar="TEXT", help="Look up a prompt's learned bundle")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    if args.lookup is not None:
        result = lookup(args.lookup)
        print(json.dumps(result, indent=2) if args.as_json else (result or "miss"))
        return
    if args.status:
        idx = _load()
        print(f"prompt-usage-index: {len(idx.get('by_signature', {}))} signatures, "
              f"{len(idx.get('by_intent', {}))} intents, "
              f"{len(idx.get('agents_by_task_type', {}))} task-types")
        return

    index = mine()
    summary = {"signatures": len(index["by_signature"]), "intents": len(index["by_intent"]),
               "task_types": len(index["agents_by_task_type"]), **index["generated_from"]}
    print(json.dumps(summary, indent=2) if args.as_json else json.dumps(summary))


if __name__ == "__main__":
    main()
