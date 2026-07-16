"""mcp_stack.py — `citadel mcp up|down|status|pin` — manage the Docker MCP retrieval stack.

`up` brings the compose stack online (our HTTP retrieval server + local Redis in local mode) and writes the
compose-flavoured `.mcp.json` so Claude Code connects over Docker. `pin` pulls each reference-server image
and resolves its `@sha256` digest (D6 — no floating tags), falling back to the npx/uvx launchers the official
reference-servers repo documents when an image can't be pulled. `status` shows containers + an HTTP liveness
ping. Everything degrades gracefully when Docker is absent (prints guidance, never crashes).
"""

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from citadel import paths
from citadel.commands.mcp_setup import _REFERENCE_SERVERS, write_mcp_json

_MCP_PORT = int(os.environ.get("CITADEL_MCP_PORT", "8848"))


def _compose_file() -> Path:
    return Path(__file__).resolve().parents[3] / "docker" / "compose" / "docker-compose.yml"


def _docker() -> bool:
    return shutil.which("docker") is not None


def _run(cmd: list[str], *, env: dict | None = None, timeout: int = 900) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def _redis_mode(ws: Path) -> str:
    """local when the resolved Redis is on localhost (we run the container), else cloud (we don't)."""
    url = paths.resolve_redis_url(ws) or ""
    return "local" if ("127.0.0.1" in url or "localhost" in url) else "cloud"


def _compose_cmd(ws: Path, extra: list[str]) -> list[str]:
    profiles = ["--profile", "local-redis"] if _redis_mode(ws) == "local" else []
    return ["docker", "compose", "-f", str(_compose_file()), *profiles, *extra]


def _http_alive(url: str, timeout: float = 3.0) -> bool:
    """A Streamable-HTTP MCP endpoint answers a bare GET with 4xx (handshake required) — that means alive."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # 406/400 = server up, MCP handshake required
    except Exception:
        return False


def up(ws: Path) -> int:
    if not _docker():
        print("  docker not found — install Docker, or use native MCP: citadel setup --mcp native")
        return 1
    if not _compose_file().exists():
        print(f"  compose file not found at {_compose_file()} (run from the citadel repo)")
        return 1
    env = {**os.environ}
    if _redis_mode(ws) == "cloud":
        env["CITADEL_REDIS_URL"] = paths.resolve_redis_url(ws) or ""
    print(f"  bringing up the MCP stack ({_redis_mode(ws)} redis)…")
    code, out = _run(_compose_cmd(ws, ["up", "-d", "--build"]), env=env)
    if code != 0:
        print("  compose up failed:\n" + out[-500:])
        return 1
    write_mcp_json(ws, "compose", paths.resolve_redis_url(ws), port=_MCP_PORT)
    print(f"  ◆ MCP stack up. citadel-retrieval on http://localhost:{_MCP_PORT}/mcp — .mcp.json written (compose).")
    print("  run `citadel mcp pin` to digest-pin the reference servers, then `citadel mcp status`.")
    return 0


def down(ws: Path) -> int:
    if not _docker() or not _compose_file().exists():
        print("  nothing to stop (docker/compose not available here).")
        return 0
    code, out = _run(_compose_cmd(ws, ["down"]))
    print("  ◆ MCP stack stopped." if code == 0 else "  compose down issue:\n" + out[-300:])
    return 0


def status(ws: Path) -> int:
    print("◆ MCP stack status")
    if _docker():
        code, out = _run(["docker", "ps", "--filter", "name=citadel-mcp", "--format", "{{.Names}} {{.Status}}"])
        print(f"  container: {out.strip() or 'not running'}")
    else:
        print("  docker: not installed")
    alive = _http_alive(f"http://localhost:{_MCP_PORT}/mcp")
    print(f"  {'[ok]' if alive else '[--]'} HTTP retrieval endpoint http://localhost:{_MCP_PORT}/mcp")
    return 0


def pin(ws: Path) -> int:
    """Pull each reference image and resolve its @sha256 digest; fall back to npx/uvx for any that can't pull."""
    if not _docker():
        print("  docker not found — writing npx/uvx launcher config instead.")
        write_mcp_json(ws, "compose", paths.resolve_redis_url(ws), port=_MCP_PORT, use_launchers=True)
        return 0
    digests: dict[str, str] = {}
    missing = False
    for name, spec in _REFERENCE_SERVERS.items():
        image = spec["image"]
        code, _ = _run(["docker", "pull", f"{image}:latest"], timeout=600)
        if code != 0:
            print(f"  {name}: image {image} unavailable → npx/uvx fallback")
            missing = True
            continue
        code, out = _run(["docker", "inspect", "--format", "{{index .RepoDigests 0}}", f"{image}:latest"])
        digest = out.strip().split("@", 1)[1] if code == 0 and "@" in out else None
        if digest:
            digests[name] = digest
            print(f"  {name}: pinned {digest[:19]}…")
        else:
            missing = True
    write_mcp_json(ws, "compose", paths.resolve_redis_url(ws), port=_MCP_PORT,
                   digests=digests, use_launchers=missing)
    print("  ◆ .mcp.json updated" + (" (some servers use the npx/uvx fallback)" if missing else " (all digest-pinned)."))
    return 0


def run(args) -> int:
    ws = Path(getattr(args, "workspace", None) or ".").resolve()
    action = getattr(args, "mcp_action", None)
    return {"up": up, "down": down, "status": status, "pin": pin}.get(action, status)(ws)
