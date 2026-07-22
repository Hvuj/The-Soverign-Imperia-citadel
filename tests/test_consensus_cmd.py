"""P6 — the `citadel consensus` command degrades gracefully when no models are available (no keys, no local)."""

import pytest

from citadel.commands import consensus


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    import citadel.config as cfg
    monkeypatch.setattr(cfg, "_env_loaded", True, raising=False)  # don't load a real .env


def test_consensus_reports_when_no_models(tmp_path, capsys):
    class Args:
        task = ["write a function"]
        workspace = str(tmp_path)
        code = False
        no_local = True   # and no keys → zero members
        local_model = None

    rc = consensus.run(Args())
    assert rc == 1
    assert "not enough models" in capsys.readouterr().out.lower()


def test_verify_python_gate():
    assert consensus._verify_python("def f():\n    return 1\n")[0] is True
    assert consensus._verify_python("```python\ndef f(): return 1\n```")[0] is True
    assert consensus._verify_python("def f( : broken")[0] is False
