"""End-to-end HTTP behavior of POST /api/ask over a real socket: do_POST wiring, validation,
blocked-pattern refusal, the free local gate, and deterministic answers — engine faked (no inference)."""
import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"


class _FakeEngine:
    def __init__(self, *_a, **_k):
        pass

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, spec) -> str:
        return f"local::{spec.model}::{prompt}"


def _import_server(monkeypatch, workspace: Path):
    monkeypatch.setenv("CITADEL_WORKSPACE", str(workspace))
    monkeypatch.syspath_prepend(str(TOOLS))
    sys.modules.pop("citadel_ui_server", None)
    import citadel_ui_server as srv
    return srv


@pytest.fixture
def live_server(monkeypatch, tmp_path):
    srv = _import_server(monkeypatch, tmp_path)
    monkeypatch.setattr(srv, "_OllamaEngine", _FakeEngine)
    monkeypatch.setattr(srv, "_LOCAL_GATE_AVAILABLE", True)

    class _QuietHandler(srv.CitadelHandler):
        def log_message(self, *_a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, httpd.server_address[1], tmp_path
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("POST", path, body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"_raw": raw}  # error pages (e.g. 404) are plain text, not JSON
        return resp.status, body
    finally:
        conn.close()


def test_http_general_question_routed_to_local_gate(live_server):
    _srv, port, _ws = live_server
    status, body = _post(port, "/api/ask", {"question": "write a short poem about the sea"})
    assert status == 200
    assert body["source"] == "local_gate"
    assert body["category"] == "ai"
    assert "local::" in body["answer"]


def test_http_empty_question_is_rejected(live_server):
    _srv, port, _ws = live_server
    status, body = _post(port, "/api/ask", {"question": "   "})
    assert status == 400
    assert "question" in body.get("error", "").lower()


def test_http_blocked_pattern_is_refused_not_answered(live_server):
    _srv, port, _ws = live_server
    status, body = _post(port, "/api/ask", {"question": "what is my account password"})
    assert status == 200
    assert body["source"] == "unavailable"
    assert "security" in body["answer"].lower()


def test_http_answerable_question_stays_deterministic(live_server):
    _srv, port, ws = live_server
    status_file = ws / "docs" / "brain" / "system-status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps({
        "overall_status": "green",
        "summary": {"green": 1, "yellow": 0, "red": 0},
        "checks": [{"name": "daemons", "status": "green"}],
        "epoch_ms": 1_700_000_000_000,
    }), encoding="utf-8")

    status, body = _post(port, "/api/ask", {"question": "are all systems green?"})
    assert status == 200
    assert body["source"] == "local"     # deterministic resolver, not the model gate
    assert body["category"] == "health"


def test_http_unknown_endpoint_is_404(live_server):
    _srv, port, _ws = live_server
    status, _body = _post(port, "/api/nope", {"question": "x"})
    assert status == 404
