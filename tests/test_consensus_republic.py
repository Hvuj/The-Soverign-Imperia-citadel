"""W2 — the Republic wired into the consensus hot path: brain-armed members (capsule reuse, redacted for
cloud), every model learns its outcome, and a verified winner with a distinct not-self quorum auto-promotes
to a Senatus Consultum (idempotently). Uses fakes/stubs — no network, no Ollama."""

from citadel.commands.consensus import _learn_from_result, _maybe_promote
from citadel.services.brain.injection import BrainContextExecutor
from citadel.services.consensus.engine import Candidate, ConsensusResult, Critique
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor
from citadel.services.republic import build_republic

_CAPSULE = {
    "chunks": [
        {"path": "src/clean.py", "start_byte": 0, "end_byte": 20, "snippet": "def add(a, b): return a + b"},
        {"path": "secrets.env", "start_byte": 0, "end_byte": 10, "snippet": "TOKEN=super-secret"},
    ],
}


class _Stub(Executor):
    def __init__(self, name: str) -> None:
        self.name = name
        self.seen = ""

    def execute(self, blueprint: Blueprint) -> ExecutionResult:
        self.seen = blueprint.context
        return ExecutionResult(task_id=blueprint.task_id, status="pass")


def test_capsule_is_reused_and_redacted_per_boundary():
    cloud = _Stub("provider:groq:openai/gpt-oss-120b")
    BrainContextExecutor(cloud, brain=None, capsule=_CAPSULE).execute(Blueprint(task_id="t", instruction="add"))
    assert "def add" in cloud.seen              # cited context injected without querying the brain
    assert "super-secret" not in cloud.seen     # private-path chunk dropped at the cloud boundary
    local = _Stub("local")
    BrainContextExecutor(local, brain=None, capsule=_CAPSULE).execute(Blueprint(task_id="t", instruction="add"))
    assert "super-secret" in local.seen         # local is trusted → full capsule


def _result(winner_member="provider:groq:openai/gpt-oss-120b"):
    cands = [
        Candidate("c0", winner_member, "gpt-oss", "def rev(s): return s[::-1]", "pass"),
        Candidate("c1", "provider:nvidia:meta/llama-3.3-70b", "llama",
                  "def rev(s): return ''.join(reversed(s))", "pass"),
        Candidate("c2", "local", "ollama", "", "fail"),
    ]
    critiques = [
        Critique("judge:provider:nvidia:meta/llama-3.3-70b", "nvidia", "c0", 0.9, "accept", "correct"),
        Critique("judge:provider:groq:openai/gpt-oss-20b", "groq", "c0", 0.8, "accept", "correct"),
        Critique("judge:provider:nvidia:meta/llama-3.3-70b", "nvidia", "c2", 0.1, "reject", "empty output"),
    ]
    return ConsensusResult("selected", cands[0].output, cands[0], cands, critiques, {"c0": 0.85, "c1": 0.7, "c2": 0.0})


def test_every_model_learns_its_outcome(tmp_path):
    rep = build_republic(tmp_path, prefer_redis=False)
    result = _result()
    n = _learn_from_result(rep, "reverse a string", result)
    assert n == 3
    # the task's EWMA saw 3 outcomes; the winner's best-practice lesson is recallable
    assert rep.ledger.success_rate("reverse a string")[1] == 3
    lessons = rep.ledger.recall("reverse a string")
    assert any(item["category"] == "best_practice" for item in lessons)


def test_winner_auto_promotes_to_consultum_with_not_self_quorum(tmp_path):
    rep = build_republic(tmp_path, prefer_redis=False)
    consultum = _maybe_promote(rep, "reverse a string", _result())
    assert consultum is not None
    assert consultum.is_binding
    assert len(consultum.quorum) >= 2                    # ≥2 distinct not-self validators carried it
    assert rep.consulta.is_binding(consultum.key)


def test_promotion_is_idempotent_on_rerun(tmp_path):
    rep = build_republic(tmp_path, prefer_redis=False)
    first = _maybe_promote(rep, "reverse a string", _result())
    second = _maybe_promote(rep, "reverse a string", _result())
    assert first.version == second.version               # same solution → no new version


def test_no_promotion_without_distinct_quorum(tmp_path):
    rep = build_republic(tmp_path, prefer_redis=False)
    # only the winner's own exact self "accepts" → 0 distinct not-self witnesses
    winner = "provider:groq:openai/gpt-oss-120b"
    cands = [Candidate("c0", winner, "gpt-oss", "x", "pass")]
    critiques = [Critique(f"judge:{winner}", "gpt-oss", "c0", 0.9, "accept", "self")]
    result = ConsensusResult("selected", "x", cands[0], cands, critiques, {"c0": 0.9})
    assert _maybe_promote(rep, "a task", result) is None
