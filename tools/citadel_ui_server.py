#!/usr/bin/env python3
"""citadel_ui_server.py â€” Citadel local UI server with grounded /api/ask Q&A endpoint.

Serves static files from docs/ and handles:
  POST /api/ask    â€” grounded local Q&A resolver (zero hosted-model tokens by default)
  GET  /api/health â€” server liveness + config + system health summary

Security design:
- Binds to 127.0.0.1 only (not 0.0.0.0).
- Path is NEVER taken from the request body.
- Only allowlisted local files are read; allowlist is from config.
- No shell execution, no secret exposure, no external network calls.
- Model-backed Q&A disabled unless allow_model_fallback=true in config.
- Body size capped; question length capped; blocked patterns return safe refusals.
- No traceback is ever sent to the client.
"""

import http.client
import json
import os
import re
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlsplit

_SCRIPT_PATH = Path(os.path.abspath(__file__))
ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or _SCRIPT_PATH.parents[1])
DOCS_DIR = ROOT / "docs"

_TOOLS_DIR = str(_SCRIPT_PATH.parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

_CLAUDE_DIR = ROOT / ".citadel" / ".claude"


def _workspace_path(relative: str | Path) -> Path:
    """Join a workspace path without traversing the root ``.claude`` junction."""
    rel = Path(relative)
    if not rel.is_absolute() and rel.parts[:1] == (".claude",):
        return _CLAUDE_DIR.joinpath(*rel.parts[1:])
    return ROOT / rel

HOST = "127.0.0.1"
PORT = int(os.environ.get("CITADEL_UI_PORT", "8765"))
MAX_REQUEST_BODY = 64 * 1024

CONFIG_PATH = _CLAUDE_DIR / "brain" / "citadel-ask-config.json"

try:
    from intent_classifier import (
        DENSE_RESPONSE_DIRECTIVE as _DENSE_DIRECTIVE,  # type: ignore[import]
        IntentClassifier as _IntentClassifier,  # type: ignore[import]
    )

    _INTENT_AVAILABLE = True
except Exception:
    _INTENT_AVAILABLE = False
    _IntentClassifier = None  # type: ignore[assignment]
    _DENSE_DIRECTIVE = "ANSWER TELEGRAPHIC. NO PREAMBLE. DENSE FACTS ONLY."

try:
    from legion_model_dispatcher import (
        dispatch as _dispatch,  # type: ignore[import]
        dispatch_stream as _dispatch_stream,  # type: ignore[import]
    )

    _MODEL_DISPATCH_AVAILABLE = True
except Exception:
    _MODEL_DISPATCH_AVAILABLE = False
    _dispatch = None  # type: ignore[assignment]
    _dispatch_stream = None  # type: ignore[assignment]

_DEFAULT_CONFIG: dict = {
    "enabled": True,
    "bind_host": "127.0.0.1",
    "port": 8765,
    "allow_model_fallback": False,
    "max_question_chars": 1000,
    "max_answer_chars": 2500,
    "max_evidence_items": 8,
    "cache_enabled": True,
    "allowed_context_files": [
        "docs/brain/system-status.json",
        "docs/brain/graph.json",
        ".claude/state/execution-manifest.json",
        ".claude/state/brain-search/index.json",
        ".claude/state/scheduler-decision.json",
        ".claude/state/model-effort-schedule.json",
        ".claude/brain/workflow-manifest-config.json",
        ".claude/brain/artifact-policy.json",
        ".claude/brain/memory-policy.json",
        ".claude/brain/scheduler-config.json",
        ".claude/brain/model-effort-config.json",
        ".claude/brain/graph-aware-config.json",
        ".claude/brain/citadel-ask-config.json",
        ".claude/state/workspace-intelligence/workspace-index.json",
        ".claude/state/workspace-intelligence/repo-index.json",
        ".claude/state/workspace-intelligence/feature-index.json",
        ".claude/state/workspace-intelligence/reuse-candidate-index.json",
        ".claude/state/workspace-intelligence/module-index.json",
        ".claude/state/workspace-intelligence/symbol-index.json",
        ".claude/state/workspace-intelligence/test-index.json",
        ".claude/state/workspace-intelligence/file-index.json",
        ".claude/state/workspace-intelligence/build-metadata.json",
        ".claude/state/workspace-intelligence/alias-index.json",
        ".claude/state/workspace-intelligence/artifact-index.json",
        ".claude/state/workspace-intelligence/dir-index.json",
    ],
    "blocked_question_patterns": [
        "run command", "execute shell", "delete", "remove files",
        "upload", "send email", "secret", "token", "password",
        "private key", "env var", "environment variable",
    ],
}

_json_cache: dict[str, tuple[float, object]] = {}
_graph_cache: dict = {}
_graph_mtime: float | None = None
_ws_cache: dict = {}
_ws_mtime: float | None = None


def load_config() -> dict:
    """Load citadel-ask-config.json; overlay on safe defaults."""
    data = cached_json(str(CONFIG_PATH))
    if isinstance(data, dict):
        return {**_DEFAULT_CONFIG, **data}
    return dict(_DEFAULT_CONFIG)


def file_mtime(path: str | Path) -> float | None:
    """Return st_mtime of path, or None on any OSError."""
    try:
        return os.stat(str(path)).st_mtime
    except OSError:
        return None


def safe_json_load(path: str | Path) -> dict | list | None:
    """Read and parse JSON. Never raises; returns None on any error."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def cached_json(path: str) -> dict | list | None:
    """Return parsed JSON for path, reparsing only when mtime changes."""
    mtime = file_mtime(path)
    if mtime is None:
        return None
    entry = _json_cache.get(path)
    if entry is not None and entry[0] == mtime:
        return entry[1]
    data = safe_json_load(path)
    _json_cache[path] = (mtime, data)
    return data


def load_allowed(relpath: str, cfg: dict) -> dict | list | None:
    """Load JSON only when relpath is in cfg['allowed_context_files'].
    Path is NEVER taken from the request â€” only from config allowlist."""
    allowed: list[str] = cfg.get("allowed_context_files", [])
    if relpath not in allowed:
        return None
    return cached_json(str(_workspace_path(relpath)))


def check_blocked(question: str, cfg: dict) -> bool:
    """Return True if question matches any blocked pattern."""
    blocked: list[str] = cfg.get("blocked_question_patterns", [])
    q_lower = question.lower()
    return any(pat.lower() in q_lower for pat in blocked)


def build_graph_cache(cfg: dict) -> dict:  # noqa: ARG001
    """Precompute graph stats; recompute only when graph.json mtime changes."""
    global _graph_cache, _graph_mtime
    graph_path = str(ROOT / "docs" / "brain" / "graph.json")
    mtime = file_mtime(graph_path)
    if mtime is not None and mtime == _graph_mtime and _graph_cache:
        return _graph_cache

    raw = cached_json(graph_path)
    if not raw or not isinstance(raw, dict):
        return {}

    nodes: list[dict] = raw.get("nodes", [])
    links: list[dict] = raw.get("links", [])

    degree: dict[str, int] = {}
    neighbors: dict[str, list[dict]] = {}

    for lnk in links:
        src = lnk.get("source", "")
        tgt = lnk.get("target", "")
        lt = lnk.get("type", "related_to")
        if src:
            degree[src] = degree.get(src, 0) + 1
            neighbors.setdefault(src, []).append({"id": tgt, "link_type": lt})
        if tgt:
            degree[tgt] = degree.get(tgt, 0) + 1
            neighbors.setdefault(tgt, []).append({"id": src, "link_type": lt})

    node_by_id: dict[str, dict] = {}
    nodes_by_type: dict[str, list[str]] = {}
    node_type_counts: dict[str, int] = {}
    norm_lookup: dict[str, str] = {}

    for nd in nodes:
        nid = nd.get("id", "")
        if not nid:
            continue
        node_by_id[nid] = nd
        t = nd.get("type", "unknown")
        nodes_by_type.setdefault(t, []).append(nid)
        node_type_counts[t] = node_type_counts.get(t, 0) + 1
        for raw_key in (nid, nd.get("title", "")):
            if raw_key:
                norm = _normalize_str(raw_key)
                norm_lookup.setdefault(norm, nid)

    top10 = sorted(degree.items(), key=lambda kv: kv[1], reverse=True)[:10]

    _graph_cache = {
        "node_count": len(nodes),
        "link_count": len(links),
        "node_type_counts": node_type_counts,
        "nodes_by_type": nodes_by_type,
        "node_by_id": node_by_id,
        "degree": degree,
        "neighbors": neighbors,
        "top10_degree": top10,
        "norm_lookup": norm_lookup,
    }
    _graph_mtime = mtime
    return _graph_cache


def build_workspace_index_cache(cfg: dict) -> dict:  # noqa: ARG001
    """Load workspace intelligence summary indexes; recompute only on mtime change."""
    global _ws_cache, _ws_mtime
    ws_meta_path = str(_CLAUDE_DIR / "state" / "workspace-intelligence" / "build-metadata.json")
    mtime = file_mtime(ws_meta_path)
    if mtime is not None and mtime == _ws_mtime and _ws_cache:
        return _ws_cache

    def _load(relpath: str):
        return cached_json(str(_workspace_path(relpath)))

    bm = _load(".claude/state/workspace-intelligence/build-metadata.json") or {}
    ws = _load(".claude/state/workspace-intelligence/workspace-index.json") or {}
    repos = _load(".claude/state/workspace-intelligence/repo-index.json") or {}
    features = _load(".claude/state/workspace-intelligence/feature-index.json") or {}
    reuse = _load(".claude/state/workspace-intelligence/reuse-candidate-index.json") or {}
    alias_idx = _load(".claude/state/workspace-intelligence/alias-index.json") or {}
    test_idx = _load(".claude/state/workspace-intelligence/test-index.json") or {}

    def _unwrap(d):
        if not isinstance(d, dict):
            return d
        return {k: v for k, v in d.items()
                if k not in ("schema_version", "generated_at", "build_id")}

    _ws_cache = {
        "available": bool(bm and bm.get("build_id")),
        "build_id": bm.get("build_id", ""),
        "repo_count": bm.get("repo_count", 0),
        "file_count": bm.get("file_count", 0),
        "repos": list(_unwrap(repos).keys()) if isinstance(repos, dict) else [],
        "features": _unwrap(features),
        "reuse": _unwrap(reuse),
        "alias_index": _unwrap(alias_idx),
        "test_index": _unwrap(test_idx),
        "workspace_root": bm.get("workspace_root", ""),
    }
    _ws_mtime = mtime
    return _ws_cache


def _normalize_str(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[\s\-_]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s


def _fuzzy_find_node(query: str, gc: dict) -> list[dict]:
    """Return matching nodes (best first) for query string."""
    if not query or not gc:
        return []
    norm = _normalize_str(query)
    node_by_id: dict[str, dict] = gc.get("node_by_id", {})
    norm_lookup: dict[str, str] = gc.get("norm_lookup", {})

    if query in node_by_id:
        return [node_by_id[query]]
    ql = query.lower()
    for nd in node_by_id.values():
        if nd.get("title", "").lower() == ql:
            return [nd]
    if norm in norm_lookup:
        nid = norm_lookup[norm]
        return [node_by_id[nid]]
    substr: list[dict] = []
    for nd in node_by_id.values():
        if norm in _normalize_str(nd.get("id", "")) or norm in _normalize_str(nd.get("title", "")):
            substr.append(nd)
    q_tokens = set(re.split(r"[\s\-_]+", ql)) - {"", "the", "a", "an", "is", "are"}
    scored: list[tuple[int, dict]] = []
    seen = {nd["id"] for nd in substr}
    for nd in node_by_id.values():
        if nd["id"] in seen:
            continue
        t_tokens = set(re.split(r"[\s\-_]+", nd.get("title", "").lower()))
        i_tokens = set(re.split(r"[\s\-_]+", nd.get("id", "").lower()))
        overlap = len(q_tokens & (t_tokens | i_tokens))
        if overlap >= 1:
            scored.append((overlap, nd))
    scored.sort(key=lambda x: -x[0])

    all_matches = substr + [m[1] for m in scored]
    seen2: set[str] = set()
    result: list[dict] = []
    for nd in all_matches:
        if nd["id"] not in seen2:
            seen2.add(nd["id"])
            result.append(nd)
    return result[:10]


def build_response(
    answer: str,
    source: str,
    confidence: str,
    category: str,
    evidence: list[dict],
    suggested_questions: list[str],
    cfg: dict | None = None,
) -> dict:
    max_ans = (cfg or {}).get("max_answer_chars", 2500)
    max_ev = (cfg or {}).get("max_evidence_items", 8)
    if len(answer) > max_ans:
        answer = answer[:max_ans - 20] + "... [truncated]"
    return {
        "answer": answer,
        "source": source,
        "confidence": confidence,
        "category": category,
        "evidence": evidence[:max_ev],
        "suggested_questions": suggested_questions[:6],
        "generated_at_epoch_ms": int(datetime.now(UTC).timestamp() * 1000),
    }


def classify_question(question: str, selected_node_id: str | None = None) -> str:
    """Deterministic keyword classifier. Returns one of the 9 category names."""
    q = question.lower()

    if re.search(r"model effort|scheduler decision|local execution|model fallback|cheap model|ollama|hermes|effort level", q):
        return "scheduler"
    if re.search(r"execution manifest|workflow selected|artifacts expected|validation required|current plan|execution state", q):
        return "manifest"
    if re.search(r"permission|what can you access|can you edit|can you run|allowed to do|external service", q):
        return "permissions"
    if re.search(r"all systems green|system.?status|what failed|checks passed|when was health checked|systems? (ok|green|red|yellow)|overall status|health check", q):
        return "health"
    if "health" in q and not re.search(r"system.?health|scheduler health", q):
        return "health"
    if re.search(r"\bdaemons?\b|ui server|scheduler health|is.+running", q):
        return "daemon"
    if re.search(
        r"\bhow many skills\b|\blist (?:the )?skills\b|\bwhat skills\b|\bwhich skills\b"
        r"|\bskills (?:do we have|exist|are there|we have)\b"
        r"|\breusable skills\b|\bskills? (?:connected|related) to\b",
        q,
    ):
        return "skills"
    if re.search(
        r"\bhow many agents\b|\blist (?:the )?agents\b|\bwhat agents\b|\bwhich agents\b"
        r"|\bagents (?:do we have|exist|are there|we have)\b",
        q,
    ):
        return "agents"
    if re.search(
        r"\bhow many workflows\b|\blist (?:the )?workflows\b|\bwhat workflows\b|\bwhich workflows\b"
        r"|\bworkflows (?:do we have|exist|are there|we have)\b",
        q,
    ):
        return "workflows"
    if re.search(r"graph status|how many nodes|how many links|node types|biggest nodes|highest degree|what (topics?|agents?|workflows?|artifacts?|tools?) (exist|are there)", q):
        return "graph"
    if re.search(r"what handles?|who handles?|what agents? handle|what knowledge exists for|related workflows?|related agents?|related knowledge", q):
        return "routing"
    if re.search(r"\bwhat repos?\b|\blist repos?\b|\ball repos?\b|\bknown repos?\b|"
                 r"\bwhich repos?\b|\brepos? (do you know|exist|are indexed)\b", q):
        return "workspace"
    if re.search(r"\breuse\b|\bcan (we|i) reuse\b|\bwhat (can|should) (we|i|you) reuse\b|"
                 r"\bwhat (to|should) reuse\b|\breusable\b|\bexisting implementation\b", q):
        return "reuse"
    if re.search(r"\bwhere is.+(implemented|defined|located|found)\b|"
                 r"\bwhich (file|module|repo).+(implement|define|contain)\b|"
                 r"\b(rate rate|sample feature|schemaval|orchestration|parcompute).+(implement|file|module|where)\b", q):
        return "feature"
    if re.search(r"\bwhat tests?\b|\btest coverage\b|\btest files?\b|"
                 r"\btests? (cover|for|related to)\b", q):
        return "tests"
    if re.search(r"\b(file|module|symbol|class|function|import)\b.+(exist|found|index|where)\b|"
                 r"\bwhat (file|module|class|function|symbol)\b", q):
        return "file"
    if re.search(r"\bwhat (artifact|schema|config|asset)\b|\bartifact (types?|index)\b", q):
        return "artifact"
    if re.search(r"\bdepend(s|ency|encies)\b|\bwhat imports?\b|\bwhat does .+ import\b|"
                 r"\breverse imports?\b", q):
        return "dependency"
    if selected_node_id and re.search(r"\bthis (node|agent|workflow|topic|tool)\b", q):
        return "node"
    if re.search(r"tell me about|what is .+ (node|agent|workflow)|connected to|files.+reference|related to|neighbors of|what does .+ do|in charge of|show connections|show referenced files|find related", q):
        return "node"
    if re.search(r"^(what is|tell me about|about)\s+\S", q):
        return "node"

    return "unknown"


_SUGGESTED: dict[str, list[str]] = {
    "permissions": [
        "Are all systems green?",
        "What daemons are running?",
        "What is the graph status?",
    ],
    "health": [
        "What daemons are running?",
        "What is the graph status?",
        "What permissions do you have?",
        "What is the current execution manifest?",
    ],
    "daemon": [
        "Are all systems green?",
        "What is the graph status?",
        "What is the current execution manifest?",
    ],
    "graph": [
        "Tell me about task queue manager",
        "What handles Orchestration?",
        "What is connected to sample feature?",
        "What agents exist?",
    ],
    "node": [
        "What is the graph status?",
        "What handles Orchestration?",
        "Are all systems green?",
    ],
    "routing": [
        "Tell me about orchestration specialist",
        "What is the graph status?",
        "What daemons are running?",
    ],
    "manifest": [
        "What is the graph status?",
        "Are all systems green?",
        "Is model fallback enabled?",
    ],
    "scheduler": [
        "What is the current execution manifest?",
        "Are all systems green?",
        "What permissions do you have?",
    ],
    "unknown": [
        "Are all systems green?",
        "What permissions do you have?",
        "What is the graph status?",
        "What daemons are running?",
    ],
    "workspace": [
        "What repos do you know?",
        "What can we reuse for sample feature?",
        "Where is rate rate implemented?",
        "What tests cover sample feature?",
    ],
    "reuse": [
        "What repos do you know?",
        "What tests cover sample feature?",
        "Where is rate rate implemented?",
        "What should I reuse for a Orchestration asset-check SchemaVal POC?",
    ],
    "feature": [
        "What can we reuse for sample feature?",
        "What tests cover sample feature?",
        "What repos do you know?",
    ],
    "tests": [
        "What can we reuse for sample feature?",
        "Where is rate rate implemented?",
        "What repos do you know?",
    ],
    "file": [
        "What can we reuse for sample feature?",
        "Where is rate rate implemented?",
        "What tests cover sample feature?",
    ],
    "artifact": [
        "What repos do you know?",
        "What can we reuse for sample feature?",
        "What is the graph status?",
    ],
    "dependency": [
        "What can we reuse for sample feature?",
        "Where is rate rate implemented?",
        "What is the graph status?",
    ],
    "skills": [
        "How many agents do we have?",
        "What workflows exist?",
        "List the agents",
    ],
    "agents": [
        "How many skills do we have?",
        "List the skills",
        "What workflows exist?",
    ],
    "workflows": [
        "How many skills do we have?",
        "How many agents do we have?",
        "What handles Orchestration?",
    ],
}


def _format_time(epoch_ms: int | None, created_at: str | None) -> str:
    try:
        if epoch_ms:
            dt = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).astimezone()
        elif created_at:
            dt = datetime.fromisoformat(created_at).astimezone()
        else:
            return "unknown time"
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return "unknown time"


def answer_permissions(question: str, cfg: dict) -> dict:  # noqa: ARG001
    allow_model: bool = cfg.get("allow_model_fallback", False)
    allowed_files: list = cfg.get("allowed_context_files", [])
    answer = (
        "From this UI, I can read allowlisted local graph/status endpoints served by the local backend, "
        "show graph metadata, system health, daemon summaries, node details, routing links, and cached "
        "execution context. "
        "I cannot edit files, run arbitrary shell commands, access secrets, tokens, or private keys, "
        "deploy code, or call external services unless the local backend explicitly enables that capability. "
        f"Model-backed Q&A is {'enabled' if allow_model else 'disabled â€” not configured'}."
    )
    evidence = [
        {"source": ".claude/brain/citadel-ask-config.json", "detail": f"allow_model_fallback: {allow_model}"},
        {"source": ".claude/brain/citadel-ask-config.json", "detail": f"allowed_context_files: {len(allowed_files)} files"},
        {"source": "server", "detail": "Bind: 127.0.0.1 only; no shell exec; path never from request"},
    ]
    return build_response(
        answer=answer, source="local", confidence="high", category="permissions",
        evidence=evidence, suggested_questions=_SUGGESTED["permissions"], cfg=cfg,
    )


def answer_health(question: str, cfg: dict) -> dict:  # noqa: ARG001
    sd = load_allowed("docs/brain/system-status.json", cfg)
    if sd is None:
        return build_response(
            answer="System health data is unavailable (docs/brain/system-status.json not found or unreadable).",
            source="unavailable", confidence="low", category="health",
            evidence=[{"source": "docs/brain/system-status.json", "detail": "File not found or unreadable"}],
            suggested_questions=_SUGGESTED["health"], cfg=cfg,
        )

    overall: str = sd.get("overall_status", "unknown")
    summary: dict = sd.get("summary", {})
    ng, ny, nr = summary.get("green", 0), summary.get("yellow", 0), summary.get("red", 0)
    checks: list[dict] = sd.get("checks", [])
    ts = _format_time(sd.get("epoch_ms"), sd.get("created_at"))

    if overall == "green":
        green_names = [c["name"] for c in checks if c.get("status") == "green"]
        answer = (
            f"Yes. Overall status is green. {ng} checks are green, {ny} yellow, {nr} red. "
            f"Green checks: {', '.join(green_names[:10])}. Checked: {ts}."
        )
    elif overall == "red":
        failures = [c for c in checks if c.get("status") == "red"]
        fail_str = "; ".join(f"{c['name']}: {c.get('details','no details')}" for c in failures[:4])
        answer = (
            f"Overall status is RED. {nr} red, {ny} yellow, {ng} green. "
            f"Failed checks: {fail_str}. Checked: {ts}."
        )
    else:
        warns = [c for c in checks if c.get("status") == "yellow"]
        warn_str = "; ".join(f"{c['name']}: {c.get('details','')}" for c in warns[:4])
        answer = (
            f"Overall status is {overall}. {ng} green, {ny} yellow, {nr} red. "
            f"Warnings: {warn_str or 'none listed'}. Checked: {ts}."
        )

    evidence = [
        {"source": "docs/brain/system-status.json", "detail": f"overall_status: {overall}"},
        {"source": "docs/brain/system-status.json", "detail": f"summary: green={ng}, yellow={ny}, red={nr}"},
    ]
    for c in checks:
        if c.get("status") in ("red", "yellow"):
            evidence.append({
                "source": f"check:{c['name']}",
                "detail": f"{c.get('status')}: {c.get('details','')} â€” {c.get('evidence','')}",
            })

    return build_response(
        answer=answer, source="local", confidence="high", category="health",
        evidence=evidence, suggested_questions=_SUGGESTED["health"], cfg=cfg,
    )


def answer_daemon(question: str, cfg: dict) -> dict:  # noqa: ARG001
    sd = load_allowed("docs/brain/system-status.json", cfg)
    if sd is None:
        return build_response(
            answer="System health data is unavailable.",
            source="unavailable", confidence="low", category="daemon",
            evidence=[{"source": "docs/brain/system-status.json", "detail": "File not found"}],
            suggested_questions=_SUGGESTED["daemon"], cfg=cfg,
        )

    checks: list[dict] = sd.get("checks", [])
    daemon_checks = [
        c for c in checks
        if any(kw in c.get("name", "") for kw in ("daemon", "server", "scheduler"))
    ]

    if not daemon_checks:
        return build_response(
            answer="No daemon/server/scheduler checks found in system-status.json.",
            source="local", confidence="medium", category="daemon",
            evidence=[{"source": "docs/brain/system-status.json", "detail": "No daemon checks found"}],
            suggested_questions=_SUGGESTED["daemon"], cfg=cfg,
        )

    parts: list[str] = []
    evidence: list[dict] = []
    for c in daemon_checks:
        status = c.get("status", "unknown")
        name = c.get("name", "").replace("_", " ")
        ev = c.get("evidence", "") or c.get("details", "") or "no details"
        state = "running" if status == "green" else ("not running" if status == "red" else "degraded")
        parts.append(f"{name}: {state} ({ev})")
        evidence.append({"source": f"check:{c['name']}", "detail": f"status={status}; {ev}"})

    return build_response(
        answer="Daemon/server status: " + "; ".join(parts) + ".",
        source="local", confidence="high", category="daemon",
        evidence=evidence, suggested_questions=_SUGGESTED["daemon"], cfg=cfg,
    )


def answer_graph_status(question: str, cfg: dict, gc: dict) -> dict:
    if not gc:
        return build_response(
            answer="Graph data is unavailable (docs/brain/graph.json not found or unreadable).",
            source="unavailable", confidence="low", category="graph",
            evidence=[{"source": "docs/brain/graph.json", "detail": "File not found or cache empty"}],
            suggested_questions=_SUGGESTED["graph"], cfg=cfg,
        )

    node_count: int = gc.get("node_count", 0)
    link_count: int = gc.get("link_count", 0)
    type_counts: dict = gc.get("node_type_counts", {})
    top10: list = gc.get("top10_degree", [])

    type_parts = sorted(type_counts.items(), key=lambda kv: -kv[1])
    type_str = ", ".join(f"{t} ({c})" for t, c in type_parts[:10])

    answer = f"The graph contains {node_count} nodes and {link_count} links. Node types: {type_str}."

    q = question.lower()
    if any(kw in q for kw in ("biggest", "highest degree", "top node")):
        top_str = ", ".join(f"{nid} ({deg})" for nid, deg in top10[:5])
        answer += f" Top nodes by connections: {top_str}."

    nodes_by_type: dict = gc.get("nodes_by_type", {})
    for kw, ntype in (("agent", "agent"), ("workflow", "workflow"), ("topic", "topic"),
                      ("artifact", "artifact"), ("tool", "tool")):
        if kw in q:
            examples = nodes_by_type.get(ntype, [])[:5]
            if examples:
                answer += f" Example {ntype}s: {', '.join(examples)}."

    evidence = [
        {"source": "docs/brain/graph.json", "detail": f"node_count={node_count}, link_count={link_count}"},
        {"source": "docs/brain/graph.json", "detail": f"types: {type_str[:200]}"},
    ]
    if top10:
        evidence.append({"source": "docs/brain/graph.json",
                         "detail": f"highest degree: {top10[0][0]} ({top10[0][1]} connections)"})

    return build_response(
        answer=answer, source="local", confidence="high", category="graph",
        evidence=evidence, suggested_questions=_SUGGESTED["graph"], cfg=cfg,
    )


def _extract_node_subject(question: str) -> str:
    """Extract the node subject from a node-lookup question.
    More-specific patterns must appear before less-specific ones."""
    q = question.strip().rstrip("?")
    patterns = [
        r"^what is connected to\s+",
        r"^what is related to\s+",
        r"^what is .+? in charge of\s*$",
        r"^what files does\s+(.+?)\s+reference",
        r"^what does\s+(.+?)\s+do",
        r"^tell me about\s+",
        r"^show connections (for|of)\s+",
        r"^show referenced files (for|of)\s+",
        r"^neighbors of\s+",
        r"^(find|what) related.+\bfor\s+",
        r"^(find|what) related.+\bto\s+",
        r"^what (is|are)\s+",
        r"^what (does|did)\s+",
    ]
    for pat in patterns:
        m = re.match(pat, q, re.IGNORECASE)
        if m:
            if m.lastindex:
                return m.group(m.lastindex).strip()
            rest = q[m.end():]
            rest = re.sub(r"\s+(do|does|reference|connect|handle|node|agent|workflow|topic|tool)$", "",
                          rest, flags=re.IGNORECASE)
            return rest.strip()
    cleaned = re.sub(r"^(tell|show|find|what|who|how|which|is|are|the|an?)\s+",
                     "", q, flags=re.IGNORECASE)
    return cleaned.strip()


def answer_node_lookup(question: str, cfg: dict, gc: dict,
                       selected_node_id: str | None = None) -> dict:
    if not gc:
        return build_response(
            answer="Graph data is unavailable.",
            source="unavailable", confidence="low", category="node",
            evidence=[], suggested_questions=_SUGGESTED["node"], cfg=cfg,
        )

    node_by_id: dict = gc.get("node_by_id", {})
    neighbors_map: dict = gc.get("neighbors", {})
    degree_map: dict = gc.get("degree", {})

    if selected_node_id and selected_node_id in node_by_id:
        matches = [node_by_id[selected_node_id]]
    else:
        subject = _extract_node_subject(question) or question
        matches = _fuzzy_find_node(subject, gc)

    if not matches:
        return build_response(
            answer="I could not find a matching node in the graph. Try using the exact node ID or title.",
            source="local", confidence="low", category="node",
            evidence=[{"source": "docs/brain/graph.json", "detail": "No matching node found"}],
            suggested_questions=_SUGGESTED["node"], cfg=cfg,
        )

    if len(matches) > 1 and not (selected_node_id and selected_node_id in node_by_id):
        opts = "\n".join(
            f"â€¢ {nd['id']} ({nd.get('type','?')}): {nd.get('title','')}"
            for nd in matches[:5]
        )
        return build_response(
            answer=f"I found multiple matching nodes. Which one did you mean?\n{opts}",
            source="local", confidence="medium", category="node",
            evidence=[{"source": "docs/brain/graph.json",
                       "detail": f"{len(matches)} nodes matched â€” please be more specific"}],
            suggested_questions=[f"Tell me about {nd['id']}" for nd in matches[:3]],
            cfg=cfg,
        )

    nd = matches[0]
    nid: str = nd.get("id", "")
    title: str = nd.get("title", nid)
    ntype: str = nd.get("type", "unknown")
    deg: int = degree_map.get(nid, 0)
    tags: list = nd.get("tags", [])
    files: list = nd.get("files", [])
    path: str = nd.get("path", "")

    raw_neighbors: list[dict] = neighbors_map.get(nid, [])
    neighbor_by_type: dict[str, list[str]] = {}
    for nb_info in raw_neighbors[:24]:
        nb_id = nb_info.get("id", "")
        nb_nd = node_by_id.get(nb_id)
        if not nb_nd:
            continue
        nt = nb_nd.get("type", "unknown")
        neighbor_by_type.setdefault(nt, []).append(nb_nd.get("title", nb_id))

    q = question.lower()
    is_resp_q = bool(re.search(r"in charge of|responsible for|what does.+do|what is.+do|what.+role", q))

    parts = [f"{title} is a {ntype} node. It has {deg} graph connection{'s' if deg != 1 else ''}."]
    if tags:
        parts.append(f"Tags: {', '.join(tags)}.")
    if path:
        parts.append(f"Path: {path}.")
    if neighbor_by_type:
        nb_parts = []
        for nt, names in sorted(neighbor_by_type.items()):
            nb_parts.append(f"{nt}: {', '.join(names[:4])}")
        parts.append(f"Connected to: {'; '.join(nb_parts[:5])}.")
    if files:
        parts.append(f"References files: {', '.join(files[:4])}.")
    if is_resp_q:
        if neighbor_by_type:
            conn_ids = [nb["id"] for nb in raw_neighbors[:6] if nb.get("id") in node_by_id]
            parts.append(
                f"Based on graph connections, it is related to: {', '.join(conn_ids)}. "
                "(Inferred from graph links â€” no standalone description is stored.)"
            )
        else:
            parts.append("Evidence is limited: no connected nodes found in the graph.")

    evidence: list[dict] = [
        {"source": "docs/brain/graph.json", "detail": f"node: id={nid}, type={ntype}, degree={deg}"},
    ]
    for f in files[:3]:
        evidence.append({"source": "docs/brain/graph.json", "detail": f"file: {f}"})
    for nb_info in raw_neighbors[:4]:
        nb_id = nb_info.get("id", "")
        lt = nb_info.get("link_type", "related_to")
        if nb_id in node_by_id:
            evidence.append({"source": "docs/brain/graph.json",
                             "detail": f"link: {nid} â€”[{lt}]â†’ {nb_id}"})

    return build_response(
        answer=" ".join(parts),
        source="local",
        confidence="high" if (selected_node_id and selected_node_id in node_by_id) else "medium",
        category="node",
        evidence=evidence,
        suggested_questions=[
            f"What is connected to {title}?",
            f"What workflows are related to {title}?",
            f"What agents are related to {title}?",
        ],
        cfg=cfg,
    )


def _extract_routing_subject(question: str) -> str:
    q = question.strip()
    patterns = [
        r"^what handles?\s+",
        r"^who handles?\s+",
        r"^what agents? handle\s+",
        r"^what knowledge exists for\s+",
        r"^what (workflows?|agents?|knowledge) (are|is) related to\s+",
        r"^what is related to\s+",
        r"^what is connected to\s+",
    ]
    for pat in patterns:
        m = re.match(pat, q, re.IGNORECASE)
        if m:
            return q[m.end():].strip().rstrip("?")
    return ""


def answer_routing(question: str, cfg: dict, gc: dict) -> dict:
    if not gc:
        return build_response(
            answer="Graph data is unavailable.",
            source="unavailable", confidence="low", category="routing",
            evidence=[], suggested_questions=_SUGGESTED["routing"], cfg=cfg,
        )

    subject = _extract_routing_subject(question)
    if not subject:
        return build_response(
            answer="I could not determine what you are asking about. Try: 'What handles Orchestration?'",
            source="local", confidence="low", category="routing",
            evidence=[], suggested_questions=_SUGGESTED["routing"], cfg=cfg,
        )

    node_by_id: dict = gc.get("node_by_id", {})
    neighbors_map: dict = gc.get("neighbors", {})
    degree_map: dict = gc.get("degree", {})

    matches = _fuzzy_find_node(subject, gc)
    if not matches:
        return build_response(
            answer=f"No graph evidence found for '{subject}'. Try a node ID or title.",
            source="local", confidence="low", category="routing",
            evidence=[{"source": "docs/brain/graph.json",
                       "detail": f"No node matched '{subject}'"}],
            suggested_questions=_SUGGESTED["routing"], cfg=cfg,
        )

    nd = matches[0]
    nid: str = nd.get("id", "")
    title: str = nd.get("title", nid)
    raw_neighbors: list[dict] = neighbors_map.get(nid, [])

    agents, workflows, knowledge, validators, tools, others = [], [], [], [], [], []
    for nb_info in raw_neighbors:
        nb_id = nb_info.get("id", "")
        nb_nd = node_by_id.get(nb_id)
        if not nb_nd:
            continue
        nt = nb_nd.get("type", "")
        nb_title = nb_nd.get("title", nb_id)
        if nt == "agent":
            agents.append(nb_title)
        elif nt == "workflow":
            workflows.append(nb_title)
        elif nt == "knowledge":
            knowledge.append(nb_title)
        elif nt in ("validation-gate", "test-suite"):
            validators.append(nb_title)
        elif nt == "tool":
            tools.append(nb_title)
        else:
            others.append(nb_title)

    if not any([agents, workflows, knowledge, validators, tools, others]):
        return build_response(
            answer=f"Node '{title}' exists in the graph but has no linked agents, workflows, or knowledge.",
            source="local", confidence="medium", category="routing",
            evidence=[{"source": "docs/brain/graph.json",
                       "detail": f"node={nid}, degree={degree_map.get(nid,0)}, no typed neighbors found"}],
            suggested_questions=_SUGGESTED["routing"], cfg=cfg,
        )

    parts = [f"For '{title}':"]
    if agents:
        parts.append(f"Agents: {', '.join(agents[:6])}.")
    if workflows:
        parts.append(f"Workflows: {', '.join(workflows[:6])}.")
    if knowledge:
        parts.append(f"Knowledge: {', '.join(knowledge[:5])}.")
    if validators:
        parts.append(f"Validators: {', '.join(validators[:4])}.")
    if tools:
        parts.append(f"Tools: {', '.join(tools[:4])}.")
    if others and not any([agents, workflows, knowledge]):
        parts.append(f"Related: {', '.join(others[:5])}.")

    evidence: list[dict] = [
        {"source": "docs/brain/graph.json",
         "detail": f"primary node: {nid} ({nd.get('type','?')})"},
    ]
    for nb_info in raw_neighbors[:5]:
        nb_id = nb_info.get("id", "")
        lt = nb_info.get("link_type", "related_to")
        if nb_id in node_by_id:
            evidence.append({"source": "docs/brain/graph.json",
                             "detail": f"{nid} â€”[{lt}]â†’ {nb_id}"})

    return build_response(
        answer=" ".join(parts),
        source="local", confidence="high", category="routing",
        evidence=evidence,
        suggested_questions=[
            f"Tell me about {title}",
            f"What is connected to {title}?",
            "What is the graph status?",
        ],
        cfg=cfg,
    )


def answer_manifest(question: str, cfg: dict) -> dict:  # noqa: ARG001
    manifest = load_allowed(".claude/state/execution-manifest.json", cfg)
    if manifest is None:
        return build_response(
            answer="Execution manifest is unavailable. No active task or file not found.",
            source="unavailable", confidence="low", category="manifest",
            evidence=[{"source": ".claude/state/execution-manifest.json",
                       "detail": "File not found or not in allowlist"}],
            suggested_questions=_SUGGESTED["manifest"], cfg=cfg,
        )

    task_type = manifest.get("task_type", "unknown")
    workflow = manifest.get("selected_workflow", "unknown")
    agents: list = manifest.get("required_agents", [])
    artifacts: list = manifest.get("required_artifacts", [])
    validations: list = manifest.get("required_validations", [])
    stop_gates: list = manifest.get("stop_gate_requirements", [])
    tier = manifest.get("planning_tier", "")
    effort = manifest.get("execution_effort_tier", "")
    plan_frozen = manifest.get("plan_frozen", False)

    parts = [f"Current task type: {task_type}.", f"Selected workflow: {workflow}."]
    if tier:
        parts.append(f"Planning tier: {tier}.")
    if effort:
        parts.append(f"Execution effort: {effort}.")
    if agents:
        parts.append(f"Required agents ({len(agents)}): {', '.join(agents[:6])}.")
    if artifacts:
        parts.append(f"Required artifacts: {', '.join(str(a) for a in artifacts[:5])}.")
    if validations:
        parts.append(f"Required validations: {', '.join(str(v) for v in validations[:5])}.")
    if stop_gates:
        parts.append(f"Stop gate requirements: {', '.join(str(s) for s in stop_gates[:4])}.")
    parts.append(f"Plan frozen: {plan_frozen}.")

    return build_response(
        answer=" ".join(parts),
        source="local", confidence="high", category="manifest",
        evidence=[
            {"source": ".claude/state/execution-manifest.json",
             "detail": f"task_type={task_type}, workflow={workflow}"},
            {"source": ".claude/state/execution-manifest.json",
             "detail": f"agents={len(agents)}, artifacts={len(artifacts)}, validations={len(validations)}"},
        ],
        suggested_questions=_SUGGESTED["manifest"], cfg=cfg,
    )


def answer_scheduler(question: str, cfg: dict) -> dict:  # noqa: ARG001
    allow_model: bool = cfg.get("allow_model_fallback", False)
    sched_dec = load_allowed(".claude/state/scheduler-decision.json", cfg)
    model_eff = load_allowed(".claude/state/model-effort-schedule.json", cfg)

    parts: list[str] = []
    evidence: list[dict] = []

    parts.append(
        f"Model fallback: {'enabled' if allow_model else 'disabled â€” not configured'}."
    )
    evidence.append({"source": ".claude/brain/citadel-ask-config.json",
                     "detail": f"allow_model_fallback={allow_model}"})

    if sched_dec:
        cheap = sched_dec.get("cheap_execution_allowed", "unknown")
        workflow = sched_dec.get("selected_workflow", "unknown")
        tier = sched_dec.get("planning_tier", "unknown")
        parts.append(f"Scheduler: workflow={workflow}, planning_tier={tier}, cheap_execution_allowed={cheap}.")
        evidence.append({"source": ".claude/state/scheduler-decision.json",
                         "detail": f"workflow={workflow}, tier={tier}, cheap={cheap}"})
    else:
        parts.append("Scheduler decision: unavailable.")

    if model_eff:
        exec_t = model_eff.get("execution_effort_tier", "unknown")
        plan_t = model_eff.get("planning_effort_tier", "unknown")
        parts.append(f"Model effort: execution={exec_t}, planning={plan_t}.")
        evidence.append({"source": ".claude/state/model-effort-schedule.json",
                         "detail": f"execution={exec_t}, planning={plan_t}"})
    else:
        parts.append("Model effort schedule: unavailable.")

    return build_response(
        answer=" ".join(parts),
        source="local",
        confidence="high" if sched_dec else "medium",
        category="scheduler",
        evidence=evidence,
        suggested_questions=_SUGGESTED["scheduler"],
        cfg=cfg,
    )


def _normalize_query_ws(q: str) -> str:
    """Normalize a workspace query for alias lookup."""
    return re.sub(r"[\s\-]+", "_", q.strip().lower())


def answer_workspace(question: str, cfg: dict) -> dict:
    """Answer workspace/repo overview questions from local indexes."""
    wc = build_workspace_index_cache(cfg)
    if not wc.get("available"):
        return build_response(
            answer="Workspace intelligence index not available. Run: "
                   "python tools/build_workspace_intelligence_index.py",
            source="unavailable", confidence="low", category="workspace",
            evidence=[], suggested_questions=_SUGGESTED["workspace"], cfg=cfg,
        )
    repos = wc.get("repos", [])
    repo_count = wc.get("repo_count", 0)
    file_count = wc.get("file_count", 0)
    answer = (
        f"I know {repo_count} repo(s): {', '.join(repos[:10])}. "
        f"Total indexed files: {file_count}. "
        f"Workspace root: {wc.get('workspace_root', 'unknown')}. "
        "Exact lookups are O(1); reuse retrieval is near-instant via precomputed indexes."
    )
    return build_response(
        answer=answer, source="local", confidence="high", category="workspace",
        evidence=[
            {"source": ".claude/state/workspace-intelligence/workspace-index.json",
             "detail": f"{repo_count} repos, {file_count} files"},
        ],
        suggested_questions=_SUGGESTED["workspace"], cfg=cfg,
    )


def answer_reuse(question: str, cfg: dict) -> dict:
    """Answer reuse candidate questions from local indexes."""
    wc = build_workspace_index_cache(cfg)
    if not wc.get("available"):
        return build_response(
            answer="Workspace intelligence index not available.",
            source="unavailable", confidence="low", category="reuse",
            evidence=[], suggested_questions=_SUGGESTED["reuse"], cfg=cfg,
        )

    q_lower = question.lower()
    norm = _normalize_query_ws(q_lower)
    reuse = wc.get("reuse", {})
    alias_idx = wc.get("alias_index", {})
    features = wc.get("features", {})

    canonical = alias_idx.get(norm) or alias_idx.get(norm.replace("_", " "))
    if not canonical:
        words = re.findall(r"[a-z][a-z0-9_]{1,}", norm)
        for word in words:
            if word in reuse:
                canonical = word
                break
            if word in alias_idx:
                canonical = alias_idx[word]
                break

    if canonical and canonical in reuse:
        rc = reuse[canonical]
        files = rc.get("candidate_files", [])[:5]
        modules = rc.get("candidate_modules", [])[:5]
        tests = rc.get("candidate_tests", [])[:3]
        confidence = rc.get("confidence", "medium")
        why = rc.get("why_reusable", [])
        evidence_list = rc.get("evidence", [])
        answer = (
            f"For '{canonical}': found {len(files)} file(s), {len(modules)} module(s), "
            f"{len(tests)} test file(s). Confidence: {confidence}. "
        )
        if why:
            answer += " ".join(why[:2]) + ". "
        if files:
            answer += f"Key files: {', '.join(files[:3])}."
        if modules:
            answer += f" Modules: {', '.join(modules[:2])}."
        return build_response(
            answer=answer, source="local", confidence=confidence, category="reuse",
            evidence=[{"source": ".claude/state/workspace-intelligence/reuse-candidate-index.json",
                       "detail": e} for e in evidence_list[:4]],
            suggested_questions=_SUGGESTED["reuse"], cfg=cfg,
        )

    feat_keys = sorted(features.keys())[:10]
    answer = (
        f"No exact reuse match for '{question}'. "
        f"Known features: {', '.join(feat_keys)}. "
        "Try: reuse 'sample feature', 'rate rate', 'orchestration asset check', 'schemaval'."
    )
    return build_response(
        answer=answer, source="local", confidence="low", category="reuse",
        evidence=[{"source": ".claude/state/workspace-intelligence/feature-index.json",
                   "detail": f"{len(feat_keys)} known features"}],
        suggested_questions=_SUGGESTED["reuse"], cfg=cfg,
    )


def answer_feature(question: str, cfg: dict) -> dict:
    """Answer 'where is X implemented?' questions from local indexes."""
    wc = build_workspace_index_cache(cfg)
    if not wc.get("available"):
        return build_response(
            answer="Workspace intelligence index not available.",
            source="unavailable", confidence="low", category="feature",
            evidence=[], suggested_questions=_SUGGESTED["feature"], cfg=cfg,
        )

    q_lower = question.lower()
    norm = _normalize_query_ws(q_lower)
    features = wc.get("features", {})
    alias_idx = wc.get("alias_index", {})

    canonical = alias_idx.get(norm) or alias_idx.get(norm.replace("_", " "))
    if not canonical:
        words = re.findall(r"[a-z][a-z0-9_]{1,}", norm)
        for word in words:
            if word in features:
                canonical = word
                break

    if canonical and canonical in features:
        fi = features[canonical]
        files = fi.get("files", [])[:5]
        modules = fi.get("modules", [])[:5]
        tests = fi.get("tests", [])[:3]
        answer = (
            f"Feature '{canonical}' is implemented in {len(files)} file(s), "
            f"{len(modules)} module(s), {len(tests)} test file(s). "
        )
        if files:
            answer += f"Files: {', '.join(files[:3])}."
        if modules:
            answer += f" Modules: {', '.join(modules[:2])}."
        return build_response(
            answer=answer, source="local", confidence="high", category="feature",
            evidence=[{"source": ".claude/state/workspace-intelligence/feature-index.json",
                       "detail": f"feature={canonical}, files={len(files)}, modules={len(modules)}"}],
            suggested_questions=_SUGGESTED["feature"], cfg=cfg,
        )

    feat_keys = sorted(features.keys())[:8]
    return build_response(
        answer=f"Feature not found for '{question}'. Known: {', '.join(feat_keys)}.",
        source="local", confidence="low", category="feature",
        evidence=[{"source": ".claude/state/workspace-intelligence/feature-index.json",
                   "detail": f"{len(features)} features indexed"}],
        suggested_questions=_SUGGESTED["feature"], cfg=cfg,
    )


def answer_tests_ws(question: str, cfg: dict) -> dict:
    """Answer test coverage questions from local indexes."""
    wc = build_workspace_index_cache(cfg)
    if not wc.get("available"):
        return build_response(
            answer="Workspace intelligence index not available.",
            source="unavailable", confidence="low", category="tests",
            evidence=[], suggested_questions=_SUGGESTED["tests"], cfg=cfg,
        )

    q_lower = question.lower()
    norm = _normalize_query_ws(q_lower)
    test_idx = wc.get("test_index", {})
    alias_idx = wc.get("alias_index", {})

    canonical = alias_idx.get(norm) or alias_idx.get(norm.replace("_", " "))
    if not canonical:
        words = re.findall(r"[a-z][a-z0-9_]{1,}", norm)
        for word in words:
            if word in test_idx:
                canonical = word
                break

    if canonical and canonical in test_idx:
        entries = test_idx[canonical]
        file_count = len(entries) if isinstance(entries, list) else 0
        answer = f"Found {file_count} test file(s) for feature '{canonical}'."
        if isinstance(entries, list) and entries:
            paths = [e.get("file_id", "") for e in entries[:3] if isinstance(e, dict)]
            if paths:
                answer += f" Files: {', '.join(paths[:3])}."
        return build_response(
            answer=answer, source="local", confidence="high", category="tests",
            evidence=[{"source": ".claude/state/workspace-intelligence/test-index.json",
                       "detail": f"feature={canonical}, test_files={file_count}"}],
            suggested_questions=_SUGGESTED["tests"], cfg=cfg,
        )

    return build_response(
        answer=f"No test coverage data found for '{question}'. "
               f"Known test features: {', '.join(sorted(test_idx.keys())[:5])}.",
        source="local", confidence="low", category="tests",
        evidence=[{"source": ".claude/state/workspace-intelligence/test-index.json",
                   "detail": f"{len(test_idx)} features with tests"}],
        suggested_questions=_SUGGESTED["tests"], cfg=cfg,
    )


def answer_file_ws(question: str, cfg: dict) -> dict:
    """Answer file/module/symbol lookup questions."""
    wc = build_workspace_index_cache(cfg)
    if not wc.get("available"):
        return build_response(
            answer="Workspace intelligence index not available.",
            source="unavailable", confidence="low", category="file",
            evidence=[], suggested_questions=_SUGGESTED["file"], cfg=cfg,
        )
    return build_response(
        answer=(
            "Use the query tool for precise file/module/symbol lookups: "
            "python tools/workspace_intelligence_query.py file REPO:PATH, "
            "module MODULE.NAME, or symbol SYMBOL_NAME. "
            f"Total indexed: {wc.get('file_count', 0)} files."
        ),
        source="local", confidence="medium", category="file",
        evidence=[{"source": ".claude/state/workspace-intelligence/build-metadata.json",
                   "detail": f"file_count={wc.get('file_count', 0)}"}],
        suggested_questions=_SUGGESTED["file"], cfg=cfg,
    )


def answer_artifact_ws(question: str, cfg: dict) -> dict:  # noqa: ARG001
    """Answer artifact-type questions."""
    artifact_idx = load_allowed(".claude/state/workspace-intelligence/artifact-index.json", cfg)
    artifact_idx = {k: v for k, v in (artifact_idx or {}).items()
                    if k not in ("schema_version", "generated_at", "build_id")}
    if artifact_idx:
        types = list(artifact_idx.keys())[:10]
        counts = {t: len(artifact_idx[t]) if isinstance(artifact_idx[t], list) else 0 for t in types}
        answer = f"Known artifact types: {', '.join(f'{t}({counts[t]})' for t in types)}."
        return build_response(
            answer=answer, source="local", confidence="high", category="artifact",
            evidence=[{"source": ".claude/state/workspace-intelligence/artifact-index.json",
                       "detail": f"{len(types)} artifact types"}],
            suggested_questions=_SUGGESTED["artifact"], cfg=cfg,
        )
    return build_response(
        answer="Artifact index not available. Run workspace intelligence build.",
        source="unavailable", confidence="low", category="artifact",
        evidence=[], suggested_questions=_SUGGESTED["artifact"], cfg=cfg,
    )


def answer_dependency_ws(question: str, cfg: dict) -> dict:  # noqa: ARG001
    """Answer dependency/import questions."""
    wc = build_workspace_index_cache(cfg)
    return build_response(
        answer=(
            "Use the query tool for dependency lookups: "
            "python tools/workspace_intelligence_query.py module MODULE.NAME "
            "or reuse FEATURE for import-aware reuse candidates. "
            f"Total indexed: {wc.get('file_count', 0)} files."
        ),
        source="local", confidence="medium", category="dependency",
        evidence=[{"source": ".claude/state/workspace-intelligence/import-index.json",
                   "detail": "import + reverse-import indexes available"}],
        suggested_questions=_SUGGESTED["dependency"], cfg=cfg,
    )


def answer_skills(question: str, cfg: dict) -> dict:
    """Answer skill count/list questions from .claude/skills/ directory."""
    skills_dir = _CLAUDE_DIR / "skills"
    q = question.lower()

    if not skills_dir.exists():
        return build_response(
            answer="Skills directory (.claude/skills/) not found. Cannot count skills locally.",
            source="unavailable", confidence="low", category="skills",
            evidence=[{"source": ".claude/skills/", "detail": "directory not found"}],
            suggested_questions=_SUGGESTED.get("skills", []), cfg=cfg,
        )

    skills: list[str] = sorted(
        e.stem if e.is_file() else e.name
        for e in skills_dir.iterdir()
        if not e.name.startswith(".") and e.name not in {"__pycache__"}
        and (e.is_dir() or e.suffix == ".md")
    )
    count = len(skills)
    evidence = [{"source": ".claude/skills/", "detail": f"{count} skills found"}]

    if re.search(r"\bhow many\b|\bcount\b", q):
        answer = f"We currently have {count} skill{'s' if count != 1 else ''}. Source: .claude/skills/."
    elif re.search(r"\blist\b|\bwhat\b|\bwhich\b|\bshow\b", q):
        answer = f"We have {count} skills: {', '.join(skills)}."
    else:
        answer = f"We currently have {count} skill{'s' if count != 1 else ''}. Use 'list skills' to see them all."

    return build_response(
        answer=answer, source="local", confidence="high", category="skills",
        evidence=evidence, suggested_questions=_SUGGESTED.get("skills", []), cfg=cfg,
    )


def answer_agents(question: str, cfg: dict) -> dict:
    """Answer agent count/list questions from .claude/agents/ directory."""
    agents_dir = _CLAUDE_DIR / "agents"
    q = question.lower()

    if not agents_dir.exists():
        return build_response(
            answer="Agents directory (.claude/agents/) not found. Cannot count agents locally.",
            source="unavailable", confidence="low", category="agents",
            evidence=[{"source": ".claude/agents/", "detail": "directory not found"}],
            suggested_questions=_SUGGESTED.get("agents", []), cfg=cfg,
        )

    agents: list[str] = sorted(
        e.stem
        for e in agents_dir.iterdir()
        if e.suffix == ".md" and not e.name.startswith(".")
    )
    count = len(agents)
    evidence = [{"source": ".claude/agents/", "detail": f"{count} agent definitions found"}]

    if re.search(r"\bhow many\b|\bcount\b", q):
        answer = f"We currently have {count} agent{'s' if count != 1 else ''}. Source: .claude/agents/."
    elif re.search(r"\blist\b|\bwhat\b|\bwhich\b|\bshow\b", q):
        answer = f"We have {count} agents: {', '.join(agents)}."
    else:
        answer = f"We currently have {count} agent{'s' if count != 1 else ''}. Use 'list agents' to see them all."

    return build_response(
        answer=answer, source="local", confidence="high", category="agents",
        evidence=evidence, suggested_questions=_SUGGESTED.get("agents", []), cfg=cfg,
    )


def answer_workflows(question: str, cfg: dict) -> dict:
    """Answer workflow count/list questions from workflow-manifest-config.json."""
    manifest_path = _CLAUDE_DIR / "brain" / "workflow-manifest-config.json"
    q = question.lower()

    if not manifest_path.exists():
        return build_response(
            answer="Workflow manifest (.claude/brain/workflow-manifest-config.json) not found.",
            source="unavailable", confidence="low", category="workflows",
            evidence=[{"source": ".claude/brain/workflow-manifest-config.json", "detail": "not found"}],
            suggested_questions=_SUGGESTED.get("workflows", []), cfg=cfg,
        )

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return build_response(
            answer="Workflow manifest could not be parsed.",
            source="unavailable", confidence="low", category="workflows",
            evidence=[{"source": ".claude/brain/workflow-manifest-config.json", "detail": "parse error"}],
            suggested_questions=_SUGGESTED.get("workflows", []), cfg=cfg,
        )

    raw_tt = manifest.get("task_types", {})
    if isinstance(raw_tt, dict):
        task_types: list[str] = list(raw_tt.keys())
    elif isinstance(raw_tt, list):
        task_types = [t if isinstance(t, str) else str(t) for t in raw_tt]
    else:
        task_types = []
    count = len(task_types)
    evidence = [{
        "source": ".claude/brain/workflow-manifest-config.json",
        "detail": f"{count} workflow types (version {manifest.get('version', '?')})",
    }]

    if re.search(r"\bhow many\b|\bcount\b", q):
        answer = f"We have {count} workflow type{'s' if count != 1 else ''}. Source: workflow-manifest-config.json."
    elif re.search(r"\blist\b|\bwhat\b|\bwhich\b|\bshow\b", q):
        answer = f"We have {count} workflow types: {', '.join(task_types)}."
    else:
        answer = f"We have {count} workflow types. Use 'list workflows' to see them all."

    return build_response(
        answer=answer, source="local", confidence="high", category="workflows",
        evidence=evidence, suggested_questions=_SUGGESTED.get("workflows", []), cfg=cfg,
    )


def _should_try_fallback(result: dict, cfg: dict) -> bool:
    """Return True if local answer is insufficient and model fallback is enabled."""
    if not cfg.get("allow_model_fallback", False):
        return False
    source = result.get("source", "local")
    confidence = result.get("confidence", "medium")
    return source == "unavailable" or confidence == "low"


def _try_model_fallback(
    question: str,
    category: str,
    local_result: dict,
    cfg: dict,
    selected_node_id: str | None = None,
) -> dict:
    """Attempt Claude fallback with bounded context. Returns merged or fallback result."""
    try:
        import citadel_model_fallback as _vmf  # type: ignore[import]
    except ImportError:
        return local_result

    if not _vmf.is_model_fallback_enabled(cfg):
        return local_result

    local_evidence = local_result.get("evidence", [])
    bounded = _vmf.build_bounded_context(question, category, local_evidence, selected_node_id, cfg)

    if not bounded.get("has_context") and cfg.get("fallback_requires_local_context", True):
        r = dict(local_result)
        r.setdefault("warnings", [])
        r["warnings"].append("Fallback requires local context but none was available.")
        return r

    prompt = _vmf.build_claude_fallback_prompt(question, category, bounded)
    fallback = _vmf.ask_claude_fallback(prompt, cfg)

    if fallback.get("source") == "unavailable":
        r = dict(local_result)
        r.setdefault("warnings", [])
        r["warnings"].extend(fallback.get("warnings", ["Fallback provider unavailable."]))
        return r

    max_ev = cfg.get("max_evidence_items", 8)
    merged_evidence = (local_evidence + fallback.get("evidence", []))[:max_ev]
    was_local = local_result.get("source") != "unavailable"
    merged_source = "local_plus_claude" if was_local else "claude_fallback"
    suggests = fallback.get("suggested_questions") or local_result.get("suggested_questions", [])

    merged = build_response(
        answer=fallback.get("answer", ""),
        source=merged_source,
        confidence=fallback.get("confidence", "medium"),
        category=category,
        evidence=merged_evidence,
        suggested_questions=suggests,
        cfg=cfg,
    )
    merged["model_fallback_used"] = True
    merged["local_context_used"] = bool(local_evidence)
    w = bounded.get("warnings", []) + fallback.get("warnings", [])
    if w:
        merged["warnings"] = w
    return merged


def answer_unknown(question: str, cfg: dict) -> dict:  # noqa: ARG001
    allow_model: bool = cfg.get("allow_model_fallback", False)
    answer = (
        "I can answer local system, graph, health, daemon, routing, node, scheduler, "
        "manifest, skills, agents, and workflows questions. "
        "I do not have enough local evidence to answer that."
    )
    if not allow_model:
        answer += " Model-backed Q&A is not configured."
    return build_response(
        answer=answer, source="unavailable", confidence="low", category="unknown",
        evidence=[], suggested_questions=_SUGGESTED["unknown"], cfg=cfg,
    )


def handle_api_ask(question: str, cfg: dict, selected_node_id: str | None = None) -> dict:
    """Route question to the correct resolver. Local first; optional Claude fallback."""
    gc = build_graph_cache(cfg)
    category = classify_question(question, selected_node_id)

    if category == "permissions":
        local = answer_permissions(question, cfg)
    elif category == "health":
        local = answer_health(question, cfg)
    elif category == "daemon":
        local = answer_daemon(question, cfg)
    elif category == "graph":
        local = answer_graph_status(question, cfg, gc)
    elif category == "node":
        local = answer_node_lookup(question, cfg, gc, selected_node_id)
    elif category == "routing":
        local = answer_routing(question, cfg, gc)
    elif category == "manifest":
        local = answer_manifest(question, cfg)
    elif category == "scheduler":
        local = answer_scheduler(question, cfg)
    elif category == "workspace":
        local = answer_workspace(question, cfg)
    elif category == "reuse":
        local = answer_reuse(question, cfg)
    elif category == "feature":
        local = answer_feature(question, cfg)
    elif category == "tests":
        local = answer_tests_ws(question, cfg)
    elif category == "file":
        local = answer_file_ws(question, cfg)
    elif category == "artifact":
        local = answer_artifact_ws(question, cfg)
    elif category == "dependency":
        local = answer_dependency_ws(question, cfg)
    elif category == "skills":
        local = answer_skills(question, cfg)
    elif category == "agents":
        local = answer_agents(question, cfg)
    elif category == "workflows":
        local = answer_workflows(question, cfg)
    else:
        local = answer_unknown(question, cfg)

    if _should_try_fallback(local, cfg):
        return _try_model_fallback(question, category, local, cfg, selected_node_id)
    return local


def handle_api_health(cfg: dict) -> dict:
    """GET /api/health â€” server liveness + config + full system health."""
    gc = build_graph_cache(cfg)
    sd = load_allowed("docs/brain/system-status.json", cfg)
    health: dict = sd if isinstance(sd, dict) else {}
    return {
        "status": "ok",
        "server": "citadel_ui_server",
        "bind": f"{HOST}:{PORT}",
        "config": {
            "enabled": cfg.get("enabled", True),
            "allow_model_fallback": cfg.get("allow_model_fallback", False),
            "allowlist_count": len(cfg.get("allowed_context_files", [])),
            "cache_enabled": cfg.get("cache_enabled", True),
        },
        "graph_cache": {
            "node_count": gc.get("node_count", 0),
            "link_count": gc.get("link_count", 0),
        },
        "health": health,
        "overall_status": health.get("overall_status", "unavailable"),
        "summary": health.get("summary", {}),
        "checks": health.get("checks", []),
        "epoch_ms": health.get("epoch_ms"),
        "system_health_overall": health.get("overall_status", "unavailable"),
        "generated_at_epoch_ms": int(datetime.now(UTC).timestamp() * 1000),
    }


_WS_STATE_REL = ".claude/state/workspace-intelligence"
_WS_ALLOWED_PARAMS = {"repo", "dir", "module", "file", "symbol", "feature", "q", "limit"}


def _ws_epoch_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _ws_ok(data: object, evidence: list | None = None) -> dict:
    return {"status": "ok", "data": data, "evidence": evidence or [],
            "generated_at_epoch_ms": _ws_epoch_ms()}


def _ws_error(msg: str, hint: str = "") -> dict:
    d: dict = {"error": msg}
    if hint:
        d["hint"] = hint
    return {"status": "error", "data": d, "evidence": [],
            "generated_at_epoch_ms": _ws_epoch_ms()}


def _ws_validate_param(value: str, max_len: int = 300) -> bool:
    """Return True if value is safe to use as an index key (not a filesystem path)."""
    if not value or len(value) > max_len:
        return False
    if ".." in value:
        return False
    return True


def _ws_unwrap(d: dict | None) -> dict:
    """Strip schema wrapper keys; return empty dict on None."""
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items()
            if k not in ("schema_version", "generated_at", "build_id")}


def _ws_parse_params(query_str: str) -> dict[str, str]:
    """Parse query string, allowing only whitelisted parameter names."""
    params: dict[str, str] = {}
    if not query_str:
        return params
    for part in query_str.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            k = k.strip()
            if k in _WS_ALLOWED_PARAMS:
                params[k] = unquote_plus(v)
    return params


def handle_api_workspace(path: str, query_str: str, cfg: dict) -> tuple[int, dict]:
    """Dispatch /api/workspace/<sub> endpoints.  Returns (http_status, response_dict).

    Security contract:
    - Reads only allowlisted index files via load_allowed().
    - No request-supplied filesystem paths.
    - No shell execution, no env access, no external calls.
    - Query params whitelist-filtered; values never used as FS paths.
    """
    sub = path[len("/api/workspace/"):]
    params = _ws_parse_params(query_str)
    limit = 20
    try:
        raw_limit = int(params.get("limit", "20"))
        limit = min(max(1, raw_limit), 100)
    except (ValueError, TypeError):
        pass

    if sub == "summary":
        bm = _ws_unwrap(load_allowed(f"{_WS_STATE_REL}/build-metadata.json", cfg))
        ws = _ws_unwrap(load_allowed(f"{_WS_STATE_REL}/workspace-index.json", cfg))
        if not bm:
            return 503, _ws_error(
                "workspace index not available",
                "Run: python tools/build_workspace_intelligence_index.py"
            )
        data = {
            "build_id": bm.get("build_id", ""),
            "build_duration_sec": bm.get("build_duration_sec", 0),
            "incremental": bm.get("incremental", False),
            "repo_count": bm.get("repo_count", 0),
            "file_count": bm.get("file_count", 0),
            "changed_count": bm.get("changed_count", 0),
            "workspace_root": bm.get("workspace_root", ""),
            "repos": ws.get("repos", []),
            "feature_count": ws.get("feature_count", 0),
            "last_build_at": bm.get("build_at", bm.get("completed_at", "")),
        }
        return 200, _ws_ok(data, [f"{_WS_STATE_REL}/build-metadata.json"])

    if sub == "repos":
        raw = load_allowed(f"{_WS_STATE_REL}/repo-index.json", cfg)
        if raw is None:
            return 503, _ws_error(
                "repo-index not available",
                "Run: python tools/build_workspace_intelligence_index.py"
            )
        repos = _ws_unwrap(raw)
        items = [v for v in repos.values() if isinstance(v, dict)]
        return 200, _ws_ok(items[:limit], [f"{_WS_STATE_REL}/repo-index.json"])

    if sub == "repo":
        name = params.get("repo", "")
        if not name or not _ws_validate_param(name):
            return 400, _ws_error("missing or invalid 'repo' parameter")
        raw = load_allowed(f"{_WS_STATE_REL}/repo-index.json", cfg)
        if raw is None:
            return 503, _ws_error("repo-index not available")
        repos = _ws_unwrap(raw)
        match = repos.get(name)
        if not match:
            for k, v in repos.items():
                if isinstance(v, dict) and name.lower() in k.lower():
                    match = v
                    break
        if match:
            return 200, _ws_ok(match, [f"{_WS_STATE_REL}/repo-index.json"])
        return 404, _ws_error(f"repo not found: {name}")

    if sub == "dir":
        dir_id = params.get("dir", "")
        if not dir_id or not _ws_validate_param(dir_id):
            return 400, _ws_error("missing or invalid 'dir' parameter")
        raw = load_allowed(f"{_WS_STATE_REL}/dir-index.json", cfg)
        if raw is None:
            return 503, _ws_error("dir-index not available")
        dirs = _ws_unwrap(raw)
        match = dirs.get(dir_id)
        if match:
            return 200, _ws_ok(match, [f"{_WS_STATE_REL}/dir-index.json"])
        return 404, _ws_error(f"directory not found: {dir_id}")

    if sub == "module":
        mod = params.get("module", "")
        if not mod or not _ws_validate_param(mod):
            return 400, _ws_error("missing or invalid 'module' parameter")
        raw = load_allowed(f"{_WS_STATE_REL}/module-index.json", cfg)
        if raw is None:
            return 503, _ws_error("module-index not available")
        mods = _ws_unwrap(raw)
        match = mods.get(mod)
        if not match:
            for k, v in mods.items():
                if mod.lower() in k.lower():
                    match = v
                    break
        if match:
            data = match if isinstance(match, dict) else {"files": match}
            return 200, _ws_ok(data, [f"{_WS_STATE_REL}/module-index.json"])
        return 404, _ws_error(f"module not found: {mod}")

    if sub == "file":
        file_id = params.get("file", "")
        if not file_id or not _ws_validate_param(file_id):
            return 400, _ws_error("missing or invalid 'file' parameter")
        raw = load_allowed(f"{_WS_STATE_REL}/file-index.json", cfg)
        if raw is None:
            return 503, _ws_error("file-index not available")
        files = _ws_unwrap(raw)
        match = files.get(file_id)
        if match:
            return 200, _ws_ok(match, [f"{_WS_STATE_REL}/file-index.json"])
        return 404, _ws_error(f"file not found: {file_id}")

    if sub == "symbol":
        sym = params.get("symbol", "")
        if not sym or not _ws_validate_param(sym):
            return 400, _ws_error("missing or invalid 'symbol' parameter")
        raw = load_allowed(f"{_WS_STATE_REL}/symbol-index.json", cfg)
        if raw is None:
            return 503, _ws_error("symbol-index not available")
        syms = _ws_unwrap(raw)
        match = syms.get(sym)
        if match:
            return 200, _ws_ok(match, [f"{_WS_STATE_REL}/symbol-index.json"])
        return 404, _ws_error(f"symbol not found: {sym}")

    if sub == "feature":
        feat = params.get("feature", "")
        if not feat or not _ws_validate_param(feat):
            return 400, _ws_error("missing or invalid 'feature' parameter")
        raw = load_allowed(f"{_WS_STATE_REL}/feature-index.json", cfg)
        if raw is None:
            return 503, _ws_error("feature-index not available")
        feats = _ws_unwrap(raw)
        match = feats.get(feat)
        if match:
            return 200, _ws_ok(match, [f"{_WS_STATE_REL}/feature-index.json"])
        return 404, _ws_error(f"feature not found: {feat}")

    if sub == "search":
        q = params.get("q", "")
        if not q or not _ws_validate_param(q, max_len=200):
            return 400, _ws_error("missing or invalid 'q' parameter")
        try:
            import workspace_intelligence_query as _wsq  # noqa: PLC0415
            result = _wsq.query_search(q, limit)
            return 200, _ws_ok(result, result.get("evidence", []))
        except ImportError as exc:
            return 503, _ws_error(f"workspace query module unavailable: {exc}")
        except Exception as exc:
            return 500, _ws_error(f"search error: {type(exc).__name__}: {exc}")

    if sub == "reuse":
        q = params.get("q", "")
        if not q or not _ws_validate_param(q, max_len=200):
            return 400, _ws_error("missing or invalid 'q' parameter")
        try:
            import workspace_intelligence_query as _wsq  # noqa: PLC0415
            result = _wsq.query_reuse(q, limit)
            return 200, _ws_ok(result, result.get("evidence", []))
        except ImportError as exc:
            return 503, _ws_error(f"workspace query module unavailable: {exc}")
        except Exception as exc:
            return 500, _ws_error(f"reuse error: {type(exc).__name__}: {exc}")

    if sub == "tests":
        q = params.get("q", "")
        if not q or not _ws_validate_param(q, max_len=200):
            return 400, _ws_error("missing or invalid 'q' parameter")
        test_raw = load_allowed(f"{_WS_STATE_REL}/test-index.json", cfg)
        file_raw = load_allowed(f"{_WS_STATE_REL}/file-index.json", cfg)
        test_idx = _ws_unwrap(test_raw)
        file_idx = _ws_unwrap(file_raw)
        results = []
        q_lo = q.lower()
        for feat_id, entries in test_idx.items():
            if q_lo not in feat_id.lower():
                continue
            for te in (entries if isinstance(entries, list) else []):
                fid = te.get("file_id", "")
                fm = file_idx.get(fid, {})
                results.append({
                    "feature": feat_id,
                    "file_id": fid,
                    "path": fm.get("relative_path", fid) if fm else fid,
                    "repo": fm.get("repo", "") if fm else "",
                    "test_names": te.get("tests", []),
                })
        return 200, _ws_ok(results[:limit], [f"{_WS_STATE_REL}/test-index.json"])

    return 404, _ws_error(f"unknown workspace endpoint: /api/workspace/{sub}")


_TASK_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_AUDIT_LOG_PATH = _CLAUDE_DIR / "state" / "ai-provider-audit.log"


def _validate_task_id(tid: str) -> bool:
    return bool(_TASK_ID_RE.match(tid or ""))


def _post_body(rfile, headers, max_bytes: int = MAX_REQUEST_BODY) -> tuple[dict | None, str]:
    length_str = headers.get("Content-Length", "")
    try:
        length = int(length_str) if length_str.strip() else 0
    except ValueError:
        return None, "Invalid Content-Length"
    if length > max_bytes:
        return None, "Request body too large"
    try:
        raw = rfile.read(length) if length > 0 else b""
        return (json.loads(raw) if raw else {}), ""
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"Invalid JSON: {exc}"


def _exec_blocked(reason: str) -> dict:
    return {"status": "blocked", "reason": reason}


def handle_api_providers_status() -> dict:
    try:
        import ai_provider_detection as _apd  # noqa: PLC0415
        return _apd.detect_all()
    except ImportError as exc:
        return {"error": f"ai_provider_detection unavailable: {exc}", "status": "unavailable"}
    except Exception as exc:
        return {"error": str(exc)[:200], "status": "error"}


def handle_api_execute_tasks(status_filter: str | None) -> dict:
    try:
        import citadel_execution_manifest as _em  # noqa: PLC0415
        tasks = _em.list_tasks(status_filter)
        return {
            "status": "ok",
            "count": len(tasks),
            "tasks": [
                {
                    "task_id": t.task_id,
                    "task_title": t.task_title,
                    "task_type": t.task_type,
                    "mode": t.mode,
                    "status": t.status,
                    "risk_level": t.classification.get("risk_level", "low"),
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                }
                for t in tasks
            ],
        }
    except ImportError as exc:
        return _exec_blocked(f"citadel_execution_manifest unavailable: {exc}")
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}


def handle_api_execute_task(task_id: str) -> tuple[int, dict]:
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid task_id format"}
    try:
        from dataclasses import asdict

        import citadel_execution_manifest as _em  # noqa: PLC0415
        m = _em.load_manifest(task_id)
        if m is None:
            return 404, {"error": f"Task {task_id!r} not found"}
        d = asdict(m)
        d.pop("approval", None)
        return 200, {"status": "ok", "task": d}
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_manifest(task_id: str) -> tuple[int, dict]:
    return handle_api_execute_task(task_id)


def handle_api_execute_validation_result(task_id: str) -> tuple[int, dict]:
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid task_id format"}
    try:
        import citadel_validation_runner as _vr  # noqa: PLC0415
        result = _vr.load_validation_result(task_id)
        if result is None:
            return 404, {"error": f"No validation result for task {task_id!r}"}
        return 200, result
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_audit(task_id: str) -> tuple[int, dict]:
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid task_id format"}
    entries: list[dict] = []
    if _AUDIT_LOG_PATH.exists():
        try:
            for line in _AUDIT_LOG_PATH.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    if entry.get("task_id") == task_id:
                        safe = {k: v for k, v in entry.items()
                                if k not in ("prompt", "context", "token", "approval_token")}
                        entries.append(safe)
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
    return 200, {"status": "ok", "task_id": task_id, "entries": entries[-50:]}


def handle_api_execute_plan(body: dict) -> tuple[int, dict]:
    task = str(body.get("task", "")).strip()
    if not task:
        return 400, {"error": "'task' is required"}
    if len(task) > 2000:
        return 400, {"error": "task too long (max 2000 chars)"}
    try:
        import citadel_ai_orchestrator as _orc  # noqa: PLC0415
        result = _orc.run("claude_code_plan_only", body)
        code = 200 if result.get("status") not in ("blocked", "error") else 422
        return code, result
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_approve(body: dict) -> tuple[int, dict]:
    task_id = str(body.get("task_id", "")).strip()
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid or missing task_id"}
    approve_plan = bool(body.get("approve_plan", False))
    approve_execution = bool(body.get("approve_execution", False))
    try:
        import citadel_execution_manifest as _em  # noqa: PLC0415
        m = _em.load_manifest(task_id)
        if m is None:
            return 404, {"error": f"Task {task_id!r} not found"}
        token: str | None = None
        if approve_plan and m.status == "awaiting_plan_approval":
            m.approval.plan_approved = True
            m.approval.approved_by_user = True
            from datetime import datetime, timezone
            m.approval.approved_at = datetime.now(UTC).isoformat()
            if approve_execution:
                m.approval.execution_approved = True
                token = _em.generate_approval_token(m)
                _em.transition(m, "execution_approved", "user_approved_execution")
            else:
                _em._store.save(m)
        elif approve_execution and m.status in ("awaiting_plan_approval", "planned"):
            m.approval.execution_approved = True
            m.approval.approved_by_user = True
            from datetime import datetime, timezone
            m.approval.approved_at = datetime.now(UTC).isoformat()
            token = _em.generate_approval_token(m)
            _em.transition(m, "execution_approved", "user_approved_execution")
        else:
            _em._store.save(m)
        resp: dict = {"status": "ok", "task_id": task_id, "task_status": m.status}
        if token:
            resp["approval_token"] = token
            resp["note"] = "Store this token â€” it is single-use and expires in 30 minutes."
        return 200, resp
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except ValueError as exc:
        return 422, {"error": str(exc)}
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_run(body: dict) -> tuple[int, dict]:
    task_id = str(body.get("task_id", "")).strip()
    token = str(body.get("approval_token", "")).strip()
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid or missing task_id"}
    if not token:
        return 400, {"error": "approval_token is required"}
    try:
        import citadel_ai_orchestrator as _orc  # noqa: PLC0415
        result = _orc.run("claude_code_execute_scoped", body)
        code = 200 if result.get("status") not in ("blocked", "error") else 422
        return code, result
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_review(body: dict) -> tuple[int, dict]:
    task_id = str(body.get("task_id", "")).strip()
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid or missing task_id"}
    try:
        import citadel_ai_orchestrator as _orc  # noqa: PLC0415
        result = _orc.run("cowork_review_only", body)
        code = 200 if result.get("status") not in ("blocked", "error") else 422
        return code, result
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_validate(body: dict) -> tuple[int, dict]:
    task_id = str(body.get("task_id", "")).strip()
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid or missing task_id"}
    try:
        import citadel_execution_manifest as _em  # noqa: PLC0415
        import citadel_validation_runner as _vr  # noqa: PLC0415
        m = _em.load_manifest(task_id)
        if m is None:
            return 404, {"error": f"Task {task_id!r} not found"}
        result = _vr.run_validation(m)
        m.validation_output = result
        _em._store.save(m)
        return 200, result
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_learn(body: dict) -> tuple[int, dict]:
    task_id = str(body.get("task_id", "")).strip()
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid or missing task_id"}
    try:
        import citadel_execution_manifest as _em  # noqa: PLC0415
        m = _em.load_manifest(task_id)
        if m is None:
            return 404, {"error": f"Task {task_id!r} not found"}
        candidate = {
            "task_id": task_id,
            "task_title": m.task_title,
            "what_worked": m.execution_output.get("warnings", []) if m.execution_output else [],
            "what_failed": m.validation_output.get("failed_commands", []) if m.validation_output else [],
            "routing_updates": [],
            "context_updates": [],
            "validation_updates": m.validation_required,
            "skill_updates": m.skills_selected,
            "agent_updates": m.agents_selected,
            "memory_candidates": [],
            "artifact_candidates": [],
            "should_update_memory": m.status == "completed",
            "requires_user_review": True,
        }
        path = _em.write_learning_candidate(task_id, candidate)
        return 200, {"status": "ok", "task_id": task_id, "candidate": candidate, "path": str(path)}
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


def handle_api_execute_cancel(body: dict) -> tuple[int, dict]:
    task_id = str(body.get("task_id", "")).strip()
    reason = str(body.get("reason", "user_cancelled"))[:200]
    if not _validate_task_id(task_id):
        return 400, {"error": "Invalid or missing task_id"}
    try:
        import citadel_execution_manifest as _em  # noqa: PLC0415
        m = _em.load_manifest(task_id)
        if m is None:
            return 404, {"error": f"Task {task_id!r} not found"}
        if m.status == "cancelled":
            return 200, {"status": "already_cancelled", "task_id": task_id}
        try:
            _em.transition(m, "cancelled", reason)
        except ValueError as exc:
            try:
                _em.transition(m, "blocked", reason)
            except ValueError:
                return 422, {"error": f"Cannot cancel from state {m.status!r}: {exc}"}
        return 200, {"status": "cancelled", "task_id": task_id, "reason": reason}
    except ImportError as exc:
        return 503, _exec_blocked(str(exc))
    except Exception as exc:
        return 500, {"error": str(exc)[:200]}


class CitadelHandler(SimpleHTTPRequestHandler):
    """Serves docs/ as static files and handles /api/* endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS_DIR), **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors_headers()
        self.end_headers()

    def _add_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin in ("null", "", f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"):
            self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/api/health":
            try:
                cfg = load_config()
                build_graph_cache(cfg)
                self._respond_json(200, handle_api_health(cfg))
            except Exception as exc:
                print(f"[citadel_ui_server] /api/health error: {exc}", file=sys.stderr)
                self._respond_json(500, {"error": "Internal server error"})
        elif path.startswith("/api/workspace/"):
            try:
                cfg = load_config()
                code, resp = handle_api_workspace(path, parsed.query or "", cfg)
                self._respond_json(code, resp)
            except Exception as exc:
                print(f"[citadel_ui_server] /api/workspace error: {exc}", file=sys.stderr)
                self._respond_json(500, {"error": "Internal server error"})
        elif path == "/api/providers/status":
            try:
                self._respond_json(200, handle_api_providers_status())
            except Exception as exc:
                print(f"[citadel_ui_server] /api/providers/status error: {exc}", file=sys.stderr)
                self._respond_json(500, {"error": "Internal server error"})
        elif path == "/api/ask/stream":
            self._handle_ask_stream(parsed.query or "")
        elif path == "/api/telemetry/stream":
            self._handle_telemetry_stream()
        elif path.startswith("/api/execute/"):
            self._handle_execute_get(path, parsed.query or "")
        else:
            super().do_GET()

    def _handle_execute_get(self, path: str, query: str):
        from urllib.parse import parse_qs
        params = {k: v[0] for k, v in parse_qs(query).items()}
        try:
            if path == "/api/execute/tasks":
                status_filter = params.get("status")
                self._respond_json(200, handle_api_execute_tasks(status_filter))
            elif path == "/api/execute/task":
                task_id = params.get("id", "")
                code, resp = handle_api_execute_task(task_id)
                self._respond_json(code, resp)
            elif path == "/api/execute/manifest":
                task_id = params.get("id", "")
                code, resp = handle_api_execute_manifest(task_id)
                self._respond_json(code, resp)
            elif path == "/api/execute/validation":
                task_id = params.get("id", "")
                code, resp = handle_api_execute_validation_result(task_id)
                self._respond_json(code, resp)
            elif path == "/api/execute/audit":
                task_id = params.get("id", "")
                code, resp = handle_api_execute_audit(task_id)
                self._respond_json(code, resp)
            else:
                self._respond_json(404, {"error": f"Unknown execute endpoint: {path}"})
        except Exception as exc:
            print(f"[citadel_ui_server] {path} error: {exc}", file=sys.stderr)
            self._respond_json(500, {"error": "Internal server error"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/ask":
            self._handle_ask()
        elif path.startswith("/api/execute/"):
            self._handle_execute_post(path)
        else:
            self.send_error(404, "Not found")

    def _handle_execute_post(self, path: str):
        body, err = _post_body(self.rfile, self.headers)
        if body is None:
            self._respond_json(400, {"error": err or "Bad request"})
            return
        try:
            if path == "/api/execute/plan":
                code, resp = handle_api_execute_plan(body)
            elif path == "/api/execute/approve":
                code, resp = handle_api_execute_approve(body)
            elif path == "/api/execute/run":
                code, resp = handle_api_execute_run(body)
            elif path == "/api/execute/review":
                code, resp = handle_api_execute_review(body)
            elif path == "/api/execute/validate":
                code, resp = handle_api_execute_validate(body)
            elif path == "/api/execute/learn":
                code, resp = handle_api_execute_learn(body)
            elif path == "/api/execute/cancel":
                code, resp = handle_api_execute_cancel(body)
            else:
                code, resp = 404, {"error": f"Unknown execute endpoint: {path}"}
            self._respond_json(code, resp)
        except Exception as exc:
            print(f"[citadel_ui_server] {path} error: {exc}", file=sys.stderr)
            self._respond_json(500, {"error": "Internal server error"})

    def _handle_ask(self):
        length_str = self.headers.get("Content-Length", "")
        try:
            length = int(length_str) if length_str.strip() else 0
        except ValueError:
            self._respond_json(400, {"error": "Invalid Content-Length", "source": "unavailable"})
            return
        if length > MAX_REQUEST_BODY:
            self._respond_json(413, {"error": "Request body too large", "source": "unavailable"})
            return

        try:
            body = self.rfile.read(length) if length > 0 else b""
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, OSError) as exc:
            self._respond_json(400, {"error": f"Invalid JSON: {exc}", "source": "unavailable"})
            return

        cfg = load_config()

        question = str(data.get("question", "")).strip()
        if not question:
            self._respond_json(400, {"error": "Missing or empty 'question'", "source": "unavailable"})
            return
        max_q = cfg.get("max_question_chars", 1000)
        if len(question) > max_q:
            self._respond_json(400, {"error": f"Question too long (max {max_q} chars)", "source": "unavailable"})
            return

        if check_blocked(question, cfg):
            refusal = build_response(
                answer="I am not able to answer questions about that topic for security reasons.",
                source="unavailable", confidence="high", category="unknown",
                evidence=[], suggested_questions=_SUGGESTED["unknown"], cfg=cfg,
            )
            self._respond_json(200, refusal)
            return

        raw_snid = data.get("selected_node_id")
        selected_node_id: str | None = None
        if isinstance(raw_snid, str):
            snid = raw_snid.strip()
            if snid and "/" not in snid and "\\" not in snid and len(snid) <= 200:
                selected_node_id = snid

        try:
            answer = handle_api_ask(question, cfg, selected_node_id)
            self._respond_json(200, answer)
        except Exception as exc:
            print(f"[citadel_ui_server] /api/ask error: {exc}", file=sys.stderr)
            self._respond_json(500, {"error": "Internal server error", "source": "unavailable"})

    def _begin_sse(self) -> None:
        """Start an SSE response: 200, text/event-stream, keep-alive. No Content-Length."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._add_cors_headers()
        self.end_headers()

    def _sse_send(self, obj: dict, event: str | None = None) -> bool:
        """Write one SSE frame; return False on client disconnect."""
        try:
            buf = ""
            if event:
                buf += f"event: {event}\n"
            buf += f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
            self.wfile.write(buf.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _sse_comment(self, text: str = "keepalive") -> bool:
        """Write an SSE keepalive comment; return False on client disconnect."""
        try:
            self.wfile.write(f": {text}\n\n".encode())
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _handle_ask_stream(self, query: str) -> None:
        """GET /api/ask/stream?question=â€¦ â€” SSE answer stream (Track A interrogation only).

        Track A (INTERROGATION): streams model answer tokens as 'chunk' events.
        Track B (ACTION): emits a single 'rejected' event with a CLI-only notice.
        Validation failures and model errors emit in-stream 'error' events.
        All paths end with an 'event: done' frame.
        """
        params = {k: v[0] for k, v in parse_qs(query).items()}
        question = params.get("question", "").strip()

        cfg = load_config()
        max_q = cfg.get("max_question_chars", 1000)

        if not question:
            self._begin_sse()
            self._sse_send({"error": "Missing or empty 'question'"}, event="error")
            self._sse_send({}, event="done")
            return
        if len(question) > max_q:
            self._begin_sse()
            self._sse_send({"error": f"Question too long (max {max_q} chars)"}, event="error")
            self._sse_send({}, event="done")
            return
        if check_blocked(question, cfg):
            self._begin_sse()
            self._sse_send(
                {"error": "I am not able to answer questions about that topic for security reasons."},
                event="error",
            )
            self._sse_send({}, event="done")
            return

        if _INTENT_AVAILABLE and _IntentClassifier is not None:
            track = _IntentClassifier().classify(question)
        else:
            track = "INTERROGATION"

        if track == "ACTION":
            self._begin_sse()
            self._sse_send(
                {
                    "message": (
                        "Mutation runs are CLI-only and require operator approval. "
                        "Run: python3 tools/megacorp_orchestrator.py --run '<task>'"
                    ),
                    "track": "ACTION",
                },
                event="rejected",
            )
            self._sse_send({}, event="done")
            return

        self._begin_sse()
        user_message = f"{_DENSE_DIRECTIVE}\n\nPROMPT:\n{question}"

        try:
            if _dispatch_stream is not None:
                for delta in _dispatch_stream(user_message):
                    if not self._sse_send({"delta": delta}, event="chunk"):
                        return
            elif _dispatch is not None:
                full = _dispatch(user_message)
                words = full.split(" ")
                for i in range(0, len(words), 4):
                    chunk = " ".join(words[i : i + 4]) + " "
                    if not self._sse_send({"delta": chunk}, event="chunk"):
                        return
            else:
                self._sse_send({"message": "Model unavailable â€” no dispatcher configured."}, event="error")
                self._sse_send({}, event="done")
                return
        except RuntimeError as exc:
            self._sse_send({"message": f"Model unavailable: {exc}"}, event="error")
            self._sse_send({}, event="done")
            return
        except Exception as exc:
            print(f"[citadel_ui_server] /api/ask/stream error: {exc}", file=sys.stderr)
            self._sse_send({"message": "Unexpected error during streaming."}, event="error")

        self._sse_send({}, event="done")

    def _handle_telemetry_stream(self) -> None:
        """GET /api/telemetry/stream â€” long-lived SSE that tails telemetry-events.ndjson.

        Only events appended after the stream connects are pushed (starts at current EOF).
        Heartbeat comments are sent every ~15 s to keep connections alive through proxies.
        Reads in binary mode so byte offsets match stat().st_size exactly.
        """
        POLL_SECS = 0.5
        HEARTBEAT_SECS = 15.0
        ledger = _CLAUDE_DIR / "state" / "telemetry-events.ndjson"

        self._begin_sse()
        if not self._sse_send({"status": "connected"}, event="ready"):
            return

        pos = ledger.stat().st_size if ledger.exists() else 0
        last_beat = time.monotonic()

        while True:
            sent_any = False
            if ledger.exists():
                try:
                    size = ledger.stat().st_size
                    if size < pos:
                        pos = 0
                    if size > pos:
                        with ledger.open("rb") as fh:
                            fh.seek(pos)
                            chunk = fh.read()
                        pos += len(chunk)
                        for raw_line in chunk.decode("utf-8", errors="replace").splitlines():
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            try:
                                evt = json.loads(raw_line)
                            except json.JSONDecodeError:
                                continue
                            if not self._sse_send(evt):
                                return
                            sent_any = True
                except OSError:
                    pass

            now = time.monotonic()
            if not sent_any and (now - last_beat) >= HEARTBEAT_SECS:
                if not self._sse_comment("keepalive"):
                    return
                last_beat = now
            if sent_any:
                last_beat = now
            time.sleep(POLL_SECS)

    def _respond_json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, fmt: str, *args):  # type: ignore[override]
        print(f"[citadel_ui_server] {self.address_string()} - {fmt % args}", file=sys.stderr)


def _already_healthy(host: str, port: int, timeout: float = 0.5) -> bool:
    """True if a Citadel UI server is already listening and answering /api/health.

    Guards against the common self-heal/restart race: a prior instance is still up
    (pidfile lost, or launched outside daemon management) â€” in that case starting a
    second instance is redundant, not an error, so we exit 0 instead of crashing.
    """
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        ok = resp.status == 200
        resp.read()
        conn.close()
        return ok
    except (OSError, http.client.HTTPException):
        return False


def main() -> None:
    if _already_healthy(HOST, PORT):
        print(
            f"[citadel_ui_server] a healthy server is already listening on "
            f"http://{HOST}:{PORT} â€” exiting (idempotent no-op, not an error)",
            file=sys.stderr,
        )
        return

    try:
        import citadel_execution_manifest as _em  # noqa: PLC0415
        recovered = _em.recover_stuck_tasks()
        if recovered:
            print(f"[citadel_ui_server] recovered {len(recovered)} stuck task(s): {recovered}", file=sys.stderr)
    except ImportError:
        pass

    cfg = load_config()
    gc = build_graph_cache(cfg)
    build_workspace_index_cache(cfg)
    allow_model = cfg.get("allow_model_fallback", False)
    n = gc.get("node_count", 0)
    l = gc.get("link_count", 0)

    try:
        server = ThreadingHTTPServer((HOST, PORT), CitadelHandler)
    except OSError as exc:
        print(
            f"[citadel_ui_server] failed to bind {HOST}:{PORT}: {exc} "
            f"(Address already in use by a process Citadel doesn't manage â€” "
            f"free the port or set CITADEL_UI_PORT)",
            file=sys.stderr,
        )
        sys.exit(1)
    server.allow_reuse_address = True
    server.daemon_threads = True

    _pidfile = _CLAUDE_DIR / "state" / "citadel-ui-server.pid"
    try:
        _pidfile.parent.mkdir(parents=True, exist_ok=True)
        _pidfile.write_text(str(os.getpid()))
    except OSError:
        pass

    def _shutdown(sig, _frame):
        print(f"\n[citadel_ui_server] shutting down (signal {sig})", file=sys.stderr)
        try:
            _pidfile.unlink(missing_ok=True)
        except OSError:
            pass
        t = threading.Thread(target=server.shutdown, daemon=True)
        t.start()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print(
        f"[citadel_ui_server] http://{HOST}:{PORT}/brain/graph.html  "
        f"(model_fallback={'on' if allow_model else 'off'}, "
        f"graph={n}nodes/{l}links)",
        file=sys.stderr,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
