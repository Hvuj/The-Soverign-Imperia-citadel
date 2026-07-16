"""queue.py — the atomic-task job queue (Redis Streams, in-memory fallback).

Redis Streams give the army a durable, multi-consumer work queue: `enqueue` is XADD, `claim` is XREADGROUP
against a consumer group (so N workers pull disjoint tasks), `ack` is XACK. With no Redis reachable it falls
back to a thread-safe in-memory queue with the same contract, so the pool runs anywhere (degrade, never
crash). Task payloads are small JSON dicts.
"""

import json
import threading
import time
from collections import deque

from citadel.paths import resolve_redis_url as _resolve_redis_url


class JobQueue:
    def __init__(self, run_id: str, *, redis_url: str | None = None, prefer_redis: bool = True) -> None:
        self.run_id = run_id
        self._group = "workers"
        self._key = f"citadel:army:{run_id}"
        self._redis = None
        url = _resolve_redis_url(explicit=redis_url)
        if prefer_redis and url:
            try:
                import redis

                self._redis = redis.from_url(url, protocol=2)
                self._redis.ping()
                self._ensure_group()
            except Exception:
                self._redis = None
        # in-memory fallback state
        self._lock = threading.Lock()
        self._ready: deque[tuple[str, dict]] = deque()
        self._inflight: dict[str, dict] = {}
        self._seq = 0

    def _ensure_group(self) -> None:
        try:
            self._redis.execute_command("XGROUP", "CREATE", self._key, self._group, "$", "MKSTREAM")
        except Exception:
            pass  # BUSYGROUP: already exists

    def enqueue(self, task: dict) -> str:
        if self._redis is not None:
            msg_id = self._redis.execute_command("XADD", self._key, "*", "task", json.dumps(task))
            return msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
        with self._lock:
            self._seq += 1
            msg_id = f"mem-{self._seq}"
            self._ready.append((msg_id, task))
            return msg_id

    def claim(self, worker_id: str, *, block_ms: int = 1000) -> tuple[str, dict] | None:
        """Claim the next task for `worker_id`, or None if the queue is empty within the block window."""
        if self._redis is not None:
            res = self._redis.execute_command(
                "XREADGROUP", "GROUP", self._group, worker_id, "COUNT", "1", "BLOCK", str(block_ms),
                "STREAMS", self._key, ">",
            )
            if not res:
                return None
            _stream, entries = res[0]
            if not entries:
                return None
            msg_id, fields = entries[0]
            msg_id = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            # redis-py may hand fields back as a dict or a flat [k, v, k, v] array — handle both.
            pairs = fields.items() if isinstance(fields, dict) else zip(fields[::2], fields[1::2])
            data = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                    for k, v in pairs}
            return msg_id, json.loads(data.get("task", "{}"))
        deadline = time.time() + block_ms / 1000.0
        while True:
            with self._lock:
                if self._ready:
                    msg_id, task = self._ready.popleft()
                    self._inflight[msg_id] = task
                    return msg_id, task
            if time.time() >= deadline:
                return None
            time.sleep(0.005)

    def ack(self, msg_id: str) -> None:
        if self._redis is not None:
            self._redis.execute_command("XACK", self._key, self._group, msg_id)
            return
        with self._lock:
            self._inflight.pop(msg_id, None)

    def pending(self) -> int:
        if self._redis is not None:
            try:
                info = self._redis.execute_command("XPENDING", self._key, self._group)
                return int(info[0]) if info else 0
            except Exception:
                return 0
        with self._lock:
            return len(self._ready) + len(self._inflight)

    def purge(self) -> None:
        if self._redis is not None:
            try:
                self._redis.delete(self._key)
            except Exception:
                pass
            return
        with self._lock:
            self._ready.clear()
            self._inflight.clear()
