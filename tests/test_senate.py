"""P5 — the Senate: Cursus Honorum promotion (not-self quorum at every rung), Senatus Consulta (versioned,
weighted, repealable, broadcast), Princeps priority-without-dictatorship, and JIT decay of stale consulta."""

from citadel.services.brain.bus import EventBus
from citadel.services.senate.consulta import DEMOTED, REPEALED, ConsultaStore
from citadel.services.senate.cursus import CursusHonorum, Proposal
from citadel.services.senate.decay import sweep
from citadel.services.senate.princeps import Princeps


# ── Cursus Honorum ──────────────────────────────────────────────────────────────────────
def _cursus(bus=None):
    return CursusHonorum(ConsultaStore(bus=bus), min_witnesses=2)


def test_promotion_requires_not_self_quorum_and_reaches_consul():
    cursus = _cursus()
    p = Proposal(id="lesson-1", author="provider:groq:openai/gpt-oss-120b", content={"rule": "cache-aside"})
    validators = ["provider:nvidia:meta/llama-3.3-70b", "provider:groq:openai/gpt-oss-20b", "cloud-claude"]
    cursus.run_to_consul(p, validators=validators, accepting=validators)
    assert p.is_consul                                   # climbed all four rungs
    assert cursus.consulta.is_binding("lesson-1")        # and was enacted as a Consultum


def test_self_promotion_is_blocked():
    cursus = _cursus()
    p = Proposal(id="l", author="provider:groq:openai/gpt-oss-120b", content={})
    # the only "validators" are the author's exact self (+ a dup) → 0 distinct not-self witnesses
    ok, reason = cursus.advance(
        p, validators=["provider:groq:openai/gpt-oss-120b"],
        accepting=["provider:groq:openai/gpt-oss-120b", "provider:groq:openai/gpt-oss-120b"],
        deterministic_ok=True,
    )
    assert ok is False
    assert "not-self" in reason
    assert p.rank == "proposed"


def test_same_family_different_config_counts_as_witness():
    cursus = _cursus()
    p = Proposal(id="l", author="cloud-claude#opus-low", content={})
    # same family, different effort/config → valid distinct witnesses (the user's rule)
    ok, _ = cursus.advance(
        p, validators=[], accepting=["cloud-claude#opus-medium", "cloud-claude#sonnet"], deterministic_ok=True
    )
    assert ok is True
    assert p.rank == "quaestor"


def test_deterministic_gate_holds_the_rung():
    cursus = _cursus()
    p = Proposal(id="l", author="a:x:1", content={})
    ok, reason = cursus.advance(p, validators=[], accepting=["b:y:2", "c:z:3"], deterministic_ok=False)
    assert ok is False
    assert "deterministic" in reason
    assert p.rank == "proposed"


# ── Senatus Consulta ────────────────────────────────────────────────────────────────────
def test_consulta_versioning_and_repeal_tombstone():
    store = ConsultaStore()
    c1 = store.enact("routing", {"prefer": "local"}, quorum=("a", "b"))
    c2 = store.enact("routing", {"prefer": "cloud"}, quorum=("a", "b"))
    assert c1.version == 1
    assert c2.version == 2
    assert c1.content_hash != c2.content_hash
    rep = store.repeal("routing")
    assert rep.status == REPEALED
    assert rep.version == 3
    assert store.is_binding("routing") is False           # tombstoned, but history preserved
    assert len(store.history("routing")) == 3


def test_consulta_broadcast_on_the_bus():
    bus = EventBus(prefer_redis=False)
    bus.subscribe("consulta", "watch")
    ConsultaStore(bus=bus).enact("k", {"x": 1}, quorum=("a", "b"))
    got = bus.poll("consulta", "watch", "c", block_ms=0)
    assert len(got) == 1
    assert got[0][1]["event"] == "enacted"
    assert got[0][1]["key"] == "k"


def test_consulta_appeal_is_reconciled_not_fatal():
    store = ConsultaStore()
    store.enact("policy", {"v": 1}, quorum=("a", "b"))
    appealed = store.appeal("policy")
    assert appealed.status == "appealed"          # suspended, not crashed
    assert store.is_binding("policy") is False


# ── Princeps ────────────────────────────────────────────────────────────────────────────
def test_princeps_speaks_first_by_trust():
    p = Princeps({"cloud-claude": 0.9, "provider:groq:openai/gpt-oss-120b": 0.4, "ollama-local": 0.1})
    order = p.order(["ollama-local", "provider:groq:openai/gpt-oss-120b", "cloud-claude"])
    assert order[0] == "cloud-claude"                      # highest trust speaks first
    assert p.speaker(["ollama-local", "cloud-claude"]) == "cloud-claude"


def test_princeps_cannot_dictate_needs_quorum():
    p = Princeps({"cloud-claude": 0.99})
    # the princeps alone cannot carry a motion
    carried, _ = p.decide(["cloud-claude"], ["cloud-claude"])
    assert carried is False
    # a real majority of distinct identities does
    carried, _ = p.decide(["cloud-claude", "provider:groq:x", "provider:nvidia:y"],
                          ["cloud-claude", "provider:groq:x"])
    assert carried is True


# ── JIT decay ───────────────────────────────────────────────────────────────────────────
def test_stale_consultum_is_demoted_on_sweep():
    store = ConsultaStore()
    store.enact("derived", {"from": "src/a.py"}, quorum=("a", "b"),
                sources=[("src/a.py", "hash-when-enacted")])
    # a fresh source → stays binding
    assert sweep(store, is_fresh=lambda path, h: True) == []
    assert store.is_binding("derived") is True
    # the source content changed (hash mismatch) → demoted lazily on read
    demoted = sweep(store, is_fresh=lambda path, h: False)
    assert demoted == ["derived"]
    assert store.latest("derived").status == DEMOTED
    assert store.is_binding("derived") is False
