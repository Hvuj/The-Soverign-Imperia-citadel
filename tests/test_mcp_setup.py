"""The .mcp.json builder (native vs compose) + the compose stack's security invariants + probe_redis."""

import json

from citadel.commands.mcp_setup import build_mcp_config, write_mcp_json
from citadel.commands.setup import probe_redis

_CODE_TOUCHING = {"filesystem", "git", "memory", "sequentialthinking", "time"}


def test_native_config_has_both_citadel_servers():
    cfg = build_mcp_config("native", redis_url="redis://myhost:6379")["mcpServers"]
    assert "sovereign-imperia-citadel" in cfg
    retr = cfg["citadel-retrieval"]
    assert retr["command"] == "python" and retr["args"] == ["-m", "citadel.mcp.server"]
    assert retr["env"]["CITADEL_REDIS_URL"] == "redis://myhost:6379"


def test_native_config_omits_redis_when_none():
    retr = build_mcp_config("native", redis_url=None)["mcpServers"]["citadel-retrieval"]
    assert "CITADEL_REDIS_URL" not in retr["env"]


def test_compose_config_our_server_is_http():
    retr = build_mcp_config("compose")["mcpServers"]["citadel-retrieval"]
    assert retr["type"] == "http" and retr["url"].endswith("/mcp")


def test_compose_code_touching_servers_have_no_egress():
    servers = build_mcp_config("compose")["mcpServers"]
    for name in _CODE_TOUCHING:
        args = servers[name]["args"]
        assert args[args.index("--network") + 1] == "none", f"{name} must be --network none"


def test_compose_fetch_is_the_only_egress_server():
    servers = build_mcp_config("compose")["mcpServers"]
    fetch_args = servers["fetch"]["args"]
    assert fetch_args[fetch_args.index("--network") + 1] == "citadel_egress"


def test_compose_images_are_digest_pinned():
    servers = build_mcp_config("compose")["mcpServers"]
    for name, spec in servers.items():
        if spec.get("command") != "docker":
            continue
        images = [a for a in spec["args"] if a.startswith("mcp/")]
        assert images and all("@sha256:" in img for img in images), f"{name} image must be digest-pinned"


def test_write_mcp_json_roundtrip(tmp_path):
    dest = write_mcp_json(tmp_path, "native", "redis://x:6379")
    assert dest.exists()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert "citadel-retrieval" in data["mcpServers"]


def test_probe_redis_unreachable_is_false():
    reachable, has_search = probe_redis("redis://127.0.0.1:6390")  # nothing listening
    assert reachable is False and has_search is False
