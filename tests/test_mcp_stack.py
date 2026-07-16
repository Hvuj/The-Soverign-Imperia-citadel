"""`citadel mcp` stack command: redis-mode inference (local vs cloud), and graceful behaviour when Docker
is absent (up refuses cleanly, pin falls back to the npx/uvx launcher config, status never crashes)."""

import json

import pytest

from citadel import paths
from citadel.commands import mcp_stack


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("CITADEL_REDIS_URL", raising=False)


def test_redis_mode_infers_local_vs_cloud(tmp_path):
    assert mcp_stack._redis_mode(tmp_path) == "local"  # default localhost
    paths.set_redis_config(tmp_path, url="rediss://cloud-host:6379")
    assert mcp_stack._redis_mode(tmp_path) == "cloud"


def test_up_refuses_cleanly_without_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_stack, "_docker", lambda: False)
    assert mcp_stack.up(tmp_path) == 1  # no crash; prints guidance


def test_pin_falls_back_to_launchers_without_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_stack, "_docker", lambda: False)
    rc = mcp_stack.pin(tmp_path)
    assert rc == 0
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert servers["citadel-retrieval"]["type"] == "http"
    # reference servers use npx/uvx (not docker) in the fallback
    assert servers["filesystem"]["command"] in ("npx", "cmd")
    assert servers["git"]["command"] == "uvx"


def test_status_runs_and_dispatch_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_stack, "_docker", lambda: False)

    class Args:
        mcp_action = "status"
        workspace = str(tmp_path)

    assert mcp_stack.run(Args()) == 0
