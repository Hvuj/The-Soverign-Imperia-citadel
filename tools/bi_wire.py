#!/usr/bin/env python3
"""bi_wire.py — connect learned domain logic into the live Republic (never orphaned).

Generation wrote the artifacts; wiring makes them *live*:
- every learned unit is recorded into the Republic **LearningStore** (System 3) so recall surfaces the
  province's domain knowledge, and the write broadcasts on the shared **EventBus** (nodes are already under
  `docs/brain/nodes/…` where the incremental-brain daemon indexes them into `BrainAccess`);
- a **wire manifest** lists what was generated + recorded (routing / audit);
- low-confidence units are queued for **T2 refinement**, gated on the **Aerarium** (token-bucket): a
  Legionnaire is summoned only when the treasury can afford it — otherwise the deterministic result stands.

Best-effort + guarded: if the Republic (or Redis) is unavailable, the deterministic artifacts already exist;
wiring simply records what it can and never raises.
"""

import contextlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_REFINE_BELOW = 0.4          # units under this confidence want a T2 refinement pass
_REFINE_COST = 1.0           # Aerarium tokens per refinement


def _build_republic(root):
    try:
        from citadel.services.republic import build_republic

        return build_republic(root)
    except Exception:
        return None


def _aerarium(*, capacity: float = 8.0, refill_per_s: float = 0.5):
    try:
        from citadel.services.senate.aerarium import Aerarium

        return Aerarium().grant_bucket("cartographer", capacity=capacity, refill_per_s=refill_per_s)
    except Exception:
        return None


def wire(root, understanding: dict, generated: dict, *, republic=None, aerarium=None) -> dict:
    """Record learned units into the Republic, broadcast, manifest, and queue affordable refinements."""
    root = Path(root).resolve()
    province = understanding["province"]
    units = understanding.get("units", [])
    rep = republic if republic is not None else _build_republic(root)

    recorded = 0
    if rep is not None:
        for u in units:
            ev = (u.get("evidence") or [{}])[0]
            summary = f"{u['kind']}: {ev.get('snippet', '')[:160]}".strip()
            task = f"{province} domain logic: {u['name']} ({u['kind']})"
            try:
                rep.ledger.record(task, f"cartographer:{province}", success=True,
                                  category="best_practice", summary=summary)
                recorded += 1
            except Exception:
                pass
        with contextlib.suppress(Exception):
            rep.bus.publish("cartographer", {"event": "wired", "province": province,
                                             "units": len(units), "recorded": recorded})

    # queue refinements for low-confidence units, funded by the Aerarium (Z-worker-first: only if affordable)
    aer = aerarium if aerarium is not None else _aerarium()
    low = [u["name"] for u in units if u.get("confidence", 0) < _REFINE_BELOW]
    refine, deferred = [], []
    for name in low:
        if aer is not None and aer.allocate("cartographer", _REFINE_COST):
            refine.append(name)          # affordable → summon a Legionnaire (actual T2 call is B-later)
        else:
            deferred.append(name)        # treasury empty → deterministic result stands

    manifest = {
        "province": province,
        "recorded_units": recorded,
        "generated": generated,
        "refine_queued": refine,
        "refine_deferred": deferred,
        "republic": rep is not None,
    }
    mpath = root / ".citadel" / "state" / "logic" / province / "wire-manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(mpath)
    return manifest


def main() -> None:
    import argparse

    from bi_cartographer import learn
    from bi_generate import generate

    ap = argparse.ArgumentParser(description="Learn → generate → wire a province into the live Republic.")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--province", default=None)
    args = ap.parse_args()
    understanding = learn(args.root, province=args.province, write=True)
    generated = generate(args.root, understanding)
    manifest = wire(args.root, understanding, generated)
    print(json.dumps({k: manifest[k] for k in ("province", "recorded_units", "refine_queued",
                                                "refine_deferred", "republic")}, indent=2))


if __name__ == "__main__":
    main()
