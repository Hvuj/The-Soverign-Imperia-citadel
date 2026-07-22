"""P6 — SCU circuit-breaker + bounded escalation, Aerarium token-bucket, Provinces routing, Foreign Policy
egress, and the bus DLQ catching a poison event. Deterministic clock (no real sleeps)."""

from citadel.services.authority.tribune import SacrosanctRegistry
from citadel.services.brain.bus import EventBus
from citadel.services.senate.aerarium import Aerarium
from citadel.services.senate.foreign import ForeignPolicy
from citadel.services.senate.provinces import Province, Provinces
from citadel.services.senate.scu import CircuitBreaker, SenatusConsultumUltimum


# ── SCU circuit breaker + bounded escalation ────────────────────────────────────────────
def test_breaker_trips_only_on_systemic_failure():
    clock = {"t": 0.0}
    b = CircuitBreaker(threshold=3, cooldown_s=10.0, now=lambda: clock["t"])
    b.record_failure()
    b.record_failure()
    assert b.is_tripped() is False           # below threshold — a couple errors don't trip it
    b.record_failure()
    assert b.is_tripped() is True            # systemic → open
    clock["t"] = 20.0
    assert b.state() == "half_open"          # cools down to half-open for recovery
    b.record_success()
    assert b.is_tripped() is False


def test_scu_grants_dictator_then_auto_expires():
    clock = {"t": 100.0}
    scu = SenatusConsultumUltimum(threshold=2, ttl_seconds=30.0, now=lambda: clock["t"])
    scu.record_failure()
    scu.record_failure()
    assert scu.should_declare() is True
    dictator = scu.declare()
    assert scu.is_active() is True
    assert dictator.is_in_command(now=clock["t"]) is True
    clock["t"] = 100.0 + 31.0                # past the TTL lease
    assert scu.is_active() is False          # absolute power auto-expired (the reaper collected the lease)


def test_scu_bulkhead_never_condemns_sacrosanct():
    tribune = SacrosanctRegistry()
    tribune.protect(4321)                    # the stop-gate watchdog
    scu = SenatusConsultumUltimum(tribune=tribune, threshold=1)
    scu.record_failure()
    scu.declare()
    assert scu.may_condemn(9999) is True     # ordinary target may be condemned under emergency
    assert scu.may_condemn(4321) is False    # sacrosanct survives even the SCU (bulkhead)
    assert any("refused" in e["event"] for e in scu.audit)   # and it's audited


def test_scu_restore_stands_down_early():
    scu = SenatusConsultumUltimum(threshold=1, ttl_seconds=999.0)
    scu.record_failure()
    scu.declare()
    assert scu.is_active() is True
    scu.restore()
    assert scu.is_active() is False
    assert any(e["event"] == "restored" for e in scu.audit)


# ── Aerarium token bucket ────────────────────────────────────────────────────────────────
def test_aerarium_caps_and_refills():
    clock = {"t": 0.0}
    a = Aerarium(now=lambda: clock["t"])
    a.grant_bucket("gpt-oss", capacity=2.0, refill_per_s=1.0)
    assert a.allocate("gpt-oss") is True
    assert a.allocate("gpt-oss") is True
    assert a.allocate("gpt-oss") is False    # bucket empty → spend refused
    clock["t"] = 1.5                          # refills 1.5 tokens
    assert a.allocate("gpt-oss") is True
    assert a.allocate("ungoverned") is False  # no treasury line → default-deny


# ── Provinces routing ────────────────────────────────────────────────────────────────────
def test_provinces_route_by_zone():
    from citadel.services.authority.pomerium import Pomerium

    prov = Provinces(Pomerium(militiae_prefixes=["/tmp", "/sandbox"], default_zone="domi"))
    prov.define(Province("core", "domi", "local")).define(Province("edge", "militiae", "docker:sandbox"))
    assert prov.route("/tmp/run.py").container == "docker:sandbox"   # risky path → sandbox
    assert prov.route("src/app.py").container == "local"             # protected → trusted local


# ── Foreign Policy egress ────────────────────────────────────────────────────────────────
def test_foreign_policy_blocks_sensitive_and_offlist_hosts():
    fp = ForeignPolicy(redact=lambda t: t.replace("sk-XYZ", "[REDACTED]"))
    ok, reason, _ = fp.vet("here is my .env file", "https://api.groq.com/openai/v1")
    assert ok is False
    assert "sensitive" in reason
    ok, reason, _ = fp.vet("harmless prompt", "https://evil.example.com/v1")
    assert ok is False
    assert "allowlist" in reason
    ok, _, payload = fp.vet("token sk-XYZ please", "https://api.groq.com/openai/v1")
    assert ok is True
    assert payload == "token [REDACTED] please"       # redacted before send


# ── citadel senate ops command ───────────────────────────────────────────────────────────
def test_senate_command_reports_all_systems_online(capsys, tmp_path):
    from citadel.commands.senate import run

    rc = run(str(tmp_path), as_json=True)
    assert rc == 0
    import json

    data = json.loads(capsys.readouterr().out)
    assert all(data["systems"].values())            # every System (0-6) imports and is wired
    assert data["learning"]["backend"] in ("memory", "redis")


# ── bus DLQ (P6 gate) ────────────────────────────────────────────────────────────────────
def test_dlq_catches_a_poison_event():
    bus = EventBus(prefer_redis=False, max_deliveries=2)
    bus.subscribe("work", "g")
    bus.publish("work", {"job": "poison"})
    dead = False
    for _ in range(4):
        batch = bus.poll("work", "g", "c", block_ms=0)
        if not batch:
            break
        mid, event = batch[0]
        dead = bus.fail("work", "g", mid, event, reason="cannot process")
        if dead:
            break
    assert dead is True
    assert bus.depth(EventBus.dlq_topic("work")) == 1
