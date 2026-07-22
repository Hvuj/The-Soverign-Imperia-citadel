"""learning.py — the shared LearningLedger (System 3): every model learns, together, into the one brain.

Two concerns, kept separate on purpose:

- **Outcome time-series** — each run's pass/fail drives a per-task-signature **EWMA success-rate** (recency
  weighted, so a freshly-fixed task's rate climbs fast). O(1) update; we keep only the running rate + count,
  never the whole history. The signature is an exact hash of the normalized token set.
- **Knowledge** — the *lessons* (what worked / failed / bug / perf / best-practice), **content-addressed and
  deduped** so ten workers recording the same insight store it once (idempotent, conflict-free merge).

Recall is **O(1)** and *fuzzy*: an intent's normalized token set is reduced to a **MinHash** signature and
indexed by **LSH bands**, so *similar* intents (high Jaccard) share a band and recall each other's lessons
without scanning — while unrelated intents stay apart. Lessons are ranked by **time-decay** (fresh wins) with
the exact signature's EWMA success attached. CQRS: `record` is the write model, `recall` the read model.
Redis hashes/sets give the O(1) hot path; an in-memory map is the exact fallback (degrade, never crash).
"""

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass

from citadel.paths import resolve_redis_url as _resolve_redis_url
from citadel.services.brain.bus import EventBus, event_hash

CATEGORIES = ("worked", "failed", "bug", "perf", "best_practice")
_TOKEN = re.compile(r"[a-z0-9_]+")
# a tiny function-word stoplist so trivial phrasing differences collapse to the same token set
_STOP = frozenset({
    "a", "an", "the", "of", "to", "in", "on", "for", "with", "and", "or", "is", "are",
    "be", "this", "that", "it", "its", "as", "at", "by", "from", "into", "we", "you", "i",
})
_MINHASH_K = 16   # MinHash slots
_LSH_ROWS = 2     # rows per band → 8 bands; a shared band ≈ Jaccard collision


def _tokens(text: str) -> list[str]:
    return sorted({t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP})


