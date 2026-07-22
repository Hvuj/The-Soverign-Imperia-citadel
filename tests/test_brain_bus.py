"""P0 — the brain event bus: idempotent publish, consumer-group poll/ack, redelivery, and DLQ. In-memory
path (no Redis) so it runs anywhere; the Redis path shares the same contract."""

from citadel.services.brain.bus import EventBus, event_hash


def _bus() -> EventBus:
    return EventBus(prefer_redis=False, max_deliveries=3)


def test_event_hash_is_order_independent():
    assert event_hash({"a": 1, "b": 2}) == event_hash({"b": 2, "a": 1})
    assert event_hash({"a": 1}) != event_hash({"a": 2})


def test_publish_is_idempotent_by_content():
    bus = _bus()
    first = bus.publish("learn", {"kind": "worked", "summary": "cache-aside"})
    dup = bus.publish("learn", {"summary": "cache-aside", "kind": "worked"})  # same content, diff order
    assert first == dup             # no re-append — same id
    assert bus.depth("learn") == 1  # only one event on the stream


def test_consumer_group_poll_ack_roundtrip():
    bus = _bus()
    bus.subscribe("learn", "senate")
    mid = bus.publish("learn", {"kind": "bug", "summary": "off-by-one"})
    got = bus.poll("learn", "senate", "c1", block_ms=0)
    assert len(got) == 1
    assert got[0][0] == mid
    assert got[0][1]["summary"] == "off-by-one"
    assert bus.pending("learn", "senate") == 1
    bus.ack("learn", "senate", mid)
    assert bus.pending("learn", "senate") == 0


def test_subscribe_reads_only_new_events():
    bus = _bus()
    bus.publish("learn", {"n": 0})           # before subscribe
    bus.subscribe("learn", "g")              # '$' semantics — only new
    bus.publish("learn", {"n": 1})
    got = bus.poll("learn", "g", "c", block_ms=0)
    assert [e["n"] for _mid, e in got] == [1]


def test_poison_event_redelivers_then_dead_letters():
    bus = _bus()  # max_deliveries=3
    bus.subscribe("learn", "g")
    bus.publish("learn", {"kind": "poison"})
    dead = False
    for _ in range(5):
        batch = bus.poll("learn", "g", "c", block_ms=0)
        if not batch:
            break
        mid, event = batch[0]
        dead = bus.fail("learn", "g", mid, event, reason="boom")
        if dead:
            break
    assert dead is True
    # the poison event landed on the DLQ, and the main stream's group is drained
    bus.subscribe(EventBus.dlq_topic("learn"), "reaper")
    # DLQ was written by publish() so it's in the log regardless of subscribe timing:
    assert bus.depth(EventBus.dlq_topic("learn")) == 1
    assert bus.pending("learn", "g") == 0


def test_two_consumers_split_the_work():
    bus = _bus()
    bus.subscribe("t", "g")
    ids = [bus.publish("t", {"n": i}) for i in range(4)]
    a = bus.poll("t", "g", "a", count=2, block_ms=0)
    b = bus.poll("t", "g", "b", count=2, block_ms=0)
    seen = {mid for mid, _ in a} | {mid for mid, _ in b}
    assert seen == set(ids)  # disjoint fan-out covering every event
