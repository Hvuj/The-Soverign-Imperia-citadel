"""B0 - the Cartographer core: agnostic multi-source discovery -> synthesis. Two synthetic provinces must
learn two DIFFERENT vocabularies from their own code/docs/sql/config, with nothing domain-specific shipped.
Zero-token, no network. Tools live in tools/; import via the tools bridge."""

import json

from citadel.services._tools_bridge import import_tool

_sources = import_tool("bi_sources")
_vocab = import_tool("bi_vocab")
_synth = import_tool("bi_synthesize")
_cart = import_tool("bi_cartographer")


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _airline_province(root):
    _write(root, "metrics.py",
           "def load_factor(seats, sold):\n    return sold.sum() / seats.sum()\n\n"
           "def revenue_per_km(rev, dist):\n    return rev.mean() / dist.mean()\n")
    _write(root, "rules.py", "def validate_fare_positive(fare):\n    assert fare > 0\n    return True\n")
    _write(root, "kpis.md", "**Load Factor**: ratio of seats sold to seats available on a flight.\n")
    _write(root, "model.sql", "CREATE VIEW route_revenue AS SELECT route, SUM(fare) FROM bookings GROUP BY route;\n")


def _clinic_province(root):
    _write(root, "metrics.py",
           "def readmission_rate(admits, readmits):\n    return readmits.sum() / admits.sum()\n\n"
           "def avg_stay(days):\n    return days.mean()\n")
    _write(root, "rules.py", "def validate_dosage(dose):\n    assert dose > 0\n    return True\n")
    _write(root, "glossary.md", "**Readmission Rate**: fraction of patients readmitted within 30 days.\n")


def test_extractors_find_units_by_structure(tmp_path):
    _airline_province(tmp_path)
    ev = _sources.ingest(tmp_path)
    kinds = {e.kind for e in ev}
    names = {e.unit for e in ev}
    assert "metric" in kinds                       # aggregations -> metric
    assert "rule" in kinds                         # validate_* -> rule
    assert "load_factor" in names                  # python metric fn
    assert any(n == "route_revenue" for n in names)  # sql view -> metric


def test_two_provinces_learn_different_vocab(tmp_path):
    air, clinic = tmp_path / "airline", tmp_path / "clinic"
    air.mkdir()
    clinic.mkdir()
    _airline_province(air)
    _clinic_province(clinic)
    v_air = _vocab.vocab_terms(_vocab.learn_vocab(_sources.ingest(air)))
    v_clinic = _vocab.vocab_terms(_vocab.learn_vocab(_sources.ingest(clinic)))
    assert "fare" in v_air
    assert "fare" not in v_clinic                  # airline term, learned not shipped
    assert "dosage" in v_clinic
    assert "dosage" not in v_air                   # clinic term
    assert v_air != v_clinic                       # genuinely province-specific


def test_synthesis_scores_confidence_by_support(tmp_path):
    _airline_province(tmp_path)
    units = _synth.synthesize(_sources.ingest(tmp_path))
    assert units
    assert units == sorted(units, key=lambda u: (-u.confidence, u.name))  # most-confident first
    lf = next(u for u in units if u.name == "load_factor")
    assert lf.kind == "metric"                     # code metric outranks the doc mention (weighted vote)
    assert 0.0 < lf.confidence <= 1.0
    assert lf.content_hash                         # content-addressed for idempotency


def test_cartographer_persists_state_and_memory(tmp_path):
    _airline_province(tmp_path)
    _cart.learn(tmp_path, province="airline")
    sd = _cart.state_dir(tmp_path, "airline")
    assert (sd / "units.json").exists()
    assert (sd / "vocab.json").exists()
    assert (sd / "scorecard.json").exists()
    units = json.loads((sd / "units.json").read_text(encoding="utf-8"))
    assert any(u["name"] == "load_factor" for u in units)
    mem = _cart.memory_path(tmp_path, "airline").read_text(encoding="utf-8")
    assert "Domain logic" in mem
    assert "airline" in mem
    assert "load_factor" in mem


def test_memory_managed_block_preserves_user_notes(tmp_path):
    _airline_province(tmp_path)
    _cart.learn(tmp_path, province="airline")
    mem = _cart.memory_path(tmp_path, "airline")
    text = mem.read_text(encoding="utf-8") + "\nMY IMPORTANT NOTE: load_factor excludes cargo flights.\n"
    mem.write_text(text, encoding="utf-8")
    _cart.learn(tmp_path, province="airline")                  # re-learn
    assert "MY IMPORTANT NOTE" in mem.read_text(encoding="utf-8")  # user note survives regeneration


def test_understanding_shape_matches_schema(tmp_path):
    _airline_province(tmp_path)
    result = _cart.learn(tmp_path, province="airline", write=False)
    assert set(result) >= {"province", "units", "scorecard"}
    assert result["scorecard"]["avg_confidence"] >= 0.0
    for u in result["units"]:
        assert {"name", "kind", "confidence"} <= set(u)
        assert u["kind"] in {"metric", "rule", "transform", "policy", "term"}
