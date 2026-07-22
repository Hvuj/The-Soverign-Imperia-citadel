"""bus.py — the brain's event bus (System 6): topic pub/sub over Redis Streams with an in-memory fallback.

Every learn / promote / decision event in the Republic travels this bus, so producers never know their
consumers (Observer / Publish-Subscribe) and subsystems stay decoupled. Guarantees:

- **Idempotent publish** — an event is content-addressed (canonical JSON → blake2b); re-publishing the same
  event returns the original id and appends nothing (effectively-once at the write edge).
- **Consumer groups** — N consumers on a group pull disjoint events (load-balanced fan-out + backpressure).
- **At-least-once + idempotent consumers** — delivery may repeat; consumers dedupe on the event's `_hash`.
- **Dead-Letter Queue** — an event that fails `max_deliveries` times is routed to `<topic>:dlq` and acked,
  so one poison event never blocks the stream.

Redis Streams give durability + multi-consumer semantics; with no Redis reachable the exact same contract
runs on a thread-safe in-memory log (degrade, never crash).
"""

import contextlib
import hashlib
import json
import threading
import time
from collections import defaultdict, deque

from citadel.paths import resolve_redis_url as _resolve_redis_url


def event_hash(event: dict) -> str:
    """Content address of an event — canonical JSON → blake2b. Structurally-equal events share it, so a
    re-publish is a no-op (idempotency) and a consumer can dedupe on it (effectively-once)."""
    raw = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=16).hexdigest()


