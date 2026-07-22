"""Live Redis behavior via the EventBus — real round-trip against the running (Docker) Redis.
Auto-skips when Redis is unreachable. Uses a unique namespace per test and deletes its keys after, so it
never pollutes the operator's brain Redis."""
import uuid

import pytest

from citadel.paths import resolve_redis_url
from citadel.services.brain.bus import EventBus


def _redis_up() -> bool:
    url = resolve_redis_url()
    if not url:
        return False
    try:
        import redis

        redis.from_url(url, protocol=2, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_up(), reason="Redis not reachable on localhost:6379")


@pytest.fixture
def ns():
    namespace = f"citadeltest:{uuid.uuid4().hex[:8]}"
    yield namespace
    try:
        import redis

        r = redis.from_url(resolve_redis_url(), protocol=2)
        keys = r.keys(f"{namespace}:*")
        if keys:
            r.delete(*keys)
    except Exception:
        pass


def test_bus_selects_redis_backend(ns):
    assert EventBus(namespace=ns).backend() == "redis"


def test_publish_poll_ack_roundtrip_on_redis(ns):
    bus = EventBus(namespace=ns)
    topic, group = "jobs", "workers"
    bus.subscribe(topic, group)
    mid = bus.publish(topic, {"task": "build", "n": 1})
    assert mid
    got = bus.poll(topic, group, "c1", count=5, block_ms=800)
    assert any(ev.get("task") == "build" for _id, ev in got), got
    for msg_id, _ev in got:
        bus.ack(topic, group, msg_id)


def test_publish_is_idempotent_by_content_hash_on_redis(ns):
    bus = EventBus(namespace=ns)
    event = {"task": "x", "v": 2}
    first = bus.publish("t", event)
    assert bus.publish("t", event) == first  # duplicate content → original id, not a new entry


def test_stream_length_reflects_distinct_publishes(ns):
    bus = EventBus(namespace=ns)
    bus.publish("t", {"a": 1})
    bus.publish("t", {"a": 2})
    bus.publish("t", {"a": 1})  # duplicate of the first
    assert bus.depth("t") == 2  # idempotent dedup → only 2 distinct entries on the stream
