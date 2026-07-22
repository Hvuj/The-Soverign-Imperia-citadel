"""B1 - generation: a province's learned units become live capabilities (nodes/skill/workflow/validator/
script), template-driven, agnostic, idempotent, per-province isolated; the generated validator detects drift.
Zero-token, no network."""

import os
import py_compile
import subprocess
import sys
from pathlib import Path

from citadel.services._tools_bridge import import_tool

_cart = import_tool("bi_cartographer")
_gen = import_tool("bi_generate")
_TOOLS_DIR = str(Path(_cart.__file__).resolve().parent)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _airline(root):
    _write(root, "metrics.py",
           "def load_factor(seats, sold):\n    return sold.sum() / seats.sum()\n\n"
           "def revenue_per_km(rev, dist):\n    return rev.mean() / dist.mean()\n")
    _write(root, "rules.py", "def validate_fare_positive(fare):\n    assert fare > 0\n    return True\n")
    _write(root, "kpis.md", "**Load Factor**: ratio of seats sold to seats available.\n")


def _clinic(root):
    _write(root, "metrics.py",
           "def readmission_rate(a, r):\n    return r.sum() / a.sum()\n\n"
           "def avg_stay(days):\n    return days.mean()\n")
    _write(root, "rules.py", "def validate_dosage(dose):\n    assert dose > 0\n    return True\n")
    _write(root, "glossary.md", "**Readmission Rate**: fraction of patients readmitted within 30 days.\n")
    _write(root, "views.sql", "CREATE VIEW readmission_rate AS SELECT p, COUNT(*) FROM v GROUP BY p;\n")


def test_generation_emits_all_artifacts(tmp_path):
    _airline(tmp_path)
    understanding = _cart.learn(tmp_path, province="airline")
    out = _gen.generate(tmp_path, understanding)
    assert out["nodes"]                                          # a node per unit
    assert len(out["skill"]) == 1
    assert len(out["workflow"]) == 1
    assert len(out["validator"]) == 1
    assert len(out["script"]) == 1
    node = tmp_path / out["nodes"][0]
    assert node.exists()
    assert "node_type: domain-logic" in node.read_text(encoding="utf-8")
    skill = tmp_path / ".claude" / "skills" / "logic-review-airline" / "SKILL.md"
    assert skill.exists()
    assert "logic-review-airline" in skill.read_text(encoding="utf-8")


def test_generated_validator_compiles(tmp_path):
    _airline(tmp_path)
    _gen.generate(tmp_path, _cart.learn(tmp_path, province="airline"))
    validator = tmp_path / "tools" / "generated" / "logic_validate_airline.py"
    py_compile.compile(str(validator), doraise=True)            # valid Python


def test_generation_is_idempotent(tmp_path):
    _airline(tmp_path)
    u = _cart.learn(tmp_path, province="airline")
    _gen.generate(tmp_path, u)
    skill = tmp_path / ".claude" / "skills" / "logic-review-airline" / "SKILL.md"
    first = skill.read_text(encoding="utf-8")
    os.utime(skill, ns=(1_000_000_000, 1_000_000_000))
    stable_mtime = skill.stat().st_mtime_ns
    _gen.generate(tmp_path, u)                                  # regenerate
    assert skill.read_text(encoding="utf-8") == first           # byte-identical
    assert skill.stat().st_mtime_ns == stable_mtime              # no rewrite/self-trigger loop


def test_templates_are_agnostic_and_isolated(tmp_path):
    air, clinic = tmp_path / "airline", tmp_path / "clinic"
    air.mkdir()
    clinic.mkdir()
    _airline(air)
    _clinic(clinic)
    _gen.generate(air, _cart.learn(air, province="airline"))
    _gen.generate(clinic, _cart.learn(clinic, province="clinic"))
    air_skill = (air / ".claude" / "skills" / "logic-review-airline" / "SKILL.md").read_text(encoding="utf-8")
    clinic_skill = (clinic / ".claude" / "skills" / "logic-review-clinic" / "SKILL.md").read_text(encoding="utf-8")
    assert "load_factor" in air_skill                       # no cross-province leakage
    assert "readmission_rate" not in air_skill
    assert "readmission_rate" in clinic_skill
    assert "load_factor" not in clinic_skill


def test_generated_validator_detects_drift(tmp_path):
    _airline(tmp_path)
    _gen.generate(tmp_path, _cart.learn(tmp_path, province="airline"))
    validator = tmp_path / "tools" / "generated" / "logic_validate_airline.py"
    env = {**os.environ, "PYTHONPATH": _TOOLS_DIR, "PYTHONUTF8": "1"}
    # baseline: no drift
    r0 = subprocess.run([sys.executable, str(validator), str(tmp_path)], capture_output=True, text=True, env=env)
    assert r0.returncode == 0
    assert "drift: none" in r0.stdout
    # add a new metric -> drift
    (tmp_path / "metrics.py").write_text(
        (tmp_path / "metrics.py").read_text(encoding="utf-8")
        + "\ndef yield_per_seat(rev, seats):\n    return rev.sum() / seats.sum()\n", encoding="utf-8")
    r1 = subprocess.run([sys.executable, str(validator), str(tmp_path)], capture_output=True, text=True, env=env)
    assert r1.returncode == 1
    assert "yield_per_seat" in r1.stdout
