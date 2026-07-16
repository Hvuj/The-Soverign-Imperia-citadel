"""mcp_setup.py — build the workspace `.mcp.json` for either the native or the compose stack.

`native` (no Docker): our two stdio servers — the stdlib server + the FastMCP retrieval server run as local
subprocesses. Works with just Python. `compose`: our retrieval server is reached over Streamable HTTP (the
long-running compose service), and the open-source reference servers are launched per-session as
`docker run --network none` containers (code-touching = data-out blocked; only Fetch gets an egress network).
Third-party images carry an `@sha256:PIN_ME` digest placeholder — `docker/compose/pin-images.sh` resolves
them (D6: never a floating tag). `citadel setup --mcp {native,compose}` writes the chosen shape.
"""

import json
import sys
from pathlib import Path

CITADEL_MCP_PORT = 8848
_WS = "${workspaceFolder}"

# Reference servers (official MCP SDK ecosystem). "none" = touches your code → data-out blocked;
# "egress" = needs the internet (Fetch only). `npx`/`uvx` are the fallback launchers the reference-servers
# repo documents, used when the Docker image can't be pulled.
_REFERENCE_SERVERS = {
    "filesystem": {"image": "mcp/filesystem", "net": "none", "mount_ro": True, "args_tail": ["/workspace"],
                   "npx": ["@modelcontextprotocol/server-filesystem", _WS]},
    "git": {"image": "mcp/git", "net": "none", "mount_ro": True, "args_tail": [],
            "uvx": ["mcp-server-git", "--repository", _WS]},
    "memory": {"image": "mcp/memory", "net": "none", "mount_ro": False, "args_tail": [],
               "npx": ["@modelcontextprotocol/server-memory"]},
    "sequentialthinking": {"image": "mcp/sequentialthinking", "net": "none", "mount_ro": False, "args_tail": [],
                           "npx": ["@modelcontextprotocol/server-sequential-thinking"]},
    "time": {"image": "mcp/time", "net": "none", "mount_ro": False, "args_tail": [], "uvx": ["mcp-server-time"]},
    "fetch": {"image": "mcp/fetch", "net": "egress", "mount_ro": False, "args_tail": [], "uvx": ["mcp-server-fetch"]},
}
FETCH_ALLOWLIST = ["docs.python.org", "github.com", "pypi.org", "raw.githubusercontent.com"]


def _docker_entry(spec: dict, digest: str = "sha256:PIN_ME") -> dict:
    network = "none" if spec["net"] == "none" else "citadel_egress"
    args = ["run", "-i", "--rm", "--network", network]
    if spec["mount_ro"]:
        args += ["--mount", f"type=bind,src={_WS},dst=/workspace,ro"]
    args += [f"{spec['image']}@{digest}", *spec["args_tail"]]
    return {"command": "docker", "args": args}


def _launcher_entry(spec: dict) -> dict | None:
    """npx/uvx fallback (the official repo's documented commands). Windows wraps npx with `cmd /c`."""
    if "npx" in spec:
        if sys.platform == "win32":
            return {"command": "cmd", "args": ["/c", "npx", "-y", *spec["npx"]]}
        return {"command": "npx", "args": ["-y", *spec["npx"]]}
    if "uvx" in spec:
        return {"command": "uvx", "args": spec["uvx"]}
    return None


def build_mcp_config(
    mode: str, *, redis_url: str | None = None, port: int = CITADEL_MCP_PORT,
    digests: dict[str, str] | None = None, use_launchers: bool = False,
) -> dict:
    """Return the .mcp.json dict for `native` or `compose`. In compose mode, `digests` pins images by
    @sha256 (from `citadel mcp pin`), and `use_launchers=True` swaps reference servers to npx/uvx."""
    if mode == "compose":
        servers: dict = {"citadel-retrieval": {"type": "http", "url": f"http://localhost:{port}/mcp"}}
        digests = digests or {}
        for name, spec in _REFERENCE_SERVERS.items():
            if use_launchers:
                entry = _launcher_entry(spec)
                servers[name] = entry if entry is not None else _docker_entry(spec, digests.get(name, "sha256:PIN_ME"))
            else:
                servers[name] = _docker_entry(spec, digests.get(name, "sha256:PIN_ME"))
        return {"mcpServers": servers}

    # native (default)
    retrieval_env = {"PYTHONPATH": "src"}
    if redis_url:
        retrieval_env["CITADEL_REDIS_URL"] = redis_url
    return {
        "mcpServers": {
            "sovereign-imperia-citadel": {"command": "python", "args": ["tools/citadel_mcp_server.py"]},
            "citadel-retrieval": {"command": "python", "args": ["-m", "citadel.mcp.server"], "env": retrieval_env},
        }
    }


def write_mcp_json(
    workspace: str | Path, mode: str, redis_url: str | None = None, *, port: int = CITADEL_MCP_PORT,
    digests: dict[str, str] | None = None, use_launchers: bool = False,
) -> Path:
    dest = Path(workspace) / ".mcp.json"
    config = build_mcp_config(mode, redis_url=redis_url, port=port, digests=digests, use_launchers=use_launchers)
    dest.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return dest
