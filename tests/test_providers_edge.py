"""OpenAI-compatible provider executor — edge/error behavior with an injected client (no network, no keys).
Covers null/empty responses, rate-limit throttling, timeouts, budget blocking, egress + sensitivity gates."""
from types import SimpleNamespace

from citadel.services.execute.blueprint import Blueprint
from citadel.services.execute.providers import OpenAICompatExecutor

_ALLOWED_URL = "https://api.x.ai/v1"  # on the egress allowlist


def _resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _Client:
    """Injected OpenAI-compatible client: replies with `reply`, or raises `exc`, or returns `choices`."""

    def __init__(self, *, reply=None, exc=None, choices=None):
        self._reply, self._exc, self._choices = reply, exc, choices
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kw):
        if self._exc is not None:
            raise self._exc
        if self._choices is not None:
            return SimpleNamespace(choices=self._choices)
        return _resp(self._reply)


class _Budget:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.throttled: list[str] = []
        self.recorded: list[str] = []

    def allow(self, provider):
        return self.allowed

    def throttle(self, provider):
        self.throttled.append(provider)

    def record(self, provider):
        self.recorded.append(provider)


class _RateLimit(Exception):
    status_code = 429


def _ex(client, **kw):
    return OpenAICompatExecutor(base_url=_ALLOWED_URL, api_key="k", model="m", provider="grok",
                                client=client, **kw)


def _bp(instruction="hello"):
    return Blueprint(task_id="t", instruction=instruction)


def test_null_content_yields_empty_output_not_crash():
    r = _ex(_Client(reply=None)).execute(_bp())
    assert r.status == "pass"
    assert r.output == ""


def test_empty_choices_is_error_not_crash():
    r = _ex(_Client(choices=[])).execute(_bp())
    assert r.status == "error"  # IndexError caught, surfaced as error


def test_rate_limit_throttles_provider_and_records_error():
    budget = _Budget()
    r = _ex(_Client(exc=_RateLimit("429 too many requests")), budget=budget).execute(_bp())
    assert r.status == "error"
    assert budget.throttled == ["grok"]
    assert budget.recorded == []


def test_timeout_is_error_not_crash():
    r = _ex(_Client(exc=TimeoutError("request timed out"))).execute(_bp())
    assert r.status == "error"
    assert "timed out" in r.reason.lower()


def test_budget_blocks_before_any_network_call():
    budget = _Budget(allowed=False)
    r = _ex(_Client(reply="should-not-be-used"), budget=budget).execute(_bp())
    assert r.status == "blocked"
    assert "budget" in r.reason.lower()


def test_successful_call_records_budget():
    budget = _Budget()
    r = _ex(_Client(reply="ok"), budget=budget).execute(_bp())
    assert r.status == "pass"
    assert budget.recorded == ["grok"]


def test_egress_denied_for_non_allowlisted_host():
    ex = OpenAICompatExecutor(base_url="https://evil.example.com/v1", api_key="k", model="m",
                              provider="grok", client=_Client(reply="x"))
    r = ex.execute(_bp())
    assert r.status == "error"
    assert "egress" in r.reason.lower()


def test_sensitive_content_is_withheld_from_cloud():
    r = _ex(_Client(reply="x")).execute(_bp("please read the private key at ~/.ssh/id_rsa"))
    assert r.status == "blocked"
    assert "sensitive" in r.reason.lower()


def test_missing_key_errors_before_gate():
    ex = OpenAICompatExecutor(base_url=_ALLOWED_URL, api_key="", model="m", provider="grok",
                              client=_Client(reply="x"))
    r = ex.execute(_bp())
    assert r.status == "error"
    assert "no api key" in r.reason.lower()
