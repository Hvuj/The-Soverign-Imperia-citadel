# Transport & wire-performance — the decision matrix

The right protocol depends on the hop. This records **which transport each hop uses and why**, so we pick by
use-case/performance/best-practice and don't bolt gRPC/WebSockets/HTTP-3 where they don't belong.

## The matrix

| Hop | Traffic shape | Transport | Why (and why not the others) |
|---|---|---|---|
| **Client ↔ our MCP server** | request/response tool calls | **stdio** (native) · **Streamable HTTP over uvicorn** (compose) | The MCP spec defines **only** stdio + Streamable HTTP. gRPC/WebSockets are **not** MCP transports — using them breaks interop with Claude Code and every other MCP client. uvicorn (ASGI, HTTP/1.1 keep-alive) is already the best-practice server. |
| **our code ↔ Ollama** | many small embed/generate POSTs | **pooled keep-alive HTTP/1.1** (`httpx`) | The win is **connection reuse**, not the protocol version. Ollama's Go server does not offer cleartext HTTP/2 (h2c) on localhost, so HTTP/2 can't negotiate. Batching (`/api/embed`) is already used. Measured **~22× faster** than the old per-call `urllib` on a 40-call embed sweep (83.99 s → 3.79 s), identical vectors. |
| **our code ↔ Redis** | vector KNN · cache · Streams queue | **RESP over a pooled connection** + pipelining | Redis speaks its own binary protocol, not HTTP. `redis.from_url` is connection-pooled by default and hot paths pipeline (`vector_store.upsert`, `embed_cache`, the `army` queue). Nothing to change. |
| **Edge / remote access** *(opt-in)* | exposing MCP beyond localhost | **HTTP/2 + HTTP/3 (QUIC) via Caddy** | uvicorn is HTTP/1.1-only; the standard way to add h2/h3/TLS is a **reverse proxy**, not an app rewrite. Caddy does h2 + h3 + automatic TLS. `docker compose --profile edge up`. |
| **Future: distributed worker mesh** | worker↔coordinator streaming, multi-machine | **gRPC / HTTP/2 streaming** — *deferred* | The only place gRPC fits. Today the agent army runs on one machine over **Redis Streams** (the correct distributed-queue primitive). Building gRPC now would be over-engineering; revisit when we go multi-node. |

## How to enable the h2/h3 edge

```bash
docker compose -f docker/compose/docker-compose.yml --profile edge up -d
# MCP over HTTP/2:            curl --http2 -k https://localhost:8443/mcp
# MCP over HTTP/3 (QUIC):     curl --http3 -k https://localhost:8443/mcp   # curl built with HTTP/3
```

Caddy (`docker/compose/Caddyfile`) terminates TLS with its internal CA and reverse-proxies plain HTTP/1.1 to
the uvicorn MCP server on `:8848`.

## Client tuning

- **Pool:** one shared `httpx.Client` (`services/execute/local/http_client.py`) with keep-alive limits
  (`max_keepalive_connections=8`, `keepalive_expiry=30s`). Falls back to stdlib `urllib` when `httpx` is
  absent (the zero-dep core still runs).
- **Opt-in HTTP/2 to Ollama:** `pip install '.[http2]'` + `CITADEL_OLLAMA_HTTP2=1`. Off by default (see the
  matrix — no h2c on localhost Ollama, so it's a no-op there; useful only behind a TLS-terminating proxy).

## What we deliberately did **not** do

- No **async** rewrite of the embed path — Ollama serializes on the GPU, so request concurrency doesn't speed
  embedding; **batching + connection reuse** are the correct levers.
- No **gRPC/WebSocket** MCP transport — outside the MCP spec.
- No **forced HTTP/2/3** on localhost hops — not negotiable (Ollama) or not worth it single-client (MCP).
