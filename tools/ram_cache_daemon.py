#!/usr/bin/env python3
"""ram_cache_daemon.py — resident RAM cache served over a local unix socket, with a
TCP-loopback fallback where AF_UNIX is unavailable (Windows).

Holds hot artifacts (brain-search indexes, precomputed capsules, symbol/commit
indexes) in a byte-budgeted LRU (citadel.services.cache.RamCache) so tools and
hooks fetch them at memory speed and context can carry a small ``ram_ref`` pointer
instead of an inlined payload. One process, one service (SRP; not microservices).
Never calls Claude and never edits production code.

Lifecycle:
    --watch    serve forever (default); SIGTERM/SIGINT → graceful shutdown
    --warm     preload hot artifacts on startup
    --status / --stop / --ping

Endpoint: unix socket at <workspace>/.citadel/state/ram-cache.sock on POSIX; on a
          platform without `socket.AF_UNIX`, a 127.0.0.1 TCP port instead — the
          bound port is written to the sidecar file <same path>.port so
          `CacheClient` can discover it (see client.py's `tcp_port_path`).
PID:      <workspace>/.claude/state/ram-cache-daemon.pid
"""

import argparse
import contextlib
import os
import signal
import sys
import threading
from pathlib import Path
from socketserver import StreamRequestHandler, TCPServer, ThreadingMixIn

try:  # UnixStreamServer only exists where AF_UNIX does (POSIX) — absent on native Windows.
    from socketserver import UnixStreamServer
except ImportError:  # pragma: no cover - platform-dependent
    UnixStreamServer = None

from citadel import paths as vp
from citadel.services.cache.client import (
    HAS_AF_UNIX,
    b64d,
    b64e,
    decode_line,
    encode_request,
    socket_path,
    tcp_port_path,
)
from citadel.services.cache.ram_cache import RamCache

_WARM_GLOBS = ("brain-search/*.json", "brain-search/capsules/*.json")
_WARM_MAX_BYTES = 4 * 1024 * 1024

_shutdown = threading.Event()


def _pid_file(ws: Path) -> Path:
    return vp.claude_dir(ws) / "state" / "ram-cache-daemon.pid"


def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(f"[ram-cache-daemon] {msg}", flush=True)


def _dispatch(cache: RamCache, req: dict) -> dict:
    op = req.get("op")
    if op == "ping":
        return {"ok": True}
    if op == "get":
        value = cache.get(req.get("key", ""))
        return {"ok": True, "hit": value is not None,
                "value": b64e(value) if value is not None else None}
    if op == "put":
        cache.put(req.get("key", ""), b64d(req.get("value", "")))
        return {"ok": True}
    if op == "delete":
        return {"ok": True, "deleted": cache.delete(req.get("key", ""))}
    if op == "stats":
        s = cache.stats()
        return {"ok": True, "stats": {
            "entries": s.entries, "bytes_used": s.bytes_used,
            "max_entries": s.max_entries, "max_bytes": s.max_bytes,
            "hits": s.hits, "misses": s.misses, "evictions": s.evictions,
        }}
    return {"ok": False, "error": f"unknown op: {op}"}


class _Handler(StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline()
        if not line:
            return
        try:
            req = decode_line(line)
        except ValueError:
            self.wfile.write(encode_request({"ok": False, "error": "bad json"}))
            return
        resp = _dispatch(self.server.cache, req)  # type: ignore[attr-defined]
        self.wfile.write(encode_request(resp))


if UnixStreamServer is not None:

    class CacheServer(ThreadingMixIn, UnixStreamServer):
        """POSIX server: a real unix socket at `sock_file`."""

        daemon_threads = True
        allow_reuse_address = True

        def __init__(self, sock_file: Path, cache: RamCache) -> None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(sock_file)
            sock_file.parent.mkdir(parents=True, exist_ok=True)
            super().__init__(str(sock_file), _Handler)
            self.cache = cache
else:  # native Windows: no AF_UNIX server; make_server() uses TCPCacheServer instead.
    CacheServer = None


class TCPCacheServer(ThreadingMixIn, TCPServer):
    """Fallback server for platforms without `socket.AF_UNIX` (Windows): binds an
    OS-assigned ephemeral port on 127.0.0.1 — same request/response protocol."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cache: RamCache) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.cache = cache


def make_server(sock_file: Path, cache: RamCache) -> tuple[object, str]:
    """Build the right server for this platform. Returns (server, endpoint_desc)."""
    if HAS_AF_UNIX:
        return CacheServer(sock_file, cache), f"unix:{sock_file}"
    server = TCPCacheServer(cache)
    port = server.server_address[1]
    tcp_port_path(sock_file).write_text(str(port), encoding="utf-8")
    return server, f"tcp:127.0.0.1:{port}"


def _cleanup_endpoint(sock_file: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(sock_file)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tcp_port_path(sock_file))


def _warm(cache: RamCache, ws: Path, quiet: bool) -> None:
    base = vp.claude_dir(ws) / "state"
    loaded = 0
    for pattern in _WARM_GLOBS:
        for path in base.glob(pattern):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if len(data) > _WARM_MAX_BYTES:
                continue
            cache.put(f"file:{path.relative_to(base).as_posix()}", data)
            loaded += 1
    _log(f"warm-loaded {loaded} artifact(s)", quiet)


def _write_pid(ws: Path) -> None:
    pid_file = _pid_file(ws)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))


def _remove_pid(ws: Path) -> None:
    pid_file = _pid_file(ws)
    with contextlib.suppress(OSError):
        if pid_file.exists() and pid_file.read_text().strip() == str(os.getpid()):
            pid_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resident RAM cache daemon")
    parser.add_argument("--max-entries", type=int, default=4096)
    parser.add_argument("--max-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--warm", action="store_true", help="Preload hot artifacts")
    parser.add_argument("--watch", action="store_true", help="Serve forever (default)")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    ws = vp.workspace_root()
    pid_file = _pid_file(ws)
    sock_file = socket_path(ws)

    if args.status:
        print(f"running (pid={pid_file.read_text().strip()})" if pid_file.exists() else "not running")
        return 0

    if args.ping:
        from citadel.services.cache.client import CacheClient
        print("pong" if CacheClient(sock_file).ping() else "no response")
        return 0

    if args.stop:
        if not pid_file.exists():
            print("not running")
            return 0
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
            print("stop signal sent")
        except (ValueError, ProcessLookupError):
            pid_file.unlink(missing_ok=True)
        return 0

    cache = RamCache(max_entries=args.max_entries, max_bytes=args.max_bytes)
    if args.warm:
        _warm(cache, ws, args.quiet)

    server, endpoint_desc = make_server(sock_file, cache)

    def _stop(_sig, _frame):
        _shutdown.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()
    _write_pid(ws)
    _log(f"listening on {endpoint_desc} (pid={os.getpid()})", args.quiet)

    try:
        _shutdown.wait()
    finally:
        server.shutdown()
        server.server_close()
        _cleanup_endpoint(sock_file)
        _remove_pid(ws)
        _log("stopped", args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
