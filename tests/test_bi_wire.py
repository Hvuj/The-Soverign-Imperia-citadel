"""B2 - auto-wire + Republic integration: learned units flow into the shared LearningStore, broadcast on the
bus, are manifested, and low-confidence units are queued for refinement gated on the Aerarium (Z-worker-first
funding). In-memory Republic, no network."""

import json

from citadel.services._tools_bridge import import_tool
from citadel.services.republic import build_republic
from citadel.services.senate.aerarium import Aerarium

_cart = import_tool("bi_cartographer")
_gen = import_tool("bi_generate")
_wire = import_tool("bi_wire")


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _province(root):
    _write(root, "metrics.py",
           "def load_factor(seats, sold):\n    return sold.sum() / seats.sum()\n\n"
           "def churn(a, b):\n    return b.count() / a.count()\n\n"
           "def uplift(x, y):\n    return x.mean() - y.mean()\n")
    _write(root, "kpis.md", "**Load Factor**: seats sold over seats available.\n")


def test_wire_records_units_into_republic_and_broadcasts(tmp_path):
    _province(tmp_path)
    rep = build_republic(tmp_path, prefer_redis=False)
    rep.bus.subscribe("cartographer", "sink")
    understanding = _cart.learn(tmp_path, province="airline")
    generated = _gen.generate(tmp_path, understanding)
    manifest = _wire.wire(tmp_path, understanding, generated, republic=rep)

    assert manifest["recorded_units"] == len(understanding["units"])   # every unit recorded
    assert manifest["republic"] is True
    # a learned unit is now recallable from the shared brain ledger
    lessons = rep.ledger.recall("airline domain logic: load_factor (metric)")
    assert any("metric" in item["summary"] for item in lessons)
    got = rep.bus.poll("cartographer", "sink", "c", block_ms=0)
    assert got
    assert got[0][1]["event"] == "wired"


def test_wire_writes_manifest(tmp_path):
    _province(tmp_path)
    rep = build_republic(tmp_path, prefer_redis=False)
    understanding = _cart.learn(tmp_path, province="airline")
    _wire.wire(tmp_path, understanding, _gen.generate(tmp_path, understanding), republic=rep)
    mpath = tmp_path / ".citadel" / "state" / "logic" / "airline" / "wire-manifest.json"
    assert mpath.exists()
    on_disk = json.loads(mpath.read_text(encoding="utf-8"))
    assert on_disk["province"] == "airline"
    assert "generated" in on_disk


def test_aerarium_gates_refinement(tmp_path):
    _province(tmp_path)
    rep = build_republic(tmp_path, prefer_redis=False)
    understanding = _cart.learn(tmp_path, province="airline")
    # a treasury that affords exactly ONE refinement
    aer = Aerarium(now=lambda: 0.0).grant_bucket("cartographer", capacity=1.0, refill_per_s=0.0)
    manifest = _wire.wire(tmp_path, understanding, _gen.generate(tmp_path, understanding),
                          republic=rep, aerarium=aer)
    low = [u["name"] for u in understanding["units"] if u["confidence"] < 0.4]
    if low:                                                    # only meaningful if there are low-conf units
        assert len(manifest["refine_queued"]) <= 1             # Aerarium capped it at one
        assert len(manifest["refine_queued"]) + len(manifest["refine_deferred"]) == len(low)


def test_wire_degrades_without_republic(tmp_path):
    _province(tmp_path)
    understanding = _cart.learn(tmp_path, province="airline")
    # republic explicitly absent → still writes the manifest, never raises
    manifest = _wire.wire(tmp_path, understanding, {"nodes": []}, republic=None, aerarium=None)
    assert "manifest_path" in manifest
    assert manifest["province"] == "airline"
