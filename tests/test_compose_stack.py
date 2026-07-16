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
    assert "redis://redis:6379" in env["CITADEL_REDIS_URL"]  # local default, cloud-overridable via env
    assert "host.docker.internal" in env["CITADEL_OLLAMA_HOST"]
    assert any("host-gateway" in h for h in mcp["extra_hosts"])


def test_workspace_is_mounted_read_only():
    mcp = _compose()["services"]["citadel-mcp"]
    assert any(str(v).endswith(":ro") for v in mcp["volumes"]), "workspace mount must be read-only"


def test_egress_network_is_defined():
    networks = _compose()["networks"]
    assert "citadel_egress" in networks and networks["citadel_egress"]["name"] == "citadel_egress"


def test_edge_h2_h3_proxy_is_opt_in():
    caddy = _compose()["services"]["caddy"]
    assert caddy["profiles"] == ["edge"]  # not started for a plain localhost `up`
    ports = " ".join(str(p) for p in caddy["ports"])
    assert "8443:8443/udp" in ports  # HTTP/3 (QUIC) over UDP is exposed


def test_local_redis_is_profile_gated_for_cloud_switch():
    redis = _compose()["services"]["redis"]
    assert redis["profiles"] == ["local-redis"]  # cloud mode omits the profile → no local container
    # citadel-mcp takes the cloud URL via env override, defaulting to the local service
    env = _compose()["services"]["citadel-mcp"]["environment"]
    assert "${CITADEL_REDIS_URL:-redis://redis:6379}" in env["CITADEL_REDIS_URL"]


def test_optional_ollama_gpu_profile_requests_all_gpus():
    ollama = _compose()["services"]["ollama"]
    assert ollama["profiles"] == ["ollama-gpu"]
    assert ollama["environment"]["OLLAMA_SCHED_SPREAD"] == "1"  # spread one model across every GPU
    devices = ollama["deploy"]["resources"]["reservations"]["devices"][0]
    assert devices["count"] == "all" and "gpu" in devices["capabilities"]
