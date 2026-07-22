"""P4 — budget/rate guard, per-provider trust weights, and provider funditors (Intercessio). No network."""

from types import SimpleNamespace

from citadel.services.authority.intercessio import Gate, dual_gate
from citadel.services.authority.trust import TrustLedger
from citadel.services.consensus.trust import record_consensus_outcome, weights_from_trust
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor
from citadel.services.execute.providers import BudgetGuard, OpenAICompatExecutor, ProviderFunditor
from citadel.services.execute.verdict import CAPITAL

_GROQ_URL = "https://api.groq.com/openai/v1"


class _Completions:
    def __init__(self, reply="ok", raise_exc=None):
        self.calls = 0
        self._reply = reply
        self._raise = raise_exc

    def create(self, **kw):
        self.calls += 1
        if self._raise:
            raise self._raise
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._reply))])


class FakeOpenAI:
    def __init__(self, reply="ok", raise_exc=None):
        self.chat = SimpleNamespace(completions=_Completions(reply, raise_exc))


class FakeExec(Executor):
    def __init__(self, name, output):
        self.name = name
        self._o = output

    def execute(self, bp):
        return ExecutionResult(bp.task_id, "pass", output=self._o, tier_used=self.name)


# ── budget guard ──────────────────────────────────────────────────────────────────
def test_budget_cap_blocks_after_limit(tmp_path):
    guard = BudgetGuard(path=tmp_path / "b.json", caps={"nvidia": 2})
    assert guard.allow("nvidia") and guard.remaining("nvidia") == 2
    guard.record("nvidia")
    guard.record("nvidia")
    assert not guard.allow("nvidia") and guard.remaining("nvidia") == 0
    assert guard.allow("groq")  # no cap → unlimited


def test_budget_persists(tmp_path):
    BudgetGuard(path=tmp_path / "b.json", caps={"nvidia": 5}).record("nvidia")
    again = BudgetGuard(path=tmp_path / "b.json", caps={"nvidia": 5})
    assert again.remaining("nvidia") == 4


def test_executor_blocks_when_budget_exhausted():
    guard = BudgetGuard(caps={"groq": 0})
    ex = OpenAICompatExecutor(base_url=_GROQ_URL, api_key="k", model="m", provider="groq",
                              client=FakeOpenAI(), budget=guard)
    r = ex.execute(Blueprint(task_id="t", instruction="hello"))
    assert r.status == "blocked" and "budget" in r.reason
    assert ex._client.chat.completions.calls == 0  # never called the API


def test_executor_throttles_on_rate_limit():
    guard = BudgetGuard()
    ex = OpenAICompatExecutor(base_url=_GROQ_URL, api_key="k", model="m", provider="groq",
                              client=FakeOpenAI(raise_exc=RuntimeError("Error 429 rate limit")), budget=guard)
    r = ex.execute(Blueprint(task_id="t", instruction="hello"))
    assert r.status == "error"
    assert guard.allow("groq") is False  # throttled after the 429


# ── trust weights ─────────────────────────────────────────────────────────────────
def test_weights_from_trust():
    trust = TrustLedger(threshold=10)
    from citadel.services.execute.verdict import PASS
    for _ in range(10):
        trust.record("groq", PASS, axe=False)   # groq earns a full clean streak
    trust.record("nvidia", CAPITAL)              # nvidia betrayed → revoked
    weights = weights_from_trust(trust, ["groq", "nvidia", "claude"])
    assert weights["groq"] == 1.0
    assert weights["nvidia"] == 0.0              # revoked → zero vote
    assert weights["claude"] == 0.5              # neutral newcomer


def test_record_consensus_outcome_rewards_winner():
    trust = TrustLedger(threshold=3)
    result = SimpleNamespace(winner=SimpleNamespace(family="groq"))
    for _ in range(3):
        record_consensus_outcome(trust, result)
    assert trust.is_citizen("groq") is True


# ── provider funditors (Intercessio) ────────────────────────────────────────────────
def test_provider_funditors_are_uncorrelated_gates():
    groq = ProviderFunditor(FakeExec("provider:groq:m", "APPROVE looks correct"), family="groq")
    nvidia = ProviderFunditor(FakeExec("provider:nvidia:m", "APPROVE safe"), family="nvidia")
    g1, g2 = groq.gate("some artifact"), nvidia.gate("some artifact")
    assert g1.family == "groq" and g1.passed and g2.family == "nvidia" and g2.passed
    approved, _ = dual_gate([g1, g2])
    assert approved is True  # two uncorrelated families → axe-class approved


def test_provider_funditor_rejects_and_single_family_fails_dual_gate():
    groq_ok = ProviderFunditor(FakeExec("provider:groq:a", "APPROVE"), family="groq")
    groq_ok2 = ProviderFunditor(FakeExec("provider:groq:b", "APPROVE"), family="groq")
    nvidia_no = ProviderFunditor(FakeExec("provider:nvidia:m", "REJECT unsafe"), family="nvidia")
    assert nvidia_no.gate("x").passed is False
    approved, reason = dual_gate([groq_ok.gate("x"), groq_ok2.gate("x")])  # both groq → one family
    assert approved is False and "uncorrelated" in reason
