"""Redis fail-soft fallback — the EventBus degrades to in-memory when Redis is disabled or unreachable,
and every operation still works. Hermetic: no server required."""
from citadel.services.brain.bus import EventBus


def test_prefer_redis_false_uses_memory():
    assert EventBus(prefer_redis=False).backend() == "memory"


def test_unreachable_redis_falls_back_to_memory_without_crashing():
    # Nothing listens on :6390 → connect/ping refused → memory backend, no exception surfaces.
    bus = EventBus(redis_url="redis://127.0.0.1:6390", prefer_redis=True)
    assert bus.backend() == "memory"


def test_memory_publish_poll_ack_roundtrip():
    bus = EventBus(prefer_redis=False)
    bus.subscribe("t", "g")
    mid = bus.publish("t", {"task": "a"})
    assert mid.startswith("mem-")
    got = bus.poll("t", "g", "c", count=5, block_ms=50)
    assert any(ev.get("task") == "a" for _id, ev in got)
    for msg_id, _ev in got:
        bus.ack("t", "g", msg_id)


def test_memory_publish_is_idempotent():
    bus = EventBus(prefer_redis=False)
    event = {"x": 1}
    assert bus.publish("t", event) == bus.publish("t", event)


def test_memory_depth_counts_distinct_events():
    bus = EventBus(prefer_redis=False)
    bus.publish("t", {"a": 1})
    bus.publish("t", {"a": 2})
    bus.publish("t", {"a": 1})  # duplicate
    assert bus.depth("t") == 2


def test_memory_failed_event_is_redelivered_before_new():
    bus = EventBus(prefer_redis=False, max_deliveries=5)
    bus.subscribe("t", "g")
    bus.publish("t", {"n": 1})
    [(mid, ev)] = bus.poll("t", "g", "c", count=1, block_ms=50)
    assert bus.fail("t", "g", mid, ev) is False   # under max_deliveries → scheduled for redelivery
    bus.publish("t", {"n": 2})
    again = bus.poll("t", "g", "c", count=1, block_ms=50)
    assert again
    assert again[0][0] == mid                     # redelivery comes before the new event


def test_memory_event_goes_to_dlq_after_max_deliveries():
    bus = EventBus(prefer_redis=False, max_deliveries=2)
    bus.subscribe("t", "g")
    bus.publish("t", {"n": 1})
    [(mid, ev)] = bus.poll("t", "g", "c", count=1, block_ms=50)
    assert bus.fail("t", "g", mid, ev) is False    # 1st failure → redeliver
    [(mid2, ev2)] = bus.poll("t", "g", "c", count=1, block_ms=50)
    assert bus.fail("t", "g", mid2, ev2) is True   # hit max_deliveries → dead-lettered (DLQ), acked
    assert bus.depth(EventBus.dlq_topic("t")) == 1  # the poison event landed on the DLQ
