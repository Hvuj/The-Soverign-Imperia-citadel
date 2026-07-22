"""P3 — brain-for-all: every member reads the shared brain, redacted at the cloud boundary. A cloud (Groq)
member's prompt carries cited, secret-stripped context and private chunks are dropped entirely; a local
member gets the full capsule. Uses a fake brain + stub executors (no network)."""

from citadel.services.brain.injection import BrainContextExecutor, attach_brain, is_cloud, render_capsule
from citadel.services.brain.learning import LearningStore
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor


class FakeBrain:
    """A stand-in BrainAccess whose context returns one secret-bearing chunk, one private-path chunk, and
    one clean chunk."""

    def context(self, task, *, top_k=6, budget_bytes=16 * 1024):
        return {
            "task": task,
            "chunks": [
                {"path": "src/clean.py", "start_byte": 0, "end_byte": 20, "snippet": "def add(a, b): return a + b"},
                {"path": "src/config.py", "start_byte": 0, "end_byte": 40,
                 "snippet": "API_KEY = sk-abcdefghij0123456789xyz"},
                {"path": "secrets.env", "start_byte": 0, "end_byte": 30, "snippet": "TOKEN=super-secret-value"},
            ],
        }


class _Stub(Executor):
    def __init__(self, name: str) -> None:
        self.name = name
        self.seen_context = ""

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        self.seen_context = blueprint.context
        return ExecutionResult(task_id=blueprint.task_id, status="pass")


def test_is_cloud_classifies_boundary():
    assert is_cloud("provider:groq:openai/gpt-oss-120b") is True
    assert is_cloud("cloud-claude") is True
    assert is_cloud("provider:nvidia:meta/llama-3.3-70b") is True
    assert is_cloud("ollama-coding") is False
    assert is_cloud("local-strong") is False


def test_cloud_member_gets_cited_secret_stripped_context():
    groq = _Stub("provider:groq:openai/gpt-oss-120b")
    wrapped = BrainContextExecutor(groq, FakeBrain())
    assert wrapped.boundary == "cloud"
    wrapped.execute(Blueprint(task_id="t", instruction="add two numbers"))
    ctx = groq.seen_context
    assert "src/clean.py" in ctx                             # clean chunk cited, with provenance
    assert "def add" in ctx
    assert "sk-abcdefghij0123456789xyz" not in ctx           # secret masked
    assert "[REDACTED]" in ctx                                # …by the redactor
    assert "super-secret-value" not in ctx                   # private-path chunk dropped entirely
    assert "secrets.env" not in ctx


def test_local_member_gets_full_unredacted_context():
    local = _Stub("ollama-coding")
    wrapped = BrainContextExecutor(local, FakeBrain())
    assert wrapped.boundary == "local"
    wrapped.execute(Blueprint(task_id="t", instruction="add two numbers"))
    ctx = local.seen_context
    assert "sk-abcdefghij0123456789xyz" in ctx                # local is trusted → full text
    assert "secrets.env" in ctx


def test_render_capsule_empty_when_no_chunks():
    assert render_capsule({"chunks": []}) == ""
    # a cloud capsule of only-sensitive chunks renders empty (all dropped)
    only_secret = {"chunks": [{"path": "secrets.env", "snippet": "TOKEN=x"}]}
    assert render_capsule(only_secret, boundary="cloud") == ""


def test_attach_brain_composes_context_and_learning():
    store = LearningStore(prefer_redis=False)
    groq = _Stub("provider:groq:openai/gpt-oss-120b")
    member = attach_brain(groq, FakeBrain(), store=store)
    member.execute(Blueprint(task_id="t", instruction="add two numbers"))
    assert "def add" in groq.seen_context                     # brain context injected
    assert store.success_rate("add two numbers")[1] == 1      # and the run was recorded (learning)


def test_injection_survives_a_brain_failure():
    class BoomBrain:
        def context(self, *a, **k):
            raise RuntimeError("brain down")

    groq = _Stub("provider:groq:x")
    wrapped = BrainContextExecutor(groq, BoomBrain())
    r = wrapped.execute(Blueprint(task_id="t", instruction="do it", context="orig"))
    assert r.status == "pass"                    # advisory: a brain failure never blocks execution
    assert groq.seen_context == "orig"
