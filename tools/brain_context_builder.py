#!/usr/bin/env python3
"""brain_context_builder.py — Citadel canonical capsule builder (live hook path).

Phase 0+1+6: connects classifier output, serves precomputed capsules (O(1) on hit),
adds secret redaction + injection-defense header, telemetry for cache/hit tracking,
and unit-scoped capsule lookup.

Hook: user-prompt-brain-search.sh (UserPromptSubmit #2)
"""
import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from _brain_common import CONFIG, ROOT, SEARCH_STATE, STATE, load_json, tokenize, write_json
from brain_search import intent as get_intent, search
from capsule_security import INJECTION_DEFENSE_HEADER, redact_secrets, safe_read

try:
    import prompt_usage_miner
except ImportError:
    prompt_usage_miner = None

MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"
TELEMETRY_PATH = STATE / "capsule-telemetry.json"

_WHAT_WORKED_PATH = ROOT / "docs" / "ai-context" / "what-worked.md"
_WHAT_FAILED_PATH = ROOT / "docs" / "ai-context" / "what-did-not-work.md"


def _publish_to_ram(key: str, cap: dict) -> str | None:
    """Store the full capsule in the RAM cache; return its key, or None on miss.

    Fail-soft: if the cache daemon is down or the package is unavailable, returns
    None and the caller simply injects the (trimmed) capsule inline as before. When
    it succeeds, context can carry the small ``ram_ref`` handle instead of the bulk.
    """
    try:
        from citadel.services.cache.client import CacheClient
    except ImportError:
        return None
    payload = json.dumps(cap).encode("utf-8")
    return key if CacheClient().put(key, payload) else None


def _bump_telemetry(key: str) -> None:
    try:
        data = load_json(TELEMETRY_PATH, {})
        data[key] = data.get(key, 0) + 1
        data["last_updated"] = datetime.now(UTC).isoformat()
        write_json(TELEMETRY_PATH, data)
    except Exception:
        pass


def _sig(query: str, labels: list | None = None, depth: int | None = None) -> str:
    it = get_intent(query)
    toks = sorted(set(tokenize(query)))[:12]
    label_str = "|".join(sorted(labels or []))
    depth_str = str(depth) if depth is not None else "auto"
    return f"{it}:{depth_str}:{label_str}:{'|'.join(toks)}"


def _serve_precomputed(top_node_ids: list[str], unit: str = "core") -> dict | None:
    """Return a precomputed capsule for the top topic/knowledge node, or None on miss."""
    n2c = load_json(SEARCH_STATE / "node-to-capsule.json", {})
    t2c = load_json(SEARCH_STATE / "topic-to-capsule.json", {})

    unit_n2c: dict = {}
    unit_t2c: dict = {}
    if unit and unit != "core":
        unit_n2c = load_json(STATE / "units" / unit / "node-to-capsule.json", {})
        unit_t2c = load_json(STATE / "units" / unit / "topic-to-capsule.json", {})

    for nid in top_node_ids:
        for lookup in (unit_n2c, n2c):
            rel = lookup.get(nid)
            if rel:
                cap_path = ROOT / rel
                if cap_path.exists():
                    data = load_json(cap_path, None)
                    if data:
                        return data
        if nid.startswith("topic:"):
            topic = nid.replace("topic:", "")
            for lookup in (unit_t2c, t2c):
                rel = lookup.get(topic)
                if rel:
                    cap_path = ROOT / rel
                    if cap_path.exists():
                        data = load_json(cap_path, None)
                        if data:
                            return data
    return None


