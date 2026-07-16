"""P2 — the cloud data-boundary gate: deny-list (sensitive material blocked from the cloud), egress
allowlist, and metadata-only audit. Fake client — no network."""

import json
from types import SimpleNamespace

from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.providers import contains_sensitive, egress_allowed
from citadel.services.execute.providers.openai_compat import OpenAICompatExecutor


class _Completions:
    def __init__(self):
        self.called = False

    def create(self, **kw):
        self.called = True
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


class FakeOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_Completions())


def test_contains_sensitive_flags_the_right_things():
    assert contains_sensitive("please read .env for config")
    assert contains_sensitive("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert contains_sensitive("look in secrets.yaml")
    assert contains_sensitive("path: src/private/keys.py")
    assert contains_sensitive("normal code: def f(): return 1") is None


def test_egress_allowlist():
    assert egress_allowed("https://api.groq.com/openai/v1")
    assert egress_allowed("https://integrate.api.nvidia.com/v1")
    assert not egress_allowed("https://evil.example.com/v1")


def test_sensitive_prompt_is_blocked_and_never_sent(tmp_path):
    fake = FakeOpenAI()
    audit = tmp_path / "audit.jsonl"
    ex = OpenAICompatExecutor(base_url="https://api.groq.com/openai/v1", api_key="k", model="m",
                              provider="groq", client=fake, audit_path=str(audit))
    result = ex.execute(Blueprint(task_id="t", instruction="fix the bug in .env loading"))
    assert result.status == "blocked" and "sensitive" in result.reason
    assert fake.chat.completions.called is False  # the client was NEVER called
    entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert entry["status"] == "blocked" and "note" in entry and "task_id" in entry


def test_egress_to_a_non_allowlisted_host_is_refused():
    ex = OpenAICompatExecutor(base_url="https://evil.example.com/v1", api_key="k", model="m",
                              provider="x", client=FakeOpenAI())
    result = ex.execute(Blueprint(task_id="t", instruction="hello"))
    assert result.status == "error" and "egress not allowed" in result.reason


def test_allowed_prompt_sends_and_audits_metadata_only(tmp_path):
    fake = FakeOpenAI()
    audit = tmp_path / "audit.jsonl"
    ex = OpenAICompatExecutor(base_url="https://api.groq.com/openai/v1", api_key="k", model="m",
                              provider="groq", client=fake, audit_path=str(audit))
    result = ex.execute(Blueprint(task_id="t", instruction="write a function to add two numbers"))
    assert result.status == "pass" and fake.chat.completions.called is True
    entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert entry["status"] == "pass" and entry["bytes_sent"] > 0 and entry["redacted"] is True
    # the audit records metadata only — never the prompt text
    assert "add two numbers" not in audit.read_text(encoding="utf-8")


def test_gate_can_be_disabled():
    fake = FakeOpenAI()
    ex = OpenAICompatExecutor(base_url="https://api.groq.com/openai/v1", api_key="k", model="m",
                              provider="groq", client=fake, gate=False)
    # with the gate off, even a .env mention goes through (secrets are still redacted in the executor)
    result = ex.execute(Blueprint(task_id="t", instruction="read .env"))
    assert result.status == "pass"
