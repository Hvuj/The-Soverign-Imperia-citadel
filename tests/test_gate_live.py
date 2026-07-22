"""Live Ollama behavior of the UI free gate — actually generates against a running Ollama server.
Auto-skips when no server / model is reachable, so CI and other hosts stay green."""
import json
import sys
import urllib.request
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

_HOST = "http://localhost:11434"
_FAST = "qwen2.5:0.5b"


def _server_up() -> bool:
    from citadel.services.execute import OllamaEngine
    return OllamaEngine(host=_HOST).available()


def _has_model(model: str) -> bool:
    try:
        # Bypass any corporate HTTP(S)_PROXY for localhost (the citadel client does this via
        # trust_env=False); a plain urlopen would route localhost through the proxy and fail.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{_HOST}/api/tags", timeout=3) as resp:
            models = json.loads(resp.read().decode("utf-8")).get("models", [])
        return any(model in (m.get("name") or "") for m in models)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_server_up() and _has_model(_FAST)),
    reason=f"Ollama server or model {_FAST} not available",
)

import citadel_ui_server as srv  # noqa: E402


def test_ui_gate_returns_a_real_local_answer_for_free():
    """A short, non-technical question → real Ollama answer via the fast model, $0."""
    cfg = dict(srv._DEFAULT_CONFIG)
    result = srv._answer_via_local_gate("say hello in one short sentence", cfg)
    assert result is not None
    assert result["source"] == "local_gate"
    assert isinstance(result["answer"], str)
    assert result["answer"].strip()
    assert result["evidence"][0]["source"] == f"ollama:{_FAST}"  # auto-picked fast model
    assert result["evidence"][0]["detail"].endswith("no hosted-model tokens")  # $0
