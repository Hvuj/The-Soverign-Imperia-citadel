"""citadel pandidakterion — status of the imperial university that governs learned domain logic.

Reports the faculty (Chairs), how many units have reached durable Senatus Consultum status, and the not-self
quorum threshold. Read-only; degrades gracefully with no Redis (in-memory Republic).
"""

import json as _json
from pathlib import Path


def run(workspace=None, *, as_json: bool = False) -> int:
    from citadel import paths as vp

    ws = Path(workspace).expanduser().resolve() if workspace else vp.workspace_root()
    try:
        from citadel.services.pandidakterion import Pandidakterion
        from citadel.services.republic import build_republic

        pand = Pandidakterion(build_republic(ws))
        status = pand.status()
    except Exception as exc:
        print(f"◆ Pandidakterion unavailable: {exc}")
        return 1

    if as_json:
        print(_json.dumps({"workspace": str(ws), **status}, indent=2))
        return 0

    print("◆ The Pandidakterion — imperial university of domain logic")
    print(f"  workspace: {ws}")
    print("  faculty (Chairs):")
    for discipline, order in status["faculty"].items():
        print(f"    [{discipline:>10}] {order}")
    print(f"  durable units (Senatus Consulta): {status['durable_units']}")
    print(f"  rule: a unit becomes durable only via >= {status['min_witnesses']} distinct not-self validators;")
    print("        a unit's Consultum decays the moment its source changes (revived on re-learn).")
    return 0
