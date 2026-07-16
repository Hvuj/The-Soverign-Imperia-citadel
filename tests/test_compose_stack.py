"""The one-command compose stack: it parses, exposes Redis + our HTTP MCP server, mounts the workspace
read-only, and wires the container to host Ollama. Skips cleanly if PyYAML isn't installed."""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML not installed")

_COMPOSE = Path(__file__).resolve().parents[1] / "docker" / "compose" / "docker-compose.yml"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def test_stack_brings_up_redis_and_our_mcp_server():
    services = _compose()["services"]
    assert "redis" in services and "citadel-mcp" in services
    assert "redis-stack" in services["redis"]["image"]


def test_our_server_runs_http_and_reaches_host_ollama():
    mcp = _compose()["services"]["citadel-mcp"]
    assert "streamable-http" in mcp["command"]
    env = mcp["environment"]
    assert env["CITADEL_REDIS_URL"] == "redis://redis:6379"
    assert "host.docker.internal" in env["CITADEL_OLLAMA_HOST"]
    assert any("host-gateway" in h for h in mcp["extra_hosts"])


def test_workspace_is_mounted_read_only():
    mcp = _compose()["services"]["citadel-mcp"]
    assert any(str(v).endswith(":ro") for v in mcp["volumes"]), "workspace mount must be read-only"


def test_egress_network_is_defined():
    networks = _compose()["networks"]
    assert "citadel_egress" in networks and networks["citadel_egress"]["name"] == "citadel_egress"
