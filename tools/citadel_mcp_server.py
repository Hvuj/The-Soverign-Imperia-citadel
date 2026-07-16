#!/usr/bin/env python3
"""citadel_mcp_server.py — The Sovereign Imperia Citadel Z's own MCP server (stdlib stdio JSON-RPC 2.0).

Exposes Legion's read-only, zero-token capabilities as MCP tools so any MCP client — Claude Code,
the Claude CLI, the API, or Claude Cowork — can query the brain, reuse index, bug ledger, workspace
discovery, sharded graph, and run governed read-only shell/grep. No third-party MCP SDK is required;
this implements the MCP stdio transport (newline-delimited JSON-RPC) directly.

Register in .mcp.json (project) or Claude Code settings `mcpServers`:
  { "mcpServers": { "sovereign-imperia-citadel": { "command": "python3",
      "args": ["tools/citadel_mcp_server.py"] } } }

Safety contract: never_call_claude; every tool is read-only (shell tool delegates to
legion_shell.py's default-deny gate).
"""

import json
import os
import sys
from pathlib import Path

import legion_shell
import prompt_usage_miner
from _brain_common import ROOT, STATE, load_json

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "sovereign-imperia-citadel", "version": "1.0.0"}

_retrieval_service = None


def _retrieval():
    """Lazily build the zero-token retrieval service against the active workspace (degrade to None)."""
    global _retrieval_service
    if _retrieval_service is None:
        try:
            from citadel.services.retrieval.service import RetrievalService

            ws = os.environ.get("CITADEL_WORKSPACE", str(ROOT))
            _retrieval_service = RetrievalService.for_workspace(ws)
        except Exception:
            _retrieval_service = False
    return _retrieval_service or None


def _t_prompt_usage(args: dict) -> dict:
    return prompt_usage_miner.lookup(args.get("text", "")) or {"miss": True}


def _t_bug_ledger(_args: dict) -> dict:
    rollup = load_json(STATE / "bug-ledger.json", {})
    open_recs = [r for r in rollup.values() if r.get("status") == "open"]
    return {"total": len(rollup), "open": len(open_recs),
            "records": sorted(open_recs, key=lambda r: -r.get("count", 0))[:20]}


def _t_workspace_repos(_args: dict) -> dict:
    idx = load_json(STATE / "workspace-intelligence" / "repo-index.json", {})
    repos = [k for k in idx if k != "build_id"]
    return {"repo_count": len(repos), "repos": sorted(repos)}


def _t_bi_index(_args: dict) -> dict:
    idx = load_json(STATE / "bi-logic-index.json", {})
    return {"record_count": idx.get("record_count", 0), "by_kind": idx.get("by_kind", {})}


def _t_self_heal_status(_args: dict) -> dict:
    log = STATE / "self-heal.ndjson"
    if not log.exists():
        return {"runs": 0}
    last = ""
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
    try:
        return json.loads(last) if last else {"runs": 0}
    except json.JSONDecodeError:
        return {"runs": 0}


def _t_graph_shard(args: dict) -> dict:
    repo = args.get("repo", "")
    index = load_json(ROOT / "docs" / "brain" / "graph-shard-index.json", {})
    if not repo:
        return {"repos": sorted(index.keys()), "shard_count": len(index)}
    meta = index.get(repo)
    if not meta:
        return {"miss": True, "repo": repo}
    shard = load_json(ROOT / meta["path"], {})
    return {"repo": repo, "node_count": meta.get("node_count", 0),
            "by_type": meta.get("by_type", {}), "nodes": shard.get("nodes", [])[:30]}


def _t_shell(args: dict) -> dict:
    cmd = args.get("command", [])
    if isinstance(cmd, str):
        cmd = cmd.split()
    return legion_shell.run(cmd)


def _t_search(args: dict) -> dict:
    svc = _retrieval()
    if svc is None:
        return {"error": "retrieval service unavailable", "hits": [], "count": 0}
    return svc.search(args.get("query", ""), top_k=int(args.get("top_k", 8)))


def _t_read(args: dict) -> dict:
    svc = _retrieval()
    if svc is None:
        return {"error": "retrieval service unavailable"}
    return svc.read(args.get("path", ""), max_bytes=int(args.get("max_bytes", 16 * 1024)))


def _t_context(args: dict) -> dict:
    svc = _retrieval()
    if svc is None:
        return {"error": "retrieval service unavailable", "chunks": []}
    return svc.context(args.get("task", ""), top_k=int(args.get("top_k", 8)))


TOOLS = [
    {"name": "legion_prompt_usage_lookup",
     "description": "Learned prompt->context bundle (intent/unit/labels) for a prompt, or miss.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]},
     "handler": _t_prompt_usage},
    {"name": "legion_bug_ledger",
     "description": "Open bug records from the bug-record company (deduped, ranked).",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": _t_bug_ledger},
    {"name": "legion_workspace_repos",
     "description": "All discovered workspace repos (workspace-agnostic).",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": _t_workspace_repos},
    {"name": "legion_bi_index",
     "description": "Discovered BI-logic signal counts by kind.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": _t_bi_index},
    {"name": "legion_self_heal_status",
     "description": "Latest init self-heal run summary.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": _t_self_heal_status},
    {"name": "legion_graph_shard",
     "description": "O(1) sharded brain graph: list repos, or a repo's shard nodes (arg: repo).",
     "inputSchema": {"type": "object", "properties": {"repo": {"type": "string"}}},
     "handler": _t_graph_shard},
    {"name": "legion_shell",
     "description": "Run a governed READ-ONLY shell/grep command (default-deny; mutating refused).",
     "inputSchema": {"type": "object",
                     "properties": {"command": {"type": "array", "items": {"type": "string"}}},
                     "required": ["command"]},
     "handler": _t_shell},
    {"name": "citadel_search",
     "description": "Zero-token semantic (dense) code search over the local vector index. Returns cited "
                    "chunks (path + byte range + snippet). Costs no model tokens — the search runs locally.",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                     "required": ["query"]},
     "handler": _t_search},
    {"name": "citadel_read",
     "description": "Read a workspace file, secret-redacted + byte-spliced + count-first (never dumps a whole "
                    "large file). Path is workspace-scoped. Zero model tokens.",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"}, "max_bytes": {"type": "integer"}},
                     "required": ["path"]},
     "handler": _t_read},
    {"name": "citadel_context",
     "description": "Assemble a budgeted, deduped, cited context capsule for a task (pre-digested pack). "
                    "Zero model tokens — retrieval + assembly happen locally.",
     "inputSchema": {"type": "object",
                     "properties": {"task": {"type": "string"}, "top_k": {"type": "integer"}},
                     "required": ["task"]},
     "handler": _t_context},
]
_BY_NAME = {t["name"]: t for t in TOOLS}


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION,
                  "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
    elif method in ("notifications/initialized", "initialized"):
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": t["name"], "description": t["description"],
                             "inputSchema": t["inputSchema"]} for t in TOOLS]}
    elif method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        tool = _BY_NAME.get(name)
        if not tool:
            return _error(req_id, -32602, f"unknown tool: {name}")
        try:
            payload = tool["handler"](params.get("arguments", {}) or {})
        except Exception as exc:
            return _error(req_id, -32603, f"tool error: {exc}")
        result = {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}
    else:
        return _error(req_id, -32601, f"method not found: {method}")
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
