"""server.py — the FastMCP retrieval server (Phase Z2b).

Wraps the one `RetrievalService` (shared with the stdlib server and `citadel ask`) as MCP tools. Every
response is already count-first + secret-redacted + cited by the service, so nothing enters an AI's context
uncounted or unscrubbed. The server performs NO network egress of its own — it reads local files, the local
vector index, and (optionally) host Redis/Ollama; it never calls Claude. Containerize it behind the Docker
MCP Gateway (see docker/mcp/) or run it as a local stdio process via `.mcp.json`.
"""

import argparse
import os

from mcp.server.fastmcp import FastMCP

from citadel.services.retrieval.service import RetrievalService

SERVER_NAME = "citadel-retrieval"
DEFAULT_PORT = 8848


def build_server(workspace: str | None = None, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    ws = workspace or os.environ.get("CITADEL_WORKSPACE", ".")
    service = RetrievalService.for_workspace(ws)
    mcp = FastMCP(SERVER_NAME, host=host, port=port)

    @mcp.tool()
    def citadel_search(query: str, top_k: int = 8) -> dict:
        """Zero-token semantic (dense+keyword) code search over the local index. Returns cited chunks
        (path + byte range + snippet). The search runs locally — it costs no model tokens."""
        return service.search(query, top_k=top_k)

    @mcp.tool()
    def citadel_read(path: str, max_bytes: int = 16 * 1024) -> dict:
        """Read a workspace file, secret-redacted + byte-spliced + count-first. Workspace-scoped; refuses
        paths outside the workspace. Zero model tokens."""
        return service.read(path, max_bytes=max_bytes)

    @mcp.tool()
    def citadel_context(task: str, top_k: int = 8) -> dict:
        """Assemble a budgeted, deduped, cited context capsule for a task — the pre-digested pack an AI can
        reason over. Retrieval + assembly happen locally. Zero model tokens."""
        return service.context(task, top_k=top_k)

    @mcp.resource("citadel://search/{query}")
    def search_resource(query: str) -> str:
        """Retrieval as an MCP resource — stream cited context by URI without a prompt-dump."""
        import json

        return json.dumps(service.search(query), default=str)

    return mcp


def main(argv: list[str] | None = None) -> None:
    """Run the server. Default stdio (native `.mcp.json`); `--transport streamable-http` for the compose
    service (long-running, connect-by-URL — the scalable path)."""
    ap = argparse.ArgumentParser(prog="citadel.mcp.server")
    ap.add_argument("--transport", default=os.environ.get("CITADEL_MCP_TRANSPORT", "stdio"),
                    choices=["stdio", "streamable-http", "sse"])
    ap.add_argument("--host", default=os.environ.get("CITADEL_MCP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("CITADEL_MCP_PORT", str(DEFAULT_PORT))))
    ap.add_argument("--workspace", default=None)
    args = ap.parse_args(argv)
    build_server(args.workspace, host=args.host, port=args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
