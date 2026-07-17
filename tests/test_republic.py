"""W1 — the composition root: build_republic assembles one shared bus that the ledger, brain, and consulta
store all publish onto, plus a registry that governs the known model families."""

from citadel.services.republic import build_republic, default_registry


def test_build_republic_shares_one_bus(tmp_path):
    rep = build_republic(tmp_path, prefer_redis=False)
    assert rep.ledger.bus is rep.bus            # ledger publishes learn events on the shared bus
    assert rep.brain.bus is rep.bus             # brain emits on the same bus
    assert rep.consulta.bus is rep.bus          # consulta broadcasts on the same bus
    assert rep.cursus.consulta is rep.consulta  # the Cursus enacts into that same store


def test_registry_governs_known_families():
    reg = default_registry()
    assert reg.for_model("provider:groq:openai/gpt-oss-120b") is not None   # gpt-oss family seeded
    assert reg.for_model("provider:nvidia:meta/llama-3.3-70b") is not None  # llama family seeded
    assert reg.for_model("cloud-claude") is not None                        # claude family seeded


def test_republic_learn_event_reaches_the_bus(tmp_path):
    rep = build_republic(tmp_path, prefer_redis=False)
    rep.bus.subscribe("learn", "sink")
    rep.ledger.record("do a thing", "provider:groq:x", success=True)
    got = rep.bus.poll("learn", "sink", "c", block_ms=0)
    assert len(got) == 1                        # the ledger's write surfaced on the shared bus