def task_signature(text: str, *, bits: int = 32) -> str:
    """Exact signature of a task's *normalized token set* (order-, case-, punctuation-, stopword-invariant).
    Used as the EWMA key: recurrences of the same intent fold into one running success-rate."""
    toks = _tokens(text)
    if not toks:
        return "0" * (bits // 4)
    return hashlib.blake2b(" ".join(toks).encode(), digest_size=bits // 8).hexdigest()


def _minhash(tokens: list[str], k: int = _MINHASH_K) -> tuple[int, ...]:
    if not tokens:
        return tuple([0] * k)
    out = []
    for i in range(k):
        salt = i.to_bytes(2, "big")
        out.append(min(int.from_bytes(hashlib.blake2b(t.encode(), salt=salt, digest_size=8).digest(), "big")
                       for t in tokens))
    return tuple(out)


def lsh_bands(text: str, *, k: int = _MINHASH_K, rows: int = _LSH_ROWS) -> list[str]:
    """LSH band keys for an intent — similar intents (high Jaccard) collide on ≥1 band → O(1) fuzzy recall."""
    mh = _minhash(_tokens(text), k)
    bands = []
    for b in range(0, k, rows):
        digest = hashlib.blake2b(repr(mh[b:b + rows]).encode(), digest_size=8).hexdigest()
        bands.append(f"{b // rows}:{digest}")
    return bands


@dataclass(frozen=True, slots=True)
class Learning:
    signature: str
    identity: str
    category: str
    summary: str
    content_hash: str
    ts: float


class LearningStore:
    """Repository + CQRS over the learning events. Redis hashes/sets (O(1)) with an in-memory fallback."""

    def __init__(
        self,
        *,
        namespace: str = "citadel:brain:learn",
        bus: EventBus | None = None,
        redis_url: str | None = None,
        prefer_redis: bool = True,
        ewma_alpha: float = 0.3,
        half_life_s: float = 14 * 86400.0,
        ttl_s: float = 90 * 86400.0,
        now=time.time,
    ) -> None:
        self.namespace = namespace
        self.bus = bus
        self._alpha = ewma_alpha
        self._half_life_s = half_life_s
        self._ttl_s = ttl_s
        self._now = now
        self._redis = None
        url = _resolve_redis_url(explicit=redis_url)
        if prefer_redis and url:
            try:
                import redis

                self._redis = redis.from_url(url, protocol=2)
                self._redis.ping()
            except Exception:
                self._redis = None
        self._lock = threading.RLock()
        self._learnings: dict[str, Learning] = {}        # content_hash -> Learning (authoritative, deduped)
        self._band_index: dict[str, set[str]] = {}       # band_key -> {content_hash}
        self._ewma: dict[str, tuple[float, int]] = {}    # signature -> (rate, count)

    # ── keys ────────────────────────────────────────────────────────────────────────
    def _learn_key(self) -> str:
        return f"{self.namespace}:learnings"

    def _band_key(self, band: str) -> str:
        return f"{self.namespace}:band:{band}"

    def _ewma_key(self) -> str:
        return f"{self.namespace}:ewma"

    # ── write model ───────────────────────────────────────────────────────────────────
    def record(self, task: str, identity: str, *, success: bool, category: str = "", summary: str = "") -> bool:
        """Record one run's outcome. Always folds the pass/fail into the signature's EWMA; when a `summary`
        is given, stores that lesson content-addressed (deduped) + LSH-indexed. Returns True iff NEW."""
        sig = task_signature(task)
        self._update_ewma(sig, success)
        added = False
        if summary:
            cat = category if category in CATEGORIES else ("worked" if success else "failed")
            ch = event_hash({"sig": sig, "identity": identity, "category": cat, "summary": summary})
            learning = Learning(sig, identity, cat, summary, ch, self._now())
            added = self._store_learning(learning, lsh_bands(task))
        if self.bus is not None:
            self.bus.publish("learn", {"sig": sig, "identity": identity, "success": success,
                                       "category": category, "summary": summary})
        return added

    def _update_ewma(self, sig: str, success: bool) -> None:
        x = 1.0 if success else 0.0
        if self._redis is not None:
            raw = self._redis.hget(self._ewma_key(), sig)
            rate, count = (json.loads(raw) if raw else (x, 0))
            rate = x if count == 0 else self._alpha * x + (1 - self._alpha) * rate
            self._redis.hset(self._ewma_key(), sig, json.dumps([rate, count + 1]))
            return
        with self._lock:
            rate, count = self._ewma.get(sig, (x, 0))
            rate = x if count == 0 else self._alpha * x + (1 - self._alpha) * rate
            self._ewma[sig] = (rate, count + 1)

    def _store_learning(self, learning: Learning, bands: list[str]) -> bool:
        if self._redis is not None:
            new = bool(self._redis.hsetnx(self._learn_key(), learning.content_hash, json.dumps(asdict(learning))))
            if new:
                for band in bands:
                    self._redis.sadd(self._band_key(band), learning.content_hash)
            return new
        with self._lock:
            if learning.content_hash in self._learnings:
                return False
            self._learnings[learning.content_hash] = learning
            for band in bands:
                self._band_index.setdefault(band, set()).add(learning.content_hash)
            return True

    # ── read model ─────────────────────────────────────────────────────────────────────
    def success_rate(self, task: str) -> tuple[float, int]:
        """The (EWMA success-rate, sample count) for the task's exact signature — 0.0/0 when unseen."""
        sig = task_signature(task)
        if self._redis is not None:
            raw = self._redis.hget(self._ewma_key(), sig)
            rate, count = (json.loads(raw) if raw else (0.0, 0))
            return float(rate), int(count)
        with self._lock:
            rate, count = self._ewma.get(sig, (0.0, 0))
            return rate, count

    def recall(self, task: str, *, limit: int = 5) -> list[dict]:
        """O(1) fuzzy recall: gather lessons from the intent's LSH bands, drop stale (past TTL) ones lazily,
        rank by time-decay (fresh first). Each carries the exact signature's EWMA success + sample count."""
        learnings = self._candidates(lsh_bands(task))
        now = self._now()
        rate, count = self.success_rate(task)
        scored = []
        for lg in learnings:
            age = max(0.0, now - lg.ts)
            if self._ttl_s and age > self._ttl_s:
                continue  # lazy time-decay (JIT retirement of stale knowledge)
            decay = 0.5 ** (age / self._half_life_s) if self._half_life_s else 1.0
            scored.append((decay, lg))
        scored.sort(key=lambda t: (t[0], t[1].ts), reverse=True)
        return [
            {"category": lg.category, "summary": lg.summary, "identity": lg.identity,
             "success_rate": round(rate, 3), "samples": count}
            for _decay, lg in scored[:limit]
        ]

    def _candidates(self, bands: list[str]) -> list[Learning]:
        if self._redis is not None:
            hashes: set[str] = set()
            for band in bands:
                hashes.update(_dec_set(self._redis.smembers(self._band_key(band))))
            if not hashes:
                return []
            raw = self._redis.hmget(self._learn_key(), list(hashes))
            out = []
            for v in raw:
                if not v:
                    continue
                try:
                    out.append(Learning(**json.loads(v)))
                except (ValueError, TypeError):
                    continue
            return out
        with self._lock:
            hashes = set()
            for band in bands:
                hashes.update(self._band_index.get(band, set()))
            return [self._learnings[h] for h in hashes if h in self._learnings]

    def recall_context(self, task: str, *, limit: int = 5) -> str:
        """Render recalled lessons as a compact context block to inject into a prompt (empty when none)."""
        items = self.recall(task, limit=limit)
        if not items:
            return ""
        lines = [f"- [{it['category']}] {it['summary']}" for it in items]
        rate, count = self.success_rate(task)
        head = f"Prior lessons for similar tasks (success-rate {rate:.0%} over {count} runs):"
        return head + "\n" + "\n".join(lines)


def _dec_set(members) -> set[str]:
    return {(m.decode() if isinstance(m, bytes) else str(m)) for m in (members or [])}
