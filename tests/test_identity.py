"""P1 — model identity + the not-self validation rule. A model can't validate its exact self, but a
different config of the same family can (opus-low vs opus-medium; sonnet-5 vs sonnet-4.6; haiku vs sonnet)."""

from citadel.services.authority.intercessio import Gate, dual_gate
from citadel.services.consensus.identity import (
    ModelIdentity,
    can_validate,
    distinct_witnesses,
    identity_of,
)


def test_identity_of_parses_names():
    g = identity_of("provider:groq:openai/gpt-oss-120b")
    assert g.vendor == "groq"
    assert g.family == "gpt-oss"
    assert g.model_id == "openai/gpt-oss-120b"
    assert identity_of("judge:provider:nvidia:meta/llama-3.3-70b").vendor == "nvidia"  # strips judge:
    assert identity_of("cloud-claude").vendor == "anthropic"
    assert identity_of("local-coding").vendor == "ollama"


def test_effort_is_part_of_identity():
    low = identity_of("cloud-claude#low")
    med = identity_of("cloud-claude#medium")
    assert low.effort == "low"
    assert med.effort == "medium"
    assert can_validate(low, med) is True  # same model, different effort → valid independent validator


def test_cannot_validate_exact_self():
    a = ModelIdentity("anthropic", "claude", "claude-opus-4-8", "medium")
    same = ModelIdentity("anthropic", "claude", "claude-opus-4-8", "medium")
    assert can_validate(a, same) is False  # exact self


def test_same_family_different_model_can_validate():
    sonnet5 = ModelIdentity("anthropic", "claude", "claude-sonnet-5")
    sonnet46 = ModelIdentity("anthropic", "claude", "claude-sonnet-4-6")
    haiku = ModelIdentity("anthropic", "claude", "claude-haiku")
    assert can_validate(sonnet5, sonnet46)
    assert can_validate(sonnet5, haiku)


def test_distinct_witnesses_excludes_self_and_dedupes():
    author = identity_of("provider:groq:openai/gpt-oss-120b")
    validators = [
        identity_of("provider:groq:openai/gpt-oss-120b"),  # == author → excluded
        identity_of("provider:groq:openai/gpt-oss-20b"),   # same family, diff model → counts
        identity_of("provider:groq:openai/gpt-oss-20b"),   # dup → dedup
        identity_of("provider:nvidia:meta/llama-3.3-70b"), # counts
    ]
    w = distinct_witnesses(author, validators)
    assert len(w) == 2  # gpt-oss-20b + llama, self excluded, dup collapsed


def test_dual_gate_identity_aware_same_family_diff_effort():
    # two Claude gates of DIFFERENT effort → distinct → approved
    approved, _ = dual_gate([Gate("claude", True, "opus-4.8-low"), Gate("claude", True, "opus-4.8-medium")])
    assert approved is True
    # two IDENTICAL identities → not approved
    approved, reason = dual_gate([Gate("claude", True, "opus-4.8-low"), Gate("claude", True, "opus-4.8-low")])
    assert approved is False
    assert "distinct 2nd" in reason


def test_dual_gate_backward_compatible_family_only():
    # no identity set → falls back to family (existing behaviour)
    assert dual_gate([Gate("claude", True), Gate("gemini", True)])[0] is True
    assert dual_gate([Gate("claude", True), Gate("claude", True)])[0] is False
