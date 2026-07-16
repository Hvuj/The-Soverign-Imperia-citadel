"""The pooled keep-alive HTTP client for the Ollama round-trips: real round-trip over a local stub server,
graceful urllib fallback when httpx is absent, and that OllamaEngine wires to the pooled client by default."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from citadel.services.execute.local import http_client


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"ok": True, "path": self.path})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self._send({"echo": payload})


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_pooled_post_and_get_roundtrip(server):
    got = http_client.pooled_get(f"{server}/api/tags", 5.0)
    assert got["ok"] is True
    posted = http_client.pooled_post(f"{server}/api/embed", {"model": "m", "input": ["x"]}, 5.0)
    assert posted["echo"]["model"] == "m"


def test_pooled_reuses_one_keepalive_connection(server):
    # Ten calls should ride the same pooled connection (the whole point). We can't easily count sockets
    # portably, so we assert correctness under repeated use + that the shared client is a singleton.
    for _ in range(10):
        assert http_client.pooled_get(f"{server}/api/tags", 5.0)["ok"] is True
    c1 = http_client._get_client()
    c2 = http_client._get_client()
    assert c1 is c2  # one shared client, not a new one per call


def test_urllib_fallback_when_httpx_absent(server, monkeypatch):
    # force the "httpx unavailable" path and confirm the stdlib fallback still works
    monkeypatch.setattr(http_client, "_client", False, raising=False)
    assert http_client._get_client() is None
    got = http_client.pooled_get(f"{server}/api/tags", 5.0)
    assert got["ok"] is True
    posted = http_client.pooled_post(f"{server}/api/embed", {"a": 1}, 5.0)
    assert posted["echo"] == {"a": 1}


def test_ollama_engine_uses_the_pooled_client_by_default():
    from citadel.services.execute.local.engine import OllamaEngine

    engine = OllamaEngine()
    assert engine._http_post is http_client.pooled_post
    assert engine._http_get is http_client.pooled_get