def _warm_preload_on_proven_reuse(cap: dict, sig: str, query: str) -> None:
    """On a `_sig()` route-cache hit, consult prompt_usage_miner's learned index.

    If this prompt has a proven usage history, warm-preload the capsule into the RAM
    cache (via the existing `_publish_to_ram` path) so other consumers get an O(1)
    RAM hit instead of a disk/JSON re-read, and annotate the capsule with the learned
    signal. Fails soft on any miss/unavailability — the caller's return is unaffected.
    Zero added tokens: this only touches local indexes.
    """
    if prompt_usage_miner is None:
        return
    try:
        usage = prompt_usage_miner.lookup(query)
    except Exception:
        return
    if not usage:
        return
    cap["learned_reuse"] = {
        "signature": usage["signature"], "intent": usage["intent"],
        "count": usage["count"], "unit": usage.get("unit"),
    }
    ram_ref = _publish_to_ram("capsule:" + sig, cap)
    if ram_ref:
        cap["ram_ref"] = ram_ref
    _bump_telemetry("learned_reuse_warm_preload")


def build(query: str, depth: int | None = None, mode: str = "prompt") -> dict:
    cfg = load_json(CONFIG, {})
    ttl = int(cfg.get("cache_ttl_seconds", 300))
    now_ts = time.time()

    classify_result = load_json(STATE / "current-task.json", {})
    classifier_labels: list[str] = classify_result.get("labels", [])
    classifier_intent: str = classify_result.get("intent", "")
    unit: str = classify_result.get("unit", "core")
    fast_path_possible: bool = classify_result.get("fast_path_possible", False)

    cache_path = SEARCH_STATE / "prompt-route-cache.json"
    cache = load_json(cache_path, {})
    sig = _sig(query, classifier_labels, depth)
    entry = cache.get(sig)
    if entry and (now_ts - entry.get("ts", 0)) < ttl and entry.get("capsule"):
        cap = dict(entry["capsule"])
        cap["created_at"] = datetime.now(UTC).isoformat()
        cap["cache_hit"] = True
        _bump_telemetry("route_cache_hit")
        _warm_preload_on_proven_reuse(cap, sig, query)
        return cap

    _bump_telemetry("route_cache_miss")

    res = search(query, depth)
    top_node_ids = [n["id"] for n in res.get("selected_nodes", [])[:3]]

    if fast_path_possible and top_node_ids:
        precomputed = _serve_precomputed(top_node_ids, unit)
        if precomputed:
            now_str = datetime.now(UTC).isoformat()
            precomputed.update({
                "created_at": now_str,
                "mode": mode,
                "query": query,
                "intent": res.get("intent"),
                "depth": res.get("depth"),
                "classifier_labels": classifier_labels,
                "unit": unit,
                "precomputed": True,
                "instruction": INJECTION_DEFENSE_HEADER,
                "recommended_agents": res.get("agents", []),
                "recommended_skills": res.get("skills", []),
                "selected_nodes": res.get("selected_nodes", []),
                "files": res.get("files", []),
            })
            cache[sig] = {"ts": now_ts, "capsule": precomputed}
            _evict(cache, cfg)
            write_json(cache_path, cache)
            _bump_telemetry("precomputed_capsule_hit")
            return precomputed

    _wf_cfg = load_json(MANIFEST_CFG, {})
    _intent_val = res.get("intent", "question")
    try:
        import re as _re
        _p = query.lower()
        _best_tt, _best_sc = None, 0.0
        for _tt, _sd in _wf_cfg.get("task_type_signals", {}).items():
            _sc = 0.0; _pri = float(_sd.get("priority", 1))
            for _kw in _sd.get("keywords", []):
                if _re.search(r'(?<![a-z0-9_])' + _re.escape(_kw.lower()) + r'(?![a-z0-9_])', _p): _sc += _pri
            for _pat in _sd.get("patterns", []):
                try:
                    if _re.search(_pat, _p, _re.IGNORECASE): _sc += _pri * 2.0
                except _re.error: pass
            if _sc > _best_sc: _best_sc = _sc; _best_tt = _tt
        if not _best_tt:
            _best_tt = {
                "implementation": "feature_change", "debugging": "debugging",
                "validation": "validation_only", "docs_ingestion": "docs_ingestion",
                "bi": "bi_logic", "question": "question",
            }.get(_intent_val, "question")
        _wf_id = _wf_cfg.get("task_type_to_workflow", {}).get(_best_tt, "question_workflow")
        _wf = _wf_cfg.get("workflows", {}).get(_wf_id, {})
        _selected_workflow = _wf_id
        _required_artifacts = [a["id"] if isinstance(a, dict) else a for a in _wf.get("required_artifacts", [])]
        _required_validations = _wf.get("required_validations", [])
        _memory_policy = _wf.get("memory_policy", "curator_decides")
    except Exception:
        _selected_workflow = "question_workflow"
        _required_artifacts = []
        _required_validations = []
        _memory_policy = "curator_decides"

    worked, _ = safe_read(_WHAT_WORKED_PATH, max_chars=800, section="what-worked")
    failed, _ = safe_read(_WHAT_FAILED_PATH, max_chars=800, section="what-failed")

    cap = {
        "created_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "query": query,
        "intent": res.get("intent"),
        "depth": res.get("depth"),
        "unit": unit,
        "classifier_labels": classifier_labels,
        "instruction": INJECTION_DEFENSE_HEADER,
        "selected_nodes": res.get("selected_nodes", []),
        "recommended_agents": res.get("agents", []),
        "recommended_skills": res.get("skills", []),
        "files": res.get("files", []),
        "memory_refs": res.get("memory_refs", []),
        "reasoning_needed": True,
        "selected_workflow": _selected_workflow,
        "required_artifacts": _required_artifacts,
        "required_validations": _required_validations,
        "memory_policy": _memory_policy,
    }
    if worked:
        cap["what_worked_excerpt"] = worked
    if failed:
        cap["what_failed_excerpt"] = failed

    max_chars = int(cfg.get("token_budget", {}).get("prompt_capsule_chars", 3000))
    if len(json.dumps(cap)) > max_chars:
        cap["selected_nodes"] = cap["selected_nodes"][:3]
        cap.pop("what_worked_excerpt", None)
        cap.pop("what_failed_excerpt", None)

    cache[sig] = {"ts": now_ts, "capsule": cap}
    _evict(cache, cfg)
    write_json(cache_path, cache)

    return cap


