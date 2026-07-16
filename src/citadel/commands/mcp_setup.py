"""mcp_setup.py — build the workspace `.mcp.json` for either the native or the compose stack.

`native` (no Docker): our two stdio servers — the stdlib server + the FastMCP retrieval server run as local
subprocesses. Works with just Python. `compose`: our retrieval server is reached over Streamable HTTP (the
long-running compose service), and the open-source reference servers are launched per-session as
`docker run --network none` containers (code-touching = data-out blocked; only Fetch gets an egress network).
Third-party images carry an `@sha256:PIN_ME` digest placeholder — `docker/compose/pin-images.sh` resolves
them (D6: never a floating tag). `citadel setup --mcp {native,compose}` writes the chosen shape.
"""

import json
from pathlib import Path

CITADEL_MCP_PORT = 8848
_WS = "${workspaceFolder}"

# Reference servers, each with its network policy. "none" = touches your code, data-out blocked;
# "egress" = needs the internet (Fetch only), restricted to the allowlist.
_REFERENCE_SERVERS = {
    "filesystem": {"image": "mcp/filesystem", "net": "none", "mount_ro": True, "args_tail": ["/workspace"]},
    "git": {"image": "mcp/git", "net": "none", "mount_ro": True, "args_tail": []},
    "memory": {"image": "mcp/memory", "net": "none", "mount_ro": False, "args_tail": []},
    "sequentialthinking": {"image": "mcp/sequentialthinking", "net": "none", "mount_ro": False, "args_tail": []},
    "time": {"image": "mcp/time", "net": "none", "mount_ro": False, "args_tail": []},
    "fetch": {"image": "mcp/fetch", "net": "egress", "mount_ro": False, "args_tail": []},
}
FETCH_ALLOWLIST = ["docs.python.org", "github.com", "pypi.org", "raw.githubusercontent.com"]


def _docker_entry(spec: dict) -> dict:
    network = "none" if spec["net"] == "none" else "citadel_egress"
    args = ["run", "-i", "--rm", "--network", network]
    if spec["mount_ro"]:
        args += ["--mount", f"type=bind,src={_WS},dst=/workspace,ro"]
    args += [f"{spec['image']}@sha256:PIN_ME", *spec["args_tail"]]
    return {"command": "docker", "args": args}


def build_mcp_config(mode: str, *, redis_url: str | None = None, port: int = CITADEL_MCP_PORT) -> dict:
    """Return the .mcp.json dict for `native` or `compose`."""
    if mode == "compose":
        servers: dict = {"citadel-retrieval": {"type": "http", "url": f"http://localhost:{port}/mcp"}}
        for name, spec in _REFERENCE_SERVERS.items():
            servers[name] = _docker_entry(spec)
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


def write_mcp_json(workspace: str | Path, mode: str, redis_url: str | None = None, *, port: int = CITADEL_MCP_PORT) -> Path:
    dest = Path(workspace) / ".mcp.json"
    dest.write_text(json.dumps(build_mcp_config(mode, redis_url=redis_url, port=port), indent=2) + "\n", encoding="utf-8")
    return dest
