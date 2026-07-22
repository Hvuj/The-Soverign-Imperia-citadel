"""decay.py — JIT freshness decay for Senatus Consulta (System 5 weak-spot fix).

"Lifetime seats never expire" is the Senate's staleness risk. The fix is **lazy JIT decay**: a Consultum
carries the `(path, content_hash)` sources it was derived from; when any source's content no longer matches
its cached hash (`is_fresh`, content-based — never mtime), the Consultum is **demoted** on read. Nothing is
swept eagerly; correctness never depends on a watcher being alive (same posture as `citadel_oracle`).
"""

from citadel.services.senate.consulta import ConsultaStore, SenatusConsultum


def _default_is_fresh():
    try:
        from citadel.services._tools_bridge import import_tool

        return import_tool("citadel_oracle").is_fresh
    except Exception:
        return lambda _path, _cached_hash: True  # can't check → assume fresh (never spuriously demote)


def is_stale(consultum: SenatusConsultum, *, is_fresh=None) -> bool:
    """True iff any source the Consultum was derived from has changed content since it was enacted."""
    check = is_fresh or _default_is_fresh()
    return any(not check(path, cached_hash) for path, cached_hash in consultum.sources)


def sweep(store: ConsultaStore, *, is_fresh=None) -> list[str]:
    """Demote every binding Consultum whose sources went stale; returns the demoted keys. Call lazily on
    read paths — this is the JIT retirement of stale knowledge, not a background job."""
    check = is_fresh or _default_is_fresh()
    demoted: list[str] = []
    for key in store.binding_keys():
        consultum = store.latest(key)
        if consultum and consultum.sources and is_stale(consultum, is_fresh=check):
            store.demote(key)
            demoted.append(key)
    return demoted
