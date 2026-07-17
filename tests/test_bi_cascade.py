"""B3 - the continuous cascade: a domain-logic change triggers incremental re-learn -> drift diff ->
regenerate -> re-wire; an irrelevant change no-ops. Zero-token, in-memory Republic, no network."""

from citadel.services._tools_bridge import import_tool
from citadel.services.republic import build_republic

_cart = import_tool("bi_cartographer")
_gen = import_tool("bi_generate")
_wire = import_tool("bi_wire")
_cascade = import_tool("bi_cascade")


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _province(root):
    _write(root, "metrics.py",
           "def load_factor(seats, sold):\n    return sold.sum() / seats.sum()\n\n"
           "def revenue_per_km(rev, dist):\n    return rev.mean() / dist.mean()\n")
    _write(root, "kpis.md", "**Load Factor**: seats sold over available.\n")


def test_is_logic_relevant_classifies():
    assert _cascade.is_logic_relevant("metrics.py") is True
    assert _cascade.is_logic_relevant("model.sql") is True
    assert _cascade.is_logic_relevant("docs/kpis.md") is True
    assert _cascade.is_logic_relevant("tools/generated/logic_validate_x.py") is False  # generated
    assert _cascade.is_logic_relevant(".citadel/state/x.json") is False                # state
    assert _cascade.is_logic_relevant("run.log") is False                              # not a logic source


def test_cascade_relearns_and_reports_new_unit(tmp_path):
    _province(tmp_path)
    rep = build_republic(tmp_path, prefer_redis=False)
    # establish a baseline (persisted units.json)
    _cart.learn(tmp_path, province=tmp_path.name)
    # a logic change: add a new metric
    (tmp_path / "metrics.py").write_text(
        (tmp_path / "metrics.py").read_text(encoding="utf-8")
        + "\ndef yield_per_seat(rev, seats):\n    return rev.sum() / seats.sum()\n", encoding="utf-8")
    report = _cascade.cascade(tmp_path, ["metrics.py"], republic=rep)
    assert report["triggered"] is True
    assert "yield_per_seat" in report["changed"]["added"]        # the new unit was detected
    assert report["recorded_units"] >= 1                         # re-wired into the ledger
    assert report["regenerated"]["nodes"] >= 1                   # artifacts regenerated


def test_cascade_noops_on_irrelevant_change(tmp_path):
    _province(tmp_path)
    rep = build_republic(tmp_path, prefer_redis=False)
    report = _cascade.cascade(tmp_path, ["notes.log", ".citadel/state/snapshot.json"], republic=rep)
    assert report["triggered"] is False


def test_diff_units_by_content_hash():
    old = [{"name": "a", "content_hash": "x"}, {"name": "b", "content_hash": "y"}]
    new = [{"name": "b", "content_hash": "Y"}, {"name": "c", "content_hash": "z"}]
    d = _cascade.diff_units(old, new)
    assert d["added"] == ["c"]
    assert d["removed"] == ["a"]
    assert d["changed"] == ["b"]


def test_daemon_hook_is_guarded(monkeypatch):
    # the incremental-brain daemon's _logic_cascade must swallow any cascade failure (never raise, never
    # touch the repo). Monkeypatch the cascade to blow up and assert the hook stays silent.
    daemon = import_tool("incremental_brain_daemon")
    bc = import_tool("bi_cascade")

    def _boom(*a, **k):
        raise RuntimeError("cascade broke")

    monkeypatch.setattr(bc, "cascade", _boom)
    monkeypatch.setattr(daemon, "event", lambda r: None)
    daemon._logic_cascade(["anything.py"])                      # no exception propagates = pass
