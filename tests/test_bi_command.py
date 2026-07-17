"""B5 - CLI smoke (citadel bi learn/status/show) + the Pandidakterion chaos drill: change a logic-defining
line and assert the cascade re-learns, regenerates, and the stale unit's Senatus Consultum decays (revived on
re-learn). This is the end-to-end '100% current' loop. Zero-token, in-memory Republic."""

from citadel.services._tools_bridge import import_tool
from citadel.services.pandidakterion import Pandidakterion
from citadel.services.republic import build_republic

_cart = import_tool("bi_cartographer")
_cascade = import_tool("bi_cascade")
_oracle = import_tool("citadel_oracle")


def _province(root):
    (root / "metrics.py").write_text(
        "def load_factor(seats, sold):\n    return sold.sum() / seats.sum()\n\n"
        "def revenue_per_km(rev, dist):\n    return rev.mean() / dist.mean()\n", encoding="utf-8")
    (root / "kpis.md").write_text("**Load Factor**: seats sold over available.\n", encoding="utf-8")


def test_bi_command_learn_status_show(tmp_path, capsys):
    from citadel.commands.bi import run

    _province(tmp_path)
    assert run("learn", str(tmp_path)) == 0
    assert run("status", str(tmp_path)) == 0
    assert run("show", str(tmp_path), name="load_factor") == 0
    out = capsys.readouterr().out
    assert "Cartographer" in out
    assert "load_factor" in out
    assert run("show", str(tmp_path), name="does_not_exist") == 1     # missing unit reports cleanly


def test_pandidakterion_command_runs(tmp_path, capsys):
    from citadel.commands.pandidakterion import run

    assert run(str(tmp_path)) == 0
    assert "Pandidakterion" in capsys.readouterr().out


def test_chaos_drill_change_a_line_refreshes_and_decays(tmp_path):
    _province(tmp_path)
    prov = tmp_path.name
    rep = build_republic(tmp_path, prefer_redis=False)
    pand = Pandidakterion(rep, min_witnesses=2)

    # learn, then promote load_factor to a durable Senatus Consultum bound to its source hash
    understanding = _cart.learn(tmp_path, province=prov)
    unit = next(u for u in understanding["units"] if u["name"] == "load_factor")
    src = tmp_path / "metrics.py"
    src_hash = _oracle.content_hash(src)
    consultum = pand.promote_unit(prov, unit, accepting=["chair:dataframe", "chair:domain-logic"],
                                  sources=[(str(src), src_hash)])
    assert consultum.is_binding
    assert pand.decay_stale(is_fresh=_oracle.is_fresh) == []          # source fresh -> stays durable

    # CHAOS: change the logic file (add a new metric)
    src.write_text(src.read_text(encoding="utf-8")
                   + "\ndef yield_per_seat(rev, seats):\n    return rev.sum() / seats.sum()\n", encoding="utf-8")

    # the cascade re-learns + regenerates + re-wires, detecting the new unit
    report = _cascade.cascade(tmp_path, ["metrics.py"], republic=rep)
    assert report["triggered"] is True
    assert "yield_per_seat" in report["changed"]["added"]
    assert report["regenerated"]["nodes"] >= 1                        # artifacts refreshed

    # JIT decay: load_factor's source changed -> its Consultum is demoted (revived on the next promotion)
    demoted = pand.decay_stale(is_fresh=_oracle.is_fresh)
    assert f"logic:{prov}:load_factor" in demoted
    assert rep.consulta.is_binding(f"logic:{prov}:load_factor") is False
