"""Tests for tools/citadel_mcp_server.py — MCP stdio JSON-RPC protocol + tool dispatch."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "citadel_mcp_server.py"


def _talk(ws: Path, requests: list[dict]) -> list[dict]:
    stdin = "".join(json.dumps(r) + "\n" for r in requests)
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    r = subprocess.run(
        [sys.executable, str(TOOL)],
        cwd=str(ws), env=env, input=stdin, capture_output=True, text=True, timeout=30,
    )
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    state = tmp_path / ".claude" / "state" / "workspace-intelligence"
    state.mkdir(parents=True)
    (state / "repo-index.json").write_text(
        json.dumps({"build_id": "x", "repoA": {}, "repoB": {}}), encoding="utf-8")
    return tmp_path


def test_initialize_and_tools_list(ws: Path):
    resp = _talk(ws, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert len(resp) == 2
    assert resp[0]["result"]["protocolVersion"]
    assert resp[0]["result"]["serverInfo"]["name"] == "sovereign-imperia-citadel"
    names = {t["name"] for t in resp[1]["result"]["tools"]}
    assert "legion_workspace_repos" in names
    assert "legion_shell" in names


def test_tools_call_workspace_repos(ws: Path):
    resp = _talk(ws, [
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "legion_workspace_repos", "arguments": {}}},
    ])
    payload = json.loads(resp[0]["result"]["content"][0]["text"])
    assert payload["repo_count"] == 2
    assert set(payload["repos"]) == {"repoA", "repoB"}


def test_tools_call_shell_denies_mutating(ws: Path):
    resp = _talk(ws, [
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "legion_shell", "arguments": {"command": ["git", "push"]}}},
    ])
    payload = json.loads(resp[0]["result"]["content"][0]["text"])
    assert payload["allowed"] is False


def test_unknown_tool_errors(ws: Path):
    resp = _talk(ws, [
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}},
    ])
    assert resp[0]["error"]["code"] == -32602


def test_retrieval_tools_listed(ws: Path):
    resp = _talk(ws, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    names = {t["name"] for t in resp[1]["result"]["tools"]}
    assert {"citadel_search", "citadel_read", "citadel_context"} <= names


def test_citadel_read_is_scoped_and_redacted(ws: Path):
    (ws / "conf.py").write_text("TOKEN=sk-abcdefghijklmnop1234\nvalue = 1\n", encoding="utf-8")
    resp = _talk(ws, [
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "citadel_read", "arguments": {"path": "conf.py"}}},
    ])
    payload = json.loads(resp[0]["result"]["content"][0]["text"])
    assert "sk-abcdefghijklmnop1234" not in payload.get("body", "")
    assert "preamble" in payload


def test_citadel_search_returns_a_shape(ws: Path):
    # Ollama may be absent in CI → the tool degrades to count 0, never crashes.
    resp = _talk(ws, [
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "citadel_search", "arguments": {"query": "anything", "top_k": 3}}},
    ])
    payload = json.loads(resp[0]["result"]["content"][0]["text"])
    assert "count" in payload and "hits" in payload
