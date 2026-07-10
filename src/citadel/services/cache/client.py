"""client.py — unix-socket (POSIX) / TCP-loopback (fallback) client + wire protocol
for the resident RAM cache.

Protocol: newline-delimited JSON, one request line -> one response line. Binary
values travel base64-encoded inside the JSON so arbitrary bytes survive the line
framing. The client is deliberately fail-soft: if the daemon is down or slow, every
operation degrades to "miss"/"false" so callers transparently fall back to disk
(graceful degradation — the cache is an accelerator, never a dependency).

Cross-platform: `socket.AF_UNIX` doesn't reliably exist on Windows, so when it's
absent this client connects over TCP to 127.0.0.1 instead, reading the ephemeral
port the daemon bound from a small sidecar file next to the (unused, on that
platform) socket path — see `ram_cache_daemon.py`'s server-selection logic.
"""

import base64
import json
import socket
from pathlib import Path

from citadel import paths as vp

_RECV_CHUNK = 65536

HAS_AF_UNIX = hasattr(socket, "AF_UNIX")


def socket_path(ws: Path | None = None) -> Path:
    """Location of the cache daemon's unix socket (POSIX) or TCP port sidecar name
    (Windows/no-AF_UNIX — see `tcp_port_path`)."""
    return vp.state_dir(ws) / "state" / "ram-cache.sock"


def tcp_port_path(sock_path: Path) -> Path:
    """Sidecar file the daemon writes its bound TCP port to, when AF_UNIX is
    unavailable. Lives next to the (unused in that mode) socket path."""
    return sock_path.with_suffix(".port")


def encode_request(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


def decode_line(line: bytes) -> dict:
    return json.loads(line.decode("utf-8"))


def b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _send_recv(sock: socket.socket, obj: dict) -> dict | None:
    sock.sendall(encode_request(obj))
    buf = bytearray()
    while b"\n" not in buf:
        chunk = sock.recv(_RECV_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
    if not buf:
        return None
    return decode_line(bytes(buf).split(b"\n", 1)[0])


class CacheClient:
    """Thin, fail-soft client for the RAM cache daemon.

    `sock_path` is a unix-socket path on POSIX. When `socket.AF_UNIX` is
    unavailable (Windows), the same path is used only to locate the TCP port
    sidecar file (`tcp_port_path`) the daemon wrote its ephemeral port to.
    """

    def __init__(self, sock_path: Path | None = None, *, timeout: float = 1.0) -> None:
        self._path = Path(sock_path or socket_path())
        self._timeout = timeout

    def _read_tcp_port(self) -> int | None:
        try:
            return int(tcp_port_path(self._path).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _request(self, obj: dict) -> dict | None:
        try:
            if HAS_AF_UNIX:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(self._timeout)
                    sock.connect(str(self._path))
                    return _send_recv(sock, obj)
            port = self._read_tcp_port()
            if port is None:
                return None
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self._timeout)
                sock.connect(("127.0.0.1", port))
                return _send_recv(sock, obj)
        except (OSError, ValueError):
            return None

    def get(self, key: str) -> bytes | None:
        resp = self._request({"op": "get", "key": key})
        if not resp or not resp.get("ok") or not resp.get("hit"):
            return None
        value = resp.get("value")
        return b64d(value) if value is not None else None

    def put(self, key: str, value: bytes) -> bool:
        resp = self._request({"op": "put", "key": key, "value": b64e(value)})
        return bool(resp and resp.get("ok"))

    def delete(self, key: str) -> bool:
        resp = self._request({"op": "delete", "key": key})
        return bool(resp and resp.get("ok") and resp.get("deleted"))

    def stats(self) -> dict | None:
        resp = self._request({"op": "stats"})
        return resp.get("stats") if resp and resp.get("ok") else None

    def ping(self) -> bool:
        resp = self._request({"op": "ping"})
        return bool(resp and resp.get("ok"))
