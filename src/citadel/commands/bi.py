"""citadel bi — agnostic domain-logic learning (the Cartographer / Pandidakterion Grammar).

`citadel bi learn` runs the deterministic pipeline (learn -> generate -> wire) for the workspace; `status`
reports what was learned and how confidently; `show <unit>` prints one unit's provenance. The primary path
is automatic (init + the watch daemon + the autolearn hook) — this CLI is for on-demand use and inspection.
"""

import json as _json
from pathlib import Path


def _state(ws: Path, province: str) -> Path:
    return ws / ".citadel" / "state" / "logic" / province


def run(action: str, workspace=None, *, province=None, name=None, as_json: bool = False) -> int:
    from citadel import paths as vp
    from citadel.services._tools_bridge import import_tool

    ws = Path(workspace).expanduser().resolve() if workspace else vp.workspace_root()
    cart = import_tool("bi_cartographer")
    prov = province or cart.province_of(ws)

    if action == "learn":
        gen = import_tool("bi_generate")
        wire = import_tool("bi_wire")
        understanding = cart.learn(ws, province=prov)
        generated = gen.generate(ws, understanding)
        manifest = wire.wire(ws, understanding, generated)
        card = understanding["scorecard"]
        if as_json:
            print(_json.dumps({"province": prov, "scorecard": card, "recorded": manifest["recorded_units"]}, indent=2))
        else:
            print(f"◆ Cartographer — learned {card['units']} units in '{prov}' "
                  f"(avg confidence {card['avg_confidence']}, by kind {card['by_kind']})")
            print(f"  generated: {sum(len(v) for v in generated.values())} artifacts · "
                  f"recorded {manifest['recorded_units']} into the shared brain")
        return 0

    if action == "status":
        card_path = _state(ws, prov) / "scorecard.json"
        if not card_path.exists():
            print(f"◆ no learned logic for '{prov}' yet — run `citadel bi learn`")
            return 1
        card = _json.loads(card_path.read_text(encoding="utf-8"))
        if as_json:
            print(_json.dumps({"province": prov, "scorecard": card}, indent=2))
        else:
            print(f"◆ Domain logic — '{prov}': {card['units']} units, "
                  f"{card.get('confident_units', 0)} confident, avg {card['avg_confidence']}, "
                  f"{card.get('by_kind', {})}")
        return 0

    if action == "show":
        units_path = _state(ws, prov) / "units.json"
        if not units_path.exists():
            print(f"◆ no learned logic for '{prov}' — run `citadel bi learn`")
            return 1
        units = _json.loads(units_path.read_text(encoding="utf-8"))
        match = next((u for u in units if u["name"] == name), None)
        if match is None:
            print(f"◆ unit '{name}' not found in '{prov}' ({len(units)} known)")
            return 1
        print(_json.dumps(match, indent=2))
        return 0

    print(f"◆ unknown bi action '{action}' (use: learn | status | show)")
    return 2
