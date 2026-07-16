"""P3 — the consensus engine (map-reduce-shuffle). Fake members/judges + a deterministic verify, no network.
Proves: winner selection needs the deterministic gate + consensus score + ≥2 uncorrelated families; a
one-family accept is rejected; a verify failure is rejected; none-qualify → synthesize + re-verify."""

from citadel.services.consensus import ConsensusEngine, Critique, ModelJudge, family_of
from citadel.services.consensus.engine import _parse_score
from citadel.services.execute.blueprint import Blueprint, ExecutionResult
from citadel.services.execute.executor import Executor


class FakeMember(Executor):
    def __init__(self, name, output, status="pass"):
        self.name = name
        self._o = output
        self._s = status

    def execute(self, bp):
        return ExecutionResult(bp.task_id, self._s, output=self._o, tier_used=self.name)


class ScriptedJudge:
    """A validator that scores by a function of the candidate — carries its own uncorrelated family."""

    def __init__(self, family, score_fn):
        self.family = family
        self.name = f"judge:{family}"
        self._f = score_fn

    def critique(self, task, candidate):
        s = self._f(candidate)
        return Critique(self.name, self.family, candidate.id, s, "accept" if s >= 0.6 else "reject")


def _good(c):
    return 0.9 if "GOOD" in c.output else 0.1


def test_family_of_and_parse_score():
    assert family_of("provider:groq:gpt-oss") == "groq"
    assert family_of("provider:nvidia:llama") == "nvidia"
    assert family_of("cloud-claude") == "claude"
    assert family_of("local-coding") == "ollama"
    assert _parse_score("SCORE: 8\nlooks right") == 0.8
    assert _parse_score("no score here") == 0.0


def test_winner_selected_with_two_families_and_verify():
    members = [FakeMember("provider:groq:m", "GOOD solution"),
               FakeMember("provider:nvidia:m", "meh solution"),
               FakeMember("local-coding", "bad solution")]
    validators = [ScriptedJudge("claude", _good), ScriptedJudge("ollama", _good), ScriptedJudge("groq", _good)]
    engine = ConsensusEngine(members=members, validators=validators, verify=lambda o: ("GOOD" in o, "chk"))
    result = engine.run(Blueprint(task_id="t", instruction="do the thing"))
    assert result.method == "selected"
    assert result.output == "GOOD solution"
    assert result.winner.family == "groq"


def test_single_family_accept_fails_the_dual_gate():
    members = [FakeMember("provider:groq:m", "GOOD solution")]
    validators = [ScriptedJudge("claude", _good), ScriptedJudge("claude", _good)]  # same family twice
    engine = ConsensusEngine(members=members, validators=validators, verify=lambda o: (True, ""))
    result = engine.run(Blueprint(task_id="t", instruction="x"))
    assert result.method == "none"  # accepted, but by only ONE family → not selected, nothing to synth from


def test_verify_gate_rejects_high_consensus_but_unverified():
    members = [FakeMember("provider:groq:m", "GOOD candidate")]
    validators = [ScriptedJudge("claude", _good), ScriptedJudge("ollama", _good)]
    # deterministic gate demands the token 'VERIFIED' — the candidate lacks it despite high scores
    engine = ConsensusEngine(members=members, validators=validators, verify=lambda o: ("VERIFIED" in o, "gate"))
    result = engine.run(Blueprint(task_id="t", instruction="x"))
    assert result.method != "selected"


def test_synthesize_when_none_qualify():
    members = [FakeMember("provider:groq:m", "attempt A"), FakeMember("provider:nvidia:m", "attempt B")]
    validators = [ScriptedJudge("claude", lambda c: 0.2), ScriptedJudge("ollama", lambda c: 0.2)]  # all low
    synth = FakeMember("provider:nvidia:big", "synthesized ok")
    engine = ConsensusEngine(members=members, validators=validators,
                             verify=lambda o: ("ok" in o, "chk"), synthesizer=synth)
    result = engine.run(Blueprint(task_id="t", instruction="x"))
    assert result.method == "synthesized" and result.output == "synthesized ok"
    assert len(result.candidates) == 2  # both attempts were considered


def test_none_when_no_candidates():
    members = [FakeMember("provider:groq:m", "", status="error")]
    engine = ConsensusEngine(members=members, validators=[ScriptedJudge("claude", _good)])
    result = engine.run(Blueprint(task_id="t", instruction="x"))
    assert result.method == "none" and result.output == ""


def test_identical_candidates_are_deduplicated():
    members = [FakeMember("provider:groq:m", "SAME"), FakeMember("provider:nvidia:m", "SAME")]
    validators = [ScriptedJudge("claude", lambda c: 0.9), ScriptedJudge("ollama", lambda c: 0.9)]
    engine = ConsensusEngine(members=members, validators=validators, verify=lambda o: (True, ""))
    result = engine.run(Blueprint(task_id="t", instruction="x"))
    assert len(result.candidates) == 1  # the two identical outputs collapsed to one


def test_model_judge_parses_score_from_an_executor():
    judge = ModelJudge(FakeMember("provider:groq:m", "SCORE: 7\nreasonable"))
    from citadel.services.consensus.engine import Candidate
    crit = judge.critique("task", Candidate("c0", "m", "groq", "some code", "pass"))
    assert crit.score == 0.7 and crit.verdict == "accept" and crit.family == "groq"
