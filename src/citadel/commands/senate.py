"""citadel senate — a read-only status view of the Republic (brain · imperia · learning · bus · senate).

Reports the live backends (does the brain bus / learning ledger have Redis, or the in-memory fallback?) and
confirms each System (0-6) is wired, so an operator can see at a glance that the Republic is online and which
tier it is running on. Everything degrades gracefully — a missing backend is reported, never fatal.
"""

import json as _json
from pathlib import Path


def _brain_status(rep) -> dict:
    return {"bus_backend": rep.bus.backend(), **rep.brain.stats()}


def _learning_status(rep) -> dict:
    store = rep.ledger
    backend = "redis" if store._redis is not None else "memory"
    out = {"backend": backend}
    if store._redis is not None:
        try:
            out["signatures"] = int(store._redis.hlen(store._ewma_key()))
            out["lessons"] = int(store._redis.hlen(store._learn_key()))
        except Exception:
            pass
    return out


_SYSTEMS = [
    ("0 · Brain", "citadel.services.brain"),
    ("1 · Identity / not-self", "citadel.services.consensus.identity"),
    ("2 · Imperia + rails", "citadel.services.imperium"),
    ("3 · Learning ledger", "citadel.services.brain.learning"),
    ("4 · Brain-for-all", "citadel.services.brain.injection"),
    ("5 · Senate", "citadel.services.senate"),
    ("6 · SCU / Aerarium / Provinces / Foreign", "citadel.services.senate.scu"),
]


def _systems_health() -> list[tuple[str, bool]]:
    import importlib

    out = []
    for label, module in _SYSTEMS:
        try:
            importlib.import_module(module)
            out.append((label, True))
        except Exception:
            out.append((label, False))
    return out


def run(workspace=None, *, as_json: bool = False) -> int:
    from citadel import paths as vp
    from citadel.services.republic import build_republic

    ws = Path(workspace).expanduser().resolve() if workspace else vp.workspace_root()

    systems = _systems_health()
    consulta = 0
    try:
        rep = build_republic(ws)
        brain = _brain_status(rep)
        learning = _learning_status(rep)
        consulta = len(rep.consulta.binding_keys())
    except Exception as exc:
        brain = {"error": str(exc)}
        learning = {"backend": "unavailable"}

    if as_json:
        payload = {"workspace": str(ws), "systems": dict(systems), "brain": brain,
                   "learning": learning, "consulta": consulta}
        print(_json.dumps(payload, indent=2))
        return 0

    print("◆ The Sovereign — Senate of the Republic")
    print(f"  workspace: {ws}")
    print("  systems:")
    for label, ok in systems:
        print(f"    [{'ok' if ok else '--'}] System {label}")
    print("  brain:")
    if "error" in brain:
        print(f"    [--] {brain['error']}")
    else:
        print(f"    [ok] bus: {brain.get('bus_backend')} · oracle symbols: {brain.get('oracle', {}).get('l0', 0)}"
              f" · graph nodes: {brain.get('adjacency_nodes', 0)}")
    print("  learning ledger:")
    extra = ""
    if "lessons" in learning:
        extra = f" · {learning['lessons']} lessons / {learning.get('signatures', 0)} signatures"
    print(f"    [ok] backend: {learning['backend']}{extra}")
    print(f"  senate: {consulta} binding Senatus Consulta")
    print("  rule: a model never validates its exact self; promotion needs a distinct not-self quorum.")
    return 0
