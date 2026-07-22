#!/usr/bin/env python3
"""bi_cascade.py — the continuous re-learning cascade (the Pandidakterion "100%" loop).

When a domain-logic file changes, the watch daemon calls this: classify the change → re-learn the affected
province (deterministic, zero-token — a Z-worker) → **diff** the new understanding against the persisted
baseline to see exactly which units moved → regenerate their artifacts → re-wire into the Republic. The
result is that every dependent component (nodes, memory, skills, workflows, validators, ledger) is refreshed
the moment the logic changes, so the system's understanding never goes stale. Governance (a not-self quorum
before a durable write + Cursus promotion + JIT decay) layers on in B4; here we do the incremental refresh.

Best-effort + guarded: nothing here is allowed to break the daemon that calls it.
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from bi_sources import _CFG_EXT, _CODE_EXT, _DOC_EXT, _IGNORE_PARTS, _SQL_EXT  # noqa: E402

_LOGIC_EXT = _CODE_EXT | _SQL_EXT | _DOC_EXT | _CFG_EXT


def is_logic_relevant(path_str: str) -> bool:
    """True for a source of domain logic (code/sql/doc/config) that isn't a generated/ignored artifact."""
    p = Path(str(path_str))
    if any(part in _IGNORE_PARTS for part in p.parts):
        return False
    return p.suffix.lower() in _LOGIC_EXT


def diff_units(old_units: list, new_units: list) -> dict:
    """What moved between two understandings, by content hash: {added, removed, changed}."""
    old = {u["name"]: u.get("content_hash", "") for u in old_units}
    new = {u["name"]: u.get("content_hash", "") for u in new_units}
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(n for n in set(old) & set(new) if old[n] != new[n]),
    }


def _persisted_units(root: Path, province: str) -> list:
    from bi_cartographer import state_dir

    path = state_dir(root, province) / "units.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return []


def cascade(root, changed_paths, *, province: str | None = None, republic=None) -> dict:
    """Run the incremental re-learn → regenerate → re-wire cascade for a logic change. Returns a report."""
    relevant = [p for p in (changed_paths or []) if is_logic_relevant(p)]
    if not relevant:
        return {"triggered": False, "reason": "no logic-relevant change"}

    from bi_cartographer import learn, province_of
    from bi_generate import generate
    from bi_wire import wire

    root = Path(root).resolve()
    prov = province or province_of(root)
    baseline = _persisted_units(root, prov)              # snapshot BEFORE re-learn overwrites units.json
    understanding = learn(root, province=prov, write=True)
    delta = diff_units(baseline, understanding["units"])
    generated = generate(root, understanding)
    manifest = wire(root, understanding, generated, republic=republic)
    return {
        "triggered": True,
        "province": prov,
        "relevant": relevant,
        "changed": delta,
        "units": len(understanding["units"]),
        "recorded_units": manifest.get("recorded_units", 0),
        "regenerated": {k: len(v) for k, v in generated.items()},
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Run the domain-logic re-learning cascade for changed paths.")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("paths", nargs="*", help="changed paths (relative); default: re-scan everything")
    ap.add_argument("--province", default=None)
    args = ap.parse_args()
    paths = args.paths or ["."]
    report = cascade(args.root, paths, province=args.province)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
