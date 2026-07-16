# Redis & caching

How the Zero-Token layer stores its vectors and everything it caches — where it lives, how to point it at
your Redis (local or cloud), and how to verify it.

---

## Redis

### What we use it for
- **Vector store** — dense embeddings + RediSearch **HNSW** index for semantic search (`vec:<model>:*`,
  index `idx:<model>`).
- **Caches** — embedding cache, answer cache (see below).
- **Job queue** — the agent army's atomic tasks over **Redis Streams** (`citadel:army:<run-id>`).

Redis is **optional**: with no Redis reachable, everything degrades to a **pure-Python on-disk vector file**
+ JSON caches. You lose native HNSW speed, not correctness.

### How the connection is resolved
One resolver, `citadel.paths.resolve_redis_url()`, with precedence:

```
--redis-url flag  >  CITADEL_REDIS_URL env  >  .citadel/config.toml [redis].url  >  redis://127.0.0.1:6379
```

`[redis] enabled = false` (or `citadel setup --no-redis`) opts out entirely → pure-Python store.

### Local vs cloud
Our compose spins the Redis we need; the config picks which one.

```bash
# LOCAL — our managed Redis Stack container (RediSearch/HNSW):
citadel setup --redis local
docker compose -f docker/compose/docker-compose.yml --profile local-redis up -d redis

# CLOUD — a managed Redis; no local container runs:
citadel setup --redis cloud --redis-url rediss://user:pass@your-host:6379
```

In compose, the `redis` service sits behind the **`local-redis` profile** (so cloud mode omits it), and the
containerized MCP server reads `CITADEL_REDIS_URL` (defaulting to the local `redis://redis:6379`). Set
`CITADEL_REDIS_URL` in `docker/compose/.env` for cloud. Port is `CITADEL_REDIS_PORT` (default 6379).

### RediSearch is required for native vectors
Native HNSW needs the **RediSearch** module (Redis Stack, `redis/redis-stack`). Plain Redis is reachable but
without RediSearch we fall back to the on-disk vector store. `citadel doctor` tells you which:

```
[ok] redis reachable: redis://127.0.0.1:6379
[ok] RediSearch module (native HNSW vectors)     # ← Redis Stack; native path
[--] RediSearch module (no RediSearch — on-disk fallback)   # ← plain Redis
```

### Verify it
```bash
citadel doctor                 # resolved URL + reachability + RediSearch
redis-cli DBSIZE               # key count grows as the embedder runs
redis-cli KEYS "vec:*"         # our vector keys (prefix vec:<model>:)
redis-cli FT._LIST             # our search indexes (idx:<embed-model>)
```
No `redis-cli`? `python -c "import redis; r=redis.from_url('redis://127.0.0.1:6379'); print(r.dbsize(), r.execute_command('FT._LIST'))"`

---

## Caching

Several layers, each **compute-once / reuse-forever**. They live in **Redis when connected, else on-disk**.

| Cache | Caches | Key | Store | Invalidation |
|---|---|---|---|---|
| **SIEVE RamCache** | hot compute results | op-specific | RAM (scan-resistant SIEVE eviction) | byte/entry budget |
| **Universal memoize** | any pure-function result | blake2b of args | RAM + content-addressed disk | content hash |
| **Embed cache** | chunk text → vector | content hash of the (redacted) chunk | Redis / JSON | new content = new key |
| **Answer cache** | `citadel ask` answers | normalized-question hash | Redis / JSON | **content-hash-gated** (below) |
| **CAS pre-images** | file backups before a write | blake2b of the pre-image | content-addressed disk | dedup (identical → one blob) |

Files:
[`services/cache/ram_cache.py`](../src/citadel/services/cache/ram_cache.py) ·
[`services/cache/memoize.py`](../src/citadel/services/cache/memoize.py) ·
[`services/retrieval/embed_cache.py`](../src/citadel/services/retrieval/embed_cache.py) ·
[`services/retrieval/answer_cache.py`](../src/citadel/services/retrieval/answer_cache.py) ·
[`tools/_content_address.py`](../tools/_content_address.py)

### The two that matter most

- **Embed cache** — embedding is the one non-free step (GPU cycles). Keyed by the **content hash** of the
  redacted chunk, so an unchanged chunk (even the same boilerplate across files) is embedded **once**. Redis
  `MGET`/pipeline when connected; a JSON file otherwise.

- **Answer cache — content-hash-gated (the important safety rule).** A cached `citadel ask` answer stores the
  `(path, file_hash)` of every chunk it cited. It is reused **only** while **every cited file is still
  `is_fresh`** (its content hash matches). Query similarity picks a *candidate*; the content hashes
  *authorize* the reuse. Edit a cited file and the next ask **re-answers** — you never get a stale answer.
  This is the fix for the classic "semantic cache returns an out-of-date answer" bug.

### Eviction & budgets
The RAM cache is **SIEVE** (scan-resistant — protects visited entries over one-hit newcomers). Redis honours
its own maxmemory/LFU policy; the on-disk caches are content-addressed (naturally dedup). The optimizer
Z-worker prunes dead/stale vectors under a budget.

---

See also: [SYSTEM-DESIGN.md §17](SYSTEM-DESIGN.md) (the Zero-Token layer) and
[TRANSPORTS.md](TRANSPORTS.md) (Redis wire: RESP pooled + pipelined).
