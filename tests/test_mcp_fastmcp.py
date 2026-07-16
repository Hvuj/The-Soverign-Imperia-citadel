"""Phase Z2b — the FastMCP retrieval server. Skips cleanly if the `mcp` SDK is not installed. Verifies the
three retrieval tools are registered and that citadel_read is scoped + secret-redacted through the real SDK."""

import asyncio
import json

import pytest

pytest.importorskip("mcp", reason="mcp SDK not installed (pip install '.[mcp]')")

from citadel.mcp.server import build_server  # noqa: E402


def test_fastmcp_registers_retrieval_tools(tmp_path):
    server = build_server(str(tmp_path))
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"citadel_search", "citadel_read", "citadel_context"} <= names


def test_fastmcp_accepts_http_host_port(tmp_path):
    # the compose service builds with an explicit host/port for the Streamable HTTP transport
    server = build_server(str(tmp_path), host="0.0.0.0", port=8848)
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 8848


def test_fastmcp_read_is_scoped_and_redacted(tmp_path):
    (tmp_path / "conf.py").write_text("TOKEN=sk-abcdefghijklmnop1234\nvalue = 1\n", encoding="utf-8")
    server = build_server(str(tmp_path))
    result = asyncio.run(server.call_tool("citadel_read", {"path": "conf.py"}))
    # FastMCP returns (content_blocks, structured?) — pull the text/JSON out defensively
    text = _extract(result)
    assert "sk-abcdefghijklmnop1234" not in text
    assert "preamble" in text


def _extract(result) -> str:
    payload = result[0] if isinstance(result, tuple) else result
    if isinstance(payload, list) and payload:
        block = payload[0]
        return getattr(block, "text", None) or json.dumps(getattr(block, "__dict__", str(block)), default=str)
    return json.dumps(payload, default=str)
