"""B4 - Pandidakterion governance: the charter monopoly, promotion of a learned unit to a durable Senatus
Consultum only via a not-self distinct-identity quorum (idempotent), and JIT decay when a source goes stale.
In-memory Republic, no network."""

from citadel.services.pandidakterion import Chair, Pandidakterion, default_faculty
from citadel.services.republic import build_republic

_UNIT = {"name": "load_factor", "kind": "metric", "confidence": 0.8, "content_hash": "abc123"}


def _pand(tmp_path):
    return Pandidakterion(build_republic(tmp_path, prefer_redis=False), min_witnesses=2)


def test_charter_admits_only_faculty(tmp_path):
    p = _pand(tmp_path)
    assert p.charter_admits("cartographer:airline") is True     # the Cartographer
    assert p.charter_admits("chair:dataframe") is True          # a seated Chair
    assert p.charter_admits("provider:groq:some-model") is False  # an outsider — monopoly refuses
    assert p.charter_admits("") is False


def test_chair_for_maps_discipline(tmp_path):
    p = _pand(tmp_path)
    assert p.chair_for({"kind": "metric"}).order == "dataframe-specialist"
    assert p.chair_for({"kind": "rule"}).identity == "chair:domain-logic"
    assert isinstance(default_faculty()["term"], Chair)


def test_promotion_requires_not_self_quorum(tmp_path):
    p = _pand(tmp_path)
    # the Cartographer alone (its own identity) cannot self-certify
    assert p.promote_unit("airline", _UNIT, accepting=["cartographer:airline"]) is None
    # a single validator is not a quorum
    assert p.promote_unit("airline", _UNIT, accepting=["chair:dataframe"]) is None
    # two DISTINCT not-self Chairs carry it to a Senatus Consultum
    consultum = p.promote_unit("airline", _UNIT, accepting=["chair:dataframe", "chair:domain-logic"])
    assert consultum is not None
    assert consultum.is_binding
    assert consultum.key == "logic:airline:load_factor"
    assert p.republic.consulta.is_binding("logic:airline:load_factor")


def test_promotion_is_idempotent(tmp_path):
    p = _pand(tmp_path)
    accepting = ["chair:dataframe", "chair:semantics"]
    first = p.promote_unit("airline", _UNIT, accepting=accepting)
    second = p.promote_unit("airline", _UNIT, accepting=accepting)
    assert first.version == second.version                      # same content → no new version


def test_jit_decay_demotes_stale_unit(tmp_path):
    p = _pand(tmp_path)
    accepting = ["chair:dataframe", "chair:domain-logic"]
    p.promote_unit("airline", _UNIT, accepting=accepting, sources=[("metrics.py", "hash-at-promotion")])
    assert p.republic.consulta.is_binding("logic:airline:load_factor")
    # source still fresh → stays
    assert p.decay_stale(is_fresh=lambda path, h: True) == []
    # source changed → demoted (revival happens on the next re-learn cascade)
    demoted = p.decay_stale(is_fresh=lambda path, h: False)
    assert "logic:airline:load_factor" in demoted
    assert p.republic.consulta.is_binding("logic:airline:load_factor") is False


def test_status_reports_faculty_and_durable(tmp_path):
    p = _pand(tmp_path)
    p.promote_unit("airline", _UNIT, accepting=["chair:dataframe", "chair:domain-logic"])
    s = p.status()
    assert s["durable_units"] == 1
    assert s["min_witnesses"] == 2
    assert "metric" in s["faculty"]
