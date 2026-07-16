"""Phase Z2b — the MCP topology's security invariants (reads in, data-out blocked). The config-integrity
tests always run; the live egress test runs only when Docker is available and proves --network none really
blocks the internet."""

import json
import subprocess
from pathlib import Path

import pytest

_CONFIG = Path(__file__).resolve().parents[1] / "docker" / "mcp" / "mcp-servers.json"
_CODE_TOUCHING = {"filesystem", "git", "memory", "sequential-thinking"}


def _config() -> dict:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def test_code_touching_servers_have_no_egress():
    servers = _config()["mcpServers"]
    for name in _CODE_TOUCHING:
        args = servers[name]["args"]
        assert "--network" in args and args[args.index("--network") + 1] == "none", f"{name} must be --network none"


def test_fetch_is_the_only_internet_server_and_has_an_allowlist():
    fetch = _config()["mcpServers"]["fetch"]
    assert "none" not in fetch["args"], "fetch needs the internet, must NOT be --network none"
    assert "citadel_egress" in fetch["args"]
    assert fetch["_egress_allowlist"], "fetch must declare an egress allowlist"


def test_our_server_is_native_and_trusted():
    ours = _config()["mcpServers"]["citadel-retrieval"]
    assert ours["command"] == "python"
    assert "docker" not in ours["command"]


def test_exec_sandbox_is_network_none():
    assert "--network none" in _config()["_exec_sandbox"]["run"]


def test_third_party_images_are_digest_pinned():
    servers = _config()["mcpServers"]
    for name, spec in servers.items():
        if spec.get("command") != "docker":
            continue
        images = [a for a in spec["args"] if a.startswith("mcp/")]
        for image in images:
            assert "@sha256:" in image, f"{name} image {image} must be pinned by digest (D6)"


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "version"], capture_output=True, timeout=8).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_network_none_blocks_internet_egress():
    script = (
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('https://pypi.org', timeout=6)\n"
        "    print('REACHED')\n"
        "except Exception:\n"
        "    print('BLOCKED')\n"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python", "python:3.12-slim", "-c", script],
        capture_output=True, text=True, timeout=180,
    )
    assert "BLOCKED" in result.stdout
    assert "REACHED" not in result.stdout