def _dec(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class EventBus:
    def __init__(
        self,
        *,
        namespace: str = "citadel:bus",
        redis_url: str | None = None,
        prefer_redis: bool = True,
        idem_ttl_s: int = 3600,
        max_deliveries: int = 5,
    ) -> None:
        self.namespace = namespace
        self._idem_ttl_s = idem_ttl_s
        self._max_deliveries = max(1, max_deliveries)
        self._redis = None
        url = _resolve_redis_url(explicit=redis_url)
        if prefer_redis and url:
            try:
                import redis

                self._redis = redis.from_url(url, protocol=2)
                self._redis.ping()
            except Exception:
                self._redis = None
        # in-memory fallback state (append-only log per topic + per-group cursors)
        self._lock = threading.RLock()
        self._log: dict[str, list[tuple[str, dict, str]]] = defaultdict(list)  # topic -> [(id, event, hash)]
        self._groups: dict[tuple[str, str], dict] = {}                          # (topic, group) -> state
        self._idem: dict[str, dict[str, str]] = defaultdict(dict)               # topic -> {hash: id}
        self._seq = 0

    # ── keys ────────────────────────────────────────────────────────────────────────
    def _stream_key(self, topic: str) -> str:
        return f"{self.namespace}:{topic}"

    def _idem_key(self, topic: str) -> str:
        return f"{self.namespace}:{topic}:idem"

    def _fails_key(self, topic: str, group: str) -> str:
        return f"{self.namespace}:{topic}:{group}:fails"

    @staticmethod
    def dlq_topic(topic: str) -> str:
        return f"{topic}:dlq"

    # ── publish (idempotent) ──────────────────────────────────────────────────────────
    def publish(self, topic: str, event: dict) -> str:
        """Append an event to `topic`; idempotent by content hash — a duplicate returns the original id."""
        h = event_hash(event)
        if self._redis is not None:
            idem = self._idem_key(topic)
            existing = self._redis.hget(idem, h)
            if existing:
                return _dec(existing)
            payload = json.dumps({"_hash": h, **event}, default=str)
            msg_id = _dec(self._redis.execute_command("XADD", self._stream_key(topic), "*", "event", payload))
            self._redis.hset(idem, h, msg_id)
            self._redis.expire(idem, self._idem_ttl_s)
            return msg_id
        with self._lock:
            existing = self._idem[topic].get(h)
            if existing:
                return existing
            self._seq += 1
            msg_id = f"mem-{self._seq}"
            self._log[topic].append((msg_id, dict(event), h))
            self._idem[topic][h] = msg_id
            return msg_id

    # ── subscribe / poll / ack (consumer groups) ──────────────────────────────────────
    def subscribe(self, topic: str, group: str) -> None:
        """Ensure a consumer group exists, reading only events published after this point (Redis '$')."""
        if self._redis is not None:
            with contextlib.suppress(Exception):  # BUSYGROUP: already exists
                self._redis.execute_command(
                    "XGROUP", "CREATE", self._stream_key(topic), group, "$", "MKSTREAM"
                )
            return
        with self._lock:
            self._groups.setdefault(
                (topic, group), {"pos": len(self._log[topic]), "inflight": {}, "retry": deque()}
            )

    def poll(
        self, topic: str, group: str, consumer: str, *, count: int = 1, block_ms: int = 100
    ) -> list[tuple[str, dict]]:
        """Pull up to `count` events for `consumer` in `group`; redeliveries (nacked events) come first."""
        if self._redis is not None:
            res = self._redis.execute_command(
                "XREADGROUP", "GROUP", group, consumer, "COUNT", str(count), "BLOCK", str(block_ms),
                "STREAMS", self._stream_key(topic), ">",
            )
            out: list[tuple[str, dict]] = []
            if res:
                _stream, entries = res[0]
                for msg_id, fields in entries or []:
                    pairs = fields.items() if isinstance(fields, dict) else zip(fields[::2], fields[1::2], strict=False)
                    data = {_dec(k): _dec(v) for k, v in pairs}
                    out.append((_dec(msg_id), json.loads(data.get("event", "{}"))))
            return out
        deadline = time.time() + block_ms / 1000.0
        while True:
            with self._lock:
                g = self._groups.setdefault(
                    (topic, group), {"pos": len(self._log[topic]), "inflight": {}, "retry": deque()}
                )
                log = self._log[topic]
                out = []
                while g["retry"] and len(out) < count:                     # redeliver nacked first
                    mid = g["retry"].popleft()
                    event, _h, _fails = g["inflight"][mid]
                    out.append((mid, dict(event)))
                while g["pos"] < len(log) and len(out) < count:            # then new events
                    mid, event, h = log[g["pos"]]
                    g["pos"] += 1
                    g["inflight"][mid] = (event, h, 0)
                    out.append((mid, dict(event)))
                if out:
                    return out
            if time.time() >= deadline:
                return []
            time.sleep(0.005)

    def ack(self, topic: str, group: str, msg_id: str) -> None:
        if self._redis is not None:
            self._redis.execute_command("XACK", self._stream_key(topic), group, msg_id)
            self._redis.hdel(self._fails_key(topic, group), msg_id)
            return
        with self._lock:
            g = self._groups.get((topic, group))
            if g:
                g["inflight"].pop(msg_id, None)

    def fail(self, topic: str, group: str, msg_id: str, event: dict, *, reason: str = "") -> bool:
        """Nack a poison event. After `max_deliveries` failures it is routed to the DLQ and acked (returns
        True); before that it is scheduled for redelivery (returns False)."""
        if self._redis is not None:
            fails = int(self._redis.hincrby(self._fails_key(topic, group), msg_id, 1))
            if fails >= self._max_deliveries:
                self.publish(self.dlq_topic(topic), {"reason": reason, "original": event, "orig_id": msg_id})
                self._redis.execute_command("XACK", self._stream_key(topic), group, msg_id)
                self._redis.hdel(self._fails_key(topic, group), msg_id)
                return True
            return False  # left pending; reclaim() redelivers it
        with self._lock:
            g = self._groups.setdefault(
                (topic, group), {"pos": len(self._log[topic]), "inflight": {}, "retry": deque()}
            )
            event_stored, h, fails = g["inflight"].get(msg_id, (event, event_hash(event), 0))
            fails += 1
            if fails >= self._max_deliveries:
                g["inflight"].pop(msg_id, None)
                self.publish(self.dlq_topic(topic), {"reason": reason, "original": event_stored, "orig_id": msg_id})
                return True
            g["inflight"][msg_id] = (event_stored, h, fails)
            g["retry"].append(msg_id)
            return False

    def reclaim(
        self, topic: str, group: str, consumer: str, *, min_idle_ms: int = 0, count: int = 16
    ) -> list[tuple[str, dict]]:
        """Redis-only: claim events left pending by a dead/slow consumer (XAUTOCLAIM). No-op in-mem
        (redelivery there is handled inline by `poll` draining the retry queue)."""
        if self._redis is None:
            return []
        try:
            res = self._redis.execute_command(
                "XAUTOCLAIM", self._stream_key(topic), group, consumer, str(min_idle_ms), "0", "COUNT", str(count)
            )
        except Exception:
            return []
        out: list[tuple[str, dict]] = []
        entries = res[1] if len(res) > 1 else []
        for msg_id, fields in entries or []:
            if not fields:
                continue
            pairs = fields.items() if isinstance(fields, dict) else zip(fields[::2], fields[1::2], strict=False)
            data = {_dec(k): _dec(v) for k, v in pairs}
            out.append((_dec(msg_id), json.loads(data.get("event", "{}"))))
        return out

    # ── introspection ─────────────────────────────────────────────────────────────────
    def pending(self, topic: str, group: str) -> int:
        if self._redis is not None:
            try:
                info = self._redis.execute_command("XPENDING", self._stream_key(topic), group)
                return int(info[0]) if info else 0
            except Exception:
                return 0
        with self._lock:
            g = self._groups.get((topic, group))
            return len(g["inflight"]) if g else 0

    def depth(self, topic: str) -> int:
        if self._redis is not None:
            try:
                return int(self._redis.execute_command("XLEN", self._stream_key(topic)))
            except Exception:
                return 0
        with self._lock:
            return len(self._log[topic])

    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"
