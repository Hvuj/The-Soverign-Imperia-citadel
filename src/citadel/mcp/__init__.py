"""citadel.mcp — our own MCP retrieval server on the official SDK (Zero-Token Sovereign, Phase Z2b).

Exposes the zero-token retrieval service (search / read / context) as MCP tools + resources so any MCP
client — Claude Code, the CLI, another AI — gets pre-digested, cited, redacted context without spending
model tokens to scan or search. Runs as a local stdio process or inside our Docker image behind the Docker
MCP Gateway. Read-only + never_call_claude by construction.
"""

from citadel.mcp.server import build_server, main

__all__ = ["build_server", "main"]
