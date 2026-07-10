---
id: topic:cache
title: Cache
type: topic
tags: [topic, cache, reuse, fast-path, route-cache, capsule-cache]
links:
  - cache-manager
  - cache-key-guardian
  - cache-performance-auditor
  - reuse-fast-path-agent
files:
  - tools/brain_context_builder.py
  - tools/build_capsule_cache.py
  - tools/reuse_fast_path.py
  - tools/build_implementation_cache_index.py
---

# Cache

Citadel caching layers: prompt-route cache, precomputed capsule cache, implementation cache, Claude prompt cache.

When to use: cache, reuse, already solved, fast path, pattern.

Key rule: `cache-key-guardian` blocks main-loop /model /effort changes. Per-agent spawn tiers exempt.