def _evict(cache: dict, cfg: dict | None = None) -> None:
    max_entries = 200
    keep = 150
    if len(cache) > max_entries:
        oldest = sorted(cache.items(), key=lambda x: x[1].get("ts", 0))
        for k, _ in oldest[:(len(cache) - keep)]:
            del cache[k]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*")
    ap.add_argument("--depth", type=int)
    ap.add_argument("--mode", default="prompt")
    ap.add_argument("--out")
    ap.add_argument("--hook-output", action="store_true")
    ap.add_argument("--hook-event", default="UserPromptSubmit")
    args = ap.parse_args()

    cap = build(" ".join(args.query).strip() or "bootstrap", args.depth, args.mode)
    out = Path(args.out) if args.out else STATE / (
        "next-context.json" if args.mode != "agent" else "agent-context/generic.json"
    )
    write_json(out, cap)

    if args.hook_output:
        _cfg = load_json(CONFIG, {})
        nodes = cap.get("selected_nodes", [])
        top_score = max((n.get("score", 0) for n in nodes), default=0)
        min_score = float(_cfg.get("token_budget", {}).get("prompt_capsule_min_score", 8.0))
        if top_score < min_score:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": args.hook_event, "additionalContext": ""}}))
        else:
            trimmed = dict(cap)
            trimmed["selected_nodes"] = [
                {**n, "summary": (n.get("summary") or "")[:160]} for n in nodes[:3]
            ]
            ram_ref = _publish_to_ram("capsule:" + _sig(" ".join(args.query).strip()), cap)
            if ram_ref:
                trimmed["ram_ref"] = ram_ref
            capsule_str, _ = redact_secrets(
                json.dumps(trimmed, indent=2)[:3000],
                section="hook_injection",
            )
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": args.hook_event,
                    "additionalContext": "Graph-aware context capsule:\n" + capsule_str,
                }
            }))
    else:
        print(json.dumps(cap, indent=2))


if __name__ == "__main__":
    main()
