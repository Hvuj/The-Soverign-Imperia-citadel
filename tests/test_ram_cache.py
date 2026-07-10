"""Tests for the RAM cache: LRU eviction, byte budget, and socket round-trip."""

import threading

import pytest

from citadel.services.cache.ram_cache import RamCache


def test_get_put_hit_miss():
    c = RamCache(max_entries=8, max_bytes=1024)
    assert c.get("a") is None
    c.put("a", b"hello")
    assert c.get("a") == b"hello"
    s = c.stats()
    assert s.hits == 1
    assert s.misses == 1
    assert s.entries == 1


def test_lru_eviction_by_entries():
    c = RamCache(max_entries=2, max_bytes=1_000_000)
    c.put("a", b"1")
    c.put("b", b"2")
    c.get("a")
    c.put("c", b"3")
    assert c.get("a") == b"1"
    assert c.get("c") == b"3"
    assert c.get("b") is None
    assert c.stats().evictions == 1


def test_byte_budget_eviction():
    c = RamCache(max_entries=100, max_bytes=10)
    c.put("a", b"aaaaa")
    c.put("b", b"bbbbb")
    c.put("c", b"c")
    assert c.get("a") is None
    assert c.stats().bytes_used <= 10


def test_oversized_value_rejected():
    c = RamCache(max_entries=10, max_bytes=4)
    c.put("big", b"12345")
    assert c.get("big") is None
    assert len(c) == 0


def test_replace_updates_byte_count():
    c = RamCache(max_entries=10, max_bytes=1000)
    c.put("a", b"xxxxx")
    c.put("a", b"y")
    assert c.get("a") == b"y"
    assert c.stats().bytes_used == 1


def test_delete_and_clear():
    c = RamCache()
    c.put("a", b"1")
    assert c.delete("a") is True
    assert c.delete("a") is False
    c.put("b", b"2")
    c.clear()
    assert len(c) == 0


def test_thread_safety_smoke():
    c = RamCache(max_entries=1000, max_bytes=10_000_000)

    def worker(n: int) -> None:
        for i in range(200):
            c.put(f"k{n}-{i}", str(i).encode())
            c.get(f"k{n}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.stats().bytes_used <= c.stats().max_bytes


def test_socket_roundtrip_and_fallback():
    import importlib
    import os
    import sys
    import tempfile
    from pathlib import Path

    tools_dir = str(Path(__file__).resolve().parents[1] / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    daemon = importlib.import_module("ram_cache_daemon")
    from citadel.services.cache.client import CacheClient

    if daemon.CacheServer is None:  # native Windows: no AF_UNIX server (TCP fallback covered separately)
        pytest.skip("AF_UNIX unix-socket server unavailable on this platform")

    short_dir = Path(tempfile.gettempdir()) / f"vlc-{os.getpid()}"
    short_dir.mkdir(exist_ok=True)
    sock = short_dir / "c.sock"
    server = daemon.CacheServer(sock, RamCache())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CacheClient(sock, timeout=2.0)
        assert client.ping() is True
        assert client.get("k") is None
        assert client.put("k", b"payload\nwith\nnewlines") is True
        assert client.get("k") == b"payload\nwith\nnewlines"
        assert client.delete("k") is True
        assert client.get("k") is None
        assert client.stats()["entries"] == 0
    finally:
        server.shutdown()
        server.server_close()

    dead = CacheClient(short_dir / "nope.sock", timeout=0.2)
    assert dead.ping() is False
    assert dead.get("k") is None
    assert dead.put("k", b"v") is False


def test_tcp_fallback_used_when_af_unix_unavailable(monkeypatch):
    """Cross-platform guard (item 10 / G6): with AF_UNIX unavailable (Windows), the
    daemon binds a 127.0.0.1 TCP port and writes it to a sidecar file; the client
    reads that sidecar and speaks the identical protocol over TCP instead."""
    import importlib
    import sys
    import tempfile
    from pathlib import Path

    tools_dir = str(Path(__file__).resolve().parents[1] / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    daemon = importlib.import_module("ram_cache_daemon")
    import citadel.services.cache.client as client_mod

    monkeypatch.setattr(daemon, "HAS_AF_UNIX", False)
    monkeypatch.setattr(client_mod, "HAS_AF_UNIX", False)

    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "c.sock"
        server, endpoint_desc = daemon.make_server(sock, RamCache())
        assert endpoint_desc.startswith("tcp:127.0.0.1:")
        assert client_mod.tcp_port_path(sock).exists()

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = client_mod.CacheClient(sock, timeout=2.0)
            assert client.ping() is True
            assert client.put("k", b"tcp-value") is True
            assert client.get("k") == b"tcp-value"
        finally:
            server.shutdown()
            server.server_close()
            daemon._cleanup_endpoint(sock)

        assert not client_mod.tcp_port_path(sock).exists()


def test_client_falls_back_to_miss_when_port_sidecar_absent(monkeypatch):
    import sys
    import tempfile
    from pathlib import Path

    import citadel.services.cache.client as client_mod

    monkeypatch.setattr(client_mod, "HAS_AF_UNIX", False)
    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "nope.sock"
        client = client_mod.CacheClient(sock, timeout=0.2)
        assert client.ping() is False
        assert client.get("k") is None
        assert client.put("k", b"v") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
