#!/usr/bin/env python3
"""bi_cartographer.py — the Cartographer order: learn → synthesize → persist a province's domain logic.

Orchestrates the agnostic pipeline (Grammar → Rhetoric): ingest multi-source evidence (`bi_sources`), learn
the province vocabulary (`bi_vocab`), assemble confidence-scored units (`bi_synthesize`), and persist to
`.citadel/state/logic/<province>/{vocab,units,scorecard}.json` plus a **user-editable** memory card whose
managed block is regenerated while the Sovereign's own notes are preserved. Zero-token and deterministic; the
model (T2) is only summoned later for low-confidence refinement (B2+).
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from bi_sources import ingest  # noqa: E402
from bi_synthesize import scorecard, synthesize  # noqa: E402
from bi_vocab import learn_vocab  # noqa: E402

# ASCII-only markers: they are parsed on re-learn, so they must survive any encoding round-trip.
_BEGIN = "<!-- CARTOGRAPHER:BEGIN (generated - edits inside are overwritten on re-learn) -->"
_END = "<!-- CARTOGRAPHER:END -->"


def province_of(root: str | Path) -> str:
    return Path(root).resolve().name or "province"


def state_dir(root: str | Path, province: str) -> Path:
    return Path(root).resolve() / ".citadel" / "state" / "logic" / province


def memory_path(root: str | Path, province: str) -> Path:
    return Path(root).resolve() / "docs" / "ai-context" / "logic" / f"{province}.md"


def _render_managed(province: str, units, vocab: dict, card: dict) -> str:
    lines = [f"# Domain logic: {province}", "", _BEGIN, "",
             f"_Learned by the Cartographer. {card['units']} units, avg confidence "
             f"{card['avg_confidence']}, by kind {card['by_kind']}._", "",
             "| unit | kind | confidence | primary source |", "|---|---|---|---|"]
    for u in units[:60]:
        src = u.evidence[0]["source_path"] if u.evidence else ""
        lines.append(f"| `{u.name}` | {u.kind} | {u.confidence} | {src} |")
    top_terms = ", ".join(list(vocab.get("terms", {}))[:25])
    lines += ["", f"**Learned vocabulary (top):** {top_terms or '(none yet)'}", "", _END, "",
              "## Sovereign notes", "", "_Add corrections below; they are preserved across re-learns._", ""]
    return "\n".join(lines) + "\n"


def _write_memory(path: Path, managed: str) -> None:
    """Write the memory card, preserving anything the user wrote outside the managed block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="replace")
        if _BEGIN in old and _END in old:
            tail = old.split(_END, 1)[1]
            new_block = managed.split(_END, 1)[0] + _END
            path.write_text(new_block + tail, encoding="utf-8")
            return
    path.write_text(managed, encoding="utf-8")


def learn(root: str | Path, *, province: str | None = None, write: bool = True) -> dict:
    """Learn a province's domain logic. Returns {province, units, vocab, scorecard, paths}."""
    root = Path(root).resolve()
    province = province or province_of(root)
    evidence = ingest(root)
    vocab = learn_vocab(evidence)
    units = synthesize(evidence)
    card = scorecard(units)
    result = {
        "province": province,
        "units": [u.to_dict() for u in units],
        "vocab": vocab,
        "scorecard": card,
    }
    if write:
        sd = state_dir(root, province)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "vocab.json").write_text(json.dumps(vocab, indent=2), encoding="utf-8")
        (sd / "units.json").write_text(json.dumps(result["units"], indent=2), encoding="utf-8")
        (sd / "scorecard.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
        _write_memory(memory_path(root, province), _render_managed(province, units, vocab, card))
        result["paths"] = {"state": str(sd), "memory": str(memory_path(root, province))}
    return result


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Cartographer: learn a province's domain logic (agnostic, T0).")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--province", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = learn(args.root, province=args.province, write=not args.no_write)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        c = result["scorecard"]
        print(f"◆ Cartographer — province '{result['province']}': {c['units']} units "
              f"(avg confidence {c['avg_confidence']}, by kind {c['by_kind']})")


if __name__ == "__main__":
    main()
